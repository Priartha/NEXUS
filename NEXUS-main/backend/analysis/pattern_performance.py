from __future__ import annotations

import time
from typing import Any

from backend.storage.schema import get_conn


def compute_pattern_performance(days: int = 30) -> dict[str, Any]:
    """
    Compute pattern performance metrics by correlating pattern detections
    with subsequent price movement.
    """
    conn = get_conn()
    try:
        cutoff = int(time.time() * 1000) - (days * 24 * 60 * 60 * 1000)

        patterns = conn.execute("""
            SELECT name, direction, confidence, score, timestamp, symbol, timeframe
            FROM pattern_history WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (cutoff,)).fetchall()

        if not patterns:
            return {
                "total_patterns": 0,
                "accuracy_by_pattern": {},
                "accuracy_by_direction": {},
                "accuracy_by_confidence_band": {},
                "best_patterns": [],
                "worst_patterns": [],
            }

        candles = conn.execute("""
            SELECT timestamp, symbol, timeframe, close
            FROM candle_archive WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """, (cutoff,)).fetchall()

        candle_map: dict[tuple[str, str, int], float] = {}
        for c in candles:
            candle_map[(c["symbol"], c["timeframe"], c["timestamp"])] = c["close"]

        results: list[dict] = []
        for p in patterns:
            entry_ts = p["timestamp"]
            symbol = p["symbol"]
            timeframe = p["timeframe"]

            exit_ts = entry_ts + _get_exit_offset(timeframe)
            entry_price = _find_price_at(candle_map, symbol, timeframe, entry_ts)
            exit_price = _find_price_at(candle_map, symbol, timeframe, exit_ts)

            if entry_price and exit_price:
                if p["direction"] == "bullish":
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                elif p["direction"] == "bearish":
                    pnl_pct = (entry_price - exit_price) / entry_price * 100
                else:
                    pnl_pct = 0
                hit = pnl_pct > 0
            else:
                pnl_pct = None
                hit = None

            results.append({
                "name": p["name"],
                "direction": p["direction"],
                "confidence": p["confidence"],
                "score": p["score"],
                "pnl_pct": pnl_pct,
                "hit": hit,
            })

        accuracy_by_pattern: dict[str, dict] = {}
        for r in results:
            if r["hit"] is None:
                continue
            name = r["name"]
            if name not in accuracy_by_pattern:
                accuracy_by_pattern[name] = {"total": 0, "hits": 0, "avg_pnl": 0.0, "count": 0}
            accuracy_by_pattern[name]["total"] += 1
            if r["hit"]:
                accuracy_by_pattern[name]["hits"] += 1
            if r["pnl_pct"] is not None:
                accuracy_by_pattern[name]["avg_pnl"] += r["pnl_pct"]
                accuracy_by_pattern[name]["count"] += 1

        for name, data in accuracy_by_pattern.items():
            data["accuracy"] = data["hits"] / data["total"] if data["total"] > 0 else 0
            data["avg_pnl"] = data["avg_pnl"] / data["count"] if data["count"] > 0 else 0

        accuracy_by_direction: dict[str, dict] = {}
        for r in results:
            if r["hit"] is None:
                continue
            direction = r["direction"]
            if direction not in accuracy_by_direction:
                accuracy_by_direction[direction] = {"total": 0, "hits": 0, "avg_pnl": 0.0, "count": 0}
            accuracy_by_direction[direction]["total"] += 1
            if r["hit"]:
                accuracy_by_direction[direction]["hits"] += 1
            if r["pnl_pct"] is not None:
                accuracy_by_direction[direction]["avg_pnl"] += r["pnl_pct"]
                accuracy_by_direction[direction]["count"] += 1

        for direction, data in accuracy_by_direction.items():
            data["accuracy"] = data["hits"] / data["total"] if data["total"] > 0 else 0
            data["avg_pnl"] = data["avg_pnl"] / data["count"] if data["count"] > 0 else 0

        accuracy_by_band: dict[str, dict] = {}
        for r in results:
            if r["hit"] is None:
                continue
            conf = r["confidence"]
            if conf >= 0.8:
                band = "high (0.8+)"
            elif conf >= 0.6:
                band = "medium (0.6-0.8)"
            elif conf >= 0.4:
                band = "low (0.4-0.6)"
            else:
                band = "very_low (<0.4)"
            if band not in accuracy_by_band:
                accuracy_by_band[band] = {"total": 0, "hits": 0, "avg_pnl": 0.0, "count": 0}
            accuracy_by_band[band]["total"] += 1
            if r["hit"]:
                accuracy_by_band[band]["hits"] += 1
            if r["pnl_pct"] is not None:
                accuracy_by_band[band]["avg_pnl"] += r["pnl_pct"]
                accuracy_by_band[band]["count"] += 1

        for band, data in accuracy_by_band.items():
            data["accuracy"] = data["hits"] / data["total"] if data["total"] > 0 else 0
            data["avg_pnl"] = data["avg_pnl"] / data["count"] if data["count"] > 0 else 0

        valid_results = [r for r in results if r["pnl_pct"] is not None]
        sorted_by_pnl = sorted(valid_results, key=lambda x: x.get("pnl_pct", 0), reverse=True)
        best_patterns = []
        worst_patterns = []
        if sorted_by_pnl:
            best_patterns = [
                {"name": r["name"], "direction": r["direction"], "avg_pnl": r["pnl_pct"]}
                for r in sorted_by_pnl[:5]
            ]
            worst_patterns = [
                {"name": r["name"], "direction": r["direction"], "avg_pnl": r["pnl_pct"]}
                for r in sorted_by_pnl[-5:]
            ]

        return {
            "total_patterns": len(results),
            "evaluated_patterns": len(valid_results),
            "accuracy_by_pattern": accuracy_by_pattern,
            "accuracy_by_direction": accuracy_by_direction,
            "accuracy_by_confidence_band": accuracy_by_band,
            "best_patterns": best_patterns,
            "worst_patterns": worst_patterns,
        }
    finally:
        conn.close()


def _get_exit_offset(timeframe: str) -> int:
    """Get exit offset in ms based on timeframe."""
    offsets = {
        "1m": 5 * 60 * 1000,
        "3m": 10 * 60 * 1000,
        "5m": 30 * 60 * 1000,
        "15m": 60 * 60 * 1000,
        "30m": 2 * 60 * 60 * 1000,
        "1h": 4 * 60 * 60 * 1000,
        "2h": 8 * 60 * 60 * 1000,
        "4h": 12 * 60 * 60 * 1000,
        "1d": 3 * 24 * 60 * 60 * 1000,
    }
    return offsets.get(timeframe, 30 * 60 * 1000)


def _find_price_at(
    candle_map: dict[tuple[str, str, int], float],
    symbol: str,
    timeframe: str,
    target_ts: int,
) -> float | None:
    """Find the closest candle price at or after target_ts."""
    for offset in range(0, 10):
        ts = target_ts + offset * _get_candle_ms(timeframe)
        key = (symbol, timeframe, ts)
        if key in candle_map:
            return candle_map[key]
    return None


def _get_candle_ms(timeframe: str) -> int:
    """Get candle duration in ms."""
    durations = {
        "1m": 60000,
        "3m": 180000,
        "5m": 300000,
        "15m": 900000,
        "30m": 1800000,
        "1h": 3600000,
        "2h": 7200000,
        "4h": 14400000,
        "1d": 86400000,
    }
    return durations.get(timeframe, 300000)
