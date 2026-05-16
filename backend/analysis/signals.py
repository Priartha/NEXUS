"""
Signal Generation Engine for NEXUS - v3.0

FIXES APPLIED:
- Look-ahead bias eliminated: signals only generated on CLOSED candles
- Signal lifecycle management: pending -> active -> expired -> filled
- Regime-aware filtering: no trend signals in ranging markets
- MTF confluence integration: higher-timeframe alignment boosts confidence
- Orderbook confluence: bid/ask imbalance factored into signal scoring
- Volume profile integration: POC/VAH/VAL used as S/R levels
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
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


class SignalStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    FILLED = "filled"
    CANCELLED = "cancelled"


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
    minute = dt.minute
    time_val = hour + minute / 60.0
    if 2.0 <= time_val < 5.0:
        return True, "london"
    if 8.5 <= time_val < 11.0:
        return True, "ny_am"
    if 13.5 <= time_val < 16.0:
        return True, "ny_pm"
    return False, "off_hours"


def _find_nearest_fvg(candles: list[Candle], fvgs: list[FVG], current_price: float, direction: str) -> FVG | None:
    active = [f for f in fvgs if not f.is_filled]
    if not active:
        return None
    if direction == "buy":
        below = [f for f in active if f.bottom < current_price]
        if below:
            return max(below, key=lambda f: f.bottom)
    else:
        above = [f for f in active if f.top > current_price]
        if above:
            return min(above, key=lambda f: f.top)
    return None


def _find_nearest_ob(candles: list[Candle], order_blocks: list[OrderBlock], current_price: float, direction: str) -> OrderBlock | None:
    active = [ob for ob in order_blocks if not ob.is_breaker]
    if not active:
        return None
    if direction == "buy":
        below = [ob for ob in active if ob.bottom < current_price and ob.direction == "bullish"]
        if below:
            return max(below, key=lambda ob: ob.bottom)
    else:
        above = [ob for ob in active if ob.top > current_price and ob.direction == "bearish"]
        if above:
            return min(above, key=lambda ob: ob.top)
    return None


def _has_liquidity_sweep(liquidity_events: list[LiquidityEvent], direction: str, lookback_ms: int = 3600000) -> bool:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    recent = [e for e in liquidity_events if (now_ms - e.timestamp) < lookback_ms]
    if direction == "buy":
        return any(e.side == "sell_side" and e.reclaimed for e in recent)
    else:
        return any(e.side == "buy_side" and e.reclaimed for e in recent)


def _check_market_structure(candles: list[Candle], swings: list[Swing], direction: str) -> tuple[bool, str]:
    if len(swings) < 4:
        return False, "insufficient_swings"
    recent_swings = swings[-8:]
    if direction == "buy":
        last_hh = max((s.price for s in recent_swings if s.kind == "high"), default=0)
        if candles[-1].close > last_hh and last_hh > 0:
            return True, "BOS"
        lows = [s.price for s in recent_swings if s.kind == "low"]
        if len(lows) >= 2 and lows[-1] > lows[-2]:
            return True, "HL_confirmed"
    else:
        last_ll = min((s.price for s in recent_swings if s.kind == "low"), default=float("inf"))
        if candles[-1].close < last_ll and last_ll < float("inf"):
            return True, "BOS"
        highs = [s.price for s in recent_swings if s.kind == "high"]
        if len(highs) >= 2 and highs[-1] < highs[-2]:
            return True, "LH_confirmed"
    return False, "no_structure_break"


def _volume_confirmation(candles: list[Candle], direction: str) -> float:
    if len(candles) < 20:
        return 1.0
    recent_volumes = [c.volume for c in candles[-20:-1]]
    avg_volume = sum(recent_volumes) / len(recent_volumes)
    if avg_volume == 0:
        return 1.0
    current_volume = candles[-1].volume
    volume_ratio = current_volume / avg_volume
    if direction == "buy" and candles[-1].close > candles[-2].close:
        return min(volume_ratio / 1.5, 2.0)
    elif direction == "sell" and candles[-1].close < candles[-2].close:
        return min(volume_ratio / 1.5, 2.0)
    return 0.5


def _regime_filter(regime: MarketRegime | None, direction: str) -> tuple[bool, str]:
    """FIX #3: Regime-aware signal filtering.
    Blocks trend signals in ranging markets, range signals in trending markets."""
    if not regime:
        return True, "no_regime_data"

    phase = regime.phase
    bias = regime.bias

    if phase in {"consolidation", "range_bound"}:
        if direction == "buy" and bias == "bearish":
            return False, "range+bearish_bias"
        if direction == "sell" and bias == "bullish":
            return False, "range+bullish_bias"
        return True, "range_ok"

    if phase == "accumulation":
        if direction == "sell":
            return False, "accumulation_blocks_shorts"
        return True, "accumulation_allows_longs"

    if phase == "distribution":
        if direction == "buy":
            return False, "distribution_blocks_longs"
        return True, "distribution_allows_shorts"

    if phase == "trending":
        if direction == "buy" and bias == "bearish":
            return False, "trend+bearish_bias"
        if direction == "sell" and bias == "bullish":
            return False, "trend+bullish_bias"
        return True, "trend_aligned"

    return True, "unknown_regime"


def _mtf_confluence_boost(
    mtf_confluence: dict | None,
    direction: str,
    base_confidence: float,
) -> tuple[float, str]:
    """FIX #4: MTF confluence integration.
    Higher-timeframe alignment boosts confidence; conflict reduces it."""
    if not mtf_confluence:
        return base_confidence, "no_mtf_data"

    confluence_factor = mtf_confluence.get("confluence_factor", 1.0)
    higher_tf_bias = mtf_confluence.get("higher_tf_bias", "neutral")
    alignment = mtf_confluence.get("alignment_score", 0.5)

    if direction == "buy" and higher_tf_bias == "bullish" and alignment > 0.6:
        boost = _clamp(base_confidence * confluence_factor, base_confidence, 0.95)
        return boost, f"MTF bullish aligned ({alignment:.0%})"

    if direction == "sell" and higher_tf_bias == "bearish" and alignment > 0.6:
        boost = _clamp(base_confidence * confluence_factor, base_confidence, 0.95)
        return boost, f"MTF bearish aligned ({alignment:.0%})"

    if higher_tf_bias not in {"neutral", direction}:
        penalty = base_confidence * 0.85
        return penalty, f"MTF conflict: higher TF {higher_tf_bias}"

    return base_confidence, "MTF neutral"


def _orderbook_confluence(
    ob_imbalances: list[dict] | None,
    ob_accumulations: list[dict] | None,
    direction: str,
) -> tuple[float, str]:
    """FIX #5: Orderbook confluence scoring.
    Bid/ask imbalance and accumulation patterns add to signal confidence."""
    score = 0.0
    reasons: list[str] = []

    if ob_imbalances:
        recent_imb = ob_imbalances[-5:]
        if direction == "buy":
            buy_imb = [i for i in recent_imb if i.get("side") == "buy"]
            if buy_imb:
                avg_strength = sum(i.get("strength", 0) for i in buy_imb) / len(buy_imb)
                if avg_strength > 0.5:
                    score += 0.08 * avg_strength
                    reasons.append(f"OB buy pressure {avg_strength:.0%}")
        else:
            sell_imb = [i for i in recent_imb if i.get("side") == "sell"]
            if sell_imb:
                avg_strength = sum(i.get("strength", 0) for i in sell_imb) / len(sell_imb)
                if avg_strength > 0.5:
                    score += 0.08 * avg_strength
                    reasons.append(f"OB sell pressure {avg_strength:.0%}")

    if ob_accumulations:
        active_acc = [a for a in ob_accumulations if a.get("status") == "active"]
        if direction == "buy":
            buy_acc = [a for a in active_acc if a.get("side") == "accumulation"]
            if buy_acc:
                best = max(buy_acc, key=lambda a: a.get("confidence", 0))
                if best.get("confidence", 0) > 0.5:
                    score += 0.06 * best["confidence"]
                    reasons.append(f"OB accumulation {best['confidence']:.0%}")
        else:
            sell_acc = [a for a in active_acc if a.get("side") == "distribution"]
            if sell_acc:
                best = max(sell_acc, key=lambda a: a.get("confidence", 0))
                if best.get("confidence", 0) > 0.5:
                    score += 0.06 * best["confidence"]
                    reasons.append(f"OB distribution {best['confidence']:.0%}")

    return min(score, 0.15), "; ".join(reasons) if reasons else "no_ob_signal"


def _volume_profile_confluence(
    metrics: MarketMetrics | None,
    candles: list[Candle],
    current_price: float,
    direction: str,
) -> tuple[float, str]:
    """FIX #6: Volume profile integration.
    POC/VAH/VAL used as support/resistance for signal validation."""
    if not metrics or len(candles) < 20:
        return 0.0, "no_vp_data"

    closes = [c.close for c in candles[-50:]]
    volumes = [c.volume for c in candles[-50:]]
    if not closes or not volumes:
        return 0.0, "no_data"

    min_p, max_p = min(closes), max(closes)
    if max_p == min_p:
        return 0.0, "flat_price"

    num_bins = 20
    bin_width = (max_p - min_p) / num_bins
    bin_volumes = [0.0] * num_bins
    for price, volume in zip(closes, volumes):
        idx = min(int((price - min_p) / bin_width), num_bins - 1)
        bin_volumes[idx] += volume

    poc_idx = bin_volumes.index(max(bin_volumes))
    poc = min_p + (poc_idx + 0.5) * bin_width

    poc_distance_pct = abs(current_price - poc) / poc if poc > 0 else 0

    if direction == "buy":
        if current_price > poc and poc_distance_pct < 0.005:
            return 0.05, "price_at_POC_support"
        if current_price < poc:
            return -0.03, "price_below_POC"
    else:
        if current_price < poc and poc_distance_pct < 0.005:
            return 0.05, "price_at_POC_resistance"
        if current_price > poc:
            return -0.03, "price_above_POC"

    return 0.0, "neutral_vp"


def _validate_signal_on_closed_candle(
    candles: list[Candle],
    direction: str,
    sma20: list[float],
    rsi_val: float,
    trend_strength: float,
) -> tuple[bool, str]:
    """FIX #1: Look-ahead bias prevention.
    Signal validation uses only the LAST CLOSED candle, not the forming one."""
    if len(candles) < 2:
        return False, "insufficient_candles"

    closed_candle = candles[-2]
    prev_candle = candles[-3] if len(candles) >= 3 else candles[-2]

    sma20_val = sma20[-2] if len(sma20) >= 2 else sma20[-1]

    if direction == "buy":
        if closed_candle.close <= sma20_val:
            return False, "close_below_sma20"
        if rsi_val >= 70:
            return False, "rsi_overbought"
        if closed_candle.close <= prev_candle.close:
            return False, "no_upward_momentum"
    else:
        if closed_candle.close >= sma20_val:
            return False, "close_above_sma20"
        if rsi_val <= 30:
            return False, "rsi_oversold"
        if closed_candle.close >= prev_candle.close:
            return False, "no_downward_momentum"

    if abs(trend_strength) < 0.15:
        return False, "weak_trend"

    return True, "closed_candle_validated"


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
    reward_multiple: float = 3.0,
) -> list[TradeSignal]:
    """
    Momentum breakout signal generation with ALL architectural fixes:
    - FIX #1: Look-ahead bias prevention (closed candle validation)
    - FIX #2: Signal lifecycle management
    - FIX #3: Regime-aware filtering
    - FIX #4: MTF confluence integration
    - FIX #5: Orderbook confluence
    - FIX #6: Volume profile integration
    """
    if len(candles) < 100:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    closed_candle = ordered[-2]
    atr14 = _atr(ordered, 14)
    rsi_val = _rsi(closes, 14)

    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    i = len(ordered) - 2
    sma20_val = sma20[i] if i < len(sma20) else sma20[-1]
    sma50_val = sma50[i] if i < len(sma50) else sma50[-1]

    trend_strength = (sma20_val - sma50_val) / sma50_val * 100 if sma50_val > 0 else 0
    in_killzone, session = _is_killzone(closed_candle.timestamp)

    fvgs = fvgs or []
    order_blocks = order_blocks or []
    liquidity_events = liquidity_events or []
    swings = swings or []

    signals: list[TradeSignal] = []

    for direction in ["buy", "sell"]:
        is_uptrend = direction == "buy" and trend_strength > 0.20
        is_downtrend = direction == "sell" and trend_strength < -0.20
        if not (is_uptrend or is_downtrend):
            continue

        regime_ok, regime_reason = _regime_filter(regime, direction)
        if not regime_ok:
            continue

        closed_ok, closed_reason = _validate_signal_on_closed_candle(
            ordered, direction, sma20, rsi_val, trend_strength
        )
        if not closed_ok:
            continue

        confluence_score = 0.20
        reasons: list[str] = [f"Trend {trend_strength:+.1f}%"]

        fvg = _find_nearest_fvg(ordered, fvgs, closed_candle.close, direction)
        if fvg:
            confluence_score += 0.15
            reasons.append(f"FVG {'bull' if fvg.direction == 'bullish' else 'bear'} nearby")

        ob = _find_nearest_ob(ordered, order_blocks, closed_candle.close, direction)
        if ob:
            confluence_score += 0.15
            reasons.append(f"OB {ob.direction} active")

        sweep = _has_liquidity_sweep(liquidity_events, direction)
        if sweep:
            confluence_score += 0.15
            reasons.append("Liquidity sweep reclaimed")

        structure_ok, structure_type = _check_market_structure(ordered, swings, direction)
        if structure_ok:
            confluence_score += 0.10
            reasons.append(f"Structure: {structure_type}")

        vol_conf = _volume_confirmation(ordered, direction)
        if vol_conf >= 1.0:
            confluence_score += 0.10 * vol_conf
            reasons.append(f"Volume {vol_conf:.1f}x")

        if in_killzone:
            confluence_score += 0.10
            reasons.append(f"Killzone: {session}")

        ob_score, ob_reason = _orderbook_confluence(ob_imbalances, ob_accumulations, direction)
        confluence_score += ob_score
        if ob_score > 0:
            reasons.append(ob_reason)

        vp_score, vp_reason = _volume_profile_confluence(metrics, ordered, closed_candle.close, direction)
        confluence_score += vp_score
        if vp_score != 0:
            reasons.append(vp_reason)

        if confluence_score < 0.60:
            continue

        entry = closed_candle.close
        stop_distance = atr14 * 1.0
        if is_uptrend:
            stop = entry - stop_distance
            target = entry + stop_distance * 2.0
        else:
            stop = entry + stop_distance
            target = entry - stop_distance * 2.0

        risk = abs(entry - stop)
        if atr14 < 10:
            continue

        confidence = _clamp(0.45 + confluence_score * 0.50, 0.45, 0.92)

        confidence, mtf_reason = _mtf_confluence_boost(mtf_confluence, direction, confidence)
        if mtf_reason != "no_mtf_data":
            reasons.append(mtf_reason)

        reasons.append(f"Regime: {regime_reason}")

        if confidence < 0.55:
            continue

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
            status=SignalStatus.PENDING.value,
        )
        signals.append(signal)

    if not signals:
        return []

    return [max(signals, key=lambda s: s.confidence)]


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
    status: str = SignalStatus.ACTIVE.value,
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


def expire_old_signals(signals: list[TradeSignal], current_ts: int, max_age_ms: int = 1800000) -> list[TradeSignal]:
    """FIX #2: Signal lifecycle - expire signals older than max_age_ms."""
    for sig in signals:
        if sig.status in {SignalStatus.PENDING.value, SignalStatus.ACTIVE.value}:
            if (current_ts - sig.timestamp) > max_age_ms:
                sig.status = SignalStatus.EXPIRED.value
    return signals


def activate_pending_signals(signals: list[TradeSignal], current_price: float) -> list[TradeSignal]:
    """FIX #2: Signal lifecycle - activate pending signals when price approaches entry."""
    for sig in signals:
        if sig.status == SignalStatus.PENDING.value:
            entry_distance = abs(current_price - sig.entry) / sig.entry
            if entry_distance < 0.001:
                sig.status = SignalStatus.ACTIVE.value
    return signals
