from __future__ import annotations

import time

import httpx

from backend.engine.candle_aggregator import timeframe_to_ms
from backend.models.types import Candle


async def fetch_historical_candles(
    base_url: str,
    symbol: str,
    timeframe: str,
    limit: int = 500,
) -> list[Candle]:
    period_seconds = timeframe_to_ms(timeframe) // 1000
    end = int(time.time())
    start = end - (period_seconds * limit * 2)
    url = f"{base_url.rstrip('/')}/v2/history/candles"
    headers = {
        "Accept": "application/json",
        "User-Agent": "NEXUS/1.0",
    }
    params = {
        "resolution": timeframe,
        "symbol": symbol,
        "start": start,
        "end": end,
    }

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        body = response.json()

    result = body.get("result", body) if isinstance(body, dict) else body
    if not isinstance(result, list):
        raise RuntimeError(f"Delta history request failed: unexpected response")

    candles = [
        Candle(
            timestamp=int(item["time"]) * 1000,
            open=float(item["open"]),
            high=float(item["high"]),
            low=float(item["low"]),
            close=float(item["close"]),
            volume=float(item.get("volume") or 0),
            is_closed=True,
        )
        for item in result
    ]
    return sorted(candles, key=lambda candle: candle.timestamp)[-limit:]


async def fetch_ticker(
    base_url: str,
    product_id: int = 27,
) -> dict:
    url = f"{base_url.rstrip('/')}/v2/tickers/{product_id}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "NEXUS/1.0",
    }

    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        body = response.json()

    result = body.get("result", body) if isinstance(body, dict) else body
    if not isinstance(result, dict) or "product_id" not in result:
        raise RuntimeError(f"Delta ticker request failed: unexpected response format")

    return {
        "funding_rate": float(result.get("funding_rate", 0)),
        "mark_price": float(result.get("mark_price", 0)),
        "spot_price": float(result.get("spot_price", 0)),
        "volume_24h": float(result.get("volume", 0)),
        "open_interest": float(result.get("oi", 0)),
        "next_funding_timestamp": int(result.get("timestamp", 0)) if result.get("timestamp") else 0,
    }


async def fetch_futures_funding(
    base_url: str,
    product_id: int = 27,
) -> dict:
    return await fetch_ticker(base_url, product_id)


async def fetch_futures_oi(
    base_url: str,
    product_id: int = 27,
) -> dict:
    ticker = await fetch_ticker(base_url, product_id)
    return {
        "open_interest": ticker.get("open_interest", 0),
        "change_pct": 0.0,
    }


async def fetch_liquidations(
    base_url: str,
    product_id: int = 27,
    limit: int = 50,
) -> list[dict]:
    return []
