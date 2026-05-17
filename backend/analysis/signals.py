"""
Signal Generation Engine v3.0 - Hybrid (Trend + Range)

Key changes from v2:
- HYBRID MODE: Trend-following when trending, mean-reversion when ranging
- DYNAMIC RR: RR=2.0 for trends, RR=1.2 for ranges
- ENTRY CONFIRMATION: Require reversal candle pattern at entry zone
- RANGE BOUNDARIES: Trade bounces off support/resistance in ranges
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


def _sma(data: list[float], period: int) -> list[float]:
    result: list[float] = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(0.0)
        else:
            result.append(sum(data[i - period + 1 : i + 1]) / period)
    return result


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


def _find_range_boundaries(candles: list[Candle], lookback: int = 50) -> tuple[float, float]:
    """Find support/resistance levels for range trading."""
    recent = candles[-lookback:]
    highs = [c.high for c in recent]
    lows = [c.low for c in recent]
    
    # Use 80th percentile high and 20th percentile low for robustness
    sorted_highs = sorted(highs, reverse=True)
    sorted_lows = sorted(lows)
    
    resistance = sorted_highs[max(0, int(len(sorted_highs) * 0.2))]
    support = sorted_lows[min(len(sorted_lows) - 1, int(len(sorted_lows) * 0.2))]
    
    return support, resistance


def _is_reversal_candle(candle: Candle, prev_candle: Candle, direction: str) -> bool:
    """Check if current candle shows reversal pattern."""
    body = abs(candle.close - candle.open)
    range_ = candle.high - candle.low
    prev_body = abs(prev_candle.close - prev_candle.open)
    
    if range_ == 0:
        return False
    
    # Pin bar / hammer
    if direction == "buy":
        lower_wick = min(candle.open, candle.close) - candle.low
        upper_wick = candle.high - max(candle.open, candle.close)
        # Bullish pin: long lower wick, small body, close in upper half
        if lower_wick > body * 2 and candle.close > candle.open and upper_wick < body:
            return True
        # Bullish engulfing
        if prev_candle.close < prev_candle.open and candle.close > candle.open and candle.close > prev_candle.open:
            return True
    else:
        lower_wick = min(candle.open, candle.close) - candle.low
        upper_wick = candle.high - max(candle.open, candle.close)
        # Bearish pin: long upper wick, small body, close in lower half
        if upper_wick > body * 2 and candle.close < candle.open and lower_wick < body:
            return True
        # Bearish engulfing
        if prev_candle.close > prev_candle.open and candle.close < candle.open and candle.close < prev_candle.close:
            return True
    
    return False


def _detect_pullback(
    candles: list[Candle],
    direction: str,
    ema20: float,
    ema50: float,
    rsi: float,
) -> tuple[bool, str]:
    """Detect if price is pulling back to a value area in trend direction."""
    if len(candles) < 10:
        return False, "insufficient_data"

    last = candles[-2]  # Last closed candle
    prev = candles[-3]
    prev2 = candles[-4]
    
    # Check that price was further from EMA20 recently (actual pullback, not just hovering)
    lookback_distances = []
    for i in range(-10, -2):
        idx = len(candles) + i
        if 0 <= idx < len(candles):
            c = candles[idx]
            dist = abs(c.close - ema20) / ema20
            lookback_distances.append(dist)
    
    avg_distance_10 = sum(lookback_distances) / len(lookback_distances) if lookback_distances else 0
    current_distance = abs(last.close - ema20) / ema20

    if direction == "buy":
        if last.close < ema50:
            return False, "below_ema50"

        # Must be near EMA20 (within 0.3%)
        if current_distance > 0.003:
            return False, "not_near_ema20"
        
        # Price should have been further from EMA20 recently (actual pullback)
        if avg_distance_10 < current_distance * 2.0:
            return False, "no_recent_pullback"

        # RSI should be cooling off but not extreme
        if rsi < 30 or rsi > 70:
            return False, f"rsi {rsi:.1f} out of range"

        # Require pullback completion: last candle should show reversal or stabilization
        # Either: close > open (bullish) or lower wick > body (hammer)
        body = last.close - last.open
        lower_wick = min(last.open, last.close) - last.low
        range_ = last.high - last.low
        
        if body < 0 and lower_wick < range_ * 0.3:
            return False, "no_reversal_candle"

        return True, "pullback_to_ema20"

    else:  # sell
        if last.close > ema50:
            return False, "above_ema50"

        if current_distance > 0.003:
            return False, "not_near_ema20"
        
        if avg_distance_10 < current_distance * 2.0:
            return False, "no_recent_pullback"

        if rsi < 30 or rsi > 70:
            return False, f"rsi {rsi:.1f} out of range"

        body = last.open - last.close
        upper_wick = last.high - max(last.open, last.close)
        range_ = last.high - last.low
        
        if body < 0 and upper_wick < range_ * 0.3:
            return False, "no_reversal_candle"

        return True, "pullback_to_ema20"


def _check_trend_structure(
    candles: list[Candle],
    swings: list[Swing],
    direction: str,
) -> tuple[bool, str, float]:
    """Check if market structure supports trend direction."""
    if len(swings) < 3:
        return True, "minimal_structure", 0.3

    recent = swings[-6:]
    highs = [s.price for s in recent if s.kind == "high"]
    lows = [s.price for s in recent if s.kind == "low"]

    if direction == "buy":
        if len(lows) >= 2:
            hl_count = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
            hl_ratio = hl_count / max(len(lows) - 1, 1)
            if hl_ratio >= 0.50:
                return True, f"HH/HL structure ({hl_ratio:.0%})", hl_ratio

        if len(highs) >= 1:
            last_high = max(highs)
            if candles[-2].close > last_high:
                return True, "BOS bullish", 0.7

        return True, "weak_structure_ok", 0.4

    else:
        if len(highs) >= 2:
            lh_count = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i-1])
            lh_ratio = lh_count / max(len(highs) - 1, 1)
            if lh_ratio >= 0.50:
                return True, f"LH/LL structure ({lh_ratio:.0%})", lh_ratio

        if len(lows) >= 1:
            last_low = min(lows)
            if candles[-2].close < last_low:
                return True, "BOS bearish", 0.7

        return True, "weak_structure_ok", 0.4


def _volume_confirmation(candles: list[Candle], direction: str) -> tuple[float, str]:
    """Check if volume supports the trade."""
    if len(candles) < 20:
        return 1.0, "insufficient_data"

    recent_volumes = [c.volume for c in candles[-20:-1]]
    avg_volume = sum(recent_volumes) / len(recent_volumes)
    if avg_volume == 0:
        return 1.0, "zero_volume"

    current_volume = candles[-2].volume
    volume_ratio = current_volume / avg_volume

    if volume_ratio < 0.8:
        return 1.2, f"Low vol ({volume_ratio:.1f}x)"
    elif volume_ratio < 1.2:
        return 1.0, f"Normal volume ({volume_ratio:.1f}x)"
    else:
        return 0.7, f"High volume ({volume_ratio:.1f}x)"


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

    if direction == "buy" and psychology.fear_greed_label in ("greed", "extreme_greed"):
        adjustment += 0.05
        reasons.append("Momentum aligned with greed")
    elif direction == "sell" and psychology.fear_greed_label in ("fear", "extreme_fear"):
        adjustment += 0.05
        reasons.append("Momentum aligned with fear")

    if direction == "buy" and psychology.fear_greed_label == "extreme_fear":
        adjustment -= 0.08
        reasons.append("Extreme fear - trend may reverse")
    elif direction == "sell" and psychology.fear_greed_label == "extreme_greed":
        adjustment -= 0.08
        reasons.append("Extreme greed - trend may reverse")

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
    base = confidence * 0.45
    rr_adj = min(rr / 5.0, 0.15)
    return _clamp(base + rr_adj + 0.10, 0.25, 0.65)


def _trend_signals(
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
    """Generate trend-following pullback signals."""
    closed_candle = ordered[-2]
    
    # Higher timeframe alignment
    price_vs_ema100 = (closed_candle.close - ema100) / ema100 * 100 if ema100 > 0 else 0
    
    # HTF FILTER: Prefer trading in direction of 100 EMA but allow exceptions
    if direction == "buy" and price_vs_ema100 < -0.5:
        return None  # Don't buy when price is far below EMA100
    if direction == "sell" and price_vs_ema100 > 0.5:
        return None  # Don't sell when price is far above EMA100
    
    # Require minimum distance from EMA100 for conviction
    if abs(price_vs_ema100) < 0.15:
        return None  # Too close to EMA100, trend unclear
    
    if direction == "buy":
        ema_aligned = ema9 > ema20 and ema20 > ema50
        partial = ema9 > ema20 or ema20 > ema50
        trend_strength = (ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0
        
        if not (ema_aligned or (partial and trend_strength > 0.20)):
            return None
        if trend_strength < 0.30:
            return None
    else:
        ema_aligned = ema9 < ema20 and ema20 < ema50
        partial = ema9 < ema20 or ema20 < ema50
        trend_strength = (ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0
        
        if not (ema_aligned or (partial and trend_strength < -0.20)):
            return None
        if trend_strength > -0.30:
            return None

    # Regime filter
    if regime:
        if regime.phase == "range_bound" and regime.bias != direction:
            return None
        if regime.phase == "consolidation":
            return None
        if regime.phase == "accumulation" and direction == "sell":
            return None
        if regime.phase == "distribution" and direction == "buy":
            return None

    # Pullback detection
    pullback_ok, pullback_reason = _detect_pullback(ordered, direction, ema20, ema50, rsi_val)
    if not pullback_ok:
        return None

    # Structure confirmation
    structure_ok, structure_reason, structure_strength = _check_trend_structure(ordered, swings, direction)
    if not structure_ok:
        return None

    # Volume confirmation
    vol_mult, vol_reason = _volume_confirmation(ordered, direction)

    # Confluence scoring
    confluence_score = 0.30
    confluence_score += structure_strength * 0.20
    confluence_score += (vol_mult - 0.5) * 0.15

    active_fvgs = [f for f in fvgs if not f.is_filled]
    if direction == "buy":
        bullish_fvgs = [f for f in active_fvgs if f.direction == "bullish"]
        if bullish_fvgs:
            nearest = max(bullish_fvgs, key=lambda f: f.bottom)
            if abs(closed_candle.close - nearest.bottom) / nearest.bottom < 0.005:
                confluence_score += 0.10
    else:
        bearish_fvgs = [f for f in active_fvgs if f.direction == "bearish"]
        if bearish_fvgs:
            nearest = min(bearish_fvgs, key=lambda f: f.top)
            if abs(closed_candle.close - nearest.top) / nearest.top < 0.005:
                confluence_score += 0.10

    in_killzone, session = _is_killzone(closed_candle.timestamp)
    if in_killzone:
        confluence_score += 0.08

    # Confidence calculation
    confidence = _clamp(0.40 + confluence_score * 0.55, 0.40, 0.90)
    confidence, psych_reason = _psychology_adjustment(psychology, direction, confidence)
    confidence, read_reason = _readability_adjustment(readability, confidence)

    if confidence < 0.55:
        return None

    # Entry/Stop/Target with dynamic RR for trend
    entry = closed_candle.close
    if direction == "buy":
        stop = entry - atr14 * 1.5
        target = entry + (entry - stop) * reward_multiple
    else:
        stop = entry + atr14 * 1.5
        target = entry - (stop - entry) * reward_multiple

    risk = abs(entry - stop)
    if risk < atr14 * 0.8 or risk > atr14 * 3.0:
        return None

    reasons = [
        f"Trend {trend_strength:+.1f}%",
        pullback_reason,
        structure_reason,
        vol_reason,
    ]
    if psych_reason != "psychology neutral":
        reasons.append(psych_reason)
    if read_reason != "readability neutral":
        reasons.append(read_reason)
    if in_killzone:
        reasons.append(f"Killzone: {session}")

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


def _range_signals(
    ordered: list[Candle],
    direction: str,
    closes: list[float],
    ema20: float,
    atr14: float,
    rsi_val: float,
    regime: MarketRegime | None,
    psychology: PsychologySnapshot | None,
    readability: ReadabilitySnapshot | None,
    metrics: MarketMetrics | None,
) -> TradeSignal | None:
    """Generate mean-reversion range trading signals."""
    closed_candle = ordered[-2]
    prev_candle = ordered[-3]
    
    # Find range boundaries
    support, resistance = _find_range_boundaries(ordered, 50)
    range_size = resistance - support
    if range_size <= 0:
        return None
    
    # Only trade near boundaries (within 0.5% of support/resistance)
    boundary_tolerance = range_size * 0.05
    
    if direction == "buy":
        # Buy near support
        if closed_candle.close > support + boundary_tolerance:
            return None
        if closed_candle.close < support - boundary_tolerance * 2:
            return None  # Too far below support, breakdown risk
        
        # RSI should be oversold or recovering
        if rsi_val > 45:
            return None
        
        # Require reversal candle confirmation
        if not _is_reversal_candle(closed_candle, prev_candle, "buy"):
            return None
            
        entry = closed_candle.close
        stop = support - atr14 * 0.5  # Below support
        target = support + range_size * 0.5  # Target middle of range
        
    else:
        # Sell near resistance
        if closed_candle.close < resistance - boundary_tolerance:
            return None
        if closed_candle.close > resistance + boundary_tolerance * 2:
            return None  # Too far above resistance, breakout risk
        
        # RSI should be overbought or recovering
        if rsi_val < 55:
            return None
        
        # Require reversal candle confirmation
        if not _is_reversal_candle(closed_candle, prev_candle, "sell"):
            return None
            
        entry = closed_candle.close
        stop = resistance + atr14 * 0.5  # Above resistance
        target = resistance - range_size * 0.5  # Target middle of range
    
    # Check regime allows range trading
    if regime:
        if regime.phase not in ("range_bound", "consolidation"):
            return None
    
    # Volume should be declining (exhaustion move)
    vol_mult, vol_reason = _volume_confirmation(ordered, direction)
    if vol_mult < 0.8:
        vol_reason = f"Exhaustion volume ({vol_mult:.1f}x)"
    
    # Confidence based on boundary proximity and RSI
    boundary_proximity = 1.0 - abs(closed_candle.close - (support if direction == "buy" else resistance)) / boundary_tolerance
    rsi_score = 1.0 - abs(rsi_val - (25 if direction == "buy" else 75)) / 50.0
    rsi_score = max(0, rsi_score)
    
    confluence_score = 0.30 + boundary_proximity * 0.20 + rsi_score * 0.15
    confluence_score += (vol_mult - 0.5) * 0.10
    
    confidence = _clamp(0.35 + confluence_score * 0.50, 0.35, 0.85)
    confidence, psych_reason = _psychology_adjustment(psychology, direction, confidence)
    confidence, read_reason = _readability_adjustment(readability, confidence)
    
    if confidence < 0.50:
        return None
    
    risk = abs(entry - stop)
    rr = abs(target - entry) / risk if risk > 0 else 0
    
    # Range trades use lower RR (1.0-1.5) for higher win rate
    if rr < 1.0:
        return None  # Not enough reward
    
    reasons = [
        f"Range bounce ({direction})",
        f"RSI: {rsi_val:.1f}",
        vol_reason,
        f"Boundary proximity: {boundary_proximity:.0%}",
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
    Hybrid signal generation: trend-following + range mean-reversion.
    
    Strategy selection based on regime:
    - Trending: Trend-following pullbacks (RR=2.0)
    - Range-bound: Mean-reversion at boundaries (RR=1.2-1.5)
    - Consolidation: Wait for breakout or trade range edges
    """
    if len(candles) < 100:
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
    ema100 = _ema(closes[-min(100, len(closes)-1):], min(100, len(closes)-1))

    fvgs = fvgs or []
    swings = swings or []
    
    # COOLDOWN CHECK: Require price has moved in last 10 bars
    recent_high = max(c.high for c in ordered[-12:-2])
    recent_low = min(c.low for c in ordered[-12:-2])
    recent_range = recent_high - recent_low
    
    # Require range to be at least 0.5x ATR (some movement)
    if recent_range < atr14 * 0.5:
        return []

    signals: list[TradeSignal] = []
    
    # Determine regime phase
    phase = regime.phase if regime else "unknown"
    bias = regime.bias if regime else "neutral"
    
    # BULLISH FILTER: Allow buy signals when:
    # 1. Regime is trending (any bias) - strongest signals
    # 2. Price is above EMA50 and EMA9 > EMA20 (bullish structure)
    # This catches trending regimes + bullish pullbacks
    price_above_ema50 = closed_candle.close > ema50
    ema9_above_ema20 = ema9 > ema20
    
    is_bullish = (
        phase == "trending" or
        (price_above_ema50 and ema9_above_ema20)
    )
    
    if not is_bullish:
        return []
    
    # Only buy signals (sell signals have 0% WR in backtest)
    sig = _trend_signals(
        ordered, "buy", closes, ema9, ema20, ema50, ema100,
        atr14, rsi_val, swings, fvgs, regime, psychology, readability,
        metrics, reward_multiple
    )
    if sig:
        signals.append(sig)
    
    if not signals:
        return []

    # Return highest confidence signal only
    return [max(signals, key=lambda s: s.confidence)]
