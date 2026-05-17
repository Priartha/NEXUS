"""
Signal Generation Engine v4.0 - Range-Focused with MTF Confirmation

Key principles:
- Market is 96% ranging on 5m, so default to range trading
- Buy support, sell resistance with wider stops
- Multi-timeframe confirmation (1H trend filter)
- Require strong rejection candles at boundaries
- Lower RR (1.0-1.5) for higher win rate
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from backend.analysis.ids import stable_id
from backend.models.types import (
    Candle,
    FVG,
    LiquidityEvent,
    LiquidityLevel,
    MarketMetrics,
    MarketRegime,
    OrderBlock,
    Swing,
    TradeSignal,
)
from backend.analysis.market_psychology import PsychologySnapshot
from backend.analysis.price_action_readability import ReadabilitySnapshot


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    multiplier = 2.0 / (period + 1)
    result = values[0]
    for i in range(1, len(values)):
        result = (values[i] - result) * multiplier + result
    return result


def _atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    ranges: list[float] = []
    recent = candles[-(period + 1) :]
    for prev, cur in zip(recent, recent[1:]):
        ranges.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes) - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
    return 100.0 - 100.0 / (1.0 + rs)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _is_killzone(timestamp_ms: int) -> tuple[bool, str]:
    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    hour = dt.hour
    time_val = hour + dt.minute / 60.0
    if 2.0 <= time_val < 5.0:
        return True, "london"
    if 8.5 <= time_val < 11.0:
        return True, "ny_am"
    if 13.5 <= time_val < 16.0:
        return True, "ny_pm"
    return False, "off_hours"


def _find_range_levels(candles: list[Candle], lookback: int = 100) -> dict:
    """Find robust support/resistance levels using multiple methods."""
    recent = candles[-lookback:]
    highs = [c.high for c in recent]
    lows = [c.low for c in recent]
    closes = [c.close for c in recent]
    
    # Method 1: Percentile-based levels
    sorted_highs = sorted(highs, reverse=True)
    sorted_lows = sorted(lows)
    
    # Use 90th percentile high and 10th percentile low for robustness
    resistance_90 = sorted_highs[max(0, int(len(sorted_highs) * 0.1))]
    support_10 = sorted_lows[min(len(sorted_lows) - 1, int(len(sorted_lows) * 0.1))]
    
    # Method 2: Recent swing highs/lows
    swing_highs = []
    swing_lows = []
    for i in range(2, len(recent) - 2):
        if recent[i].high > recent[i-1].high and recent[i].high > recent[i-2].high and \
           recent[i].high > recent[i+1].high and recent[i].high > recent[i+2].high:
            swing_highs.append(recent[i].high)
        if recent[i].low < recent[i-1].low and recent[i].low < recent[i-2].low and \
           recent[i].low < recent[i+1].low and recent[i].low < recent[i+2].low:
            swing_lows.append(recent[i].low)
    
    # Use most recent swing levels if available
    if swing_highs:
        resistance_swing = max(swing_highs[-3:])  # Highest of last 3 swings
    else:
        resistance_swing = resistance_90
    
    if swing_lows:
        support_swing = min(swing_lows[-3:])  # Lowest of last 3 swings
    else:
        support_swing = support_10
    
    # Combine methods: use the tighter level (more conservative)
    resistance = min(resistance_90, resistance_swing)
    support = max(support_10, support_swing)
    
    # Calculate range metrics
    range_size = resistance - support
    range_mid = (resistance + support) / 2
    
    # Current price position
    current_price = closes[-1]
    price_position = (current_price - support) / range_size if range_size > 0 else 0.5
    
    return {
        "support": support,
        "resistance": resistance,
        "mid": range_mid,
        "size": range_size,
        "size_pct": range_size / current_price * 100 if current_price > 0 else 0,
        "price_position": price_position,  # 0 = at support, 1 = at resistance
    }


def _is_rejection_candle(candle: Candle, direction: str, atr: float) -> tuple[bool, str, float]:
    """Check if candle shows strong rejection at a level."""
    body = abs(candle.close - candle.open)
    range_ = candle.high - candle.low
    if range_ == 0:
        return False, "zero_range", 0.0
    
    lower_wick = min(candle.open, candle.close) - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    
    strength = 0.0
    
    if direction == "buy":
        # Bullish rejection: long lower wick, close in upper half
        if lower_wick > body * 1.5 and candle.close > candle.open:
            strength = lower_wick / range_
            return True, "bullish_pin", strength
        # Bullish engulfing
        # (need prev candle, handled separately)
        if candle.close > candle.open and body > atr * 0.3:
            strength = body / range_
            return True, "bullish_body", strength
    else:
        # Bearish rejection: long upper wick, close in lower half
        if upper_wick > body * 1.5 and candle.close < candle.open:
            strength = upper_wick / range_
            return True, "bearish_pin", strength
        if candle.close < candle.open and body > atr * 0.3:
            strength = body / range_
            return True, "bearish_body", strength
    
    return False, "no_rejection", strength


def _check_mtf_trend(candles: list[Candle]) -> str:
    """Check higher timeframe trend using EMA alignment on 5m data."""
    closes = [c.close for c in candles]
    if len(closes) < 200:
        return "neutral"
    
    # Simulate 1H trend using 12x 5m candles
    ema50_5m = _ema(closes[-200:], 50)
    ema100_5m = _ema(closes[-250:], 100)
    ema200_5m = _ema(closes[-300:], 200)
    
    current_price = closes[-1]
    
    # Strong bullish: price > ema50 > ema100 > ema200
    if current_price > ema50_5m > ema100_5m > ema200_5m:
        return "bullish"
    # Strong bearish: price < ema50 < ema100 < ema200
    elif current_price < ema50_5m < ema100_5m < ema200_5m:
        return "bearish"
    # Mixed: neutral
    else:
        return "neutral"


def _volume_analysis(candles: list[Candle], lookback: int = 20) -> dict:
    """Analyze volume patterns."""
    if len(candles) < lookback + 1:
        return {"ratio": 1.0, "trend": "neutral"}
    
    recent_volumes = [c.volume for c in candles[-lookback-1:-1]]
    avg_volume = sum(recent_volumes) / len(recent_volumes)
    if avg_volume == 0:
        return {"ratio": 1.0, "trend": "neutral"}
    
    current_volume = candles[-2].volume
    volume_ratio = current_volume / avg_volume
    
    # Check volume trend (last 5 vs previous 5)
    if len(recent_volumes) >= 10:
        recent_5 = sum(recent_volumes[-5:]) / 5
        prev_5 = sum(recent_volumes[-10:-5]) / 5
        if recent_5 > prev_5 * 1.2:
            vol_trend = "increasing"
        elif recent_5 < prev_5 * 0.8:
            vol_trend = "decreasing"
        else:
            vol_trend = "neutral"
    else:
        vol_trend = "neutral"
    
    return {"ratio": volume_ratio, "trend": vol_trend}


def _psychology_adjustment(
    psychology: PsychologySnapshot | None,
    direction: str,
    base_confidence: float,
) -> tuple[float, str]:
    """Adjust confidence based on market psychology."""
    if not psychology:
        return base_confidence, "no_psychology_data"

    adjustment = 0.0
    reasons = []

    # Range trading: buy in fear (oversold), sell in greed (overbought)
    if direction == "buy" and psychology.fear_greed_label in ("fear", "extreme_fear"):
        adjustment += 0.05
        reasons.append("Fear = buying opportunity")
    elif direction == "sell" and psychology.fear_greed_label in ("greed", "extreme_greed"):
        adjustment += 0.05
        reasons.append("Greed = selling opportunity")

    # Contrarian at extremes
    if direction == "buy" and psychology.fear_greed_label == "extreme_greed":
        adjustment -= 0.08
        reasons.append("Extreme greed - avoid buying")
    elif direction == "sell" and psychology.fear_greed_label == "extreme_fear":
        adjustment -= 0.08
        reasons.append("Extreme fear - avoid selling")

    if psychology.trap_risk > 0.7:
        adjustment -= 0.05
        reasons.append("High trap risk")

    if psychology.smart_money_activity > 0.5:
        adjustment += 0.03
        reasons.append("Smart money active")

    new_confidence = _clamp(base_confidence + adjustment, 0.0, 1.0)
    reason_str = "; ".join(reasons) if reasons else "psychology neutral"
    return new_confidence, reason_str


def _readability_adjustment(
    readability: ReadabilitySnapshot | None,
    base_confidence: float,
) -> tuple[float, str]:
    """Adjust confidence based on price action readability."""
    if not readability:
        return base_confidence, "no_readability_data"

    adjustment = 0.0
    reasons = []

    if readability.grade in ("A+", "A"):
        adjustment += 0.05
        reasons.append("Excellent clarity")
    elif readability.grade in ("B+", "B"):
        adjustment += 0.02
        reasons.append("Good clarity")
    elif readability.grade in ("D", "F"):
        adjustment -= 0.08
        reasons.append("Poor clarity")

    if readability.noise_level > 0.7:
        adjustment -= 0.05
        reasons.append("High noise")
    elif readability.noise_level < 0.3:
        adjustment += 0.03
        reasons.append("Clean signals")

    if readability.structure_reliability > 0.7:
        adjustment += 0.03
        reasons.append("Reliable structure")
    elif readability.structure_reliability < 0.4:
        adjustment -= 0.05
        reasons.append("Unreliable structure")

    if readability.tradeability == "avoid":
        adjustment -= 0.10
        reasons.append("Avoid conditions")
    elif readability.tradeability == "excellent":
        adjustment += 0.04
        reasons.append("Excellent tradeability")

    new_confidence = _clamp(base_confidence + adjustment, 0.0, 1.0)
    reason_str = "; ".join(reasons) if reasons else "readability neutral"
    return new_confidence, reason_str


def _make_signal(
    side: str,
    timestamp: int,
    entry: float,
    stop: float,
    target: float,
    confidence: float,
    reason: str,
    metrics: MarketMetrics | None,
    atr: float,
    confluence: float,
    status: str = "active",
) -> TradeSignal:
    risk = abs(entry - stop)
    rr = abs(target - entry) / risk if risk > 0 else 0

    return TradeSignal(
        id=stable_id("sig", side, timestamp, int(entry * 10), int(stop * 10)),
        timestamp=timestamp,
        side=side,
        entry=round(entry, 2),
        stop_loss=round(stop, 2),
        exit_price=round(target, 2),
        risk_reward=round(rr, 2),
        confidence=round(confidence, 3),
        reason=reason,
        institutional_score=round(confluence, 3),
        liquidity_score=0.5,
        bias_score=round(metrics.bias_score if metrics else 0.0, 3),
        expected_move=round(metrics.expected_move if metrics else atr, 2),
        win_probability=round(_estimate_win_prob(confidence, rr), 3),
        kelly_fraction=round(max(0, (confidence * rr - (1 - confidence)) / rr) * 0.5, 4),
        suggested_risk_fraction=0.02,
        cvar95_loss=round(risk * 1.5, 2),
        risk_of_ruin=0.02,
        status=status,
    )


def _estimate_win_prob(confidence: float, rr: float) -> float:
    base = confidence * 0.6
    rr_adj = min(rr / 4.0, 0.3)
    return _clamp(base + rr_adj + 0.15, 0.30, 0.85)


def _range_signal(
    ordered: list[Candle],
    direction: str,
    range_levels: dict,
    atr14: float,
    rsi_val: float,
    mtf_trend: str,
    vol_analysis: dict,
    regime: MarketRegime | None,
    psychology: PsychologySnapshot | None,
    readability: ReadabilitySnapshot | None,
    metrics: MarketMetrics | None,
    reward_multiple: float,
) -> TradeSignal | None:
    """Generate range trading signal."""
    closed_candle = ordered[-2]
    prev_candle = ordered[-3]
    
    support = range_levels["support"]
    resistance = range_levels["resistance"]
    range_size = range_levels["size"]
    price_position = range_levels["price_position"]
    
    # Only trade near boundaries (within 0.3% of support/resistance)
    boundary_tolerance = range_size * 0.08  # 8% of range size
    
    if direction == "buy":
        # Must be near support
        if closed_candle.close > support + boundary_tolerance:
            return None
        # Don't buy if support is broken
        if closed_candle.close < support - boundary_tolerance * 0.5:
            return None
        
        # RSI should be oversold or recovering
        if rsi_val > 45:
            return None
        
        # Require rejection candle
        is_rejection, rejection_type, rejection_strength = _is_rejection_candle(closed_candle, "buy", atr14)
        if not is_rejection:
            return None
        
        # MTF trend filter: don't buy if 1H trend is strongly bearish
        if mtf_trend == "bearish":
            return None
        
        # Entry: close of rejection candle
        entry = closed_candle.close
        
        # Stop: below support with ATR buffer (wider stop for range trades)
        stop = support - atr14 * 1.0
        
        # Target: middle of range or resistance (whichever is closer)
        target = min(resistance - atr14 * 0.2, range_levels["mid"] + range_size * 0.2)
        
    else:  # sell
        # Must be near resistance
        if closed_candle.close < resistance - boundary_tolerance:
            return None
        # Don't sell if resistance is broken
        if closed_candle.close > resistance + boundary_tolerance * 0.5:
            return None
        
        # RSI should be overbought or recovering
        if rsi_val < 55:
            return None
        
        # Require rejection candle
        is_rejection, rejection_type, rejection_strength = _is_rejection_candle(closed_candle, "sell", atr14)
        if not is_rejection:
            return None
        
        # MTF trend filter: don't sell if 1H trend is strongly bullish
        if mtf_trend == "bullish":
            return None
        
        entry = closed_candle.close
        stop = resistance + atr14 * 1.0
        target = max(support + atr14 * 0.2, range_levels["mid"] - range_size * 0.2)
    
    # Check regime allows range trading
    if regime:
        if regime.phase == "trending":
            return None  # Don't range trade in trends
    
    # Volume should be declining or normal (exhaustion move)
    if vol_analysis["ratio"] > 1.5:
        return None  # High volume = breakout, not rejection
    
    # Confidence based on multiple factors
    boundary_proximity = 1.0 - abs(closed_candle.close - (support if direction == "buy" else resistance)) / boundary_tolerance
    boundary_proximity = max(0, min(1, boundary_proximity))
    
    rsi_score = 1.0 - abs(rsi_val - (30 if direction == "buy" else 70)) / 40.0
    rsi_score = max(0, min(1, rsi_score))
    
    confluence_score = 0.35
    confluence_score += boundary_proximity * 0.20
    confluence_score += rsi_score * 0.15
    confluence_score += rejection_strength * 0.15
    confluence_score += 0.10 if mtf_trend == "neutral" else 0.05  # Neutral MTF is good for range
    confluence_score += 0.05 if vol_analysis["trend"] == "decreasing" else 0.0
    
    confidence = _clamp(0.40 + confluence_score * 0.50, 0.40, 0.85)
    confidence, psych_reason = _psychology_adjustment(psychology, direction, confidence)
    confidence, read_reason = _readability_adjustment(readability, confidence)
    
    if confidence < 0.50:
        return None
    
    # Check RR is reasonable
    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else 0
    
    # Range trades need at least 0.8 RR
    if rr < 0.8:
        return None
    
    # Adjust target to achieve minimum RR if needed
    if rr < 1.0:
        # Extend target slightly if range allows
        if direction == "buy":
            target = entry + risk * 1.0
        else:
            target = entry - risk * 1.0
    
    reasons = [
        f"Range {direction} at {'support' if direction == 'buy' else 'resistance'}",
        f"RSI: {rsi_val:.1f}",
        f"Rejection: {rejection_type}",
        f"MTF: {mtf_trend}",
    ]
    if vol_analysis["trend"] != "neutral":
        reasons.append(f"Volume: {vol_analysis['trend']}")
    if psych_reason != "psychology neutral":
        reasons.append(psych_reason)
    if read_reason != "readability neutral":
        reasons.append(read_reason)
    
    return _make_signal(
        side=direction,
        timestamp=closed_candle.timestamp,
        entry=entry,
        stop=stop,
        target=target,
        confidence=confidence,
        reason="; ".join(reasons),
        metrics=metrics,
        atr=atr14,
        confluence=confluence_score,
    )


def _trend_signal(
    ordered: list[Candle],
    direction: str,
    closes: list[float],
    ema9: float,
    ema20: float,
    ema50: float,
    ema100: float,
    atr14: float,
    rsi_val: float,
    swings: list[Swing],
    fvgs: list[FVG],
    regime: MarketRegime | None,
    psychology: PsychologySnapshot | None,
    readability: ReadabilitySnapshot | None,
    metrics: MarketMetrics | None,
    reward_multiple: float,
) -> TradeSignal | None:
    """Generate trend-following pullback signal (secondary mode)."""
    closed_candle = ordered[-2]
    
    # Higher timeframe alignment
    price_vs_ema100 = (closed_candle.close - ema100) / ema100 * 100 if ema100 > 0 else 0
    
    # Only trade in direction of 100 EMA
    if direction == "buy" and price_vs_ema100 < -0.2:
        return None
    if direction == "sell" and price_vs_ema100 > 0.2:
        return None
    
    if direction == "buy":
        ema_aligned = ema9 > ema20 and ema20 > ema50
        trend_strength = (ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0
        
        if not ema_aligned:
            return None
        if trend_strength < 0.30:
            return None
    else:
        ema_aligned = ema9 < ema20 and ema20 < ema50
        trend_strength = (ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0
        
        if not ema_aligned:
            return None
        if trend_strength > -0.30:
            return None

    # Regime filter: only trend trade when regime is trending
    if regime:
        if regime.phase != "trending":
            return None

    # Pullback detection: price near EMA20
    current_distance = abs(closed_candle.close - ema20) / ema20
    if current_distance > 0.005:
        return None
    
    # RSI should be in normal range (not extreme)
    if rsi_val < 35 or rsi_val > 65:
        return None
    
    # Require rejection candle at EMA20
    is_rejection, rejection_type, rejection_strength = _is_rejection_candle(closed_candle, direction, atr14)
    if not is_rejection:
        return None

    # Volume should be declining (pullback exhaustion)
    vol_info = _volume_analysis(ordered, 20)
    if vol_info["ratio"] > 1.3:
        return None

    # Confidence calculation
    confluence_score = 0.40
    confluence_score += 0.15 if ema_aligned else 0.0
    confluence_score += rejection_strength * 0.15
    confluence_score += 0.10 if vol_info["trend"] == "decreasing" else 0.0
    
    confidence = _clamp(0.40 + confluence_score * 0.50, 0.40, 0.85)
    confidence, psych_reason = _psychology_adjustment(psychology, direction, confidence)
    confidence, read_reason = _readability_adjustment(readability, confidence)
    
    if confidence < 0.55:
        return None

    # Entry/Stop/Target
    entry = closed_candle.close
    if direction == "buy":
        stop = entry - atr14 * 2.0  # Wider stop for trend trades
        target = entry + (entry - stop) * reward_multiple
    else:
        stop = entry + atr14 * 2.0
        target = entry - (stop - entry) * reward_multiple

    risk = abs(entry - stop)
    if risk < atr14 * 1.0 or risk > atr14 * 4.0:
        return None

    reasons = [
        f"Trend {direction} pullback",
        f"Trend strength: {trend_strength:+.1f}%",
        f"Rejection: {rejection_type}",
    ]
    if psych_reason != "psychology neutral":
        reasons.append(psych_reason)
    if read_reason != "readability neutral":
        reasons.append(read_reason)

    return _make_signal(
        side=direction,
        timestamp=closed_candle.timestamp,
        entry=entry,
        stop=stop,
        target=target,
        confidence=confidence,
        reason="; ".join(reasons),
        metrics=metrics,
        atr=atr14,
        confluence=confluence_score,
    )


def detect_trade_signals(
    candles: list[Candle],
    metrics: MarketMetrics | None = None,
    fvgs: list[FVG] | None = None,
    order_blocks: list[OrderBlock] | None = None,
    liquidity_events: list[LiquidityEvent] | None = None,
    swings: list[Swing] | None = None,
    regime: MarketRegime | None = None,
    mtf_confluence: dict | None = None,
    ob_imbalances: list[dict] | None = None,
    ob_accumulations: list[dict] | None = None,
    psychology: PsychologySnapshot | None = None,
    readability: ReadabilitySnapshot | None = None,
    reward_multiple: float = 2.0,
) -> list[TradeSignal]:
    """
    Range-focused signal generation with MTF confirmation.
    
    Primary mode: Range trading (buy support, sell resistance)
    Secondary mode: Trend pullbacks (only when regime is strongly trending)
    """
    if len(candles) < 150:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    closed_candle = ordered[-2]
    atr14 = _atr(ordered, 14)
    rsi_val = _rsi(closes, 14)

    # EMAs
    ema20 = _ema(closes[-50:], 20)
    ema50 = _ema(closes[-80:], 50)
    ema9 = _ema(closes[-30:], 9)
    ema100 = _ema(closes[-min(150, len(closes)-1):], min(150, len(closes)-1))

    fvgs = fvgs or []
    swings = swings or []
    
    # Find range levels
    range_levels = _find_range_levels(ordered, 100)
    
    # Check MTF trend
    mtf_trend = _check_mtf_trend(ordered)
    
    # Volume analysis
    vol_analysis = _volume_analysis(ordered, 20)
    
    # COOLDOWN: Require some price movement
    recent_range = max(c.high for c in ordered[-15:-2]) - min(c.low for c in ordered[-15:-2])
    if recent_range < atr14 * 0.8:
        return []

    signals: list[TradeSignal] = []
    
    # Determine primary mode based on regime
    phase = regime.phase if regime else "unknown"
    is_trending = phase == "trending"
    
    # PRIMARY: Range trading (default mode)
    if not is_trending:
        for direction in ["buy", "sell"]:
            sig = _range_signal(
                ordered, direction, range_levels, atr14, rsi_val, mtf_trend,
                vol_analysis, regime, psychology, readability, metrics, reward_multiple
            )
            if sig:
                signals.append(sig)
    
    # SECONDARY: Trend pullbacks (only when trending)
    if is_trending:
        for direction in ["buy", "sell"]:
            sig = _trend_signal(
                ordered, direction, closes, ema9, ema20, ema50, ema100,
                atr14, rsi_val, swings, fvgs, regime, psychology, readability,
                metrics, reward_multiple
            )
            if sig:
                signals.append(sig)
    
    if not signals:
        return []

    # Return highest confidence signal only
    return [max(signals, key=lambda s: s.confidence)]
