from __future__ import annotations

from typing import Any

from backend.config import settings
from backend.models.types import Candle, ScalpWickRejection


def _safe(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError, ArithmeticError):
        return 0.0


def analyze_wick_rejection(candles: list[Candle]) -> ScalpWickRejection:
    if len(candles) < 3:
        return ScalpWickRejection()

    ordered = sorted(candles, key=lambda c: c.timestamp)
    recent = ordered[-(settings.scalp_wick_max_lookback):]
    min_ratio = settings.scalp_wick_min_ratio

    upper_ratios: list[float] = []
    lower_ratios: list[float] = []

    for c in recent:
        body = max(abs(c.close - c.open), 1e-8)
        upper = max(0.0, c.high - max(c.open, c.close))
        lower = max(0.0, min(c.open, c.close) - c.low)
        upper_ratios.append(upper / body)
        lower_ratios.append(lower / body)

    max_upper = max(upper_ratios) if upper_ratios else 0.0
    max_lower = max(lower_ratios) if lower_ratios else 0.0
    avg_upper = sum(upper_ratios) / len(upper_ratios) if upper_ratios else 0.0
    avg_lower = sum(lower_ratios) / len(lower_ratios) if lower_ratios else 0.0

    consecutive_upper = _consecutive(recent, min_ratio, side="upper")
    consecutive_lower = _consecutive(recent, min_ratio, side="lower")

    bearish_active = consecutive_upper >= 1
    bullish_active = consecutive_lower >= 1

    net_strength = 0.0
    if bearish_active and not bullish_active:
        strength = min(max_upper / 5.0, 1.0)
        net_strength = -(strength * 0.5 + min(consecutive_upper / 3.0, 1.0) * 0.5)
    elif bullish_active and not bearish_active:
        strength = min(max_lower / 5.0, 1.0)
        net_strength = strength * 0.5 + min(consecutive_lower / 3.0, 1.0) * 0.5
    elif bearish_active and bullish_active:
        if max_upper > max_lower * 1.3:
            net_strength = -min(max_upper / 5.0, 1.0) * 0.6
        elif max_lower > max_upper * 1.3:
            net_strength = min(max_lower / 5.0, 1.0) * 0.6

    desc = _build_description(bearish_active, bullish_active, max_upper, max_lower,
                              consecutive_upper, consecutive_lower, net_strength)

    return ScalpWickRejection(
        active_upper_wick_candles=sum(1 for r in upper_ratios if r >= min_ratio) if upper_ratios else 0,
        active_lower_wick_candles=sum(1 for r in lower_ratios if r >= min_ratio) if lower_ratios else 0,
        max_upper_wick_ratio=round(max_upper, 2),
        max_lower_wick_ratio=round(max_lower, 2),
        avg_upper_wick_ratio=round(avg_upper, 2),
        avg_lower_wick_ratio=round(avg_lower, 2),
        bearish_rejection_active=bearish_active,
        bullish_rejection_active=bullish_active,
        rejection_strength=round(net_strength, 4),
        description=desc,
    )


def _consecutive(candles: list[Candle], min_ratio: float, side: str) -> int:
    count = 0
    for c in reversed(candles):
        body = max(abs(c.close - c.open), 1e-8)
        if side == "upper":
            wick = max(0.0, c.high - max(c.open, c.close))
        else:
            wick = max(0.0, min(c.open, c.close) - c.low)
        if wick / body >= min_ratio:
            count += 1
        else:
            break
    return count


def _build_description(bearish, bullish, max_upper, max_lower, cons_upper, cons_lower, strength) -> str:
    parts = []
    if bearish:
        parts.append(f"Long upper wick (×{max_upper:.1f} body) {cons_upper}c")
    if bullish:
        parts.append(f"Long lower wick (×{max_lower:.1f} body) {cons_lower}c")
    if not parts:
        return "No significant wick rejection"
    direction = "bearish" if strength < -0.1 else ("bullish" if strength > 0.1 else "neutral")
    parts.append(f"→ {direction}")
    return " | ".join(parts)
