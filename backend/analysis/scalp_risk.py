"""
BTC/USDT Scalping Risk Manager

Enforces strict risk parameters for scalping:
- Max risk per trade: 1% of capital
- Max leverage: 10x Futures
- Max simultaneous positions: 1 futures position
- Daily loss limit: 3% -> STOP ALL TRADING for the day
- Minimum RRR: 1:1.5
- Position sizing: Based on SL distance, not gut feel
- Max hold time: 15 minutes per scalp trade
- Exit ALL positions before funding rate reset (every 8 hours)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings
from backend.models.types import ScalpSignal


@dataclass
class ScalpRiskState:
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    open_futures_positions: int = 0
    total_exposure: float = 0.0
    last_reset_date: str = ""
    daily_loss_hit: bool = False
    funding_reset_exit_done: bool = False


class ScalpRiskManager:
    """Strict risk enforcement for BTC/USDT scalping."""

    def __init__(
        self,
        initial_balance: float = 10_000.0,
    ) -> None:
        self.initial_balance = initial_balance
        self.max_risk_per_trade = initial_balance * settings.scalp_max_risk_pct
        self.max_daily_loss = initial_balance * settings.scalp_daily_loss_limit_pct
        self.state = ScalpRiskState()
        self._reset_if_new_day()

    def _reset_if_new_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.state.last_reset_date != today:
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.daily_wins = 0
            self.state.daily_losses = 0
            self.state.consecutive_losses = 0
            self.state.daily_loss_hit = False
            self.state.funding_reset_exit_done = False
            self.state.last_reset_date = today

    def can_open_trade(self, signal: ScalpSignal) -> tuple[bool, list[str]]:
        self._reset_if_new_day()
        blockers: list[str] = []

        if self.state.daily_loss_hit:
            blockers.append("Daily loss limit hit — all trading stopped")

        if self.state.daily_trades >= 10:
            blockers.append("Max daily trades reached (10)")

        if self.state.open_futures_positions >= 1:
            blockers.append("Max 1 futures position allowed")

        total_open = self.state.open_futures_positions
        if total_open >= settings.scalp_max_positions:
            blockers.append(f"Max simultaneous positions: {settings.scalp_max_positions}")

        if signal.risk_reward < settings.scalp_min_rrr:
            blockers.append(f"RRR {signal.risk_reward:.2f} below minimum {settings.scalp_min_rrr}")

        if signal.confidence == "LOW":
            blockers.append("LOW confidence — do not trade")

        if signal.leverage > settings.scalp_max_leverage:
            blockers.append(f"Leverage {signal.leverage}x exceeds max {settings.scalp_max_leverage}x")

        now_ms = int(time.time() * 1000)
        if signal.time_limit_ms and now_ms > signal.time_limit_ms:
            blockers.append("Signal time limit expired")

        return len(blockers) == 0, blockers

    def calculate_position_size(
        self,
        signal: ScalpSignal,
        account_balance: float | None = None,
    ) -> dict[str, Any]:
        balance = account_balance or self.initial_balance
        risk_amount = balance * settings.scalp_max_risk_pct

        entry_mid = (signal.entry_zone_low + signal.entry_zone_high) / 2
        sl_distance = abs(entry_mid - signal.sl_level)

        if sl_distance <= 0:
            return {
                "position_size": 0.0,
                "notional": 0.0,
                "risk_amount": 0.0,
                "leverage": 0,
                "error": "Zero stop distance",
            }

        position_size = risk_amount / sl_distance
        notional = position_size * entry_mid

        leverage = min(signal.leverage, settings.scalp_max_leverage)
        notional = position_size * entry_mid
        margin = notional / leverage

        return {
            "position_size": round(position_size, 6),
            "notional": round(notional, 2),
            "margin_required": round(margin, 2),
            "risk_amount": round(risk_amount, 2),
            "risk_pct": round(risk_amount / balance * 100, 2),
            "leverage": leverage,
            "sl_distance": round(sl_distance, 2),
            "sl_distance_pct": round(sl_distance / entry_mid * 100, 3),
        }

    def record_trade_open(self, signal: ScalpSignal) -> None:
        self._reset_if_new_day()
        self.state.daily_trades += 1
        self.state.open_futures_positions += 1

    def record_trade_close(self, pnl: float) -> None:
        self._reset_if_new_day()
        self.state.daily_pnl += pnl
        self.state.open_futures_positions = max(0, self.state.open_futures_positions - 1)

        if pnl > 0:
            self.state.daily_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.daily_losses += 1
            self.state.consecutive_losses += 1
            self.state.max_consecutive_losses = max(
                self.state.max_consecutive_losses,
                self.state.consecutive_losses,
            )

        if self.state.daily_pnl <= -self.max_daily_loss:
            self.state.daily_loss_hit = True

    def should_exit_before_funding(self, now_ms: int, next_funding_ms: int) -> bool:
        minutes_to_funding = (next_funding_ms - now_ms) / 60000
        return minutes_to_funding < 30

    def should_force_exit(self, signal: ScalpSignal, entry_time_ms: int) -> tuple[bool, str]:
        now_ms = int(time.time() * 1000)
        hold_minutes = (now_ms - entry_time_ms) / 60000

        if hold_minutes > settings.scalp_max_hold_minutes:
            return True, f"Max hold time exceeded: {hold_minutes:.0f}m > {settings.scalp_max_hold_minutes}m"

        if signal.time_limit_ms and now_ms > signal.time_limit_ms:
            return True, "Signal time limit expired"

        return False, ""

    def get_risk_summary(self) -> dict[str, Any]:
        self._reset_if_new_day()
        current_balance = self.initial_balance + self.state.daily_pnl
        daily_loss_pct = abs(min(self.state.daily_pnl, 0)) / self.initial_balance * 100

        return {
            "current_balance": round(current_balance, 2),
            "initial_balance": self.initial_balance,
            "daily_pnl": round(self.state.daily_pnl, 2),
            "daily_trades": self.state.daily_trades,
            "daily_wins": self.state.daily_wins,
            "daily_losses": self.state.daily_losses,
            "daily_win_rate": round(
                self.state.daily_wins / max(self.state.daily_trades, 1), 3
            ),
            "daily_loss_pct": round(daily_loss_pct, 2),
            "max_daily_loss_pct": round(settings.scalp_daily_loss_limit_pct * 100, 2),
            "daily_loss_hit": self.state.daily_loss_hit,
            "consecutive_losses": self.state.consecutive_losses,
            "max_consecutive_losses": self.state.max_consecutive_losses,
            "open_futures": self.state.open_futures_positions,
            "total_open": self.state.open_futures_positions,
            "max_positions": settings.scalp_max_positions,
            "max_risk_per_trade_pct": round(settings.scalp_max_risk_pct * 100, 2),
            "max_leverage": settings.scalp_max_leverage,
            "min_rrr": settings.scalp_min_rrr,
            "max_hold_minutes": settings.scalp_max_hold_minutes,
        }
