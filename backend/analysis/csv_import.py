"""
CSV Data Import Utility
Supports multiple formats: Binance, TradingView, generic OHLCV, and custom mappings.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from backend.models.types import Candle


# Column name mappings for different formats
FORMAT_MAPPINGS = {
    "binance": {
        "timestamp": "open_time",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    },
    "tradingview": {
        "timestamp": "time",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    },
    "coinmarketcap": {
        "timestamp": "timeOpen",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    },
    "coingecko": {
        "timestamp": "date",
        "open": None,
        "high": None,
        "low": None,
        "close": "current_price",
        "volume": "total_volume",
    },
    "bitfinex": {
        "timestamp": "date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "price",
        "volume": "vol.",
    },
    "generic": {
        "timestamp": None,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": None,
    },
}


def _parse_timestamp(value: str) -> int | None:
    """Parse various timestamp formats to milliseconds."""
    value = value.strip()
    if not value:
        return None

    # Numeric timestamp (milliseconds)
    try:
        ts = int(value)
        if ts > 1e12:
            return ts
        elif ts > 1e9:
            return ts * 1000
        return None
    except ValueError:
        pass

    # Float timestamp
    try:
        ts = float(value)
        if ts > 1e12:
            return int(ts)
        elif ts > 1e9:
            return int(ts * 1000)
        return None
    except ValueError:
        pass

    # Date string formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.year < 2000:
                continue
            dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue

    return None


def _parse_float(value: str) -> float | None:
    """Parse a float value, handling commas, whitespace, and K/M suffixes."""
    if not value or value.strip() in ("", "null", "None", "N/A", "--"):
        return None
    try:
        cleaned = value.strip().replace(",", "")
        if cleaned.endswith("K"):
            return float(cleaned[:-1]) * 1000
        elif cleaned.endswith("M"):
            return float(cleaned[:-1]) * 1_000_000
        elif cleaned.endswith("B"):
            return float(cleaned[:-1]) * 1_000_000_000
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def _detect_format(headers: list[str]) -> str:
    """Auto-detect CSV format based on column headers."""
    lower_headers = [h.lower().strip() for h in headers]

    # Check for Bitfinex/Investing.com format (has "vol." and "change %")
    if "vol." in lower_headers and "change %" in lower_headers:
        return "bitfinex"

    # Check for TradingView format
    if "time" in lower_headers:
        return "tradingview"

    # Check for Binance format
    if "open_time" in lower_headers:
        return "binance"

    # Check for CoinMarketCap
    if any("open*" in h for h in lower_headers):
        return "coinmarketcap"

    # CoinMarketCap alternative format (timeOpen, timeClose, etc.)
    if "timeopen" in lower_headers and "timeclose" in lower_headers:
        return "coinmarketcap"

    # Check for CoinGecko
    if "current_price" in lower_headers:
        return "coingecko"

    # Generic detection by common names
    has_timestamp = any(h in lower_headers for h in ["timestamp", "time", "date", "datetime", "open_time"])
    has_open = any(h in lower_headers for h in ["open", "open*"])
    has_close = any(h in lower_headers for h in ["close", "close*", "current_price", "price"])

    if has_timestamp and has_open and has_close:
        return "generic"

    return "unknown"


def _find_column(headers: list[str], possible_names: list[str]) -> int | None:
    """Find column index by matching possible names."""
    lower_headers = [h.lower().strip() for h in headers]
    for name in possible_names:
        if name.lower() in lower_headers:
            return lower_headers.index(name.lower())
    return None


def parse_csv(
    content: str,
    format_type: str = "auto",
    custom_mapping: dict[str, str] | None = None,
    timeframe: str = "5m",
    symbol: str = "BTCUSDT",
) -> dict:
    """
    Parse CSV content into Candle objects.

    Args:
        content: Raw CSV string
        format_type: "auto", "binance", "tradingview", "coinmarketcap", "coingecko", "generic"
        custom_mapping: Custom column mapping {field: column_name}
        timeframe: Timeframe for the data
        symbol: Trading pair symbol

    Returns:
        {
            "success": bool,
            "candles": list[Candle],
            "count": int,
            "errors": list[str],
            "warnings": list[str],
            "metadata": dict,
        }
    """
    errors: list[str] = []
    warnings: list[str] = []
    candles: list[Candle] = []

    # Auto-detect delimiter
    sample_lines = content.split('\n')[:5]
    delimiter = ','
    for line in sample_lines:
        if ';' in line and ',' not in line:
            delimiter = ';'
            break
        elif '\t' in line:
            delimiter = '\t'
            break

    try:
        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows = list(reader)
    except Exception as e:
        return {"success": False, "candles": [], "count": 0, "errors": [f"CSV parse error: {e}"], "warnings": [], "metadata": {}}

    if not rows:
        return {"success": False, "candles": [], "count": 0, "errors": ["Empty CSV file"], "warnings": [], "metadata": {}}

    # Detect headers
    first_row = rows[0]
    headers = first_row

    # Check if first row is headers or data
    has_headers = False
    try:
        float(first_row[1])
        float(first_row[2])
    except (ValueError, IndexError):
        has_headers = True

    if has_headers:
        data_rows = rows[1:]
        if format_type == "auto":
            format_type = _detect_format(headers)
    else:
        data_rows = rows
        format_type = "generic"

    if format_type == "unknown":
        return {"success": False, "candles": [], "count": 0, "errors": ["Cannot detect CSV format. Use a supported format or provide custom mapping."], "warnings": [], "metadata": {}}

    # Build column mapping
    mapping = FORMAT_MAPPINGS.get(format_type, FORMAT_MAPPINGS["generic"]).copy()
    if custom_mapping:
        mapping.update(custom_mapping)

    # Find column indices
    if has_headers:
        col_indices = {}
        for field, col_name in mapping.items():
            if col_name:
                idx = _find_column(headers, [col_name])
                if idx is not None:
                    col_indices[field] = idx
                else:
                    warnings.append(f"Column '{col_name}' not found for field '{field}'")
            else:
                col_indices[field] = None
    else:
        # Assume standard order: timestamp, open, high, low, close, volume
        col_indices = {
            "timestamp": 0 if len(first_row) > 0 else None,
            "open": 1 if len(first_row) > 1 else None,
            "high": 2 if len(first_row) > 2 else None,
            "low": 3 if len(first_row) > 3 else None,
            "close": 4 if len(first_row) > 4 else None,
            "volume": 5 if len(first_row) > 5 else None,
        }

    # Parse rows
    skipped = 0
    for row_idx, row in enumerate(data_rows):
        if not row or all(c.strip() == "" for c in row):
            continue

        try:
            # Parse timestamp
            ts_idx = col_indices.get("timestamp")
            if ts_idx is not None and ts_idx < len(row):
                timestamp = _parse_timestamp(row[ts_idx])
            else:
                # Generate timestamp if missing (sequential)
                timestamp = None

            if timestamp is None:
                skipped += 1
                continue

            # Parse OHLCV
            open_idx = col_indices.get("open")
            high_idx = col_indices.get("high")
            low_idx = col_indices.get("low")
            close_idx = col_indices.get("close")
            volume_idx = col_indices.get("volume")

            open_price = _parse_float(row[open_idx]) if open_idx is not None and open_idx < len(row) else None
            high_price = _parse_float(row[high_idx]) if high_idx is not None and high_idx < len(row) else None
            low_price = _parse_float(row[low_idx]) if low_idx is not None and low_idx < len(row) else None
            close_price = _parse_float(row[close_idx]) if close_idx is not None and close_idx < len(row) else None
            volume = _parse_float(row[volume_idx]) if volume_idx is not None and volume_idx < len(row) else 0.0

            # Validate required fields
            if open_price is None or close_price is None:
                skipped += 1
                continue

            # Fill missing high/low
            if high_price is None:
                high_price = max(open_price, close_price)
            if low_price is None:
                low_price = min(open_price, close_price)

            # Validate OHLC
            if high_price < max(open_price, close_price):
                high_price = max(open_price, close_price)
            if low_price > min(open_price, close_price):
                low_price = min(open_price, close_price)

            candle = Candle(
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume or 0.0,
                is_closed=True,
            )
            candles.append(candle)

        except Exception as e:
            skipped += 1
            if skipped <= 5:
                warnings.append(f"Row {row_idx + 1}: {e}")

    # Sort by timestamp
    candles.sort(key=lambda c: c.timestamp)

    # Remove duplicates
    seen = set()
    unique_candles = []
    for c in candles:
        if c.timestamp not in seen:
            seen.add(c.timestamp)
            unique_candles.append(c)
    candles = unique_candles

    # Calculate metadata
    if candles:
        start_ts = candles[0].timestamp
        end_ts = candles[-1].timestamp
        days = (end_ts - start_ts) / (1000 * 86400)
        price_range = f"${min(c.close for c in candles):,.2f} - ${max(c.close for c in candles):,.2f}"
    else:
        days = 0
        price_range = "N/A"

    metadata = {
        "format_detected": format_type,
        "total_rows": len(data_rows),
        "parsed_candles": len(candles),
        "skipped_rows": skipped,
        "date_range": f"{days:.1f} days",
        "price_range": price_range,
        "symbol": symbol,
        "timeframe": timeframe,
    }

    if skipped > 0:
        warnings.append(f"Skipped {skipped} rows (missing timestamp or price data)")

    return {
        "success": len(candles) > 0,
        "candles": candles,
        "count": len(candles),
        "errors": errors,
        "warnings": warnings,
        "metadata": metadata,
    }


def get_supported_formats() -> list[dict]:
    """Return list of supported CSV formats with example headers."""
    return [
        {
            "id": "auto",
            "name": "Auto-detect",
            "description": "Automatically detect format from column headers",
            "example_headers": "time,open,high,low,close,volume",
        },
        {
            "id": "binance",
            "name": "Binance Export",
            "description": "Binance kline/candlestick export format",
            "example_headers": "open_time,open,high,low,close,volume,close_time,...",
        },
        {
            "id": "tradingview",
            "name": "TradingView",
            "description": "TradingView exported data",
            "example_headers": "time,open,high,low,close,volume",
        },
        {
            "id": "coinmarketcap",
            "name": "CoinMarketCap",
            "description": "CoinMarketCap historical data",
            "example_headers": "timestamp,open*,high*,low*,close*,volume*,market_cap*",
        },
        {
            "id": "coingecko",
            "name": "CoinGecko",
            "description": "CoinGecko market data (price only, OHLC estimated)",
            "example_headers": "date,current_price,total_volume,market_cap",
        },
        {
            "id": "bitfinex",
            "name": "Bitfinex / Investing.com",
            "description": "Bitfinex or Investing.com historical data with price, OHLC, volume",
            "example_headers": "Date,Price,Open,High,Low,Vol.,Change %",
        },
        {
            "id": "generic",
            "name": "Generic OHLCV",
            "description": "Standard OHLCV format (no headers, positional)",
            "example_headers": "timestamp,open,high,low,close,volume",
        },
    ]
