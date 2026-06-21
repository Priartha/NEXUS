from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.models.types import Candle, TradeSignal

logger = logging.getLogger(__name__)


DEFAULT_TRADER_PROFILE: dict[str, Any] = {
    "timezone": "Asia/Kolkata",
    "execution_profile": {
        "high_performance_hours": [0, 2, 3, 4, 7, 8, 9, 11, 14, 16, 20, 22, 23],
        "blocked_hours": [1, 15, 17, 18, 19, 21],
        "reduced_size_hours": [6, 12, 13],
        "good_hour_confidence_delta": -0.04,
        "reduced_hour_confidence_delta": 0.05,
        "min_fee_edge_ratio": 3.5,
        "post_win_cooldown_minutes": 30,
        "risk_per_trade_pct": 0.008,
    },
    "notes": [
        "Default profile inferred from 79 BTCUSD perpetual trades over 28 days.",
        "Win rate: 65.8%, Profit factor: 2.30",
        "Use this as an execution overlay, not a guarantee of future win rate.",
    ],
}


@dataclass(frozen=True)
class TraderStyleProfile:
    """Execution profile inferred from the user's realised Delta PnL export.

    This profile is deliberately an execution/risk overlay, not a signal source.
    It should reduce churn and avoid empirically poor timing windows while letting
    the existing model continue to decide direction.
    """

    timezone: str
    high_performance_hours: tuple[int, ...]
    blocked_hours: tuple[int, ...]
    reduced_size_hours: tuple[int, ...]
    good_hour_confidence_delta: float
    reduced_hour_confidence_delta: float
    min_fee_edge_ratio: float
    post_win_cooldown_minutes: int
    risk_per_trade_pct: float
    notes: tuple[str, ...]

    @classmethod
    def disabled(cls) -> "TraderStyleProfile":
        return cls(
            timezone="Asia/Kolkata",
            high_performance_hours=(),
            blocked_hours=(),
            reduced_size_hours=(),
            good_hour_confidence_delta=0.0,
            reduced_hour_confidence_delta=0.0,
            min_fee_edge_ratio=0.0,
            post_win_cooldown_minutes=0,
            risk_per_trade_pct=0.02,
            notes=(),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TraderStyleProfile":
        execution = payload.get("execution_profile", {})
        return cls(
            timezone=str(payload.get("timezone") or "Asia/Kolkata"),
            high_performance_hours=tuple(int(h) for h in execution.get("high_performance_hours", [])),
            blocked_hours=tuple(int(h) for h in execution.get("blocked_hours", [])),
            reduced_size_hours=tuple(int(h) for h in execution.get("reduced_size_hours", [])),
            good_hour_confidence_delta=float(execution.get("good_hour_confidence_delta", 0.0) or 0.0),
            reduced_hour_confidence_delta=float(execution.get("reduced_hour_confidence_delta", 0.0) or 0.0),
            min_fee_edge_ratio=float(execution.get("min_fee_edge_ratio", 0.0) or 0.0),
            post_win_cooldown_minutes=int(execution.get("post_win_cooldown_minutes", 0) or 0),
            risk_per_trade_pct=float(execution.get("risk_per_trade_pct", 0.02) or 0.02),
            notes=tuple(str(item) for item in payload.get("notes", [])),
        )

    def local_hour(self, timestamp_ms: int) -> int:
        try:
            zone = ZoneInfo(self.timezone)
        except Exception:
            zone = ZoneInfo("Asia/Kolkata")
        return int(datetime.fromtimestamp(timestamp_ms / 1000, tz=zone).hour)

    def confidence_threshold(self, base_threshold: float, candle: Candle) -> float:
        hour = self.local_hour(candle.timestamp)
        threshold = float(base_threshold)
        if hour in self.high_performance_hours:
            threshold += self.good_hour_confidence_delta
        elif hour in self.reduced_size_hours:
            threshold += self.reduced_hour_confidence_delta
        return max(0.35, min(0.85, threshold))

    def edge_threshold(self, base_edge: float, timestamp_ms: int) -> float:
        hour = self.local_hour(timestamp_ms)
        edge = float(base_edge)
        if hour in self.high_performance_hours:
            edge -= 0.01
        elif hour in self.reduced_size_hours:
            edge += 0.02
        return max(0.02, min(0.20, edge))

    def signal_blockers(self, signal: TradeSignal | None, candle: Candle) -> list[str]:
        hour = self.local_hour(candle.timestamp)
        blockers: list[str] = []
        if hour in self.blocked_hours:
            blockers.append(f"Trader profile blocks {hour:02d}:00 {self.timezone}: negative realised PnL window")
        if signal is not None and signal.risk_reward and signal.risk_reward < 1.5:
            blockers.append(f"Trader profile requires cleaner R:R; signal R:R {signal.risk_reward:.2f}")
        return blockers

    def fee_edge_blockers(self, signal: TradeSignal, quantity: float, entry_price: float, commission_pct: float) -> list[str]:
        if self.min_fee_edge_ratio <= 0 or quantity <= 0:
            return []
        target_gross = abs(float(signal.exit_price) - entry_price) * quantity
        round_trip_fee = abs(entry_price * quantity) * commission_pct * 2.0
        if round_trip_fee <= 0:
            return []
        ratio = target_gross / round_trip_fee
        if ratio < self.min_fee_edge_ratio:
            return [f"Trader profile fee filter: target/fee {ratio:.1f}x below {self.min_fee_edge_ratio:.1f}x"]
        return []


_cached_profile: TraderStyleProfile | None = None
_cached_mtime: float | None = None


def get_trader_profile() -> TraderStyleProfile:
    global _cached_profile, _cached_mtime
    if not settings.trader_profile_enabled:
        return TraderStyleProfile.disabled()

    path = Path(settings.trader_profile_path)
    try:
        mtime = path.stat().st_mtime
        if _cached_profile is not None and _cached_mtime == mtime:
            return _cached_profile
        raw = path.read_bytes()
        # Strip UTF-8 BOM if present (Windows often writes one)
        if raw[:3] == b"\xef\xbb\xbf":
            raw = raw[3:]
        payload = json.loads(raw)
        _cached_profile = TraderStyleProfile.from_dict(payload)
        _cached_mtime = mtime
        return _cached_profile
    except FileNotFoundError:
        _cached_profile = TraderStyleProfile.from_dict(DEFAULT_TRADER_PROFILE)
        _cached_mtime = None
        return _cached_profile
    except Exception:
        logger.exception("Failed to load trader style profile from %s", path)
        return TraderStyleProfile.disabled()
