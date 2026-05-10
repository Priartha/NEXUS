from __future__ import annotations

from backend.models.types import Candle, LiquidityEvent, MarketMetrics, MarketRegime


def detect_market_regime(
    candles: list[Candle],
    metrics: MarketMetrics | None,
    liquidity_events: list[LiquidityEvent],
    lookback: int = 48,
) -> MarketRegime | None:
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    if len(ordered) < 12 or metrics is None:
        return None

    window = ordered[-lookback:]
    latest = ordered[-1]
    range_high = max(candle.high for candle in window)
    range_low = min(candle.low for candle in window)
    range_mid = (range_high + range_low) / 2
    width = max(range_high - range_low, 0.0)
    width_pct = _safe_div(width, latest.close) * 100
    atr_pct = _safe_div(metrics.atr14, latest.close) * 100
    atr_compression = _safe_div(metrics.atr14, max(width, metrics.atr14))
    efficiency_ratio = _safe_div(abs(latest.close - window[0].open), width)
    trend_pressure = abs(metrics.trend_score)
    low_efficiency = efficiency_ratio <= 0.28
    compressed = atr_compression <= 0.24 or width_pct <= max(atr_pct * 5.2, 0.42)
    balanced = abs(metrics.premium_discount) <= 0.42

    recent_events = liquidity_events[-8:]
    sell_side_sweep = any(event.side == "sell_side" and event.reclaimed for event in recent_events)
    buy_side_sweep = any(event.side == "buy_side" and event.reclaimed for event in recent_events)

    volume_state = "expanding" if metrics.volume_zscore >= 1.0 else "compressed" if metrics.volume_zscore <= -0.7 else "normal"
    phase = "trending"
    bias = metrics.institutional_bias
    confidence = min(0.92, 0.42 + min(trend_pressure * 0.6, 0.3))
    reasons = [
        f"efficiency {efficiency_ratio:.2f}",
        f"width {width_pct:.2f}%",
        f"ATR compression {atr_compression:.2f}",
    ]

    if low_efficiency and compressed and trend_pressure < 0.28:
        phase = "consolidation"
        bias = "neutral"
        confidence = 0.68
        reasons.append("low expansion and balanced structure")
    elif low_efficiency and balanced and trend_pressure < 0.38:
        phase = "range_bound"
        bias = "neutral"
        confidence = 0.62
        reasons.append("two-sided mean reversion")

    if phase in {"consolidation", "range_bound"}:
        if sell_side_sweep and latest.close >= range_mid:
            phase = "accumulation"
            bias = "bullish"
            confidence = min(0.9, confidence + 0.16)
            reasons.append("sell-side sweep reclaimed into range")
        elif buy_side_sweep and latest.close <= range_mid:
            phase = "distribution"
            bias = "bearish"
            confidence = min(0.9, confidence + 0.16)
            reasons.append("buy-side sweep rejected into range")
    elif sell_side_sweep and metrics.premium_discount <= -0.2:
        phase = "accumulation"
        bias = "bullish"
        confidence = 0.72
        reasons.append("discount sweep absorption")
    elif buy_side_sweep and metrics.premium_discount >= 0.2:
        phase = "distribution"
        bias = "bearish"
        confidence = 0.72
        reasons.append("premium sweep rejection")

    return MarketRegime(
        timestamp=latest.timestamp,
        phase=phase,
        confidence=round(confidence, 3),
        range_high=round(range_high, 2),
        range_low=round(range_low, 2),
        range_mid=round(range_mid, 2),
        width_pct=round(width_pct, 3),
        atr_compression=round(atr_compression, 3),
        efficiency_ratio=round(efficiency_ratio, 3),
        volume_state=volume_state,
        bias=bias,
        reason=", ".join(reasons),
    )


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
