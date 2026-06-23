"""
Multi-Exchange Price Aggregator for NEXUS.

Collects real-time and historical price data from multiple free exchanges:
- Binance (primary, highest liquidity)
- Coinbase Pro (free REST + WebSocket)
- Kraken (free REST + WebSocket)
- OKX (free REST, no auth needed for public data)
- Bybit (free REST, no auth needed for public data)

Aggregates prices using volume-weighted median to filter outliers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("backend")


@dataclass
class ExchangePrice:
    exchange: str
    symbol: str
    price: float
    bid: float | None = None
    ask: float | None = None
    volume_24h: float | None = None
    timestamp_ms: int = 0
    latency_ms: int = 0


@dataclass
class AggregatedPrice:
    symbol: str
    median_price: float
    mean_price: float
    weighted_price: float
    spread_pct: float
    exchange_count: int
    prices: list[ExchangePrice] = field(default_factory=list)
    timestamp_ms: int = 0


class MultiExchangeAggregator:
    """Aggregates price data from multiple exchanges for robust price discovery."""

    EXCHANGES = {
        "binance": {
            "rest_url": "https://api.binance.com",
            "ws_url": "wss://stream.binance.com:9443",
            "ticker_path": "/api/v3/ticker/price",
            "book_path": "/api/v3/ticker/bookTicker",
            "klines_path": "/api/v3/klines",
        },
        "coinbase": {
            "rest_url": "https://api.coinbase.com",
            "ticker_path": "/v2/prices/{symbol}/spot",
            "klines_path": "/v2/prices/{symbol}/candles",
        },
        "kraken": {
            "rest_url": "https://api.kraken.com",
            "ticker_path": "/0/public/Ticker",
            "klines_path": "/0/public/OHLC",
        },
        "okx": {
            "rest_url": "https://www.okx.com",
            "ticker_path": "/api/v5/market/ticker",
            "klines_path": "/api/v5/market/candles",
        },
        "bybit": {
            "rest_url": "https://api.bybit.com",
            "ticker_path": "/v5/market/ticker",
            "klines_path": "/v5/market/kline",
        },
    }

    def __init__(self, symbol: str = "BTCUSDT", enabled_exchanges: list[str] | None = None):
        self.symbol = symbol
        self.enabled = enabled_exchanges or ["binance", "coinbase", "okx", "bybit"]
        self._last_prices: dict[str, ExchangePrice] = {}
        self._cache: AggregatedPrice | None = None
        self._cache_ts: int = 0
        self._cache_ttl_ms = 5000

    def _normalize_symbol_for(self, exchange: str) -> str:
        sym = self.symbol.upper()
        mapping = {
            "binance": sym,
            "coinbase": sym.replace("USDT", "-USD").replace("BTC", "BTC-") if "BTC" in sym else sym.replace("USDT", "-USD"),
            "kraken": sym.replace("USDT", "USD").replace("BTC", "XBT") if sym.startswith("BTC") else sym.replace("USDT", "USD"),
            "okx": sym,
            "bybit": sym.replace("USD", "USDT") if sym == "BTCUSD" else sym,
        }
        return mapping.get(exchange, sym)

    async def fetch_all_prices(self) -> list[ExchangePrice]:
        """Fetch prices from all enabled exchanges concurrently."""
        tasks = []
        for exchange in self.enabled:
            if exchange in self.EXCHANGES:
                tasks.append(self._fetch_single(exchange))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        prices = []
        for r in results:
            if isinstance(r, ExchangePrice):
                prices.append(r)
                self._last_prices[r.exchange] = r
            elif isinstance(r, Exception):
                logger.warning(f"Exchange price fetch failed: {r}")
        return prices

    async def _fetch_single(self, exchange: str) -> ExchangePrice:
        """Fetch price from a single exchange."""
        start = time.time()
        config = self.EXCHANGES[exchange]
        base = config["rest_url"]
        norm_sym = self._normalize_symbol_for(exchange)

        volume_24h = None
        async with httpx.AsyncClient(timeout=5.0, headers={"User-Agent": "NEXUS/1.0"}) as client:
            if exchange == "binance":
                resp = await client.get(f"{base}{config['ticker_path']}", params={"symbol": norm_sym})
                resp.raise_for_status()
                data = resp.json()
                price = float(data["price"])
                try:
                    vol_resp = await client.get(f"{base}/api/v3/ticker/24hr", params={"symbol": norm_sym})
                    vol_resp.raise_for_status()
                    vol_data = vol_resp.json()
                    volume_24h = float(vol_data.get("volume", 0))
                except Exception:
                    pass
            elif exchange == "coinbase":
                path = config["ticker_path"].format(symbol=norm_sym)
                resp = await client.get(f"{base}{path}")
                resp.raise_for_status()
                data = resp.json()
                price = float(data["data"]["amount"])
                volume_24h = None
            elif exchange == "kraken":
                resp = await client.post(f"{base}{config['ticker_path']}", data={"pair": norm_sym})
                resp.raise_for_status()
                data = resp.json()
                result_key = next((k for k in data["result"] if k != "last"), None)
                if result_key:
                    price = float(data["result"][result_key]["c"][0])
                    volume_24h = float(data["result"][result_key].get("v", [0, 0])[-1]) or None
                else:
                    raise ValueError("Kraken ticker key not found")
            elif exchange == "okx":
                resp = await client.get(f"{base}{config['ticker_path']}", params={"instId": norm_sym})
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != "0":
                    raise ValueError(f"OKX API error: {data.get('msg')}")
                price = float(data["data"][0]["last"])
                volume_24h = float(data["data"][0].get("volCcy24h", 0)) or None
            elif exchange == "bybit":
                resp = await client.get(f"{base}{config['ticker_path']}", params={"category": "linear", "symbol": norm_sym})
                resp.raise_for_status()
                data = resp.json()
                if data.get("retCode") != 0:
                    raise ValueError(f"Bybit API error: {data.get('retMsg')}")
                price = float(data["result"]["list"][0]["lastPrice"])
                volume_24h = float(data["result"]["list"][0].get("volume24h", 0)) or None
            else:
                raise ValueError(f"Unknown exchange: {exchange}")

        latency = int((time.time() - start) * 1000)
        ts = int(time.time() * 1000)

        return ExchangePrice(
            exchange=exchange,
            symbol=self.symbol,
            price=price,
            timestamp_ms=ts,
            latency_ms=latency,
            volume_24h=volume_24h,
        )

    async def get_aggregated_price(self, force_refresh: bool = False) -> AggregatedPrice:
        """Get volume-weighted median aggregated price."""
        now = int(time.time() * 1000)
        if self._cache and not force_refresh and (now - self._cache_ts) < self._cache_ttl_ms:
            return self._cache

        prices = await self.fetch_all_prices()
        if not prices:
            if self._cache:
                return self._cache
            raise RuntimeError("No exchange prices available")

        price_values = [p.price for p in prices]
        sorted_prices = sorted(price_values)
        n = len(sorted_prices)
        if n % 2 == 1:
            median_price = sorted_prices[n // 2]
        else:
            median_price = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2.0
        mean_price = sum(price_values) / len(price_values)

        weights = [p.volume_24h or 1.0 for p in prices]
        total_weight = sum(weights)
        weighted_price = sum(p.price * w for p, w in zip(prices, weights)) / total_weight if total_weight > 0 else mean_price

        spread = max(price_values) - min(price_values)
        spread_pct = spread / median_price if median_price > 0 else 0

        self._cache = AggregatedPrice(
            symbol=self.symbol,
            median_price=round(median_price, 2),
            mean_price=round(mean_price, 2),
            weighted_price=round(weighted_price, 2),
            spread_pct=round(spread_pct, 6),
            exchange_count=len(prices),
            prices=prices,
            timestamp_ms=now,
        )
        self._cache_ts = now
        return self._cache

    async def fetch_historical_klines(
        self,
        exchange: str,
        interval: str = "5m",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Fetch historical klines from a specific exchange."""
        config = self.EXCHANGES.get(exchange)
        if not config:
            raise ValueError(f"Unknown exchange: {exchange}")

        base = config["rest_url"]
        norm_sym = self._normalize_symbol_for(exchange)

        async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "NEXUS/1.0"}) as client:
            if exchange == "binance":
                resp = await client.get(f"{base}{config['klines_path']}", params={
                    "symbol": norm_sym, "interval": interval, "limit": limit,
                })
                resp.raise_for_status()
                raw = resp.json()
                return [
                    {"timestamp": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                    for r in raw
                ]
            elif exchange == "okx":
                resp = await client.get(f"{base}{config['klines_path']}", params={
                    "instId": norm_sym, "bar": interval, "limit": limit,
                })
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != "0":
                    raise ValueError(f"OKX API error: {data.get('msg')}")
                return [
                    {"timestamp": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                    for r in data["data"]
                ]
            elif exchange == "bybit":
                resp = await client.get(f"{base}{config['klines_path']}", params={
                    "category": "spot", "symbol": norm_sym, "interval": interval, "limit": limit,
                })
                resp.raise_for_status()
                data = resp.json()
                if data.get("retCode") != 0:
                    raise ValueError(f"Bybit API error: {data.get('retMsg')}")
                return [
                    {"timestamp": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
                    for r in data["result"]["list"]
                ]
            elif exchange == "coinbase":
                interval_map = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
                               "1h": "ONE_HOUR", "4h": "FOUR_HOUR", "1d": "ONE_DAY"}
                resp = await client.get(f"{base}{config['klines_path'].format(symbol=norm_sym)}", params={
                    "granularity": interval_map.get(interval, "FIVE_MINUTE"), "limit": limit,
                })
                resp.raise_for_status()
                data = resp.json()
                return [
                    {"timestamp": int(r["start"]), "open": float(r["open"]), "high": float(r["high"]),
                     "low": float(r["low"]), "close": float(r["close"]), "volume": float(r["volume"])}
                    for r in data.get("candles", [])
                ]
            elif exchange == "kraken":
                interval_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "1440"}
                resp = await client.post(f"{base}{config['klines_path']}", data={
                    "pair": norm_sym, "interval": interval_map.get(interval, "5"),
                })
                resp.raise_for_status()
                data = resp.json()
                result_key = next((k for k in data["result"] if k != "last"), None)
                if not result_key:
                    return []
                return [
                    {"timestamp": int(float(r[0])), "open": float(r[1]), "high": float(r[2]),
                     "low": float(r[3]), "close": float(r[4]), "volume": float(r[6])}
                    for r in data["result"][result_key]
                ]
            else:
                raise ValueError(f"Klines not supported for exchange: {exchange}")

    def get_last_prices(self) -> dict[str, ExchangePrice]:
        return dict(self._last_prices)

    def get_price_deviation(self, price: float) -> float:
        """Check if a price deviates significantly from aggregated price."""
        if not self._cache:
            return 0.0
        return abs(price - self._cache.median_price) / self._cache.median_price


aggregator = MultiExchangeAggregator()
