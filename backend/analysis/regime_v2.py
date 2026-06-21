"""
Market Regime Detector v2.0

Uses price structure (HH/HL/LH/LL) instead of just ADX proxy.
Properly distinguishes trending, ranging, accumulation, distribution.
"""

from __future__ import annotations

from backend.models.types import Candle, LiquidityEvent, MarketMetrics, MarketRegime


def detect_market_regime(
    candles: list[Candle],
    metrics: MarketMetrics | None,
    liquidity_events: list[LiquidityEvent],
    lookback: int = 48,
) -> MarketRegime | None:
    ordered = sorted(candles, key=lambda c: c.timestamp)
    if len(ordered) < 12 or metrics is None:
        return None

    window = ordered[-lookback:]
    latest = ordered[-1]
    closes = [c.close for c in window]

    # ── Price Structure Analysis ──
    swings = _find_swings(closes, swing_len=5)
    structure = _analyze_structure(swings)

    # ── Range Metrics ──
    range_high = max(c.high for c in window)
    range_low = min(c.low for c in window)
    range_mid = (range_high + range_low) / 2
    width = max(range_high - range_low, 0.0)
    width_pct = _safe_div(width, latest.close) * 100
    atr_pct = _safe_div(metrics.atr14, latest.close) * 100

    # ── Trend Metrics ──
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    ema50 = _ema(closes, min(50, len(closes)))
    ema_spread_pct = abs(ema9 - ema21) / max(ema21, 1e-10) * 100

    # Price position relative to EMAs
    price_above_ema9 = latest.close > ema9
    price_above_ema21 = latest.close > ema21
    price_above_ema50 = latest.close > ema50
    emas_aligned_bullish = ema9 > ema21 > ema50
    emas_aligned_bearish = ema9 < ema21 < ema50

    # Price direction over lookback period
    price_change_pct = (latest.close - window[0].open) / window[0].open * 100
    is_price_rising = price_change_pct > 0.5
    is_price_falling = price_change_pct < -0.5

    # ── Efficiency Ratio ──
    net_move = abs(latest.close - window[0].open)
    total_move = sum(abs(closes[i] - closes[i-1]) for i in range(1, len(closes)))
    efficiency = _safe_div(net_move, total_move) if total_move > 0 else 0

    # ── ATR Compression ──
    atr_compression = _safe_div(metrics.atr14, max(width, metrics.atr14))

    # ── Volume State ──
    volume_state = "expanding" if metrics.volume_zscore >= 1.0 else "compressed" if metrics.volume_zscore <= -0.7 else "normal"

    # ── Liquidity Sweep Analysis ──
    recent_events = liquidity_events[-8:]
    sell_side_sweep = any(e.side == "sell_side" and e.reclaimed for e in recent_events)
    buy_side_sweep = any(e.side == "buy_side" and e.reclaimed for e in recent_events)

    # ── Regime Classification ──
    phase = "trending"
    bias = "neutral"
    confidence = 0.5
    reasons: list[str] = []

    # 1. TRENDING: requires structure + EMA alignment + price direction + efficiency
    is_structured_trend = structure["is_trending"] and structure["direction"] != "neutral"
    is_ema_aligned = emas_aligned_bullish or emas_aligned_bearish
    is_efficient = efficiency > 0.30

    # Require price direction to match structure
    price_direction_matches = (
        (structure["direction"] == "bullish" and is_price_rising) or
        (structure["direction"] == "bearish" and is_price_falling)
    )
    
    # Require minimum EMA spread for trending
    has_ema_spread = ema_spread_pct > 0.15

    # Count how many trending conditions are met (out of 5)
    trend_conditions_met = sum([is_structured_trend, is_ema_aligned, is_efficient, price_direction_matches, has_ema_spread])

    # Classify regime in priority order (first match wins)
    if trend_conditions_met >= 4:
        # Strong trending
        phase = "trending"
        bias = structure["direction"]
        confidence = min(0.92, 0.50 + efficiency * 0.25 + (0.10 if is_ema_aligned else 0))
        reasons = [
            f"Structure: {structure['pattern']}",
            f"EMA {'bull' if emas_aligned_bullish else 'bear'} aligned",
            f"Efficiency: {efficiency:.2f}",
            f"Price: {price_change_pct:+.2f}%",
            f"EMA spread: {ema_spread_pct:.2f}%",
        ]
    elif trend_conditions_met >= 3:
        # Moderate trending - still trending but lower confidence
        phase = "trending"
        bias = structure["direction"]
        confidence = min(0.75, 0.40 + efficiency * 0.20)
        reasons = [
            f"Structure: {structure['pattern']}",
            f"EMA {'bull' if emas_aligned_bullish else 'bear'} aligned",
            f"Price: {price_change_pct:+.2f}%",
        ]
    elif sell_side_sweep and latest.close >= range_mid:
        # 4. ACCUMULATION: sell-side sweep + reclaim + price above mid
        phase = "accumulation"
        bias = "bullish"
        confidence = 0.70
        reasons = ["Sell-side sweep reclaimed above mid"]
    elif buy_side_sweep and latest.close <= range_mid:
        # 5. DISTRIBUTION: buy-side sweep + rejection + price below mid
        phase = "distribution"
        bias = "bearish"
        confidence = 0.70
        reasons = ["Buy-side sweep rejected below mid"]
    elif width_pct < 1.0 and atr_compression < 0.15:
        # 3. CONSOLIDATION: tight range, low volatility
        phase = "consolidation"
        bias = "neutral"
        confidence = 0.55
        reasons = [
            f"Tight range: {width_pct:.2f}%",
            f"ATR compressed: {atr_compression:.2f}",
            f"Volume: {volume_state}",
        ]
    elif not is_structured_trend and atr_compression < 0.35:
        # 2. RANGING: no structure, price oscillating
        phase = "range_bound"
        bias = "neutral"
        confidence = 0.60
        reasons = [
            f"No clear structure ({structure['pattern']})",
            f"ATR compressed: {atr_compression:.2f}",
            f"Width: {width_pct:.2f}%",
        ]
    elif is_structured_trend:
        # Has structure direction but doesn't meet all criteria - still trending
        phase = "trending"
        bias = structure["direction"]
        confidence = 0.50
        reasons = [f"Weak trend: {structure['pattern']} (eff={efficiency:.2f}, ema={ema_spread_pct:.2f}%)"]
    else:
        # Default: trending with neutral bias (will be caught by safety check below)
        phase = "trending"
        bias = structure["direction"] if structure["direction"] != "neutral" else "neutral"
        confidence = 0.50
        reasons = [f"Fallback: {structure['pattern']}"]

    # 6. TRENDING breakout from consolidation (override if strong volume expansion)
    if phase in {"consolidation", "range_bound"} and volume_state == "expanding" and ema_spread_pct > 0.30:
        if price_above_ema9 and price_above_ema21:
            phase = "trending"
            bias = "bullish"
            confidence = min(0.85, confidence + 0.10)
            reasons.append("Volume expansion + bullish EMA breakout")
        elif not price_above_ema9 and not price_above_ema21:
            phase = "trending"
            bias = "bearish"
            confidence = min(0.85, confidence + 0.10)
            reasons.append("Volume expansion + bearish EMA breakout")

    # Safety check: trending phase must have directional bias
    if phase == "trending" and bias == "neutral":
        # Fall back to range_bound if we can't determine direction
        phase = "range_bound"
        bias = "neutral"
        confidence = 0.50
        reasons = ["Trending structure without clear direction"]

    return MarketRegime(
        timestamp=latest.timestamp,
        phase=phase,
        confidence=round(confidence, 3),
        range_high=round(range_high, 2),
        range_low=round(range_low, 2),
        range_mid=round(range_mid, 2),
        width_pct=round(width_pct, 3),
        atr_compression=round(atr_compression, 3),
        efficiency_ratio=round(efficiency, 3),
        volume_state=volume_state,
        bias=bias,
        reason=", ".join(reasons),
    )


def _find_swings(closes: list[float], swing_len: int = 5) -> list[dict]:
    """Find swing highs and lows."""
    swings = []
    for i in range(swing_len, len(closes) - swing_len):
        is_high = all(closes[i] > closes[i - j] for j in range(1, swing_len + 1)) and \
                  all(closes[i] > closes[i + j] for j in range(1, swing_len + 1))
        is_low = all(closes[i] < closes[i - j] for j in range(1, swing_len + 1)) and \
                 all(closes[i] < closes[i + j] for j in range(1, swing_len + 1))
        if is_high:
            swings.append({"index": i, "price": closes[i], "type": "high"})
        elif is_low:
            swings.append({"index": i, "price": closes[i], "type": "low"})
    return swings


def _analyze_structure(swings: list[dict]) -> dict:
    """Analyze swing structure to determine trend direction."""
    if len(swings) < 3:
        return {"is_trending": False, "direction": "neutral", "pattern": "insufficient_data"}

    # Take last 6 swings
    recent = swings[-6:]
    highs = [s for s in recent if s["type"] == "high"]
    lows = [s for s in recent if s["type"] == "low"]

    if len(highs) < 2 or len(lows) < 2:
        return {"is_trending": False, "direction": "neutral", "pattern": "not_enough_swings"}

    # Check for HH/HL pattern (bullish trend)
    last_2_highs = highs[-2:]
    last_2_lows = lows[-2:]

    hh = last_2_highs[1]["price"] > last_2_highs[0]["price"]
    lh = last_2_highs[1]["price"] < last_2_highs[0]["price"]
    hl = last_2_lows[1]["price"] > last_2_lows[0]["price"]
    ll = last_2_lows[1]["price"] < last_2_lows[0]["price"]

    # Count patterns in recent swings
    hh_count = sum(1 for i in range(1, len(highs)) if highs[i]["price"] > highs[i-1]["price"])
    hl_count = sum(1 for i in range(1, len(lows)) if lows[i]["price"] > lows[i-1]["price"])
    lh_count = sum(1 for i in range(1, len(highs)) if highs[i]["price"] < highs[i-1]["price"])
    ll_count = sum(1 for i in range(1, len(lows)) if lows[i]["price"] < lows[i-1]["price"])

    bullish_score = hh_count + hl_count
    bearish_score = lh_count + ll_count
    total = max(bullish_score + bearish_score, 1)

    bullish_ratio = bullish_score / total
    bearish_ratio = bearish_score / total

    if bullish_ratio >= 0.70:
        return {"is_trending": True, "direction": "bullish", "pattern": "HH/HL"}
    elif bearish_ratio >= 0.70:
        return {"is_trending": True, "direction": "bearish", "pattern": "LH/LL"}
    elif bullish_ratio >= 0.55:
        return {"is_trending": True, "direction": "bullish", "pattern": "weak_HH/HL"}
    elif bearish_ratio >= 0.55:
        return {"is_trending": True, "direction": "bearish", "pattern": "weak_LH/LL"}
    else:
        return {"is_trending": False, "direction": "neutral", "pattern": "mixed"}


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    multiplier = 2.0 / (period + 1)
    result = values[0]
    for i in range(1, len(values)):
        result = (values[i] - result) * multiplier + result
    return result


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
