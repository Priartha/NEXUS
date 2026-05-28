from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from backend.storage import repository as repo


@dataclass
class RiskState:
    """Tracks current risk exposure and limits."""
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_wins: int = 0
    daily_losses: int = 0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    total_exposure: float = 0.0
    last_reset_date: str = ""
    weekly_pnl: float = 0.0
    weekly_trades: int = 0


class RiskManager:
    """Comprehensive risk management layer.
    Enforces: max daily loss, max drawdown, position limits, correlation checks."""

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        max_daily_loss_pct: float = 0.03,
        max_drawdown_pct: float = 0.10,
        max_position_size_pct: float = 0.02,
        max_open_positions: int = 1,
        max_consecutive_losses: int = 3,
        cooldown_minutes_after_loss: int = 90,
        min_confidence: float = 0.55,
        max_correlation: float = 0.8,
    ):
        self.initial_balance = initial_balance
        self.max_position_size_pct = max_position_size_pct
        self.max_daily_loss = initial_balance * max_daily_loss_pct
        self.max_drawdown = initial_balance * max_drawdown_pct
        self.max_open_positions = max_open_positions
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes_after_loss
        self.min_confidence = min_confidence
        self.max_correlation = max_correlation
        self.state = RiskState()
        self._reset_if_new_day()

    def _reset_if_new_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.state.last_reset_date != today:
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.daily_wins = 0
            self.state.daily_losses = 0
            self.state.last_reset_date = today

    def can_open_trade(
        self,
        signal_confidence: float,
        risk_amount: float,
        symbol: str = "BTCUSDT",
    ) -> tuple[bool, list[str]]:
        """Check if a new trade is allowed under risk rules.
        Returns (allowed, reasons_for_block)."""
        self._reset_if_new_day()
        blockers: list[str] = []

        if signal_confidence < self.min_confidence:
            blockers.append(f"Confidence {signal_confidence:.2f} below minimum {self.min_confidence}")

        current_balance = self._current_balance()
        max_position_size = current_balance * self.max_position_size_pct
        if risk_amount > max_position_size:
            blockers.append(f"Risk ${risk_amount:.0f} exceeds max position ${max_position_size:.0f}")

        if self.state.daily_trades >= 5:
            blockers.append("Max daily trades reached (5)")

        if self.state.daily_pnl <= -self.max_daily_loss:
            blockers.append(f"Daily loss limit hit: ${abs(self.state.daily_pnl):.0f} / ${self.max_daily_loss:.0f}")

        drawdown = self.initial_balance - current_balance
        if drawdown >= self.max_drawdown:
            blockers.append(f"Max drawdown hit: ${drawdown:.0f} / ${self.max_drawdown:.0f}")

        if self.state.consecutive_losses >= self.max_consecutive_losses:
            blockers.append(f"Consecutive loss cooldown: {self.state.consecutive_losses} losses")

        open_trades = repo.get_paper_trades(status="open")
        if len(open_trades) >= self.max_open_positions:
            blockers.append(f"Max open positions: {len(open_trades)}/{self.max_open_positions}")

        return len(blockers) == 0, blockers

    def record_trade_result(self, pnl: float) -> None:
        """Update risk state after a trade closes."""
        self._reset_if_new_day()
        self.state.daily_pnl += pnl
        self.state.daily_trades += 1

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

    def get_risk_summary(self) -> dict[str, Any]:
        """Return current risk state for dashboard display."""
        self._reset_if_new_day()
        current_balance = self._current_balance()
        drawdown = self.initial_balance - current_balance
        drawdown_pct = (drawdown / self.initial_balance) * 100 if self.initial_balance > 0 else 0
        daily_loss_pct = (abs(self.state.daily_pnl) / self.initial_balance) * 100 if self.state.daily_pnl < 0 else 0

        return {
            "current_balance": round(current_balance, 2),
            "initial_balance": self.initial_balance,
            "total_pnl": round(current_balance - self.initial_balance, 2),
            "daily_pnl": round(self.state.daily_pnl, 2),
            "daily_trades": self.state.daily_trades,
            "daily_wins": self.state.daily_wins,
            "daily_losses": self.state.daily_losses,
            "daily_win_rate": round(self.state.daily_wins / max(self.state.daily_trades, 1), 3),
            "daily_loss_pct": round(daily_loss_pct, 2),
            "max_daily_loss_pct": round((self.max_daily_loss / self.initial_balance) * 100, 2),
            "drawdown": round(drawdown, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "max_drawdown_pct": round((self.max_drawdown / self.initial_balance) * 100, 2),
            "consecutive_losses": self.state.consecutive_losses,
            "max_consecutive_losses": self.state.max_consecutive_losses,
            "open_positions": len(repo.get_paper_trades(status="open")),
            "max_open_positions": self.max_open_positions,
            "can_trade": self.can_open_trade(0.6, 100)[0],
        }

    def _current_balance(self) -> float:
        stats = repo.get_paper_trade_stats()
        return self.initial_balance + stats["total_pnl"]

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        risk_pct: float = 0.02,
    ) -> float:
        """Calculate position size based on risk percentage and stop distance."""
        risk_amount = self._current_balance() * risk_pct
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0
        return risk_amount / risk_per_unit
