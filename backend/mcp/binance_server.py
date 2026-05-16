"""Binance MCP Server - Provides market data tools for AI analysis."""
from __future__ import annotations

import asyncio
import httpx
import json
import math
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

BINANCE_REST = "https://api.binance.com"
BINANCE_WS = "wss://stream.binance.com:9443/ws"

mcp = FastMCP("binance-crypto")


# ─── Utility ─────────────────────────────────────────────────────────

async def _get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{BINANCE_REST}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ─── Connectivity ────────────────────────────────────────────────────

@mcp.tool()
async def binance_ping() -> dict:
    """Test connectivity to Binance API server."""
    data = await _get("/api/v3/ping")
    return {"status": "ok", "response": data}


@mcp.tool()
async def binance_server_time() -> dict:
    """Get current server time from Binance."""
    data = await _get("/api/v3/time")
    return {
        "server_time_ms": data.get("serverTime"),
        "server_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(data.get("serverTime", 0) / 1000)),
    }


# ─── Price Data ──────────────────────────────────────────────────────

@mcp.tool()
async def binance_get_price(symbol: str = "BTCUSDT") -> dict:
    """Get current price for a trading pair.
    
    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT, ETHUSDT)
    """
    data = await _get("/api/v3/ticker/price", {"symbol": symbol.upper()})
    return {
        "symbol": data.get("symbol"),
        "price": _safe_float(data.get("price")),
        "timestamp_ms": int(time.time() * 1000),
    }


@mcp.tool()
async def binance_get_all_prices() -> list[dict]:
    """Get current prices for all trading pairs on Binance."""
    data = await _get("/api/v3/ticker/price")
    return [
        {"symbol": item["symbol"], "price": _safe_float(item["price"])}
        for item in data
    ]


@mcp.tool()
async def binance_get_24hr_ticker(symbol: str = "BTCUSDT") -> dict:
    """Get 24-hour price change statistics for a trading pair.
    
    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
    """
    data = await _get("/api/v3/ticker/24hr", {"symbol": symbol.upper()})
    return {
        "symbol": data.get("symbol"),
        "price_change": _safe_float(data.get("priceChange")),
        "price_change_pct": _safe_float(data.get("priceChangePercent")),
        "high_24h": _safe_float(data.get("highPrice")),
        "low_24h": _safe_float(data.get("lowPrice")),
        "volume_24h": _safe_float(data.get("volume")),
        "quote_volume_24h": _safe_float(data.get("quoteVolume")),
        "trades_24h": data.get("count"),
        "last_price": _safe_float(data.get("lastPrice")),
    }


# ─── Order Book ──────────────────────────────────────────────────────

@mcp.tool()
async def binance_get_orderbook(symbol: str = "BTCUSDT", depth: int = 20) -> dict:
    """Get current order book snapshot.
    
    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        depth: Order book depth (5, 10, 20, 50, 100, 500, 1000, 5000)
    """
    valid_depths = [5, 10, 20, 50, 100, 500, 1000, 5000]
    depth = min(valid_depths, key=lambda x: abs(x - depth))
    data = await _get("/api/v3/depth", {"symbol": symbol.upper(), "limit": depth})
    
    bids = [{"price": _safe_float(b[0]), "qty": _safe_float(b[1])} for b in data.get("bids", [])]
    asks = [{"price": _safe_float(a[0]), "qty": _safe_float(a[1])} for a in data.get("asks", [])]
    
    spread = asks[0]["price"] - bids[0]["price"] if asks and bids else 0
    spread_pct = (spread / bids[0]["price"] * 100) if bids[0]["price"] > 0 else 0
    
    return {
        "symbol": data.get("symbol"),
        "last_update_id": data.get("lastUpdateId"),
        "bids": bids,
        "asks": asks,
        "spread": round(spread, 2),
        "spread_pct": round(spread_pct, 4),
        "mid_price": round((bids[0]["price"] + asks[0]["price"]) / 2, 2) if bids and asks else 0,
    }


# ─── Historical Candles (OHLCV) ──────────────────────────────────────

@mcp.tool()
async def binance_get_candles(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 500,
) -> list[dict]:
    """Get historical OHLCV candlestick data.
    
    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        interval: Candle interval (1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M)
        limit: Number of candles (max 1000)
    """
    valid_intervals = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
    if interval not in valid_intervals:
        return {"error": f"Invalid interval. Must be one of: {valid_intervals}"}
    
    limit = min(limit, 1000)
    data = await _get("/api/v3/klines", {"symbol": symbol.upper(), "interval": interval, "limit": limit})
    
    candles = []
    for item in data:
        candles.append({
            "timestamp": item[0],
            "open": _safe_float(item[1]),
            "high": _safe_float(item[2]),
            "low": _safe_float(item[3]),
            "close": _safe_float(item[4]),
            "volume": _safe_float(item[5]),
            "close_time": item[6],
            "quote_volume": _safe_float(item[7]),
            "trades": item[8],
            "taker_buy_base": _safe_float(item[9]),
            "taker_buy_quote": _safe_float(item[10]),
        })
    return candles


# ─── Recent Trades ───────────────────────────────────────────────────

@mcp.tool()
async def binance_get_recent_trades(symbol: str = "BTCUSDT", limit: int = 50) -> list[dict]:
    """Get recent trades for a trading pair.
    
    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        limit: Number of recent trades (max 1000)
    """
    limit = min(limit, 1000)
    data = await _get("/api/v3/trades", {"symbol": symbol.upper(), "limit": limit})
    
    return [
        {
            "id": item.get("id"),
            "price": _safe_float(item.get("price")),
            "qty": _safe_float(item.get("qty")),
            "time": item.get("time"),
            "is_buyer_maker": item.get("isBuyerMaker"),
        }
        for item in data
    ]


# ─── Exchange Info ───────────────────────────────────────────────────

@mcp.tool()
async def binance_get_exchange_info(symbol: str | None = None) -> dict:
    """Get exchange trading rules and symbol information.
    
    Args:
        symbol: Optional trading pair symbol to filter (e.g., BTCUSDT)
    """
    params = {"symbol": symbol.upper()} if symbol else {}
    data = await _get("/api/v3/exchangeInfo", params)
    
    symbols = data.get("symbols", [])
    if symbol:
        symbols = [s for s in symbols if s.get("symbol") == symbol.upper()]
    
    return {
        "timezone": data.get("timezone"),
        "server_time": data.get("serverTime"),
        "rate_limits": data.get("rateLimits", []),
        "symbols_count": len(symbols),
        "symbols": [
            {
                "symbol": s.get("symbol"),
                "status": s.get("status"),
                "base_asset": s.get("baseAsset"),
                "quote_asset": s.get("quoteAsset"),
                "min_qty": _safe_float(next((f.get("minQty") for f in s.get("filters", []) if f.get("filterType") == "LOT_SIZE"), 0)),
                "min_notional": _safe_float(next((f.get("minNotional") for f in s.get("filters", []) if f.get("filterType") == "MIN_NOTIONAL"), 0)),
                "tick_size": _safe_float(next((f.get("tickSize") for f in s.get("filters", []) if f.get("filterType") == "PRICE_FILTER"), 0)),
            }
            for s in symbols[:50]  # Limit to first 50 for readability
        ],
    }


# ─── Technical Analysis Helpers ──────────────────────────────────────

@mcp.tool()
async def binance_get_analysis(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 100,
) -> dict:
    """Get comprehensive market analysis including price, candles, and basic indicators.
    
    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        interval: Candle interval
        limit: Number of candles for analysis
    """
    # Fetch candles
    candles = await binance_get_candles(symbol, interval, limit)
    if isinstance(candles, dict) and "error" in candles:
        return candles
    
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    
    if len(closes) < 20:
        return {"error": "Not enough data for analysis"}
    
    # Calculate basic indicators
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-min(50, len(closes)):]) / min(50, len(closes))
    
    # RSI calculation
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    
    avg_gain = sum(gains[-14:]) / 14 if len(gains) >= 14 else sum(gains) / len(gains)
    avg_loss = sum(losses[-14:]) / 14 if len(losses) >= 14 else sum(losses) / len(losses)
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs))
    
    # Volatility (ATR approximation)
    atr_values = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - candles[i-1]["close"]),
            abs(candles[i]["low"] - candles[i-1]["close"]),
        )
        atr_values.append(tr)
    atr14 = sum(atr_values[-14:]) / 14 if len(atr_values) >= 14 else sum(atr_values) / len(atr_values)
    
    # Volume analysis
    avg_volume = sum(volumes[-20:]) / 20
    current_volume = volumes[-1]
    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
    
    # Trend detection
    current_price = closes[-1]
    trend = "bullish" if current_price > sma20 > sma50 else "bearish" if current_price < sma20 < sma50 else "neutral"
    
    return {
        "symbol": symbol,
        "interval": interval,
        "current_price": current_price,
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "rsi14": round(rsi, 2),
        "atr14": round(atr14, 2),
        "volume_ratio": round(volume_ratio, 2),
        "trend": trend,
        "candles_analyzed": len(candles),
        "price_change_pct": round((closes[-1] - closes[0]) / closes[0] * 100, 3) if closes[0] > 0 else 0,
        "high": round(max(c["high"] for c in candles), 2),
        "low": round(min(c["low"] for c in candles), 2),
    }


# ─── Run Server ──────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
