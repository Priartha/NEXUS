"""
Adaptive Stop-Loss / Take-Profit using Volatility Quantile Regression.

Instead of fixed ATR multipliers, SL and TP levels are set dynamically
based on recent volatility distribution, market regime, and signal confidence.

Key insight: the optimal SL/TP for BTCUSD futures depends on:
  - Current volatility regime (wide stops in high vol, tight in low vol)
  - Market regime phase (trending vs range-bound)
  - Signal confidence (higher confidence = wider TP, tighter SL)
  - Recent liquidity levels (known support/resistance)
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.config import settings
from backend.models.types import Candle, MarketRegime

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveSLTP:
    timestamp: int
    side: str  # "long" or "short"
    sl_price: float
    tp1_price: float
    tp2_price: float
    sl_atr_multiple: float
    tp_atr_multiple: float
    sl_quantile: float
    tp_quantile: float
    confidence_adjustment: float
    liquidity_adjustment: float
    regime_sl_mult: float
    regime_tp_mult: float
    description: str


class AdaptiveSLTPEngine:
    """
    Sets SL/TP levels using volatility quantiles + regime + confidence.

    Algorithm:
      1. Compute rolling volatility distribution (ATR over N periods)
      2. Pick SL at volatility quantile q_sl (default 1.5× median ATR)
      3. Pick TP at volatility quantile q_tp (default 3.0× median ATR)
      4. Adjust for regime: trending → wider SL, range → tighter SL
      5. Adjust for confidence: high conf → wider TP
      6. Snap to nearest liquidity levels if within tolerance
    """

    def __init__(
        self,
        volatility_lookback: int = 100,
        sl_quantile_default: float = 1.5,
        tp_quantile_default: float = 3.0,
        min_sl_atr: float = 0.8,
        max_sl_atr: float = 5.0,
        min_tp_atr: float = 1.5,
        max_tp_atr: float = 10.0,
        conf_adjustment_strength: float = 0.3,
        liquidity_snap_tolerance_pct: float = 0.1,
    ) -> None:
        self.volatility_lookback = volatility_lookback
        self.sl_quantile_default = sl_quantile_default
        self.tp_quantile_default = tp_quantile_default
        self.min_sl_atr = min_sl_atr
        self.max_sl_atr = max_sl_atr
        self.min_tp_atr = min_tp_atr
        self.max_tp_atr = max_tp_atr
        self.conf_adjustment_strength = conf_adjustment_strength
        self.liquidity_snap_tolerance_pct = liquidity_snap_tolerance_pct

        # Regime-specific multipliers
        self._regime_sl_mult = {
            "trending": 1.3,
            "trending_volatile": 1.5,
            "range_bound": 0.8,
            "consolidation": 0.7,
            "accumulation": 1.1,
            "distribution": 1.1,
        }
        self._regime_tp_mult = {
            "trending": 1.2,
            "trending_volatile": 1.0,
            "range_bound": 0.9,
            "consolidation": 0.8,
            "accumulation": 1.1,
            "distribution": 1.1,
        }

    def compute(
        self,
        candles: list[Candle],
        side: str,
        entry_price: float,
        confidence: float = 0.5,
        regime: MarketRegime | None = None,
        liquidity_levels: list[float] | None = None,
    ) -> AdaptiveSLTP:
        now_ms = candles[-1].timestamp if candles else int(__import__("time").time() * 1000)

        # 1. Compute ATR distribution
        atr_values = self._compute_atr_series(candles)
        if len(atr_values) < 10:
            atr_val = candles[-1].close * 0.005  # fallback 0.5%
        else:
            atr_val = float(np.median(atr_values[-self.volatility_lookback:]))

        # 2. Base multiples from quantiles
        sl_base = self.sl_quantile_default
        tp_base = self.tp_quantile_default

        # 3. Regime adjustment
        regime_sl_mult = 1.0
        regime_tp_mult = 1.0
        regime_phase = "unknown"
        if regime:
            regime_phase = regime.phase
            regime_sl_mult = self._regime_sl_mult.get(regime_phase, 1.0)
            regime_tp_mult = self._regime_tp_mult.get(regime_phase, 1.0)

        sl_atr = sl_base * regime_sl_mult
        tp_atr = tp_base * regime_tp_mult

        # 4. Confidence adjustment
        conf_adj = 1.0 + (confidence - 0.5) * self.conf_adjustment_strength
        tp_atr *= conf_adj

        # Clamp
        sl_atr = max(self.min_sl_atr, min(self.max_sl_atr, sl_atr))
        tp_atr = max(self.min_tp_atr, min(self.max_tp_atr, tp_atr))

        # 5. Compute absolute levels
        if side == "long":
            sl_price = entry_price - sl_atr * atr_val
            tp1_price = entry_price + tp_atr * atr_val
            tp2_price = entry_price + tp_atr * 1.5 * atr_val
        else:
            sl_price = entry_price + sl_atr * atr_val
            tp1_price = entry_price - tp_atr * atr_val
            tp2_price = entry_price - tp_atr * 1.5 * atr_val

        # 6. Snap to nearest liquidity level if within tolerance
        liquidity_adjustment = 0.0
        if liquidity_levels:
            tolerance = entry_price * self.liquidity_snap_tolerance_pct / 100
            for liq_level in liquidity_levels:
                if side == "long":
                    dist = abs(liq_level - sl_price)
                    if dist < tolerance:
                        liq_below = liq_level < entry_price
                        if liq_below:
                            sl_price = liq_level
                            liquidity_adjustment = dist / atr_val
                            break
                else:
                    dist = abs(liq_level - tp1_price)
                    if dist < tolerance:
                        liq_above = liq_level > entry_price
                        if liq_above:
                            tp1_price = liq_level
                            liquidity_adjustment = dist / atr_val
                            break

        desc = f"Adaptive SL/TP: sl={sl_atr:.1f}xATR, tp={tp_atr:.1f}xATR, regime={regime_phase}, conf_adj={conf_adj:.2f}"

        return AdaptiveSLTP(
            timestamp=now_ms,
            side=side,
            sl_price=round(sl_price, 2),
            tp1_price=round(tp1_price, 2),
            tp2_price=round(tp2_price, 2),
            sl_atr_multiple=round(sl_atr, 2),
            tp_atr_multiple=round(tp_atr, 2),
            sl_quantile=round(self.sl_quantile_default, 2),
            tp_quantile=round(self.tp_quantile_default, 2),
            confidence_adjustment=round(conf_adj, 3),
            liquidity_adjustment=round(liquidity_adjustment, 3),
            regime_sl_mult=round(regime_sl_mult, 2),
            regime_tp_mult=round(regime_tp_mult, 2),
            description=desc,
        )

    def _compute_atr_series(self, candles: list[Candle]) -> np.ndarray:
        if len(candles) < 2:
            return np.array([0.0])
        tr = np.array([
            max(c.high - c.low, abs(c.high - candles[i - 1].close), abs(c.low - candles[i - 1].close))
            for i, c in enumerate(candles[1:], start=1)
        ])
        atr = np.zeros(len(candles))
        atr[0] = tr[0] if len(tr) > 0 else 0.0
        for i in range(1, len(candles)):
            if i < 14:
                atr[i] = np.mean(tr[:i])
            else:
                atr[i] = (atr[i - 1] * 13 + tr[i - 1]) / 14
        return atr

    def get_state(self) -> dict:
        return {
            "sl_quantile_default": self.sl_quantile_default,
            "tp_quantile_default": self.tp_quantile_default,
            "regime_sl_mult": self._regime_sl_mult,
            "regime_tp_mult": self._regime_tp_mult,
        }


# Singleton
adaptive_sltp = AdaptiveSLTPEngine()
