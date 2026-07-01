"""
Funding Rate Strategy Subsystem for BTCUSD Perpetual Futures.

Funding rate arbitrage / mean-reversion strategy:
  - Enter long when funding rate is extremely negative (shorts pay longs)
  - Enter short when funding rate is extremely positive (longs pay shorts)
  - Exit when funding rate normalizes

The funding rate z-score against its rolling history determines entry/exit.
This is a top-3 alpha source for BTCUSD futures.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from backend.models.types import ScalpSignal

logger = logging.getLogger(__name__)


@dataclass
class FundingSignal:
    timestamp: int
    direction: str  # long, short, neutral
    strength: float  # 0 to 1
    zscore: float
    current_rate: float
    annualized_rate: float
    time_to_next_funding: int  # ms
    expected_pnl_8h: float  # estimated PnL from funding over 8h
    max_pain_level: float  # liquidation level that would wipe this trade
    reason: str


class FundingStrategy:
    """
    Standalone funding rate strategy for BTCUSD perpetuals.

    Uses rolling z-score of funding rate to detect extreme readings.
    Enters contrarian position when |z| > threshold.
    Exits when |z| < exit_threshold (mean reversion).
    """

    def __init__(
        self,
        entry_zscore: float = 2.5,
        exit_zscore: float = 0.5,
        lookback_hours: int = 168,
        min_rate_abs: float = 0.0001,
        max_leverage: int = 3,
        cooldown_hours: float = 4.0,
        position_size_pct: float = 0.05,
    ) -> None:
        self.entry_zscore = entry_zscore
        self.exit_zscore = exit_zscore
        self.lookback_hours = lookback_hours
        self.min_rate_abs = min_rate_abs
        self.max_leverage = max_leverage
        self.cooldown_hours = cooldown_hours
        self.position_size_pct = position_size_pct

        # History: (timestamp_ms, rate)
        self._history: deque[tuple[int, float]] = deque(maxlen=10000)
        self._signals: deque[FundingSignal] = deque(maxlen=50)

        # Open position tracking
        self._current_position: str | None = None  # "long" or "short"
        self._position_entry_ts: int = 0
        self._last_signal_ts: int = 0

        # Regime-adaptive thresholds
        self._regime_thresholds: dict[str, dict] = {
            "trending": {"entry": 3.0, "exit": 0.8, "leverage": 2},
            "trending_volatile": {"entry": 3.5, "exit": 1.0, "leverage": 1},
            "range_bound": {"entry": 2.0, "exit": 0.5, "leverage": 3},
            "consolidation": {"entry": 2.0, "exit": 0.5, "leverage": 3},
            "accumulation": {"entry": 2.5, "exit": 0.5, "leverage": 2},
            "distribution": {"entry": 2.5, "exit": 0.5, "leverage": 2},
        }

    def ingest_rate(self, rate: float, timestamp_ms: int | None = None) -> None:
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        self._history.append((timestamp_ms, rate))

    def compute(self, current_rate: float, price: float, regime: str | None = None) -> FundingSignal:
        """Compute funding rate signal."""
        now_ms = int(time.time() * 1000)
        self.ingest_rate(current_rate, now_ms)

        if len(self._history) < 24:
            return FundingSignal(now_ms, "neutral", 0.0, 0.0, current_rate, 0.0, 0, 0.0, 0.0, "Insufficient history")

        rates = np.array([r[1] for r in self._history])

        # Apply regime-adaptive thresholds
        entry_z = self.entry_zscore
        exit_z = self.exit_zscore
        leverage = self.max_leverage
        if regime and regime in self._regime_thresholds:
            rt = self._regime_thresholds[regime]
            entry_z = rt["entry"]
            exit_z = rt["exit"]
            leverage = rt["leverage"]

        # Check cooldown
        if self._current_position is not None:
            elapsed_hours = (now_ms - self._position_entry_ts) / 3600000
            if elapsed_hours < self.cooldown_hours:
                # Still in position, check exit
                zscore = float((current_rate - np.mean(rates)) / max(np.std(rates), 1e-10))
                if abs(zscore) < exit_z:
                    sig = FundingSignal(now_ms, "exit", 0.0, zscore, current_rate, current_rate * 365 * 3 * 100,
                                        self._next_funding_ms(now_ms), current_rate * 3 * price, 0.0,
                                        f"Funding normalized: z={zscore:.2f}")
                    self._signals.append(sig)
                    self._current_position = None
                    return sig
                return FundingSignal(now_ms, "neutral", 0.0, zscore, current_rate, current_rate * 365 * 3 * 100,
                                     self._next_funding_ms(now_ms), current_rate * 3 * price, 0.0,
                                     f"In position ({self._current_position}), {elapsed_hours:.1f}h elapsed")

        # Compute z-score
        mean_rate = float(np.mean(rates))
        std_rate = float(np.std(rates))
        if std_rate < 1e-10:
            return FundingSignal(now_ms, "neutral", 0.0, 0.0, current_rate, 0.0, 0, 0.0, 0.0, "Zero std")

        zscore = float((current_rate - mean_rate) / std_rate)

        # Check entry
        direction = "neutral"
        strength = 0.0
        reason = ""

        if zscore > entry_z and abs(current_rate) >= self.min_rate_abs:
            direction = "short"
            strength = min((zscore - entry_z) / 2.0, 1.0)
            reason = f"Funding extreme positive: z={zscore:.2f}, rate={current_rate*100:.4f}%"
            self._current_position = "short"
            self._position_entry_ts = now_ms
        elif zscore < -entry_z and abs(current_rate) >= self.min_rate_abs:
            direction = "long"
            strength = min((abs(zscore) - entry_z) / 2.0, 1.0)
            reason = f"Funding extreme negative: z={zscore:.2f}, rate={current_rate*100:.4f}%"
            self._current_position = "long"
            self._position_entry_ts = now_ms
        else:
            reason = f"Funding neutral: z={zscore:.2f}, rate={current_rate*100:.4f}%"

        # Estimate max pain (liquidation level that would wipe the position)
        annualized = current_rate * 365 * 3
        expected_pnl_8h = current_rate * 3 * price  # 3 funding periods
        time_to_next = self._next_funding_ms(now_ms) - now_ms
        liq_level = price * (1 + 0.5 / leverage) if direction == "long" else price * (1 - 0.5 / leverage)

        sig = FundingSignal(
            timestamp=now_ms,
            direction=direction,
            strength=strength,
            zscore=zscore,
            current_rate=current_rate,
            annualized_rate=annualized * 100,
            time_to_next_funding=time_to_next,
            expected_pnl_8h=expected_pnl_8h,
            max_pain_level=liq_level,
            reason=reason,
        )
        self._signals.append(sig)
        self._last_signal_ts = now_ms
        return sig

    def close_position(self, reason: str = "manual") -> None:
        self._current_position = None
        self._position_entry_ts = 0

    def _next_funding_ms(self, now_ms: int) -> int:
        from datetime import datetime, timezone, timedelta
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        for h in [0, 8, 16]:
            r = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if r > now:
                return int(r.timestamp() * 1000)
        nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return int(nxt.timestamp() * 1000)

    def get_state(self) -> dict:
        return {
            "current_position": self._current_position,
            "position_entry_ts": self._position_entry_ts,
            "history_length": len(self._history),
            "recent_signals": [
                {"ts": s.timestamp, "dir": s.direction, "strength": round(s.strength, 3), "zscore": round(s.zscore, 2)}
                for s in list(self._signals)[-5:]
            ],
            "entry_zscore": self.entry_zscore,
            "exit_zscore": self.exit_zscore,
            "max_leverage": self.max_leverage,
        }


# Singleton
funding_strategy = FundingStrategy()
