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


async def fetch_option_tickers(
    base_url: str,
    underlying_asset: str = "BTC",
) -> list[dict]:
    url = f"{base_url.rstrip('/')}/v2/tickers"
    headers = {
        "Accept": "application/json",
        "User-Agent": "NEXUS/1.0",
    }
    params = {
        "contract_types": "call_options,put_options",
        "underlying_asset_symbols": underlying_asset,
    }

    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        body = response.json()

    if not body.get("success", True):
        raise RuntimeError(f"Delta options ticker request failed: {body}")

    result = body.get("result", [])
    return result if isinstance(result, list) else []
