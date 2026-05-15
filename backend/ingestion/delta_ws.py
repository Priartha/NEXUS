from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass

import websockets

from backend.analysis.pipeline import AnalysisPipeline
from backend.broadcast.ws_manager import ConnectionManager
from backend.config import Settings
from backend.engine.candle_aggregator import normalize_timestamp_ms
from backend.engine.candle_store import CandleStore
from backend.ingestion.delta_rest import fetch_historical_candles
from backend.models.types import MarketQuote, to_wire


@dataclass(frozen=True)
class TradeTick:
    price: float
    qty: float
    timestamp_ms: int


async def seed_historical(
    store: CandleStore,
    pipeline: AnalysisPipeline,
    manager: ConnectionManager,
    config: Settings,
) -> None:
    candles = await fetch_historical_candles(
        base_url=config.rest_base_url,
        symbol=store.symbol,
        timeframe=store.timeframe,
        limit=config.history_seed_candles,
    )
    store.seed(candles, now_ms=int(time.time() * 1000))
    await pipeline.run_async(store, force_full=True)
    payload = pipeline.snapshot(store)
    await manager.broadcast(payload, timeframe=store.timeframe)


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


async def start_delta_stream(
    manager: ConnectionManager,
    stores: dict[str, CandleStore],
    pipelines: dict[str, AnalysisPipeline],
    config: Settings,
) -> None:
    import logging
    logger = logging.getLogger("backend")
    
    logger.info(f"Starting Delta stream for {config.symbol}")
    await seed_all_historical(stores, pipelines, manager, config)

    backoff = config.ws_reconnect_initial_seconds
    last_quote_key: tuple[float | None, ...] | None = None
    while True:
        try:
            logger.info(f"Connecting to Delta WebSocket: {config.ws_url}")
            async with websockets.connect(
                config.ws_url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_queue=1024,
            ) as websocket:
                logger.info("Delta WebSocket connected, sending subscription")
                await websocket.send(json.dumps({"type": "enable_heartbeat"}))
                await websocket.send(
                    json.dumps(
                        {
                            "type": "subscribe",
                            "payload": {
                                "channels": [
                                    {
                                        "name": "trades",
                                        "symbols": [config.symbol],
                                    },
                                    {
                                        "name": "ob_l1",
                                        "symbols": [config.symbol],
                                    },
                                    {
                                        "name": "ticker",
                                        "symbols": [config.symbol],
                                    }
                                ]
                            },
                        }
                    )
                )
                logger.info(f"Subscribed to Delta channels for {config.symbol}")
                await manager.broadcast(
                    {
                        "update_type": "status",
                        "status": "stream_connected",
                        "symbol": config.symbol,
                    }
                )
                backoff = config.ws_reconnect_initial_seconds

                async for raw in websocket:
                    logger.debug(f"Received Delta message: {raw[:200]}...")
                    message = json.loads(raw)
                    message_type = message.get("type")
                    if message_type == "subscriptions":
                        logger.info("Delta subscription response: %s", message)
                        continue
                    if message_type == "heartbeat":
                        continue
                    quote = parse_quote_message(message, config.symbol)
                    if quote is not None:
                        quote_key = _quote_key(quote)
                        if quote_key == last_quote_key:
                            continue
                        last_quote_key = quote_key
                        logger.debug(f"Parsed quote: {quote}")
                        # Feed quote to all pipelines for orderbook analysis
                        for pipeline in pipelines.values():
                            pipeline.add_quote(quote)
                        await manager.broadcast(
                            {
                                "update_type": "quote",
                                "symbol": config.symbol,
                                "quote": to_wire(quote),
                            }
                        )

                    tick = parse_trade_message(message, config.symbol)
                    if tick is None:
                        continue

                    logger.debug(f"Parsed trade tick: {tick}")
                    trade_quote = MarketQuote(
                        symbol=config.symbol,
                        timestamp=tick.timestamp_ms,
                        source="trades",
                        last_trade=tick.price,
                        latency_ms=max(0, int(time.time() * 1000) - tick.timestamp_ms),
                    )
                    # Feed trade quote to pipelines for orderbook analysis
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
                            pipeline = pipelines[timeframe]
                            result = await pipeline.run_async(store)
                            timeframe_updates.append(
                                asyncio.create_task(
                                    manager.broadcast(result, timeframe=timeframe)
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
            logger.info("Delta stream cancelled")
            raise
        except Exception as exc:
            logger.warning("Delta WebSocket disconnected: %s", exc)
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
    message_type = message.get("type")
    if message_type not in {"trades", "all_trades"}:
        return None

    message_symbol = message.get("sy") or message.get("symbol") or message.get("product_symbol")
    if message_symbol and message_symbol != symbol:
        return None

    price_raw = (
        message.get("p")
        or message.get("price")
    )
    size_raw = message.get("s", message.get("size", message.get("qty", 0)))
    ts_raw = message.get("t", message.get("timestamp", message.get("ts")))
    if price_raw is None or ts_raw is None:
        return None

    try:
        price = float(price_raw)
        qty = float(size_raw or 0)
        timestamp_ms = normalize_timestamp_ms(ts_raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or not math.isfinite(qty):
        return None
    if price <= 0 or qty < 0:
        return None
    now_ms = int(time.time() * 1000)
    if timestamp_ms <= 0 or abs(now_ms - timestamp_ms) > 86_400_000:
        return None

    return TradeTick(price=price, qty=qty, timestamp_ms=timestamp_ms)


def parse_quote_message(message: dict, symbol: str) -> MarketQuote | None:
    message_type = message.get("type")
    message_symbol = message.get("sy") or message.get("symbol") or message.get("product_symbol")
    if message_symbol and message_symbol != symbol:
        return None

    now_ms = int(time.time() * 1000)
    if message_type == "ob_l1":
        bid = _optional_float(message.get("bp"))
        ask = _optional_float(message.get("ap"))
        ts_raw = message.get("ts") or message.get("timestamp")
        timestamp_ms = normalize_timestamp_ms(ts_raw) if ts_raw is not None else now_ms
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        return MarketQuote(
            symbol=symbol,
            timestamp=timestamp_ms,
            source="ob_l1",
            bid=bid,
            ask=ask,
            mid=mid,
            latency_ms=max(0, now_ms - timestamp_ms),
        )

    if message_type in {"ticker", "v2/ticker"}:
        ts_raw = message.get("ts") or message.get("timestamp")
        timestamp_ms = normalize_timestamp_ms(ts_raw) if ts_raw is not None else now_ms
        mark_price = _optional_float(message.get("mark_price") or message.get("m"))
        spot_price = _optional_float(message.get("spot_price") or message.get("sp"))
        last_trade = _optional_float(message.get("close") or message.get("c") or message.get("p"))
        return MarketQuote(
            symbol=symbol,
            timestamp=timestamp_ms,
            source=message_type,
            last_trade=last_trade,
            mark_price=mark_price,
            spot_price=spot_price,
            latency_ms=max(0, now_ms - timestamp_ms),
        )

    return None


def _optional_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_key(quote: MarketQuote) -> tuple[float | None, ...]:
    return (
        quote.bid,
        quote.ask,
        quote.mid,
        quote.last_trade,
        quote.mark_price,
        quote.spot_price,
    )
