"""
Optimized signal detection using simplified scalping logic.
"""

import math
import time
from typing import Any, Optional

from backend.models.types import (
    Candle, FVG, LiquidityEvent, MarketMetrics, OrderBlock,
    ScalpSignal, Swing,
)


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    r = values[0]
    for v in values[1:]:
        r = (v - r) * k + r
    return r


def _atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    rng: list[float] = []
    for a, b in zip(candles[-(period + 1):], candles[-period:]):
        rng.append(max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)))
    return sum(rng) / len(rng)


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    g: list[float] = []
    l: list[float] = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g.append(max(d, 0.0))
        l.append(max(-d, 0.0))
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(closes) - 1):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    rs = ag / al if al > 0 else 100.0
    return 100.0 - 100.0 / (1.0 + rs)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _adx(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: list[float] = []
    plus_dms: list[float] = []
    minus_dms: list[float] = []
    for i in range(1, len(candles)):
        hi = candles[i].high
        lo = candles[i].low
        pc = candles[i - 1].close
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
        up_move = hi - candles[i - 1].high
        down_move = candles[i - 1].low - lo
        plus_dms.append(max(up_move, 0.0) if up_move > down_move else 0.0)
        minus_dms.append(max(down_move, 0.0) if down_move > up_move else 0.0)
    if len(trs) < period:
        return 0.0
    atr_val = sum(trs[-period:]) / period
    avg_plus = sum(plus_dms[-period:]) / period
    avg_minus = sum(minus_dms[-period:]) / period
    if atr_val == 0:
        return 0.0
    plus_di = (avg_plus / atr_val) * 100
    minus_di = (avg_minus / atr_val) * 100
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return dx


def detect_optimized_signals(
    candles: list[Candle],
    metrics: Optional[MarketMetrics] = None,
    fvgs: list[FVG] = None,
    order_blocks: list[OrderBlock] = None,
    liquidity_events: list[LiquidityEvent] = None,
    swings: list[Swing] = None,
    last_signal_ts: int = 0,
    signal_cooldown_candles: int = 12,
    min_confidence: float = 0.55,
    stop_loss_multiplier: float = 2.0,
    use_adx_filter: bool = True,
    adx_threshold: float = 25.0,
    use_limit_orders: bool = True,
    **kwargs: Any,
) -> list[ScalpSignal]:
    if fvgs is None:
        fvgs = []
    if order_blocks is None:
        order_blocks = []
    if liquidity_events is None:
        liquidity_events = []
    if swings is None:
        swings = []

    if len(candles) < 50:
        return []

    closes = [c.close for c in candles]
    price = closes[-1]
    atr = _atr(candles, 14)

    adx_val = _adx(candles) if use_adx_filter else 100.0

    latest_ts = candles[-1].timestamp
    candles_since_last = sum(1 for c in candles if c.timestamp > last_signal_ts)
    if candles_since_last < signal_cooldown_candles:
        return []

    rsi_14 = _rsi(closes, 14)
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)

    long_score = 0.0
    short_score = 0.0
    long_reasons: list[str] = []
    short_reasons: list[str] = []

    if ema9 > ema21:
        long_score += 0.10
        long_reasons.append("EMA9 > EMA21")
    else:
        short_score += 0.10
        short_reasons.append("EMA9 < EMA21")

    if price > ema9:
        long_score += 0.05
        long_reasons.append("Price above EMA9")
    elif price < ema9:
        short_score += 0.05
        short_reasons.append("Price below EMA9")

    if rsi_14 > 50:
        long_score += 0.05
        long_reasons.append(f"RSI {rsi_14:.0f}")
    elif rsi_14 < 50:
        short_score += 0.05
        short_reasons.append(f"RSI {rsi_14:.0f}")

    if use_adx_filter and adx_val < adx_threshold:
        return []

    active_fvgs = [f for f in fvgs if not f.is_filled]
    for f in active_fvgs:
        if f.direction == "bullish" and abs(price - f.bottom) / price < 0.003:
            long_score += 0.08
            long_reasons.append("Bullish FVG proximity")
        elif f.direction == "bearish" and abs(price - f.top) / price < 0.003:
            short_score += 0.08
            short_reasons.append("Bearish FVG proximity")

    active_obs = [o for o in order_blocks if not o.is_breaker]
    for o in active_obs:
        if o.direction == "bullish" and abs(price - o.top) / price < 0.003:
            long_score += 0.08
            long_reasons.append("Bullish OB proximity")
        elif o.direction == "bearish" and abs(price - o.bottom) / price < 0.003:
            short_score += 0.08
            short_reasons.append("Bearish OB proximity")

    if len(swings) >= 2:
        last_s = swings[-1]
        prev_s = swings[-2]
        if last_s.kind == "high" and last_s.price > prev_s.price:
            long_score += 0.06
            long_reasons.append("HH structure")
        elif last_s.kind == "low" and last_s.price < prev_s.price:
            short_score += 0.06
            short_reasons.append("LL structure")

    if metrics and metrics.vwap:
        if price > metrics.vwap:
            long_score += 0.05
            long_reasons.append("Above VWAP")
        else:
            short_score += 0.05
            short_reasons.append("Below VWAP")

    if long_score < min_confidence and short_score < min_confidence:
        return []

    from backend.analysis.ids import stable_id

    signals: list[ScalpSignal] = []
    now_ms = int(time.time() * 1000)

    if long_score >= short_score and long_score >= min_confidence:
        sl = price - atr * stop_loss_multiplier
        t1 = price + atr * stop_loss_multiplier * 1.0
        t2 = price + atr * stop_loss_multiplier * 2.0
        rr = round(abs(t2 - price) / abs(price - sl), 2) if abs(price - sl) > 0 else 0.0
        sig = ScalpSignal(
            id=stable_id("opt", "buy", now_ms, int(price), int(sl)),
            timestamp=latest_ts,
            signal_type="LONG BTCUSD",
            entry_zone_low=round(price * 0.999, 2),
            entry_zone_high=round(price * 1.001, 2),
            sl_level=round(sl, 2),
            target_1=round(t1, 2),
            target_2=round(t2, 2),
            leverage=5,
            reason=" | ".join(long_reasons),
            risk_reward=rr,
            confidence="HIGH" if long_score >= 0.65 else "MEDIUM",
            score=round(long_score, 4),
            entry=round(price, 2),
            stop_loss=round(sl, 2),
            exit_price=round(t2, 2),
            side="buy",
            model="optimized",
        )
        signals.append(sig)
    elif short_score > long_score and short_score >= min_confidence:
        sl = price + atr * stop_loss_multiplier
        t1 = price - atr * stop_loss_multiplier * 1.0
        t2 = price - atr * stop_loss_multiplier * 2.0
        rr = round(abs(price - t2) / abs(price - sl), 2) if abs(price - sl) > 0 else 0.0
        sig = ScalpSignal(
            id=stable_id("opt", "sell", now_ms, int(price), int(sl)),
            timestamp=latest_ts,
            signal_type="SHORT BTCUSD",
            entry_zone_low=round(price * 0.999, 2),
            entry_zone_high=round(price * 1.001, 2),
            sl_level=round(sl, 2),
            target_1=round(t1, 2),
            target_2=round(t2, 2),
            leverage=5,
            reason=" | ".join(short_reasons),
            risk_reward=rr,
            confidence="HIGH" if short_score >= 0.65 else "MEDIUM",
            score=round(short_score, 4),
            entry=round(price, 2),
            stop_loss=round(sl, 2),
            exit_price=round(t2, 2),
            side="sell",
            model="optimized",
        )
        signals.append(sig)

    return signals
