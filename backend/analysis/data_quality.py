from __future__ import annotations

import time
from collections import Counter
from typing import Any, Iterable

from backend.engine.candle_aggregator import timeframe_to_ms


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").upper()


def symbol_aliases(symbol: str) -> list[str]:
    normalized = normalize_symbol(symbol)
    aliases = [symbol]
    if normalized in {"BTCUSD", "BTCUSDT"}:
        aliases.extend(["BTCUSD", "BTCUSDT", "BTC/USDT"])
    aliases.append(normalized)
    return list(dict.fromkeys(aliases))


def _get(candle: Any, key: str, default: Any = None) -> Any:
    if isinstance(candle, dict):
        return candle.get(key, default)
    return getattr(candle, key, default)


def _num(candle: Any, key: str) -> float | None:
    value = _get(candle, key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def analyze_candles(
    candles: Iterable[Any],
    *,
    requested_symbol: str,
    actual_symbol: str | None,
    timeframe: str,
    source_type: str,
    provider: str,
    native_timeframe: bool = True,
    requested_count: int | None = None,
    now_ms: int | None = None,
) -> dict:
    rows = sorted(list(candles), key=lambda candle: int(_get(candle, "timestamp", 0) or 0))
    expected_ms = timeframe_to_ms(timeframe)
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    timestamps = [int(_get(candle, "timestamp", 0) or 0) for candle in rows]
    counts = Counter(timestamps)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    unique_timestamps = sorted(counts)

    gaps: list[dict] = []
    off_interval_count = 0
    missing_candles = 0
    for prev_ts, ts in zip(unique_timestamps, unique_timestamps[1:]):
        step = ts - prev_ts
        if step <= 0:
            continue
        expected_slots = round(step / expected_ms) if expected_ms > 0 else 1
        if abs(step - expected_ms) > max(1, expected_ms * 0.05):
            off_interval_count += 1
        if expected_slots > 1 and step > expected_ms * 1.5:
            missing = expected_slots - 1
            missing_candles += missing
            gaps.append(
                {
                    "from": prev_ts,
                    "to": ts,
                    "gap_ms": step,
                    "missing_candles": missing,
                }
            )

    invalid_ohlc = 0
    zero_volume = 0
    for candle in rows:
        open_ = _num(candle, "open")
        high = _num(candle, "high")
        low = _num(candle, "low")
        close = _num(candle, "close")
        volume = _num(candle, "volume")
        if None in (open_, high, low, close) or high < low or open_ < low or open_ > high or close < low or close > high:
            invalid_ohlc += 1
        if volume is not None and volume <= 0:
            zero_volume += 1

    first_ts = unique_timestamps[0] if unique_timestamps else None
    last_ts = unique_timestamps[-1] if unique_timestamps else None
    latest_age_ms = now - last_ts if last_ts is not None else None
    stale = latest_age_ms is None or latest_age_ms > expected_ms * 3

    score = 100
    if len(rows) < 80:
        score -= 40
    if requested_count and len(rows) < min(requested_count, 80):
        score -= 20
    if duplicate_count:
        score -= min(20, duplicate_count * 2)
    if missing_candles:
        score -= min(35, missing_candles * 2)
    if off_interval_count:
        score -= min(20, off_interval_count)
    if invalid_ohlc:
        score -= min(40, invalid_ohlc * 5)
    if stale:
        score -= 25
    if not native_timeframe:
        score -= 5
    score = max(score, 0)

    if score >= 90:
        verdict = "trusted"
    elif score >= 70:
        verdict = "usable_with_warnings"
    else:
        verdict = "do_not_trust"

    warnings: list[str] = []
    if not native_timeframe:
        warnings.append("timeframe was aggregated, not native")
    if stale:
        warnings.append("latest candle is stale")
    if duplicate_count:
        warnings.append(f"{duplicate_count} duplicate candle rows")
    if missing_candles:
        warnings.append(f"{missing_candles} missing candle slots")
    if off_interval_count:
        warnings.append(f"{off_interval_count} irregular intervals")
    if invalid_ohlc:
        warnings.append(f"{invalid_ohlc} invalid OHLC rows")
    if len(rows) < 80:
        warnings.append("not enough candles for engine warmup")

    return {
        "verdict": verdict,
        "score": score,
        "source_type": source_type,
        "provider": provider,
        "requested_symbol": requested_symbol,
        "actual_symbol": actual_symbol or requested_symbol,
        "symbol_alias_used": bool(actual_symbol and normalize_symbol(actual_symbol) != normalize_symbol(requested_symbol)),
        "timeframe": timeframe,
        "native_timeframe": native_timeframe,
        "requested_count": requested_count,
        "candle_count": len(rows),
        "unique_candle_count": len(unique_timestamps),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "expected_interval_ms": expected_ms,
        "latest_age_ms": latest_age_ms,
        "stale": stale,
        "duplicate_count": duplicate_count,
        "missing_candle_count": missing_candles,
        "irregular_interval_count": off_interval_count,
        "invalid_ohlc_count": invalid_ohlc,
        "zero_volume_count": zero_volume,
        "largest_gaps": sorted(gaps, key=lambda gap: gap["gap_ms"], reverse=True)[:5],
        "warnings": warnings,
    }


def aggregate_candles(candles: Iterable[Any], timeframe: str) -> list[dict]:
    rows = sorted(list(candles), key=lambda candle: int(_get(candle, "timestamp", 0) or 0))
    target_ms = timeframe_to_ms(timeframe)
    buckets: dict[int, list[Any]] = {}
    for candle in rows:
        timestamp = int(_get(candle, "timestamp", 0) or 0)
        bucket = timestamp - (timestamp % target_ms)
        buckets.setdefault(bucket, []).append(candle)

    aggregated: list[dict] = []
    for bucket, group in sorted(buckets.items()):
        ordered = sorted(group, key=lambda candle: int(_get(candle, "timestamp", 0) or 0))
        if not ordered:
            continue
        opens = [_num(candle, "open") for candle in ordered]
        highs = [_num(candle, "high") for candle in ordered]
        lows = [_num(candle, "low") for candle in ordered]
        closes = [_num(candle, "close") for candle in ordered]
        volumes = [_num(candle, "volume") or 0.0 for candle in ordered]
        if None in (opens[0], closes[-1]) or any(value is None for value in highs + lows):
            continue
        aggregated.append(
            {
                "timestamp": bucket,
                "open": opens[0],
                "high": max(value for value in highs if value is not None),
                "low": min(value for value in lows if value is not None),
                "close": closes[-1],
                "volume": sum(volumes),
                "is_closed": all(bool(_get(candle, "is_closed", True)) for candle in ordered),
            }
        )
    return aggregated
