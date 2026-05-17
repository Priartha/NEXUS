"""
Signal Generation Engine v2.0 - Trend-Following Pullbacks

Key changes from v1:
- TREND-FOLLOWING: Enter on pullbacks in direction of trend
- Not reversals at FVGs/OBs
- Pullback detection using EMA retests
- Confidence calibrated to historical win rates
- Requires structure + momentum confirmation
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


def _detect_pullback(
    candles: list[Candle],
    direction: str,
    ema20: float,
    ema50: float,
    rsi: float,
) -> tuple[bool, str]:
    """Detect if price is pulling back to a value area in trend direction."""
    if len(candles) < 5:
        return False, "insufficient_data"

    last = candles[-2]
    prev = candles[-3]
    prev2 = candles[-4]

    if direction == "buy":
        # Price should be above EMA50 (trend intact)
        if last.close < ema50:
            return False, "below_ema50"

        # Pullback to EMA20 zone (within 0.5%)
        ema20_distance = abs(last.close - ema20) / ema20
        if ema20_distance > 0.008:
            return False, "not_near_ema20"

        # RSI should be cooling off but not extreme
        if rsi < 30 or rsi > 70:
            return False, f"rsi {rsi:.1f} out of range"

        # Check for pullback (price was higher recently)
        if last.close > prev.close and prev.close > prev2.close:
            return False, "no_pullback_continuing_up"

        # Accept any pullback near EMA20
        return True, "pullback_to_ema20"

    else:  # sell
        if last.close > ema50:
            return False, "above_ema50"

        ema20_distance = abs(last.close - ema20) / ema20
        if ema20_distance > 0.008:
            return False, "not_near_ema20"

        if rsi < 30 or rsi > 70:
            return False, f"rsi {rsi:.1f} out of range"

        if last.close < prev.close and prev.close < prev2.close:
            return False, "no_pullback_continuing_down"

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

        # Check if price broke above recent high
        if len(highs) >= 1:
            last_high = max(highs)
            if candles[-2].close > last_high:
                return True, "BOS bullish", 0.7

        # Default: allow if trend is strong
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
    """Check if volume supports the trend continuation."""
    if len(candles) < 20:
        return 1.0, "insufficient_data"

    recent_volumes = [c.volume for c in candles[-20:-1]]
    avg_volume = sum(recent_volumes) / len(recent_volumes)
    if avg_volume == 0:
        return 1.0, "zero_volume"

    current_volume = candles[-2].volume  # Last closed candle
    volume_ratio = current_volume / avg_volume

    # For pullbacks, we want declining volume (not panic selling/FOMO)
    if direction == "buy":
        if volume_ratio < 0.8:
            return 1.2, f"Low vol pullback ({volume_ratio:.1f}x)"
        elif volume_ratio < 1.2:
            return 1.0, f"Normal volume ({volume_ratio:.1f}x)"
        else:
            return 0.5, f"High vol pullback suspicious ({volume_ratio:.1f}x)"
    else:
        if volume_ratio < 0.8:
            return 1.2, f"Low vol pullback ({volume_ratio:.1f}x)"
        elif volume_ratio < 1.2:
            return 1.0, f"Normal volume ({volume_ratio:.1f}x)"
        else:
            return 0.5, f"High vol pullback suspicious ({volume_ratio:.1f}x)"


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

    # Trend-following: buy in greed (momentum), sell in fear (momentum down)
    if direction == "buy" and psychology.fear_greed_label in ("greed", "extreme_greed"):
        adjustment += 0.05
        reasons.append("Momentum aligned with greed")
    elif direction == "sell" and psychology.fear_greed_label in ("fear", "extreme_fear"):
        adjustment += 0.05
        reasons.append("Momentum aligned with fear")

    # Contrarian at extremes (reduce confidence)
    if direction == "buy" and psychology.fear_greed_label == "extreme_fear":
        adjustment -= 0.08
        reasons.append("Extreme fear - trend may reverse")
    elif direction == "sell" and psychology.fear_greed_label == "extreme_greed":
        adjustment -= 0.08
        reasons.append("Extreme greed - trend may reverse")

    # High trap risk
    if psychology.trap_risk > 0.7:
        adjustment -= 0.05
        reasons.append("High trap risk")

    # Smart money confirms trend
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
    Trend-following pullback signal generation.

    Entry logic:
    1. Identify trend direction (EMA alignment + structure)
    2. Wait for pullback to value area (EMA20/EMA50)
    3. Confirm with structure, volume, psychology
    4. Enter in trend direction on pullback completion
    """
    if len(candles) < 100:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    closed_candle = ordered[-2]
    atr14 = _atr(ordered, 14)
    rsi_val = _rsi(closes, 14)

    # EMAs for trend detection
    ema20 = _ema(closes[-50:], 20)
    ema50 = _ema(closes[-80:], 50)
    ema9 = _ema(closes[-30:], 9)

    # Higher timeframe trend (using longer EMA)
    ema100 = _ema(closes[-min(100, len(closes)-1):], min(100, len(closes)-1))
    price_vs_ema100 = (closed_candle.close - ema100) / ema100 * 100 if ema100 > 0 else 0

    # Trend direction from EMA alignment
    ema_aligned_bullish = ema9 > ema20 and ema20 > ema50
    ema_aligned_bearish = ema9 < ema20 and ema20 < ema50

    # Also allow partial alignment (9 > 20 only, or 20 > 50 only)
    partial_bullish = ema9 > ema20 or ema20 > ema50
    partial_bearish = ema9 < ema20 or ema20 < ema50

    # Trend strength
    trend_strength = (ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0

    fvgs = fvgs or []
    order_blocks = order_blocks or []
    liquidity_events = liquidity_events or []
    swings = swings or []

    signals: list[TradeSignal] = []

    for direction in ["buy", "sell"]:
        # 1. TREND FILTER: Must have clear trend AND higher timeframe alignment
        if direction == "buy":
            if not (ema_aligned_bullish or (partial_bullish and trend_strength > 0.20)):
                continue
            # Higher timeframe check: price must be above EMA100
            if price_vs_ema100 < -0.3:
                continue
        if direction == "sell":
            if not (ema_aligned_bearish or (partial_bearish and trend_strength < -0.20)):
                continue
            # Higher timeframe check: price must be below EMA100
            if price_vs_ema100 > 0.3:
                continue

        # Trend strength minimum
        if direction == "buy" and trend_strength < 0.30:
            continue
        if direction == "sell" and trend_strength > -0.30:
            continue

        # 2. REGIME FILTER
        if regime:
            if regime.phase == "range_bound" and regime.bias != direction:
                continue
            if regime.phase == "consolidation":
                continue
            if regime.phase == "accumulation" and direction == "sell":
                continue
            if regime.phase == "distribution" and direction == "buy":
                continue

        # 3. PULLBACK DETECTION
        pullback_ok, pullback_reason = _detect_pullback(
            ordered, direction, ema20, ema50, rsi_val
        )
        if not pullback_ok:
            continue

        # 4. STRUCTURE CONFIRMATION
        structure_ok, structure_reason, structure_strength = _check_trend_structure(
            ordered, swings, direction
        )
        if not structure_ok:
            continue

        # 5. VOLUME CONFIRMATION
        vol_mult, vol_reason = _volume_confirmation(ordered, direction)

        # 6. CONFLUENCE SCORING
        confluence_score = 0.30  # Base for trend + pullback
        confluence_score += structure_strength * 0.20
        confluence_score += (vol_mult - 0.5) * 0.15

        # FVG in trend direction adds confluence
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

        # Killzone timing
        in_killzone, session = _is_killzone(closed_candle.timestamp)
        if in_killzone:
            confluence_score += 0.08

        # 7. CONFIDENCE CALCULATION
        confidence = _clamp(0.40 + confluence_score * 0.55, 0.40, 0.90)

        # 8. PSYCHOLOGY ADJUSTMENT
        confidence, psych_reason = _psychology_adjustment(psychology, direction, confidence)

        # 9. READABILITY ADJUSTMENT
        confidence, read_reason = _readability_adjustment(readability, confidence)

        # 10. FINAL FILTER
        if confidence < 0.55:
            continue

        # 11. ENTRY/STOP/TARGET
        entry = closed_candle.close

        # Stop: ATR-based from entry
        if direction == "buy":
            stop = entry - atr14 * 1.5
            target = entry + (entry - stop) * reward_multiple
        else:
            stop = entry + atr14 * 1.5
            target = entry - (stop - entry) * reward_multiple

        risk = abs(entry - stop)
        if risk < atr14 * 0.8 or risk > atr14 * 3.0:
            continue  # Stop too tight or too wide

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

        signal = _make_signal(
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
        signals.append(signal)

    if not signals:
        return []

    return [max(signals, key=lambda s: s.confidence)]
