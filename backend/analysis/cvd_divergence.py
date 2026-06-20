"""
CVD Divergence Detector.

Detects regular and hidden divergences between Cumulative Volume Delta (CVD)
and price. CVD divergence is one of the strongest reversal signals in BTCUSD
futures trading.

Types:
  - Regular Bullish Divergence: Price makes lower low, CVD makes higher low
  - Regular Bearish Divergence: Price makes higher high, CVD makes lower high
  - Hidden Bullish Divergence: Price makes higher low, CVD makes lower low
  - Hidden Bearish Divergence: Price makes lower high, CVD makes higher high
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CVDDivergence:
    timestamp: int
    divergence_type: str  # bullish_regular, bearish_regular, bullish_hidden, bearish_hidden
    strength: float  # 0.0 to 1.0
    price_swing_high: float
    price_swing_low: float
    cvd_swing_high: float
    cvd_swing_low: float
    bars_since_start: int
    confirmed: bool
    description: str


class CVDDivergenceDetector:
    """
    Detects CVD-price divergences using swing point comparison.

    Uses a sliding window to find swing highs/lows in both price and CVD,
    then compares them for divergence patterns.
    """

    def __init__(
        self,
        lookback: int = 80,
        min_swing_bars: int = 5,
        confirmation_bars: int = 3,
        strength_threshold: float = 0.3,
    ) -> None:
        self.lookback = lookback
        self.min_swing_bars = min_swing_bars
        self.confirmation_bars = confirmation_bars
        self.strength_threshold = strength_threshold

        self._cvd_history: deque[tuple[int, float]] = deque(maxlen=2000)
        self._price_history: deque[tuple[int, float]] = deque(maxlen=2000)
        self._divergences: deque[CVDDivergence] = deque(maxlen=50)
        self._last_divergence_ts: int = 0

    def ingest(self, timestamp: int, price: float, cvd: float) -> None:
        self._price_history.append((timestamp, price))
        self._cvd_history.append((timestamp, cvd))

    def detect(self) -> list[CVDDivergence]:
        """Run divergence detection on current history buffers."""
        if len(self._price_history) < self.lookback or len(self._cvd_history) < self.lookback:
            return []

        prices = np.array([p[1] for p in self._price_history])
        cvds = np.array([c[1] for c in self._cvd_history])
        timestamps = np.array([p[0] for p in self._price_history])

        # Find swing highs/lows
        price_highs, price_lows = self._find_swings(prices)
        cvd_highs, cvd_lows = self._find_swings(cvds)

        divergences: list[CVDDivergence] = []
        n = len(prices)

        # Regular Bullish Divergence: price lower low, CVD higher low
        for i in range(len(price_lows) - 1):
            pl_idx = price_lows[i]
            pl_val = prices[pl_idx]
            pl2_idx = price_lows[i + 1]
            pl2_val = prices[pl2_idx]

            # Find corresponding CVD lows within a tolerance window
            cvd_candidates = [c for c in cvd_lows if abs(c - pl_idx) <= self.min_swing_bars * 2 or abs(c - pl2_idx) <= self.min_swing_bars * 2]
            if len(cvd_candidates) < 2:
                continue

            # Match CVD lows to price lows
            cl1 = min(cvd_candidates, key=lambda x: abs(x - pl_idx))
            cl2 = min(cvd_candidates, key=lambda x: abs(x - pl2_idx))
            if cl1 == cl2:
                continue

            if pl2_val < pl_val and cvds[cl2] > cvds[cl1]:
                strength = self._compute_strength(
                    price_drop=(pl_val - pl2_val) / pl_val,
                    cvd_rise=(cvds[cl2] - cvds[cl1]) / (abs(cvds[cl1]) + 1e-8),
                    confirmation=pl2_idx - pl_idx,
                )
                if strength >= self.strength_threshold:
                    div = CVDDivergence(
                        timestamp=int(timestamps[pl2_idx]),
                        divergence_type="bullish_regular",
                        strength=strength,
                        price_swing_high=pl_val,
                        price_swing_low=pl2_val,
                        cvd_swing_high=cvds[cl1],
                        cvd_swing_low=cvds[cl2],
                        bars_since_start=int(pl2_idx - pl_idx),
                        confirmed=True,
                        description=f"Regular bullish CVD divergence: price low {pl_val:.0f}->{pl2_val:.0f}, CVD {cvds[cl1]:.0f}->{cvds[cl2]:.0f}",
                    )
                    divergences.append(div)

        # Regular Bearish Divergence: price higher high, CVD lower high
        for i in range(len(price_highs) - 1):
            ph_idx = price_highs[i]
            ph_val = prices[ph_idx]
            ph2_idx = price_highs[i + 1]
            ph2_val = prices[ph2_idx]

            cvd_candidates = [c for c in cvd_highs if abs(c - ph_idx) <= self.min_swing_bars * 2 or abs(c - ph2_idx) <= self.min_swing_bars * 2]
            if len(cvd_candidates) < 2:
                continue

            ch1 = min(cvd_candidates, key=lambda x: abs(x - ph_idx))
            ch2 = min(cvd_candidates, key=lambda x: abs(x - ph2_idx))
            if ch1 == ch2:
                continue

            if ph2_val > ph_val and cvds[ch2] < cvds[ch1]:
                strength = self._compute_strength(
                    price_drop=(ph2_val - ph_val) / ph_val,
                    cvd_rise=(cvds[ch1] - cvds[ch2]) / (abs(cvds[ch1]) + 1e-8),
                    confirmation=ph2_idx - ph_idx,
                )
                if strength >= self.strength_threshold:
                    div = CVDDivergence(
                        timestamp=int(timestamps[ph2_idx]),
                        divergence_type="bearish_regular",
                        strength=strength,
                        price_swing_high=ph2_val,
                        price_swing_low=ph_val,
                        cvd_swing_high=cvds[ch1],
                        cvd_swing_low=cvds[ch2],
                        bars_since_start=int(ph2_idx - ph_idx),
                        confirmed=True,
                        description=f"Regular bearish CVD divergence: price high {ph_val:.0f}->{ph2_val:.0f}, CVD {cvds[ch1]:.0f}->{cvds[ch2]:.0f}",
                    )
                    divergences.append(div)

        # Hidden Bullish Divergence: price higher low, CVD lower low
        for i in range(len(price_lows) - 1):
            pl_idx = price_lows[i]
            pl_val = prices[pl_idx]
            pl2_idx = price_lows[i + 1]
            pl2_val = prices[pl2_idx]

            cvd_candidates = [c for c in cvd_lows if abs(c - pl_idx) <= self.min_swing_bars * 2 or abs(c - pl2_idx) <= self.min_swing_bars * 2]
            if len(cvd_candidates) < 2:
                continue

            cl1 = min(cvd_candidates, key=lambda x: abs(x - pl_idx))
            cl2 = min(cvd_candidates, key=lambda x: abs(x - pl2_idx))
            if cl1 == cl2:
                continue

            if pl2_val > pl_val and cvds[cl2] < cvds[cl1]:
                strength = self._compute_strength(
                    price_drop=(pl2_val - pl_val) / pl_val,
                    cvd_rise=(cvds[cl1] - cvds[cl2]) / (abs(cvds[cl1]) + 1e-8),
                    confirmation=pl2_idx - pl_idx,
                ) * 0.8  # Hidden divergences are usually weaker
                if strength >= self.strength_threshold:
                    div = CVDDivergence(
                        timestamp=int(timestamps[pl2_idx]),
                        divergence_type="bullish_hidden",
                        strength=strength,
                        price_swing_high=pl2_val,
                        price_swing_low=pl_val,
                        cvd_swing_high=cvds[cl1],
                        cvd_swing_low=cvds[cl2],
                        bars_since_start=int(pl2_idx - pl_idx),
                        confirmed=True,
                        description=f"Hidden bullish CVD divergence: price low {pl_val:.0f}->{pl2_val:.0f}, CVD {cvds[cl1]:.0f}->{cvds[cl2]:.0f}",
                    )
                    divergences.append(div)

        # Hidden Bearish Divergence: price lower high, CVD higher high
        for i in range(len(price_highs) - 1):
            ph_idx = price_highs[i]
            ph_val = prices[ph_idx]
            ph2_idx = price_highs[i + 1]
            ph2_val = prices[ph2_idx]

            cvd_candidates = [c for c in cvd_highs if abs(c - ph_idx) <= self.min_swing_bars * 2 or abs(c - ph2_idx) <= self.min_swing_bars * 2]
            if len(cvd_candidates) < 2:
                continue

            ch1 = min(cvd_candidates, key=lambda x: abs(x - ph_idx))
            ch2 = min(cvd_candidates, key=lambda x: abs(x - ph2_idx))
            if ch1 == ch2:
                continue

            if ph2_val < ph_val and cvds[ch2] > cvds[ch1]:
                strength = self._compute_strength(
                    price_drop=(ph_val - ph2_val) / ph_val,
                    cvd_rise=(cvds[ch2] - cvds[ch1]) / (abs(cvds[ch1]) + 1e-8),
                    confirmation=ph2_idx - ph_idx,
                ) * 0.8
                if strength >= self.strength_threshold:
                    div = CVDDivergence(
                        timestamp=int(timestamps[ph2_idx]),
                        divergence_type="bearish_hidden",
                        strength=strength,
                        price_swing_high=ph_val,
                        price_swing_low=ph2_val,
                        cvd_swing_high=cvds[ch1],
                        cvd_swing_low=cvds[ch2],
                        bars_since_start=int(ph2_idx - ph_idx),
                        confirmed=True,
                        description=f"Hidden bearish CVD divergence: price high {ph_val:.0f}->{ph2_val:.0f}, CVD {cvds[ch1]:.0f}->{cvds[ch2]:.0f}",
                    )
                    divergences.append(div)

        # Store and update state
        for d in divergences:
            self._divergences.append(d)
            if d.timestamp > self._last_divergence_ts:
                self._last_divergence_ts = d.timestamp

        # Sort by strength descending, return top 5
        divergences.sort(key=lambda d: d.strength, reverse=True)
        return divergences[:5]

    def _find_swings(self, data: np.ndarray) -> tuple[list[int], list[int]]:
        """Find swing high and low indices using local extrema."""
        highs: list[int] = []
        lows: list[int] = []
        half_window = max(self.min_swing_bars, 2)

        for i in range(half_window, len(data) - half_window):
            window = data[i - half_window : i + half_window + 1]
            if data[i] == np.max(window):
                highs.append(i)
            if data[i] == np.min(window):
                lows.append(i)

        # Remove duplicates and ensure alternating
        return self._filter_alternating(highs, lows)

    def _filter_alternating(self, highs: list[int], lows: list[int]) -> tuple[list[int], list[int]]:
        """Ensure swings alternate properly (high, low, high, low...)."""
        if not highs or not lows:
            return highs, lows

        merged: list[tuple[int, str]] = [(i, "high") for i in highs] + [(i, "low") for i in lows]
        merged.sort(key=lambda x: x[0])

        filtered_highs: list[int] = []
        filtered_lows: list[int] = []
        last_type: str | None = None

        for idx, typ in merged:
            if typ != last_type:
                if typ == "high":
                    filtered_highs.append(idx)
                else:
                    filtered_lows.append(idx)
                last_type = typ

        return filtered_highs, filtered_lows

    def _compute_strength(self, price_drop: float, cvd_rise: float, confirmation: int) -> float:
        """Compute divergence strength 0-1 based on price change, CVD change, and bar confirmation."""
        price_component = min(abs(price_drop) * 50, 0.5)
        cvd_component = min(abs(cvd_rise) * 10, 0.3)
        conf_component = min(confirmation / 50, 0.2)
        return round(min(price_component + cvd_component + conf_component, 1.0), 4)

    def get_active_divergences(self) -> list[CVDDivergence]:
        return list(self._divergences)[-10:]

    def get_state(self) -> dict:
        return {
            "active_divergences": len(self._divergences),
            "last_divergence_ts": self._last_divergence_ts,
            "price_history": len(self._price_history),
            "cvd_history": len(self._cvd_history),
        }


# Singleton
cvd_divergence_detector = CVDDivergenceDetector()
