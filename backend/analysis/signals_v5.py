"""
Signal Generation Engine v5.0 - Optimized Range Trading

Key insights from backtests:
- v3: PF 1.20, +$138 PnL, but only 15.4% WR
- v4: Too few signals, stops too wide
- Market is 96% ranging on 5m

Optimization strategy:
- Keep tight stops (1.5x ATR) from v3
- Range-focused entries from v4
- Better entry timing with multi-candle confirmation
- Target 25%+ win rate with RR 1.5-2.0
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


def _find_range_levels(candles: list[Candle], lookback: int = 80) -> dict:
    """Find robust support/resistance levels."""
    recent = candles[-lookback:]
    highs = [c.high for c in recent]
    lows = [c.low for c in recent]
    closes = [c.close for c in recent]
    
    # Use percentile-based levels (more robust than min/max)
    sorted_highs = sorted(highs, reverse=True)
    sorted_lows = sorted(lows)
    
    # 85th percentile high, 15th percentile low
    resistance = sorted_highs[max(0, int(len(sorted_highs) * 0.15))]
    support = sorted_lows[min(len(sorted_lows) - 1, int(len(sorted_lows) * 0.15))]
    
    range_size = resistance - support
    range_mid = (resistance + support) / 2
    current_price = closes[-1]
    price_position = (current_price - support) / range_size if range_size > 0 else 0.5
    
    return {
        "support": support,
        "resistance": resistance,
        "mid": range_mid,
        "size": range_size,
        "size_pct": range_size / current_price * 100 if current_price > 0 else 0,
        "price_position": price_position,
    }


def _check_rejection_sequence(candles: list[Candle], direction: str, level: float, atr: float) -> tuple[bool, str, float]:
    """Check for multi-candle rejection pattern at a level."""
    if len(candles) < 4:
        return False, "insufficient_data", 0.0
    
    # Last 3 closed candles
    c1 = candles[-2]  # Most recent
    c2 = candles[-3]
    c3 = candles[-4]
    
    strength = 0.0
    
    if direction == "buy":
        # Check if price tested support and bounced
        # 1. At least one candle should have wick touching/near support
        min_low = min(c1.low, c2.low, c3.low)
        if min_low > level + atr * 0.5:
            return False, "no_level_test", 0.0
        
        # 2. Most recent candle should be bullish or have long lower wick
        body1 = c1.close - c1.open
        lower_wick1 = min(c1.open, c1.close) - c1.low
        range1 = c1.high - c1.low
        
        if body1 > 0:
            strength += 0.4  # Bullish close
        if lower_wick1 > body1 * 0.5 and range1 > 0:
            strength += 0.3  # Lower wick rejection
        if c1.close > c2.close:
            strength += 0.2  # Higher close than prev
        if c1.close > c3.close:
            strength += 0.1  # Higher close than 2 bars ago
        
        return strength >= 0.5, "support_bounce", strength
        
    else:  # sell
        max_high = max(c1.high, c2.high, c3.high)
        if max_high < level - atr * 0.5:
            return False, "no_level_test", 0.0
        
        body1 = c1.open - c1.close
        upper_wick1 = c1.high - max(c1.open, c1.close)
        range1 = c1.high - c1.low
        
        if body1 > 0:
            strength += 0.4  # Bearish close
        if upper_wick1 > body1 * 0.5 and range1 > 0:
            strength += 0.3  # Upper wick rejection
        if c1.close < c2.close:
            strength += 0.2
        if c1.close < c3.close:
            strength += 0.1
        
        return strength >= 0.5, "resistance_rejection", strength


def _check_mtf_trend(candles: list[Candle]) -> str:
    """Check higher timeframe trend."""
    closes = [c.close for c in candles]
    if len(closes) < 250:
        return "neutral"
    
    ema50 = _ema(closes[-250:], 50)
    ema100 = _ema(closes[-250:], 100)
    ema200 = _ema(closes[-250:], 200)
    current_price = closes[-1]
    
    if current_price > ema50 > ema100 > ema200:
        return "bullish"
    elif current_price < ema50 < ema100 < ema200:
        return "bearish"
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
    if not psychology:
        return base_confidence, "no_psychology_data"

    adjustment = 0.0
    reasons = []

    if direction == "buy" and psychology.fear_greed_label in ("fear", "extreme_fear"):
        adjustment += 0.05
        reasons.append("Fear = buying opportunity")
    elif direction == "sell" and psychology.fear_greed_label in ("greed", "extreme_greed"):
        adjustment += 0.05
        reasons.append("Greed = selling opportunity")

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
    """Generate range trading signal with tight stops."""
    closed_candle = ordered[-2]
    
    support = range_levels["support"]
    resistance = range_levels["resistance"]
    range_size = range_levels["size"]
    price_position = range_levels["price_position"]
    
    # Only trade near boundaries (within 0.2% of support/resistance)
    boundary_tolerance = range_size * 0.06
    
    if direction == "buy":
        if closed_candle.close > support + boundary_tolerance:
            return None
        if closed_candle.close < support - boundary_tolerance * 0.3:
            return None  # Support broken
        
        # RSI oversold
        if rsi_val > 40:
            return None
        
        # Multi-candle rejection at support
        is_rejection, rejection_type, rejection_strength = _check_rejection_sequence(
            ordered, "buy", support, atr14
        )
        if not is_rejection:
            return None
        
        # Don't buy if MTF trend is strongly bearish
        if mtf_trend == "bearish":
            return None
        
        entry = closed_candle.close
        stop = support - atr14 * 0.8  # Tight stop below support
        target = range_levels["mid"] + range_size * 0.15  # Target above middle
        
    else:  # sell
        if closed_candle.close < resistance - boundary_tolerance:
            return None
        if closed_candle.close > resistance + boundary_tolerance * 0.3:
            return None  # Resistance broken
        
        if rsi_val < 60:
            return None
        
        is_rejection, rejection_type, rejection_strength = _check_rejection_sequence(
            ordered, "sell", resistance, atr14
        )
        if not is_rejection:
            return None
        
        if mtf_trend == "bullish":
            return None
        
        entry = closed_candle.close
        stop = resistance + atr14 * 0.8
        target = range_levels["mid"] - range_size * 0.15
    
    # Regime filter: don't range trade in trends
    if regime and regime.phase == "trending":
        return None
    
    # Volume filter: declining volume = exhaustion
    if vol_analysis["ratio"] > 1.4:
        return None
    
    # Confidence calculation
    boundary_proximity = 1.0 - abs(closed_candle.close - (support if direction == "buy" else resistance)) / boundary_tolerance
    boundary_proximity = max(0, min(1, boundary_proximity))
    
    rsi_score = 1.0 - abs(rsi_val - (30 if direction == "buy" else 70)) / 40.0
    rsi_score = max(0, min(1, rsi_score))
    
    confluence_score = 0.40
    confluence_score += boundary_proximity * 0.20
    confluence_score += rsi_score * 0.15
    confluence_score += rejection_strength * 0.15
    confluence_score += 0.05 if vol_analysis["trend"] == "decreasing" else 0.0
    
    confidence = _clamp(0.40 + confluence_score * 0.50, 0.40, 0.85)
    confidence, psych_reason = _psychology_adjustment(psychology, direction, confidence)
    confidence, read_reason = _readability_adjustment(readability, confidence)
    
    if confidence < 0.50:
        return None
    
    # Check RR
    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else 0
    
    if rr < 1.0:
        return None
    
    reasons = [
        f"Range {direction}",
        f"RSI: {rsi_val:.1f}",
        f"Rejection: {rejection_type} ({rejection_strength:.0%})",
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
    Range-focused signal generation with tight stops.
    """
    if len(candles) < 120:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    atr14 = _atr(ordered, 14)
    rsi_val = _rsi(closes, 14)

    # Find range levels
    range_levels = _find_range_levels(ordered, 80)
    
    # Check MTF trend
    mtf_trend = _check_mtf_trend(ordered)
    
    # Volume analysis
    vol_analysis = _volume_analysis(ordered, 20)
    
    # COOLDOWN: Require some price movement
    recent_range = max(c.high for c in ordered[-12:-2]) - min(c.low for c in ordered[-12:-2])
    if recent_range < atr14 * 0.6:
        return []

    signals: list[TradeSignal] = []
    
    # Range trading (primary mode)
    phase = regime.phase if regime else "unknown"
    if phase != "trending":
        for direction in ["buy", "sell"]:
            sig = _range_signal(
                ordered, direction, range_levels, atr14, rsi_val, mtf_trend,
                vol_analysis, regime, psychology, readability, metrics, reward_multiple
            )
            if sig:
                signals.append(sig)
    
    if not signals:
        return []

    return [max(signals, key=lambda s: s.confidence)]
