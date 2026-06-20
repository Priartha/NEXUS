"""
Triple-Barrier Label Generator (de Prado method).

Generates supervised learning labels from price action:
  1 = bullish (upper barrier touched first)
  0 = neutral (time barrier expired / both touched)
 -1 = bearish (lower barrier touched first)

Used to train XGBoost classifier on forward returns.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.models.types import Candle

logger = logging.getLogger(__name__)


@dataclass
class LabeledBar:
    timestamp: int
    label: int  # 1=bullish, 0=neutral, -1=bearish
    forward_return: float
    volatility_at_entry: float
    touched_upper_first: bool
    touched_lower_first: bool
    time_expired: bool
    upper_barrier: float
    lower_barrier: float
    max_barriers: int


class TripleBarrierLabeler:
    """
    Generates triple-barrier labels for supervised learning.

    For each point in time, looks ahead up to `max_bars` and checks
    whether price touches the upper barrier (volatility-adjusted) first,
    the lower barrier first, or neither (neutral).
    """

    def __init__(
        self,
        atr_period: int = 14,
        upper_multiplier: float = 2.0,
        lower_multiplier: float = 2.0,
        max_bars: int = 24,
        volatility_lookback: int = 48,
        min_labeled_samples: int = 200,
    ) -> None:
        self.atr_period = atr_period
        self.upper_multiplier = upper_multiplier
        self.lower_multiplier = lower_multiplier
        self.max_bars = max_bars
        self.volatility_lookback = volatility_lookback
        self.min_labeled_samples = min_labeled_samples

        # Feature store: labels indexed by timestamp
        self._labels: dict[int, LabeledBar] = {}
        self._labels_deque: deque[LabeledBar] = deque(maxlen=5000)

        # Regime-adaptive multipliers
        self.regime_multipliers: dict[str, dict[str, float]] = {
            "trending": {"upper": 2.5, "lower": 1.5},
            "trending_volatile": {"upper": 3.0, "lower": 1.5},
            "range_bound": {"upper": 1.5, "lower": 1.5},
            "consolidation": {"upper": 1.5, "lower": 1.5},
            "accumulation": {"upper": 2.0, "lower": 1.8},
            "distribution": {"upper": 1.8, "lower": 2.0},
        }

    def compute_labels(
        self,
        candles: list[Candle],
        regime: str | None = None,
    ) -> list[LabeledBar]:
        """Generate triple-barrier labels for all candles that have enough lookahead."""
        if len(candles) < self.max_bars + self.atr_period + 5:
            return []

        # Get multipliers for current regime
        upper_mult = self.upper_multiplier
        lower_mult = self.lower_multiplier
        if regime and regime in self.regime_multipliers:
            rm = self.regime_multipliers[regime]
            upper_mult = rm["upper"]
            lower_mult = rm["lower"]

        closes = np.array([c.close for c in candles])
        highs = np.array([c.high for c in candles])
        lows = np.array([c.low for c in candles])

        # Volatility series (ATR)
        atr_series = self._compute_atr(candles)
        atr_median = float(np.median(atr_series[-self.volatility_lookback:])) if len(atr_series) >= self.volatility_lookback else float(np.mean(atr_series))

        labels: list[LabeledBar] = []
        n = len(candles) - self.max_bars

        for i in range(n):
            ts = candles[i].timestamp
            entry_price = closes[i]
            atr_val = atr_series[i] if i < len(atr_series) else atr_median

            if atr_val <= 0:
                continue

            upper_barrier = entry_price + upper_mult * atr_val
            lower_barrier = entry_price - lower_mult * atr_val

            lookahead_highs = highs[i + 1 : i + self.max_bars + 1]
            lookahead_lows = lows[i + 1 : i + self.max_bars + 1]

            upper_touch_idx = self._first_touch(lookahead_highs, upper_barrier, "upper")
            lower_touch_idx = self._first_touch(lookahead_lows, lower_barrier, "lower")

            touched_upper_first = False
            touched_lower_first = False
            time_expired = False
            label = 0

            if upper_touch_idx is not None and lower_touch_idx is not None:
                if upper_touch_idx <= lower_touch_idx:
                    label = 1
                    touched_upper_first = True
                else:
                    label = -1
                    touched_lower_first = True
            elif upper_touch_idx is not None:
                label = 1
                touched_upper_first = True
            elif lower_touch_idx is not None:
                label = -1
                touched_lower_first = True
            else:
                time_expired = True
                # For neutral: check if price ended up or down
                final_price = closes[min(i + self.max_bars, len(closes) - 1)]
                label = 1 if final_price > entry_price else (-1 if final_price < entry_price else 0)

            forward_return = (closes[min(i + self.max_bars, len(closes) - 1)] - entry_price) / entry_price if entry_price > 0 else 0.0

            lb = LabeledBar(
                timestamp=ts,
                label=label,
                forward_return=forward_return * 100,
                volatility_at_entry=atr_val / entry_price * 100 if entry_price > 0 else 0.0,
                touched_upper_first=touched_upper_first,
                touched_lower_first=touched_lower_first,
                time_expired=time_expired,
                upper_barrier=upper_barrier,
                lower_barrier=lower_barrier,
                max_barriers=self.max_bars,
            )
            labels.append(lb)
            self._labels[ts] = lb
            self._labels_deque.append(lb)

        return labels

    def label_for_timestamp(self, ts: int) -> LabeledBar | None:
        return self._labels.get(ts)

    def get_recent_labels(self, n: int = 100) -> list[LabeledBar]:
        return list(self._labels_deque)[-n:]

    def get_class_distribution(self) -> dict[str, float]:
        if not self._labels_deque:
            return {"bullish": 0.0, "neutral": 0.0, "bearish": 0.0}
        labels = list(self._labels_deque)[-500:]
        total = len(labels)
        bullish = sum(1 for l in labels if l.label == 1)
        neutral = sum(1 for l in labels if l.label == 0)
        bearish = sum(1 for l in labels if l.label == -1)
        return {
            "bullish": bullish / total if total > 0 else 0.0,
            "neutral": neutral / total if total > 0 else 0.0,
            "bearish": bearish / total if total > 0 else 0.0,
        }

    def _first_touch(self, prices: np.ndarray, barrier: float, direction: str) -> int | None:
        """Find first index where prices touch/breach the barrier."""
        if direction == "upper":
            touches = np.where(prices >= barrier)[0]
        else:
            touches = np.where(prices <= barrier)[0]
        return int(touches[0]) + 1 if len(touches) > 0 else None

    def _compute_atr(self, candles: list[Candle]) -> list[float]:
        """Compute ATR series. Returns list same length as candles."""
        if len(candles) < 2:
            return [0.0] * len(candles)
        tr_values: list[float] = []
        for i in range(1, len(candles)):
            high, low = candles[i].high, candles[i].low
            prev_close = candles[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_values.append(tr)
        # First value
        tr_values.insert(0, tr_values[0] if tr_values else 0.0)

        atr: list[float] = []
        for i in range(len(tr_values)):
            if i < self.atr_period:
                atr.append(sum(tr_values[: i + 1]) / (i + 1))
            else:
                atr.append((atr[-1] * (self.atr_period - 1) + tr_values[i]) / self.atr_period)
        return atr[: len(candles)]

    def get_state(self) -> dict:
        return {
            "total_labels": len(self._labels),
            "recent_labels": len(self._labels_deque),
            "distribution": self.get_class_distribution(),
            "upper_multiplier": self.upper_multiplier,
            "lower_multiplier": self.lower_multiplier,
            "max_bars": self.max_bars,
            "atr_period": self.atr_period,
        }


# Singleton
labeler = TripleBarrierLabeler()
