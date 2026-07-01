"""
NEXUS Momentum Engine v2.0 — Genuine Momentum Detection for HFT-Style Scalping

Detects real price momentum using:
1. Price Velocity: Rate of change acceleration across 1-3-5 bar windows
2. Volume Momentum: Volume-weighted price validation 
3. Order Flow Momentum: Delta acceleration, CVD inflection
4. Breakout Momentum: Volatility compression + expansion cycles
5. Trend Alignment: Price relative to SMA50 (filters counter-trend noise)

Scoring is multiplicative (not additive) — velocity is the dominant factor.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from backend.models.types import Candle, ScalpOrderFlow

logger = logging.getLogger(__name__)


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    r = values[0]
    for v in values[1:]:
        r = (v - r) * k + r
    return r


def _sma(values: list[float], period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    return sum(values[-period:]) / period


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class MomentumResult:
    """Result of momentum detection."""
    def __init__(self):
        self.direction: str = "neutral"
        self.strength: float = 0.0
        self.velocity: float = 0.0
        self.acceleration: float = 0.0
        self.volume_confirmation: bool = False
        self.orderflow_confirmation: bool = False
        self.breakout_confirmation: bool = False
        self.trend_aligned: bool = False
        self.reasons: list[str] = []
        self.entry_urgency: float = 0.0

    def is_valid(self, min_strength: float = 0.50) -> bool:
        return self.direction != "neutral" and self.strength >= min_strength

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "strength": round(self.strength, 4),
            "velocity": round(self.velocity, 2),
            "acceleration": round(self.acceleration, 4),
            "volume_confirmation": self.volume_confirmation,
            "orderflow_confirmation": self.orderflow_confirmation,
            "breakout_confirmation": self.breakout_confirmation,
            "trend_aligned": self.trend_aligned,
            "reasons": self.reasons,
            "entry_urgency": round(self.entry_urgency, 3),
        }


class MomentumEngine:
    """
    Pure momentum detection engine v2.

    Uses ONLY:
    - Price velocity and acceleration (dominant factor)
    - Volume confirmation (multiplier)
    - Order flow momentum (multiplier)
    - Volatility breakouts
    - Trend alignment (SMA50 filter)

    Scoring is MULTIPLICATIVE to prevent weak velocity + strong noise = strong signal.
    """
    
    def __init__(self):
        self._velocity_window: deque = deque(maxlen=10)
        self._volume_window: deque = deque(maxlen=50)
        self._atr_cache: float = 0.0
        self._last_candle_close: float | None = None
        self._compression_count: int = 0

    def detect(self, candles: list[Candle], order_flow: ScalpOrderFlow | None = None) -> MomentumResult:
        """Detect genuine momentum from price and order flow data."""
        result = MomentumResult()
        
        if len(candles) < 20:
            return result
        
        ordered = sorted(candles, key=lambda c: c.timestamp)
        closes = [c.close for c in ordered]
        highs = [c.high for c in ordered]
        lows = [c.low for c in ordered]
        volumes = [c.volume for c in ordered]
        price = closes[-1]
        
        # ── 0. TREND FILTER (SMA50) ──
        sma50 = _sma(closes, 50)
        above_sma = price > sma50
        below_sma = price < sma50
        
        # ── 1. PRICE VELOCITY ──
        roc_1 = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] > 0 else 0
        roc_3 = (closes[-1] - closes[-4]) / closes[-4] * 100 if len(closes) >= 5 and closes[-4] > 0 else roc_1
        roc_5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 7 and closes[-6] > 0 else roc_3
        velocity = roc_1 * 0.5 + roc_3 * 0.3 + roc_5 * 0.2
        result.velocity = velocity
        
        # ── 2. ACCELERATION ──
        if len(closes) >= 6:
            prev_roc_1 = (closes[-2] - closes[-3]) / closes[-3] * 100 if closes[-3] > 0 else 0
            prev_roc_3 = (closes[-2] - closes[-5]) / closes[-5] * 100 if len(closes) >= 6 and closes[-5] > 0 else prev_roc_1
            prev_vel = prev_roc_1 * 0.5 + prev_roc_3 * 0.3 + (closes[-2] - closes[-6]) / closes[-6] * 100 * 0.2 if len(closes) >= 7 else prev_roc_1
            acceleration = velocity - prev_vel
        else:
            acceleration = 0
        result.acceleration = acceleration
        
        # ── 3. ATR FOR CONTEXT ──
        atr = self._compute_atr(ordered)
        self._atr_cache = atr
        atr_pct = atr / price * 100 if price > 0 else 0
        
        # ── 4. DIRECTION & MINIMUM VELOCITY CHECK ──
        # Require meaningful velocity relative to ATR
        min_vel = 0.03 * max(atr_pct, 0.01)
        is_bullish_vel = velocity > min_vel
        is_bearish_vel = velocity < -min_vel
        
        # ── 5. VOLUME CONFIRMATION ──
        recent_vol = sum(volumes[-3:]) / 3
        base_vol = sum(volumes[-20:-3]) / 17 if len(volumes) >= 20 else recent_vol
        vol_ratio = recent_vol / base_vol if base_vol > 0 else 1.0
        result.volume_confirmation = vol_ratio > 1.5
        
        # Volume-weighted direction
        bull_vol = sum(v for i, v in enumerate(volumes[-5:]) if i > 0 and closes[-5+i] > closes[-6+i])
        bear_vol = sum(v for i, v in enumerate(volumes[-5:]) if i > 0 and closes[-5+i] < closes[-6+i])
        total_vol_5 = sum(volumes[-5:])
        vol_bull_ratio = bull_vol / total_vol_5 if total_vol_5 > 0 else 0.5
        
        # ── 6. ORDER FLOW MOMENTUM ──
        of_bullish = False
        of_bearish = False
        if order_flow:
            of_bullish = order_flow.delta > 0 and order_flow.cvd_slope > 0
            of_bearish = order_flow.delta < 0 and order_flow.cvd_slope < 0
            result.orderflow_confirmation = of_bullish or of_bearish
        
        # ── 7. BREAKOUT DETECTION ──
        if len(candles) >= 20:
            ranges = [ordered[i].high - ordered[i].low for i in range(-14, 0)]
            avg_range = sum(ranges) / len(ranges) if ranges else 0
            current_range = ordered[-1].high - ordered[-1].low
            compressed = current_range < avg_range * 0.6 if avg_range > 0 else False
            expanding = current_range > avg_range * 1.4 if avg_range > 0 else False
            
            if compressed:
                self._compression_count += 1
            else:
                if self._compression_count >= 3 and expanding:
                    bd = "bullish" if closes[-1] > closes[-2] and vol_ratio > 1.3 else ("bearish" if closes[-1] < closes[-2] and vol_ratio > 1.3 else None)
                    if bd:
                        result.breakout_confirmation = True
                        result.reasons.append(f"Volatility breakout ({bd})")
                self._compression_count = 0
        
        # ── 8. COMPUTE MOMENTUM STRENGTH (Multiplicative) ──
        # Velocity magnitude is the BASE — everything else is a multiplier
        # Scale: at ATR × 5, velocity_magnitude = 1.0
        velocity_magnitude = _clamp(abs(velocity) / max(atr_pct * 5, 0.01), 0.0, 1.0)
        
        # Direction-specific signal
        if is_bullish_vel:
            result.direction = "bullish"
            result.trend_aligned = above_sma
            base = velocity_magnitude
            
            mult_vol = 1.3 if result.volume_confirmation else 1.0
            mult_of = 1.2 if (of_bullish and order_flow and order_flow.delta > 0) else 1.0
            mult_accel = 1.2 if acceleration > 0 else 1.0
            mult_trend = 1.2 if above_sma else 0.6
            mult_breakout = 1.2 if result.breakout_confirmation else 1.0
            
            result.strength = base * mult_vol * mult_of * mult_accel * mult_trend * mult_breakout
            
            if result.volume_confirmation:
                result.reasons.append(f"Volume confirmation ({vol_ratio:.1f}x)")
            if above_sma:
                result.reasons.append("Price above SMA50 (bullish)")
            else:
                result.reasons.append("Price below SMA50 — counter-trend")
            if of_bullish:
                result.reasons.append("Delta+ / CVD rising")
            if acceleration > 0:
                result.reasons.append(f"Accelerating ({acceleration:.3f}%)")
            result.reasons.append(f"Velocity={velocity:.3f}%, ROC1={roc_1:.3f}%")
            
        elif is_bearish_vel:
            result.direction = "bearish"
            result.trend_aligned = below_sma
            base = velocity_magnitude
            
            mult_vol = 1.3 if result.volume_confirmation else 1.0
            mult_of = 1.2 if (of_bearish and order_flow and order_flow.delta < 0) else 1.0
            mult_accel = 1.2 if acceleration < 0 else 1.0
            mult_trend = 1.2 if below_sma else 0.6
            mult_breakout = 1.2 if result.breakout_confirmation else 1.0
            
            result.strength = base * mult_vol * mult_of * mult_accel * mult_trend * mult_breakout
            
            if result.volume_confirmation:
                result.reasons.append(f"Volume confirmation ({vol_ratio:.1f}x)")
            if below_sma:
                result.reasons.append("Price below SMA50 (bearish)")
            else:
                result.reasons.append("Price above SMA50 — counter-trend")
            if of_bearish:
                result.reasons.append("Delta- / CVD falling")
            if acceleration < 0:
                result.reasons.append(f"Accelerating ({acceleration:.3f}%)")
            result.reasons.append(f"Velocity={velocity:.3f}%, ROC1={roc_1:.3f}%")
        
        result.strength = _clamp(result.strength, 0.0, 1.0)
        
        # Entry urgency
        urgency = 0.0
        if abs(velocity) > 0.05 * max(atr_pct, 0.01):
            urgency += 0.3
        if vol_ratio > 1.5:
            urgency += 0.3
        if result.breakout_confirmation:
            urgency += 0.4
        if result.orderflow_confirmation:
            urgency += 0.2
        if result.trend_aligned:
            urgency += 0.2
        result.entry_urgency = _clamp(urgency, 0, 1)
        
        return result

    def _compute_atr(self, candles: list[Candle], period: int = 14) -> float:
        if len(candles) < 2:
            return 0.0
        rng: list[float] = []
        for a, b in zip(candles[-(period + 1):], candles[-period:]):
            rng.append(max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)))
        return sum(rng) / len(rng)


# Singleton
momentum_engine = MomentumEngine()
