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

    if not body.get("success", True):
        raise RuntimeError(f"Delta history request failed: {body}")

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
        for item in body.get("result", [])
    ]
    return sorted(candles, key=lambda candle: candle.timestamp)[-limit:]


async def fetch_futures_funding(
    base_url: str,
    product_id: int = 372,
) -> dict:
    url = f"{base_url.rstrip('/')}/v2/ticker"
    headers = {
        "Accept": "application/json",
        "User-Agent": "NEXUS/1.0",
    }
    params = {"product_id": product_id}

    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        body = response.json()

    if not body.get("success", True):
        raise RuntimeError(f"Delta ticker request failed: {body}")

    result = body.get("result", {})
    return {
        "funding_rate": float(result.get("funding_rate", 0)),
        "mark_price": float(result.get("mark_price", 0)),
        "spot_price": float(result.get("spot_price", 0)),
        "volume_24h": float(result.get("volume_24h", 0)),
        "next_funding_timestamp": int(result.get("next_funding_timestamp", 0) or 0),
    }


async def fetch_futures_oi(
    base_url: str,
    product_id: int = 372,
) -> dict:
    url = f"{base_url.rstrip('/')}/v2/products/{product_id}/open_interest"
    headers = {
        "Accept": "application/json",
        "User-Agent": "NEXUS/1.0",
    }

    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        body = response.json()

    if not body.get("success", True):
        raise RuntimeError(f"Delta OI request failed: {body}")

    result = body.get("result", {})
    return {
        "open_interest": float(result.get("open_interest", 0)),
        "change_pct": float(result.get("change_pct", 0)),
    }


async def fetch_liquidations(
    base_url: str,
    product_id: int = 372,
    limit: int = 50,
) -> list[dict]:
    url = f"{base_url.rstrip('/')}/v2/liquidations"
    headers = {
        "Accept": "application/json",
        "User-Agent": "NEXUS/1.0",
    }
    params = {"product_id": product_id, "limit": limit}

    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        body = response.json()

    if not body.get("success", True):
        raise RuntimeError(f"Delta liquidations request failed: {body}")

    result = body.get("result", [])
    return result if isinstance(result, list) else []
