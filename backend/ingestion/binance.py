from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass

import httpx
import websockets

from backend.analysis.pipeline import AnalysisPipeline
from backend.broadcast.ws_manager import ConnectionManager
from backend.config import Settings
from backend.engine.candle_aggregator import normalize_timestamp_ms, timeframe_to_ms
from backend.engine.candle_store import CandleStore
from backend.models.types import Candle, MarketQuote, to_wire


@dataclass(frozen=True)
class TradeTick:
    price: float
    qty: float
    timestamp_ms: int


def _normalize_symbol(symbol: str) -> str:
    return symbol.upper().replace("/", "")


def _binance_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if normalized.endswith("USD") and not normalized.endswith("USDT"):
        return normalized[:-3] + "USDT"
    return normalized


def _symbols_equal(provider_symbol: str | None, target_symbol: str) -> bool:
    if provider_symbol is None:
        return False
    return _normalize_symbol(provider_symbol) == _binance_symbol(target_symbol)


async def seed_historical(
    store: CandleStore,
    pipeline: AnalysisPipeline,
    manager: ConnectionManager,
    config: Settings,
) -> None:
    candles = await fetch_historical_candles(
        base_url=config.market_data_rest_base_url,
        symbol=store.symbol,
        timeframe=store.timeframe,
        limit=config.history_seed_candles,
    )
    store.seed(candles, now_ms=int(time.time() * 1000))
    pipeline.run(store, force_full=True)
    await manager.broadcast(pipeline.snapshot(store), timeframe=store.timeframe)


async def seed_all_historical(
    stores: dict[str, CandleStore],
    pipelines: dict[str, AnalysisPipeline],
    manager: ConnectionManager,
    config: Settings,
) -> None:
    for timeframe, store in stores.items():
        try:
            await seed_historical(store, pipelines[timeframe], manager, config)
        except Exception as exc:
            await manager.broadcast(
                {
                    "update_type": "status",
                    "status": "history_error",
                    "message": str(exc),
                    "symbol": store.symbol,
                    "timeframe": store.timeframe,
                },
                timeframe=timeframe,
            )


async def start_binance_stream(
    manager: ConnectionManager,
    stores: dict[str, CandleStore],
    pipelines: dict[str, AnalysisPipeline],
    config: Settings,
) -> None:
    import logging

    logger = logging.getLogger("backend")
    logger.info(f"Starting Binance stream for {config.symbol}")
    await seed_all_historical(stores, pipelines, manager, config)

    backoff = config.ws_reconnect_initial_seconds
    stream_symbol = _binance_symbol(config.symbol).lower()
    base_ws = config.market_data_ws_url.rstrip("/")
    stream_url = f"{base_ws}/stream?streams={stream_symbol}@trade/{stream_symbol}@bookTicker"

    while True:
        try:
            logger.info(f"Connecting to Binance WebSocket: {stream_url}")
            async with websockets.connect(
                stream_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_queue=1024,
            ) as websocket:
                logger.info("Binance WebSocket connected")
                await manager.broadcast(
                    {
                        "update_type": "status",
                        "status": "stream_connected",
                        "symbol": config.symbol,
                    }
                )
                backoff = config.ws_reconnect_initial_seconds

                async for raw in websocket:
                    logger.debug(f"Received Binance message: {raw[:200]}...")
                    message = json.loads(raw)
                    payload = message.get("data") or message
                    if not isinstance(payload, dict):
                        continue

                    quote = parse_quote_message(payload, config.symbol)
                    if quote is not None:
                        logger.debug(f"Parsed Binance quote: {quote}")
                        for pipeline in pipelines.values():
                            pipeline.add_quote(quote)
                        await manager.broadcast(
                            {
                                "update_type": "quote",
                                "symbol": config.symbol,
                                "quote": to_wire(quote),
                            }
                        )

                    tick = parse_trade_message(payload, config.symbol)
                    if tick is None:
                        continue

                    logger.debug(f"Parsed Binance trade tick: {tick}")
                    trade_quote = MarketQuote(
                        symbol=config.symbol,
                        timestamp=tick.timestamp_ms,
                        source="trades",
                        last_trade=tick.price,
                        latency_ms=max(0, int(time.time() * 1000) - tick.timestamp_ms),
                    )
                    for pipeline in pipelines.values():
                        pipeline.add_quote(trade_quote)
                    await manager.broadcast(
                        {
                            "update_type": "quote",
                            "symbol": config.symbol,
                            "quote": to_wire(trade_quote),
                        }
                    )

                    timeframe_updates: list[asyncio.Future] = []
                    for timeframe, store in stores.items():
                        candle_closed = store.update_tick(tick.price, tick.qty, tick.timestamp_ms)
                        if candle_closed:
                            timeframe_updates.append(
                                asyncio.create_task(
                                    manager.broadcast(pipelines[timeframe].run(store), timeframe=timeframe)
                                )
                            )
                        elif store.live_candle is not None:
                            timeframe_updates.append(
                                asyncio.create_task(
                                    manager.broadcast(
                                        {
                                            "update_type": "tick",
                                            "symbol": store.symbol,
                                            "timeframe": store.timeframe,
                                            "candle": to_wire(store.live_candle),
                                        },
                                        timeframe=timeframe,
                                    )
                                )
                            )
                    if timeframe_updates:
                        await asyncio.gather(*timeframe_updates)
        except asyncio.CancelledError:
            logger.info("Binance stream cancelled")
            raise
        except Exception as exc:
            logger.error(f"Binance WebSocket error: {exc}", exc_info=True)
            await manager.broadcast(
                {
                    "update_type": "status",
                    "status": "stream_disconnected",
                    "message": str(exc),
                    "retry_in_seconds": backoff,
                    "symbol": config.symbol,
                }
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.8, config.ws_reconnect_max_seconds)


def parse_trade_message(message: dict, symbol: str) -> TradeTick | None:
    if message.get("e") != "trade":
        return None

    message_symbol = message.get("s")
    if not _symbols_equal(message_symbol, symbol):
        return None

    price_raw = message.get("p")
    qty_raw = message.get("q")
    ts_raw = message.get("T")
    if price_raw is None or ts_raw is None:
        return None

    try:
        price = float(price_raw)
        qty = float(qty_raw or 0)
        timestamp_ms = normalize_timestamp_ms(ts_raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or not math.isfinite(qty):
        return None
    if price <= 0 or qty < 0:
        return None
    if timestamp_ms <= 0:
        return None

    return TradeTick(price=price, qty=qty, timestamp_ms=timestamp_ms)


def parse_quote_message(message: dict, symbol: str) -> MarketQuote | None:
    # bookTicker from combined stream has no "e" field, detect by "u" (updateId)
    is_book = message.get("e") == "bookTicker" or ("u" in message and message.get("s") is not None)
    if not is_book:
        return None

    message_symbol = message.get("s")
    if not _symbols_equal(message_symbol, symbol):
        return None

    bid = _optional_float(message.get("b"))
    ask = _optional_float(message.get("a"))
    bid_qty = _optional_float(message.get("B"))
    ask_qty = _optional_float(message.get("A"))
    ts_raw = message.get("E") or message.get("T")
    timestamp_ms = normalize_timestamp_ms(ts_raw) if ts_raw is not None else int(time.time() * 1000)
    mid = (bid + ask) / 2 if bid is not None and ask is not None else None
    return MarketQuote(
        symbol=symbol,
        timestamp=timestamp_ms,
        source="bookTicker",
        bid=bid,
        ask=ask,
        mid=mid,
        bid_qty=bid_qty,
        ask_qty=ask_qty,
        latency_ms=max(0, int(time.time() * 1000) - timestamp_ms),
    )


def _optional_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_historical_candles(
    base_url: str,
    symbol: str,
    timeframe: str,
    limit: int = 500,
) -> list[Candle]:
    binance_symbol = _binance_symbol(symbol)
    url = f"{base_url.rstrip('/')}/api/v3/klines"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Codex-ICT-Terminal/1.0",
    }
    params = {
        "symbol": binance_symbol,
        "interval": timeframe,
        "limit": limit,
    }

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        body = response.json()

    if not isinstance(body, list):
        raise RuntimeError(f"Binance history request failed: {body}")

    candles = [
        Candle(
            timestamp=int(item[0]),
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
            is_closed=True,
        )
        for item in body
    ]
    return sorted(candles, key=lambda candle: candle.timestamp)[-limit:]
