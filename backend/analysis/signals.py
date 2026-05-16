from __future__ import annotations

import math
from datetime import datetime, timezone

from backend.analysis.ids import stable_id
from backend.models.types import (
    Candle,
    FVG,
    LiquidityEvent,
    LiquidityLevel,
    MarketMetrics,
    OrderBlock,
    Swing,
    TradeSignal,
)


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
    """Check if current time is within ICT killzones (UTC).
    London: 02:00-05:00 UTC, NY AM: 08:30-11:00 UTC, NY PM: 13:30-16:00 UTC"""
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
    """Find the nearest unfilled FVG in the direction of trade."""
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
    """Find the nearest valid order block in the direction of trade."""
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
    """Check if there's been a recent liquidity sweep in our favor."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    recent = [e for e in liquidity_events if (now_ms - e.timestamp) < lookback_ms]

    if direction == "buy":
        return any(e.side == "sell_side" and e.reclaimed for e in recent)
    else:
        return any(e.side == "buy_side" and e.reclaimed for e in recent)


def _check_market_structure(candles: list[Candle], swings: list[Swing], direction: str) -> tuple[bool, str]:
    """Check for BOS (Break of Structure) or CHoCH (Change of Character)."""
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
    """Check if volume confirms the move direction."""
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


def detect_trade_signals(
    candles: list[Candle],
    metrics: MarketMetrics | None = None,
    fvgs: list[FVG] | None = None,
    order_blocks: list[OrderBlock] | None = None,
    liquidity_events: list[LiquidityEvent] | None = None,
    swings: list[Swing] | None = None,
    reward_multiple: float = 3.0,
    regime: Any = None,
) -> list[TradeSignal]:
    """Momentum breakout signal generation with ATR-based risk management.
    Enters on pullbacks in established trends with tight ATR stops."""
    if len(candles) < 100:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    latest = ordered[-1]
    atr14 = _atr(ordered, 14)
    rsi_i = _rsi(closes, 14)

    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    i = len(ordered) - 1
    sma20_i = sma20[i]
    sma50_i = sma50[i]

    trend_strength = (sma20_i - sma50_i) / sma50_i * 100 if sma50_i > 0 else 0

    in_killzone, session = _is_killzone(latest.timestamp)

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

        confluence_score = 0.0
        reasons: list[str] = []

        if is_uptrend:
            pullback_pct = (latest.close - sma20_i) / sma20_i * 100
            if not (-3.0 < pullback_pct < 0.5):
                continue
            if not (25 < rsi_i < 60):
                continue
        else:
            pullback_pct = (latest.close - sma20_i) / sma20_i * 100
            if not (-0.5 < pullback_pct < 3.0):
                continue
            if not (40 < rsi_i < 75):
                continue

        confluence_score += 0.20
        reasons.append(f"Trend {trend_strength:+.1f}%")

        fvg = _find_nearest_fvg(ordered, fvgs, latest.close, direction)
        if fvg:
            confluence_score += 0.15
            reasons.append(f"FVG {'bull' if fvg.direction == 'bullish' else 'bear'} nearby")

        ob = _find_nearest_ob(ordered, order_blocks, latest.close, direction)
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

        if confluence_score < 0.60:
            continue

        if not in_killzone:
            continue

        entry = latest.close
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

        signal = _make_signal(
            side=direction,
            timestamp=latest.timestamp,
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
) -> TradeSignal:
    risk = abs(entry - stop)
    rr = abs(target - entry) / risk if risk > 0 else 0

    return TradeSignal(
        id=stable_id("sel", side, timestamp, int(entry * 10), int(stop * 10)),
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
        status="open",
    )


def _estimate_win_prob(confidence: float, rr: float) -> float:
    """Estimate win probability from confidence and RR ratio."""
    base = confidence * 0.6
    rr_adj = min(rr / 4.0, 0.3)
    return _clamp(base + rr_adj + 0.15, 0.30, 0.85)
