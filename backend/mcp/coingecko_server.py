"""CoinGecko MCP Server - Provides cryptocurrency market data from CoinGecko API."""
from __future__ import annotations

import asyncio
import httpx
import json
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

COINGECKO_API = "https://api.coingecko.com/api/v3"

mcp = FastMCP("coingecko")


# ─── Utility ─────────────────────────────────────────────────────────

async def _get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{COINGECKO_API}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ─── Simple Price ────────────────────────────────────────────────────

@mcp.tool()
async def coingecko_get_price(
    ids: str = "bitcoin",
    vs_currencies: str = "usd",
    include_market_cap: bool = True,
    include_24hr_vol: bool = True,
    include_24hr_change: bool = True,
) -> dict:
    """Get current price and market data for cryptocurrencies.
    
    Args:
        ids: Comma-separated coin IDs (e.g., bitcoin,ethereum,solana)
        vs_currencies: Comma-separated currency codes (e.g., usd,eur,btc)
        include_market_cap: Include market cap data
        include_24hr_vol: Include 24h volume
        include_24hr_change: Include 24h price change percentage
    """
    params = {
        "ids": ids,
        "vs_currencies": vs_currencies,
        "include_market_cap": str(include_market_cap).lower(),
        "include_24hr_vol": str(include_24hr_vol).lower(),
        "include_24hr_change": str(include_24hr_change).lower(),
    }
    data = await _get("/simple/price", params)
    return data


# ─── Market Data ─────────────────────────────────────────────────────

@mcp.tool()
async def coingecko_get_market_data(
    vs_currency: str = "usd",
    order: str = "market_cap_desc",
    per_page: int = 50,
    page: int = 1,
    sparkline: bool = False,
    price_change_percentage: str = "1h,24h,7d",
) -> list[dict]:
    """Get list of cryptocurrencies with market data.
    
    Args:
        vs_currency: Target currency (usd, eur, btc, etc.)
        order: Sort order (market_cap_desc, market_cap_asc, volume_desc, etc.)
        per_page: Results per page (max 250)
        page: Page number
        sparkline: Include 7-day sparkline data
        price_change_percentage: Comma-separated time periods for price change %
    """
    params = {
        "vs_currency": vs_currency,
        "order": order,
        "per_page": min(per_page, 250),
        "page": page,
        "sparkline": str(sparkline).lower(),
        "price_change_percentage": price_change_percentage,
    }
    data = await _get("/coins/markets", params)
    
    return [
        {
            "rank": item.get("market_cap_rank"),
            "id": item.get("id"),
            "symbol": item.get("symbol").upper(),
            "name": item.get("name"),
            "price": _safe_float(item.get("current_price")),
            "market_cap": _safe_float(item.get("market_cap")),
            "volume_24h": _safe_float(item.get("total_volume")),
            "price_change_1h_pct": _safe_float(item.get("price_change_percentage_1h_in_currency")),
            "price_change_24h_pct": _safe_float(item.get("price_change_percentage_24h_in_currency")),
            "price_change_7d_pct": _safe_float(item.get("price_change_percentage_7d_in_currency")),
            "ath": _safe_float(item.get("ath")),
            "ath_change_pct": _safe_float(item.get("ath_change_percentage")),
            "circulating_supply": _safe_float(item.get("circulating_supply")),
            "total_supply": _safe_float(item.get("total_supply")),
            "max_supply": _safe_float(item.get("max_supply")),
        }
        for item in data
    ]


# ─── Coin Details ────────────────────────────────────────────────────

@mcp.tool()
async def coingecko_get_coin_details(
    coin_id: str = "bitcoin",
    localization: bool = False,
    tickers: bool = False,
    market_data: bool = True,
    community_data: bool = True,
    developer_data: bool = False,
) -> dict:
    """Get detailed information about a specific cryptocurrency.
    
    Args:
        coin_id: Coin ID (e.g., bitcoin, ethereum, solana)
        localization: Include localized language data
        tickers: Include exchange ticker data
        market_data: Include market data (price, market cap, volume)
        community_data: Include community stats (Twitter, Reddit, etc.)
        developer_data: Include GitHub developer stats
    """
    params = {
        "localization": str(localization).lower(),
        "tickers": str(tickers).lower(),
        "market_data": str(market_data).lower(),
        "community_data": str(community_data).lower(),
        "developer_data": str(developer_data).lower(),
    }
    data = await _get(f"/coins/{coin_id}", params)
    
    md = data.get("market_data", {})
    return {
        "id": data.get("id"),
        "symbol": data.get("symbol", "").upper(),
        "name": data.get("name"),
        "description": (data.get("description", {}).get("en", "") or "")[:500],
        "homepage": data.get("links", {}).get("homepage", [""])[0],
        "current_price": _safe_float(md.get("current_price", {}).get("usd")),
        "market_cap": _safe_float(md.get("market_cap", {}).get("usd")),
        "market_cap_rank": md.get("market_cap_rank"),
        "total_volume": _safe_float(md.get("total_volume", {}).get("usd")),
        "price_change_24h": _safe_float(md.get("price_change_24h")),
        "price_change_24h_pct": _safe_float(md.get("price_change_percentage_24h")),
        "price_change_7d_pct": _safe_float(md.get("price_change_percentage_7d_in_currency", {}).get("usd")),
        "price_change_30d_pct": _safe_float(md.get("price_change_percentage_30d_in_currency", {}).get("usd")),
        "ath": _safe_float(md.get("ath", {}).get("usd")),
        "ath_date": md.get("ath_date", {}).get("usd"),
        "atl": _safe_float(md.get("atl", {}).get("usd")),
        "atl_date": md.get("atl_date", {}).get("usd"),
        "circulating_supply": _safe_float(md.get("circulating_supply")),
        "total_supply": _safe_float(md.get("total_supply")),
        "max_supply": _safe_float(md.get("max_supply")),
        "roi": md.get("roi"),
        "community": {
            "twitter_followers": data.get("community_data", {}).get("twitter_followers"),
            "reddit_subscribers": data.get("community_data", {}).get("reddit_subscribers"),
            "reddit_active": data.get("community_data", {}).get("reddit_accounts_active_48h"),
        } if community_data else None,
    }


# ─── Market Chart ────────────────────────────────────────────────────

@mcp.tool()
async def coingecko_get_market_chart(
    coin_id: str = "bitcoin",
    vs_currency: str = "usd",
    days: int = 7,
    interval: str = "",
) -> dict:
    """Get historical market data (price, market cap, volume) for a coin.
    
    Args:
        coin_id: Coin ID (e.g., bitcoin, ethereum)
        vs_currency: Target currency (usd, eur, btc)
        days: Number of days of data (1, 7, 14, 30, 90, 180, 365, max)
        interval: Data interval (empty for auto, or "daily", "hourly")
    """
    params = {
        "vs_currency": vs_currency,
        "days": days,
    }
    if interval:
        params["interval"] = interval
    
    data = await _get(f"/coins/{coin_id}/market_chart", params)
    
    prices = data.get("prices", [])
    market_caps = data.get("market_caps", [])
    total_volumes = data.get("total_volumes", [])
    
    return {
        "coin_id": coin_id,
        "currency": vs_currency,
        "days": days,
        "data_points": len(prices),
        "current_price": _safe_float(prices[-1][1]) if prices else 0,
        "current_market_cap": _safe_float(market_caps[-1][1]) if market_caps else 0,
        "current_volume": _safe_float(total_volumes[-1][1]) if total_volumes else 0,
        "price_high": _safe_float(max(p[1] for p in prices)) if prices else 0,
        "price_low": _safe_float(min(p[1] for p in prices)) if prices else 0,
        "price_change_pct": round(
            (prices[-1][1] - prices[0][1]) / prices[0][1] * 100, 3
        ) if len(prices) >= 2 and prices[0][1] > 0 else 0,
        "latest_prices": prices[-10:] if prices else [],
    }


# ─── Global Market Data ──────────────────────────────────────────────

@mcp.tool()
async def coingecko_get_global_data() -> dict:
    """Get global cryptocurrency market overview."""
    data = await _get("/global")
    gd = data.get("data", {})
    return {
        "total_market_cap_usd": _safe_float(gd.get("total_market_cap", {}).get("usd")),
        "total_volume_24h_usd": _safe_float(gd.get("total_volume", {}).get("usd")),
        "btc_dominance_pct": round(gd.get("market_cap_percentage", {}).get("btc", 0), 2),
        "eth_dominance_pct": round(gd.get("market_cap_percentage", {}).get("eth", 0), 2),
        "active_cryptocurrencies": gd.get("active_cryptocurrencies"),
        "markets": gd.get("markets"),
        "market_cap_change_24h_pct": round(gd.get("market_cap_change_percentage_24h_usd", 0), 2),
    }


# ─── Trending ────────────────────────────────────────────────────────

@mcp.tool()
async def coingecko_get_trending() -> dict:
    """Get trending cryptocurrencies on CoinGecko."""
    data = await _get("/search/trending")
    
    coins = []
    for item in data.get("coins", [])[:10]:
        coin = item.get("item", {})
        coins.append({
            "id": coin.get("id"),
            "symbol": coin.get("symbol"),
            "name": coin.get("name"),
            "market_cap_rank": coin.get("market_cap_rank"),
            "price_btc": coin.get("price_btc"),
            "score": coin.get("score"),
        })
    
    return {
        "trending_coins": coins,
        "nfts": data.get("nfts", [])[:5],
    }


# ─── Categories ──────────────────────────────────────────────────────

@mcp.tool()
async def coingecko_get_categories() -> list[dict]:
    """Get list of cryptocurrency categories."""
    data = await _get("/coins/categories/list")
    
    return [
        {
            "id": item.get("category_id"),
            "name": item.get("name"),
        }
        for item in data[:50]
    ]


# ─── Run Server ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
