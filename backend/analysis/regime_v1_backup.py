from __future__ import annotations

import math

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

    # ── ADX-like trend strength using EMA spread + price momentum ──
    closes = [c.close for c in ordered]
    adx_strength = _compute_adx_proxy(closes, metrics)

    # ── Volatility regime classification ──
    vol_regime = _classify_volatility(ordered, metrics)

    # ── Liquidity sweep analysis ──
    recent_events = liquidity_events[-8:]
    sell_side_sweep = any(event.side == "sell_side" and event.reclaimed for event in recent_events)
    buy_side_sweep = any(event.side == "buy_side" and event.reclaimed for event in recent_events)

    volume_state = "expanding" if metrics.volume_zscore >= 1.0 else "compressed" if metrics.volume_zscore <= -0.7 else "normal"

    # ── Primary regime classification ──
    low_efficiency = efficiency_ratio <= 0.28
    compressed = atr_compression <= 0.24 or width_pct <= max(atr_pct * 5.2, 0.42)
    balanced = abs(metrics.premium_discount) <= 0.42

    # Trend detection: require both ADX strength AND trend score alignment
    is_trending = adx_strength > 0.50 and trend_pressure > 0.40
    is_ranging = adx_strength < 0.25 and low_efficiency

    phase = "trending"
    bias = metrics.institutional_bias
    confidence = min(0.92, 0.42 + min(trend_pressure * 0.5, 0.25) + min(adx_strength * 0.2, 0.15))
    reasons = [
        f"efficiency {efficiency_ratio:.2f}",
        f"ADX {adx_strength:.2f}",
        f"width {width_pct:.2f}%",
        f"vol {vol_regime}",
    ]

    if is_ranging and compressed:
        phase = "consolidation"
        bias = "neutral"
        confidence = 0.65
        reasons.append("low expansion, compressed ATR")
    elif is_ranging and balanced:
        phase = "range_bound"
        bias = "neutral"
        confidence = 0.60
        reasons.append("two-sided mean reversion")

    # Accumulation/distribution detection via liquidity sweeps
    if phase in {"consolidation", "range_bound"}:
        if sell_side_sweep and latest.close >= range_mid:
            phase = "accumulation"
            bias = "bullish"
            confidence = min(0.9, confidence + 0.14)
            reasons.append("sell-side sweep reclaimed into range")
        elif buy_side_sweep and latest.close <= range_mid:
            phase = "distribution"
            bias = "bearish"
            confidence = min(0.9, confidence + 0.14)
            reasons.append("buy-side sweep rejected into range")
    elif sell_side_sweep and metrics.premium_discount <= -0.2:
        phase = "accumulation"
        bias = "bullish"
        confidence = 0.70
        reasons.append("discount sweep absorption")
    elif buy_side_sweep and metrics.premium_discount >= 0.2:
        phase = "distribution"
        bias = "bearish"
        confidence = 0.70
        reasons.append("premium sweep rejection")

    # Volatility expansion can signal trend breakout from range
    if phase in {"consolidation", "range_bound"} and vol_regime == "expanding" and adx_strength > 0.45:
        phase = "trending"
        bias = "bullish" if metrics.trend_score > 0 else "bearish"
        confidence = min(0.85, confidence + 0.10)
        reasons.append("volatility expansion + ADX breakout")

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


def _compute_adx_proxy(closes: list[float], metrics: MarketMetrics) -> float:
    """Compute ADX-like trend strength using EMA spread + price momentum.
    Returns value in [0, 1] where >0.35 indicates trending market."""
    n = len(closes)
    if n < 20:
        return 0.0

    # EMA spread component
    ema_fast = _ema(closes, 9)
    ema_slow = _ema(closes, 21)
    spread_pct = abs(ema_fast - ema_slow) / max(ema_slow, 1e-10) * 100
    spread_strength = min(spread_pct / 1.0, 1.0)  # Normalize: 1.0% spread = max strength

    # Directional movement component
    up_moves = 0.0
    down_moves = 0.0
    for i in range(1, min(14, n)):
        up = max(closes[i] - closes[i-1], 0)
        down = max(closes[i-1] - closes[i], 0)
        up_moves += up
        down_moves += down
    total_move = up_moves + down_moves
    if total_move == 0:
        dx = 0.0
    else:
        dx = abs(up_moves - down_moves) / total_move

    # Combine: 60% spread strength + 40% directional movement
    adx = spread_strength * 0.6 + dx * 0.4
    return max(0.0, min(1.0, adx))


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    multiplier = 2.0 / (period + 1)
    result = values[0]
    for i in range(1, len(values)):
        result = (values[i] - result) * multiplier + result
    return result


def _classify_volatility(candles: list[Candle], metrics: MarketMetrics) -> str:
    """Classify volatility regime using ATR percentile and volume."""
    if len(candles) < 20:
        return "unknown"

    atr_values: list[float] = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i-1].close),
            abs(candles[i].low - candles[i-1].close),
        )
        atr_values.append(tr)

    if len(atr_values) < 14:
        return "unknown"

    current_atr = sum(atr_values[-14:]) / 14
    atr_sorted = sorted(atr_values)
    percentile = atr_sorted.index(min(atr_sorted, key=lambda x: abs(x - current_atr))) / len(atr_sorted)

    if percentile < 0.2:
        return "compressed"
    elif percentile > 0.8:
        return "expanding"
    return "normal"


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
