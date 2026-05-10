from __future__ import annotations

import math
import numpy as np
import pandas as pd
import ta

from backend.models.types import Candle, LiquidityEvent, MarketMetrics, PriceProjection, Swing


def compute_market_metrics(candles: list[Candle], swings: list[Swing], lookback: int = 80) -> MarketMetrics | None:
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    if not ordered:
        return None

    window = ordered[-lookback:]
    latest = ordered[-1]
    closes = [candle.close for candle in ordered]
    df = _to_df(ordered)

    atr14 = _atr(df, 14)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    rsi14 = _rsi(closes, 14)
    vwap = _vwap(df)
    vwap_distance_pct = _safe_div(latest.close - vwap, latest.close)
    volume_zscore = _volume_zscore(window)
    realized_volatility = _realized_volatility(window)
    parkinson_volatility = _parkinson_volatility(window)
    garman_klass_volatility = _garman_klass_volatility(window)
    displacement_ratio = _safe_div(abs(latest.close - latest.open), atr14)
    range_high, range_low = _dealing_range(window, swings)
    range_size = max(range_high - range_low, 0.0)
    equilibrium = (range_high + range_low) / 2 if range_size else latest.close
    premium_discount = _safe_div((latest.close - equilibrium) * 2, range_size)
    trend_score = _trend_score(
        close=latest.close,
        atr=atr14,
        ema20=ema20,
        ema50=ema50,
        rsi14=rsi14,
        vwap_distance_pct=vwap_distance_pct,
        premium_discount=premium_discount,
    )
    volatility_score = _clamp(_safe_div(atr14, latest.close * 0.012), 0.0, 1.0)
    expected_move = max(atr14, realized_volatility, parkinson_volatility, garman_klass_volatility)

    if trend_score > 0.18:
        institutional_bias = "bullish"
    elif trend_score < -0.18:
        institutional_bias = "bearish"
    else:
        institutional_bias = "neutral"

    return MarketMetrics(
        timestamp=latest.timestamp,
        atr14=_round(atr14),
        ema20=_round(ema20),
        ema50=_round(ema50),
        rsi14=_round(rsi14, 2),
        vwap=_round(vwap),
        vwap_distance_pct=_round(vwap_distance_pct * 100, 4),
        volume_zscore=_round(volume_zscore, 2),
        realized_volatility=_round(realized_volatility),
        parkinson_volatility=_round(parkinson_volatility),
        garman_klass_volatility=_round(garman_klass_volatility),
        displacement_ratio=_round(displacement_ratio, 2),
        premium_discount=_round(_clamp(premium_discount, -1.0, 1.0), 3),
        equilibrium=_round(equilibrium),
        range_high=_round(range_high),
        range_low=_round(range_low),
        trend_score=_round(trend_score, 3),
        volatility_score=_round(volatility_score, 3),
        institutional_bias=institutional_bias,
        bias_score=_round(trend_score, 3),
        expected_move=_round(expected_move),
        expected_move_pct=_round(_safe_div(expected_move, latest.close) * 100, 3),
    )


def build_price_projection(
    candles: list[Candle],
    metrics: MarketMetrics | None,
    liquidity_events: list[LiquidityEvent],
) -> PriceProjection | None:
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    if not ordered or metrics is None:
        return None

    latest = ordered[-1]
    score = metrics.bias_score
    reasons = [
        f"{metrics.institutional_bias} bias {metrics.bias_score:.2f}",
        f"expected move {metrics.expected_move:.1f}",
    ]

    recent_cutoff = latest.timestamp - _median_period_ms(ordered) * 8
    recent_events = [event for event in liquidity_events if event.timestamp >= recent_cutoff]
    if recent_events:
        event = max(recent_events, key=lambda item: item.engineered_score)
        event_weight = event.engineered_score * 0.35
        if event.side == "sell_side":
            score += event_weight
            reasons.append("sell-side liquidity engineered below market")
        elif event.side == "buy_side":
            score -= event_weight
            reasons.append("buy-side liquidity engineered above market")

    body_direction = 1.0 if latest.close >= latest.open else -1.0
    if metrics.displacement_ratio >= 1.15:
        score += body_direction * min(0.16, metrics.displacement_ratio * 0.05)
        reasons.append("displacement candle")

    score = _clamp(score, -1.0, 1.0)
    if score > 0.16:
        direction = "bullish"
    elif score < -0.16:
        direction = "bearish"
    else:
        direction = "neutral"

    probability = 0.5 if direction == "neutral" else 0.5 + min(abs(score) * 0.38, 0.38)
    expected_move = max(metrics.expected_move, metrics.atr14) * (1 + abs(score) * 0.35)
    neutral_span = expected_move * 0.62

    if direction == "bullish":
        expected_high = latest.close + expected_move
        expected_low = latest.close - expected_move * 0.45
        invalidation = latest.close - max(metrics.atr14, expected_move * 0.75)
    elif direction == "bearish":
        expected_high = latest.close + expected_move * 0.45
        expected_low = latest.close - expected_move
        invalidation = latest.close + max(metrics.atr14, expected_move * 0.75)
    else:
        expected_high = latest.close + neutral_span
        expected_low = latest.close - neutral_span
        invalidation = metrics.equilibrium

    return PriceProjection(
        timestamp=latest.timestamp,
        direction=direction,
        probability=_round(probability, 3),
        expected_move=_round(expected_move),
        expected_high=_round(expected_high),
        expected_low=_round(expected_low),
        invalidation=_round(invalidation),
        score=_round(score, 3),
        reason=", ".join(reasons),
    )


def _to_df(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame([
        {"high": c.high, "low": c.low, "close": c.close, "open": c.open, "volume": c.volume}
        for c in candles
    ])


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return float(tr.iloc[-period:].mean())


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    s = pd.Series(values)
    ema = ta.trend.ema_indicator(s, window=period)
    return float(ema.iloc[-1]) if not pd.isna(ema.iloc[-1]) else float(s.iloc[-1])


def _rsi(values: list[float], period: int) -> float:
    if len(values) <= period:
        return 50.0
    s = pd.Series(values)
    rsi = ta.momentum.rsi(s, window=period)
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0


def _vwap(df: pd.DataFrame) -> float:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].clip(lower=1.0)
    numerator = (typical * vol).sum()
    denominator = vol.sum()
    return float(numerator / denominator) if denominator > 0 else float(df["close"].iloc[-1])


def _volume_zscore(candles: list[Candle], period: int = 30) -> float:
    recent = np.array([c.volume for c in candles[-period:] if c.volume > 0])
    if len(recent) < 5:
        return 0.0
    mean = np.mean(recent[:-1])
    std = np.std(recent[:-1], ddof=1)
    if std == 0:
        return 0.0
    return float((recent[-1] - mean) / std)


def _realized_volatility(candles: list[Candle]) -> float:
    closes = np.array([c.close for c in candles])
    log_returns = np.diff(np.log(closes[closes > 0]))
    if len(log_returns) < 2:
        return 0.0
    return float(np.std(log_returns, ddof=1) * candles[-1].close)


def _parkinson_volatility(candles: list[Candle]) -> float:
    highs = np.array([c.high for c in candles])
    lows = np.array([c.low for c in candles])
    mask = (highs > 0) & (lows > 0) & (highs >= lows)
    if not mask.any():
        return 0.0
    samples = np.log(highs[mask] / lows[mask]) ** 2
    variance = np.sum(samples) / (4 * len(samples) * math.log(2))
    return float(np.sqrt(max(variance, 0.0)) * candles[-1].close)


def _garman_klass_volatility(candles: list[Candle]) -> float:
    arr = np.array([(c.open, c.high, c.low, c.close) for c in candles])
    mask = (arr.min(axis=1) > 0)
    if not mask.any():
        return 0.0
    o, h, l, c = arr[mask].T
    log_hl = np.log(h / l)
    log_co = np.log(c / o)
    samples = 0.5 * log_hl**2 - ((2 * math.log(2) - 1) * log_co**2)
    variance = np.mean(samples)
    return float(np.sqrt(max(variance, 0.0)) * candles[-1].close)


def _dealing_range(candles: list[Candle], swings: list[Swing]) -> tuple[float, float]:
    recent_swings = [swing for swing in swings[-40:] if swing.kind in {"high", "low"}]
    highs = [swing.price for swing in recent_swings if swing.kind == "high"]
    lows = [swing.price for swing in recent_swings if swing.kind == "low"]
    if highs and lows:
        return max(highs), min(lows)
    return max(candle.high for candle in candles), min(candle.low for candle in candles)


def _trend_score(
    close: float,
    atr: float,
    ema20: float,
    ema50: float,
    rsi14: float,
    vwap_distance_pct: float,
    premium_discount: float,
) -> float:
    atr = max(atr, close * 0.001)
    ema_spread = _clamp((ema20 - ema50) / (atr * 3), -1.0, 1.0)
    price_ema = 0.18 if close >= ema20 else -0.18
    vwap_score = _clamp(vwap_distance_pct / 0.02, -1.0, 1.0)
    rsi_score = _clamp((rsi14 - 50) / 28, -1.0, 1.0)
    range_score = _clamp(premium_discount, -1.0, 1.0)
    score = (ema_spread * 0.32) + (price_ema * 0.14) + (vwap_score * 0.2) + (rsi_score * 0.2) + (range_score * 0.14)
    return _clamp(score, -1.0, 1.0)


def _median_period_ms(candles: list[Candle]) -> int:
    if len(candles) < 2:
        return 60_000
    timestamps = np.array([c.timestamp for c in candles[-20:]])
    deltas = np.diff(timestamps)
    deltas = deltas[deltas > 0]
    if len(deltas) == 0:
        return 60_000
    return int(np.median(deltas))


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round(value: float, places: int = 2) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(value, places)
