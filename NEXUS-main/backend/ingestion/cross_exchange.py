"""
Cross-Exchange BTCUSD Data Aggregator.

Fetches BTCUSD perpetual futures data from multiple exchanges:
  - Binance
  - Bybit
  - OKX
  - Deribit
  - Kraken

Provides:
  - Price basis (difference between exchanges)
  - Funding rate comparison
  - Volume-weighted median price
  - Arbitrage opportunity detection
  - Basis trade signals (long on cheapest, short on most expensive)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ExchangeTicker:
    exchange: str
    symbol: str
    bid: float
    ask: float
    last: float
    funding_rate: float
    open_interest: float
    volume_24h: float
    timestamp: int
    latency_ms: int | None = None


@dataclass
class CrossExchangeSnapshot:
    timestamp: int
    tickers: list[ExchangeTicker]
    median_price: float
    mean_price: float
    min_price: float
    max_price: float
    spread_pct: float  # (max - min) / median
    volume_weighted_price: float
    total_volume_24h: float
    exchange_count: int


@dataclass
class BasisSignal:
    timestamp: int
    long_exchange: str
    short_exchange: str
    basis_pct: float
    strength: float
    confidence: float
    description: str


class CrossExchangeAggregator:
    """
    Aggregates BTCUSD perpetual prices across multiple exchanges.

    Updates every N seconds. Provides volume-weighted median price
    as the most reliable single BTCUSD price estimate.
    """

    def __init__(
        self,
        refresh_interval: float = 15.0,
        symbol: str = "BTCUSD",
        exchanges: list[str] | None = None,
        basis_threshold_pct: float = 0.05,
    ) -> None:
        self.refresh_interval = refresh_interval
        self.symbol = symbol
        self.basis_threshold_pct = basis_threshold_pct

        self._exchanges = exchanges or ["binance", "bybit", "okx", "deribit", "kraken"]
        self._cache: CrossExchangeSnapshot | None = None
        self._history: deque[CrossExchangeSnapshot] = deque(maxlen=500)
        self._basis_signals: deque[BasisSignal] = deque(maxlen=50)
        self._last_refresh: float = 0

    async def refresh(self) -> CrossExchangeSnapshot:
        """Fetch latest tickers from all exchanges."""
        now = time.time()
        if self._cache and (now - self._last_refresh) < self.refresh_interval:
            return self._cache

        tasks = [self._fetch_exchange(ex) for ex in self._exchanges]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        tickers: list[ExchangeTicker] = []
        for result in results:
            if isinstance(result, ExchangeTicker):
                tickers.append(result)
            elif isinstance(result, Exception):
                logger.debug(f"Cross-exchange fetch failed: {result}")

        if not tickers:
            if self._cache:
                return self._cache
            return self._empty_snapshot()

        prices = np.array([t.last for t in tickers if t.last > 0 and t.volume_24h > 0])
        volumes = np.array([t.volume_24h for t in tickers if t.last > 0 and t.volume_24h > 0])

        if len(prices) == 0:
            prices = np.array([t.last for t in tickers if t.last > 0])
            volumes = np.array([t.volume_24h for t in tickers if t.last > 0])

        median_price = float(np.median(prices)) if len(prices) > 0 else 0.0
        mean_price = float(np.mean(prices)) if len(prices) > 0 else 0.0
        min_price = float(np.min(prices)) if len(prices) > 0 else 0.0
        max_price = float(np.max(prices)) if len(prices) > 0 else 0.0

        # Volume-weighted price (only if shapes match)
        if len(prices) > 0 and len(prices) == len(volumes) and np.sum(volumes) > 0:
            vwap = float(np.average(prices, weights=volumes))
        else:
            vwap = median_price

        spread = ((max_price - min_price) / median_price * 100) if median_price > 0 else 0.0

        snapshot = CrossExchangeSnapshot(
            timestamp=int(time.time() * 1000),
            tickers=tickers,
            median_price=round(median_price, 2),
            mean_price=round(mean_price, 2),
            min_price=round(min_price, 2),
            max_price=round(max_price, 2),
            spread_pct=round(spread, 4),
            volume_weighted_price=round(vwap, 2),
            total_volume_24h=round(float(np.sum(volumes)), 2),
            exchange_count=len(tickers),
        )

        self._cache = snapshot
        self._history.append(snapshot)
        self._last_refresh = now
        return snapshot

    async def _fetch_exchange(self, exchange: str) -> ExchangeTicker:
        """Fetch ticker from a specific exchange."""
        import httpx

        start = time.time()
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                if exchange == "binance":
                    resp = await client.get("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=BTCUSDT")
                    data = resp.json()
                    return ExchangeTicker(
                        exchange="binance",
                        symbol="BTCUSDT",
                        bid=float(data.get("bidPrice", 0)),
                        ask=float(data.get("askPrice", 0)),
                        last=float(data["lastPrice"]),
                        funding_rate=float(data.get("lastFundingRate", 0)),
                        open_interest=float(data.get("openInterest", 0)),
                        volume_24h=float(data.get("quoteVolume", 0)),
                        timestamp=int(time.time() * 1000),
                        latency_ms=int((time.time() - start) * 1000),
                    )

                elif exchange == "bybit":
                    resp = await client.get("https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT")
                    data = resp.json()
                    ticker = data["result"]["list"][0]
                    return ExchangeTicker(
                        exchange="bybit",
                        symbol="BTCUSDT",
                        bid=float(ticker.get("bidPrice", 0)),
                        ask=float(ticker.get("askPrice", 0)),
                        last=float(ticker["lastPrice"]),
                        funding_rate=float(ticker.get("fundingRate", 0)),
                        open_interest=float(ticker.get("openInterest", 0)),
                        volume_24h=float(ticker.get("volume24h", 0)),
                        timestamp=int(time.time() * 1000),
                        latency_ms=int((time.time() - start) * 1000),
                    )

                elif exchange == "okx":
                    resp = await client.get("https://www.okx.com/api/v5/market/ticker?instId=BTC-USD-SWAP")
                    data = resp.json()
                    ticker = data["data"][0]
                    return ExchangeTicker(
                        exchange="okx",
                        symbol="BTC-USD-SWAP",
                        bid=float(ticker.get("bidPx", 0)),
                        ask=float(ticker.get("askPx", 0)),
                        last=float(ticker["last"]),
                        funding_rate=float(ticker.get("fundingRate", 0)),
                        open_interest=float(ticker.get("openInterest", 0)),
                        volume_24h=float(ticker.get("volCcy24h", 0)),
                        timestamp=int(time.time() * 1000),
                        latency_ms=int((time.time() - start) * 1000),
                    )

                elif exchange == "deribit":
                    resp = await client.get("https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd")
                    data = resp.json()
                    price = float(data["result"]["index_price"])
                    return ExchangeTicker(
                        exchange="deribit",
                        symbol="BTC-USD",
                        bid=price * 0.999,
                        ask=price * 1.001,
                        last=price,
                        funding_rate=0.0,
                        open_interest=0.0,
                        volume_24h=0.0,
                        timestamp=int(time.time() * 1000),
                        latency_ms=int((time.time() - start) * 1000),
                    )

                elif exchange == "kraken":
                    resp = await client.get("https://api.kraken.com/0/public/Ticker?pair=XBTUSD")
                    data = resp.json()
                    ticker = data["result"]["XXBTZUSD"]
                    last = float(ticker["c"][0])
                    bid = float(ticker["b"][0])
                    ask = float(ticker["a"][0])
                    return ExchangeTicker(
                        exchange="kraken",
                        symbol="XBT/USD",
                        bid=bid,
                        ask=ask,
                        last=last,
                        funding_rate=0.0,
                        open_interest=0.0,
                        volume_24h=float(ticker["v"][1]),
                        timestamp=int(time.time() * 1000),
                        latency_ms=int((time.time() - start) * 1000),
                    )

                else:
                    raise ValueError(f"Unknown exchange: {exchange}")

            except Exception as e:
                raise RuntimeError(f"{exchange} fetch failed: {e}")

    def detect_basis(self) -> list[BasisSignal]:
        """Detect arbitrage opportunities across exchanges."""
        snap = self._cache
        if not snap or len(snap.tickers) < 2:
            return []

        signals: list[BasisSignal] = []

        for i, t1 in enumerate(snap.tickers):
            for t2 in snap.tickers[i + 1:]:
                if t1.last <= 0 or t2.last <= 0:
                    continue
                basis = (t1.last - t2.last) / t2.last * 100
                if abs(basis) < self.basis_threshold_pct:
                    continue

                long_ex = t1.exchange if basis < 0 else t2.exchange
                short_ex = t2.exchange if basis < 0 else t1.exchange
                strength = min(abs(basis) / 0.5, 1.0)
                confidence = min(strength * (1 - snap.spread_pct / 10), 0.95)

                sig = BasisSignal(
                    timestamp=int(time.time() * 1000),
                    long_exchange=long_ex,
                    short_exchange=short_ex,
                    basis_pct=round(abs(basis), 4),
                    strength=round(strength, 4),
                    confidence=round(confidence, 4),
                    description=f"Basis: long {long_ex} / short {short_ex} ({abs(basis):.3f}%)",
                )
                signals.append(sig)
                self._basis_signals.append(sig)

        signals.sort(key=lambda s: s.strength, reverse=True)
        return signals[:5]

    def _empty_snapshot(self) -> CrossExchangeSnapshot:
        return CrossExchangeSnapshot(
            timestamp=int(time.time() * 1000),
            tickers=[],
            median_price=0.0,
            mean_price=0.0,
            min_price=0.0,
            max_price=0.0,
            spread_pct=0.0,
            volume_weighted_price=0.0,
            total_volume_24h=0.0,
            exchange_count=0,
        )

    def get_state(self) -> dict:
        return {
            "exchanges": self._exchanges,
            "cached": self._cache is not None,
            "last_refresh": self._last_refresh,
            "history_length": len(self._history),
            "exchange_count": self._cache.exchange_count if self._cache else 0,
            "median_price": self._cache.median_price if self._cache else 0.0,
            "spread_pct": self._cache.spread_pct if self._cache else 0.0,
            "recent_basis_signals": [
                {"exchanges": f"{s.long_exchange}/{s.short_exchange}", "basis": round(s.basis_pct, 3)}
                for s in list(self._basis_signals)[-5:]
            ],
        }


# Singleton
cross_exchange = CrossExchangeAggregator()
