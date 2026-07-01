"""CoinMarketCap MCP Server - Provides cryptocurrency market data from CoinMarketCap API.
Note: Requires CMC_API_KEY environment variable for authenticated requests."""
from __future__ import annotations

import httpx
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

CMC_API = "https://pro-api.coinmarketcap.com/v1"
CMC_API_KEY = os.environ.get("CMC_API_KEY", "")

mcp = FastMCP("coinmarketcap")


# ─── Utility ─────────────────────────────────────────────────────────

async def _get(path: str, params: dict | None = None) -> Any:
    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{CMC_API}{path}", params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ─── Cryptocurrency Listings ─────────────────────────────────────────

@mcp.tool()
async def cmc_get_listings(
    start: int = 1,
    limit: int = 50,
    sort: str = "market_cap",
    sort_dir: str = "desc",
    convert: str = "USD",
) -> list[dict]:
    """Get latest cryptocurrency listings with market data.
    
    Args:
        start: Start position (1-based)
        limit: Number of results (max 5000)
        sort: Sort field (market_cap, price, volume, etc.)
        sort_dir: Sort direction (asc, desc)
        convert: Convert to currency (USD, EUR, BTC, etc.)
    """
    params = {
        "start": start,
        "limit": min(limit, 5000),
        "sort": sort,
        "sort_dir": sort_dir,
        "convert": convert,
    }
    data = await _get("/cryptocurrency/listings/latest", params)
    
    results = []
    for item in data.get("data", []):
        quote = item.get("quote", {}).get(convert, {})
        results.append({
            "id": item.get("id"),
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "rank": item.get("cmc_rank"),
            "price": _safe_float(quote.get("price")),
            "market_cap": _safe_float(quote.get("market_cap")),
            "volume_24h": _safe_float(quote.get("volume_24h")),
            "volume_change_24h_pct": _safe_float(quote.get("volume_change_24h")),
            "price_change_1h_pct": _safe_float(quote.get("percent_change_1h")),
            "price_change_24h_pct": _safe_float(quote.get("percent_change_24h")),
            "price_change_7d_pct": _safe_float(quote.get("percent_change_7d")),
            "price_change_30d_pct": _safe_float(quote.get("percent_change_30d")),
            "circulating_supply": _safe_float(item.get("circulating_supply")),
            "total_supply": _safe_float(item.get("total_supply")),
            "max_supply": _safe_float(item.get("max_supply")),
            "ath": _safe_float(quote.get("ath_price")),
            "ath_date": quote.get("ath_date"),
        })
    
    return results


# ─── Single Coin Info ────────────────────────────────────────────────

@mcp.tool()
async def cmc_get_coin_info(
    symbol: str = "BTC",
    convert: str = "USD",
) -> dict:
    """Get detailed information about a specific cryptocurrency by symbol.
    
    Args:
        symbol: Cryptocurrency symbol (e.g., BTC, ETH, SOL)
        convert: Convert to currency (USD, EUR, BTC)
    """
    params = {
        "symbol": symbol.upper(),
        "convert": convert,
    }
    data = await _get("/cryptocurrency/quotes/latest", params)
    
    coin_data = data.get("data", {}).get(symbol.upper())
    if not coin_data:
        return {"error": f"Coin {symbol} not found"}
    
    quote = coin_data.get("quote", {}).get(convert, {})
    
    return {
        "id": coin_data.get("id"),
        "symbol": coin_data.get("symbol"),
        "name": coin_data.get("name"),
        "rank": coin_data.get("cmc_rank"),
        "price": _safe_float(quote.get("price")),
        "market_cap": _safe_float(quote.get("market_cap")),
        "volume_24h": _safe_float(quote.get("volume_24h")),
        "price_change_1h_pct": _safe_float(quote.get("percent_change_1h")),
        "price_change_24h_pct": _safe_float(quote.get("percent_change_24h")),
        "price_change_7d_pct": _safe_float(quote.get("percent_change_7d")),
        "price_change_30d_pct": _safe_float(quote.get("percent_change_30d")),
        "circulating_supply": _safe_float(coin_data.get("circulating_supply")),
        "total_supply": _safe_float(coin_data.get("total_supply")),
        "max_supply": _safe_float(coin_data.get("max_supply")),
        "fully_diluted_market_cap": _safe_float(quote.get("fully_diluted_market_cap")),
        "ath": _safe_float(quote.get("ath_price")),
        "ath_date": quote.get("ath_date"),
        "atl": _safe_float(quote.get("atl_price")),
        "atl_date": quote.get("atl_date"),
        "last_updated": coin_data.get("last_updated"),
    }


# ─── OHLCV Historical Data ──────────────────────────────────────────

@mcp.tool()
async def cmc_get_ohlcv(
    symbol: str = "BTC",
    time_start: str = "",
    time_end: str = "",
    convert: str = "USD",
    count: int = 100,
    interval: str = "daily",
) -> list[dict]:
    """Get historical OHLCV (Open, High, Low, Close, Volume) data for a cryptocurrency.
    
    Args:
        symbol: Cryptocurrency symbol (e.g., BTC, ETH)
        time_start: Start time in ISO 8601 format (e.g., 2024-01-01T00:00:00Z)
        time_end: End time in ISO 8601 format
        convert: Convert to currency (USD, EUR, BTC)
        count: Number of data points (max 365 for daily)
        interval: Data interval (hourly, daily)
    """
    params = {
        "symbol": symbol.upper(),
        "convert": convert,
        "count": min(count, 365),
        "interval": interval,
    }
    if time_start:
        params["time_start"] = time_start
    if time_end:
        params["time_end"] = time_end
    
    data = await _get("/cryptocurrency/ohlcv/historical", params)
    
    quotes = data.get("data", {}).get("quotes", [])
    
    return [
        {
            "timestamp": q.get("time_open"),
            "open": _safe_float(q.get("quote", {}).get(convert, {}).get("open")),
            "high": _safe_float(q.get("quote", {}).get(convert, {}).get("high")),
            "low": _safe_float(q.get("quote", {}).get(convert, {}).get("low")),
            "close": _safe_float(q.get("quote", {}).get(convert, {}).get("close")),
            "volume": _safe_float(q.get("quote", {}).get(convert, {}).get("volume")),
            "market_cap": _safe_float(q.get("quote", {}).get(convert, {}).get("market_cap")),
        }
        for q in quotes
    ]


# ─── Global Metrics ──────────────────────────────────────────────────

@mcp.tool()
async def cmc_get_global_metrics(convert: str = "USD") -> dict:
    """Get global cryptocurrency market metrics.
    
    Args:
        convert: Convert to currency (USD, EUR, BTC)
    """
    params = {"convert": convert}
    data = await _get("/global-metrics/quotes/latest", params)
    
    gm = data.get("data", {}).get("quote", {}).get(convert, {})
    
    return {
        "total_market_cap": _safe_float(gm.get("total_market_cap")),
        "total_volume_24h": _safe_float(gm.get("total_volume_24h")),
        "market_cap_dominance": {
            "btc_pct": round(data.get("data", {}).get("btc_dominance", 0), 2),
            "eth_pct": round(data.get("data", {}).get("eth_dominance", 0), 2),
        },
        "active_cryptocurrencies": data.get("data", {}).get("active_cryptocurrencies"),
        "active_market_pairs": data.get("data", {}).get("active_market_pairs"),
        "active_exchanges": data.get("data", {}).get("active_exchanges"),
        "total_market_cap_yesterday": _safe_float(gm.get("total_market_cap_yesterday")),
        "total_volume_yesterday": _safe_float(gm.get("total_volume_24h_yesterday")),
        "market_cap_change_24h_pct": round(
            data.get("data", {}).get("market_cap_change_24h", 0), 2
        ),
        "last_updated": data.get("data", {}).get("last_updated"),
    }


# ─── Market Tickers ──────────────────────────────────────────────────

@mcp.tool()
async def cmc_get_market_tickers(
    symbol: str = "BTC",
    convert: str = "USD",
    limit: int = 20,
) -> list[dict]:
    """Get market tickers (exchange-level trading data) for a cryptocurrency.
    
    Args:
        symbol: Cryptocurrency symbol (e.g., BTC, ETH)
        convert: Convert to currency (USD, EUR, BTC)
        limit: Number of results
    """
    params = {
        "symbol": symbol.upper(),
        "convert": convert,
        "limit": min(limit, 100),
    }
    data = await _get("/cryptocurrency/market-pairs/latest", params)
    
    pairs = data.get("data", {}).get("market_pairs", [])
    
    return [
        {
            "exchange": p.get("exchange", {}).get("name"),
            "pair": p.get("market_pair"),
            "price": _safe_float(p.get("quote", {}).get(convert, {}).get("price")),
            "volume_24h": _safe_float(p.get("quote", {}).get(convert, {}).get("volume_24h")),
            "volume_24h_base": _safe_float(p.get("volume_24h_base")),
            "last_updated": p.get("last_updated"),
        }
        for p in pairs[:limit]
    ]


# ─── Price Conversion ────────────────────────────────────────────────

@mcp.tool()
async def cmc_convert_price(
    symbol: str = "BTC",
    amount: float = 1.0,
    convert: str = "USD",
) -> dict:
    """Convert cryptocurrency amount to fiat or other crypto.
    
    Args:
        symbol: Cryptocurrency symbol to convert from
        amount: Amount to convert
        convert: Target currency (USD, EUR, BTC, etc.)
    """
    params = {
        "symbol": symbol.upper(),
        "amount": amount,
        "convert": convert,
    }
    data = await _get("/tools/price-conversion", params)
    
    quote = data.get("data", {}).get("quote", {}).get(convert, {})
    
    return {
        "from_symbol": data.get("data", {}).get("symbol"),
        "amount": data.get("data", {}).get("amount"),
        "converted_amount": _safe_float(quote.get("price")) * amount,
        "converted_currency": convert,
        "price_per_unit": _safe_float(quote.get("price")),
    }


# ─── Run Server ──────────────────────────────────────────────────────

if __name__ == "__main__":
    if not CMC_API_KEY:
        print("WARNING: CMC_API_KEY environment variable not set. Some tools will fail.")
    mcp.run()
