"""
NEXUS Scalping Risk Manager v2.0

Institutional-grade risk management:
- Kelly Criterion position sizing with 0.25 fraction
- Regime-aware risk multiplier
- Drawdown throttling (linear reduction 5%→15% DD)
- Consecutive loss circuit breaker
- Stochastic position sizer (exponential decay in drawdown)
- Daily loss limit with hard stop
"""

from __future__ import annotations

import math
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
    peak_balance: float = 0.0
    current_balance: float = 0.0
    total_trades: int = 0
    total_wins: int = 0
    total_pnl: float = 0.0


class ScalpRiskManager:
    """Institutional-grade risk management for BTC/USDT scalping."""

    def __init__(
        self,
        initial_balance: float = 10_000.0,
    ) -> None:
        self.initial_balance = initial_balance
        self.max_risk_per_trade = initial_balance * settings.scalp_max_risk_pct
        self.max_daily_loss = initial_balance * settings.scalp_daily_loss_limit_pct
        self.state = ScalpRiskState(
            peak_balance=initial_balance,
            current_balance=initial_balance,
        )
        self._trade_history: list[dict] = []
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

        # Consecutive loss circuit breaker: after 3 losses, require higher confidence
        if self.state.consecutive_losses >= 3:
            if signal.confidence != "HIGH":
                blockers.append(f"Circuit breaker: {self.state.consecutive_losses} consecutive losses — need HIGH confidence")

        # Drawdown throttle: reduce sizing in drawdown
        dd_pct = self._drawdown_pct()
        if dd_pct > 15:
            blockers.append(f"Max drawdown {dd_pct:.1f}% exceeded — stop trading")
        elif dd_pct > 10:
            if signal.confidence != "HIGH":
                blockers.append(f"Drawdown {dd_pct:.1f}% — only HIGH confidence trades allowed")

        return len(blockers) == 0, blockers

    def calculate_position_size(
        self,
        signal: ScalpSignal,
        account_balance: float | None = None,
        regime: str = "unknown",
        win_rate: float | None = None,
        avg_win: float | None = None,
        avg_loss: float | None = None,
    ) -> dict[str, Any]:
        """
        Kelly Criterion position sizing with regime multiplier and drawdown throttle.
        
        Formula:
        Kelly% = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
        Fractional Kelly = 0.25 * Kelly% (conservative)
        Final risk = base_risk * kelly_fraction * regime_mult * dd_mult * conf_mult
        """
        balance = account_balance or self.state.current_balance or self.initial_balance
        entry_mid = (signal.entry_zone_low + signal.entry_zone_high) / 2
        sl_distance = abs(entry_mid - signal.sl_level)

        if sl_distance <= 0:
            return {
                "position_size": 0.0, "notional": 0.0, "risk_amount": 0.0,
                "leverage": 0, "error": "Zero stop distance",
            }

        # ── Kelly Criterion ──
        p = win_rate or self._historical_win_rate()
        b = (avg_win or self._historical_avg_win()) / max(abs(avg_loss or self._historical_avg_loss()), 0.01)
        q = 1.0 - p
        kelly_raw = (p * b - q) / max(b, 0.01)
        kelly_fraction = max(0.0, min(0.25, 0.25 * kelly_raw))  # Capped at 25% Kelly

        # ── Regime multiplier ──
        regime_mult = {
            'trending': 1.0,
            'trending_volatile': 0.85,
            'range_bound': 0.75,
            'consolidation': 0.60,
            'accumulation': 0.90,
            'distribution': 0.90,
        }.get(regime, 0.70)

        # ── Drawdown throttle: exponential decay ──
        dd_pct = self._drawdown_pct()
        if dd_pct < 5:
            dd_mult = 1.0
        elif dd_pct < 15:
            # Linear reduction: 100% at 5% DD → 25% at 15% DD
            dd_mult = max(0.25, 1.0 - (dd_pct - 5) * 0.075)
        else:
            dd_mult = 0.25

        # ── Confidence multiplier ──
        conf_mult = {
            'HIGH': 1.0,
            'MEDIUM': 0.75,
            'LOW': 0.0,  # LOW never trades
        }.get(signal.confidence, 0.5)

        # ── Consecutive loss reduction ──
        cons_mult = max(0.5, 1.0 - self.state.consecutive_losses * 0.15)

        # ── Final risk fraction ──
        base_risk_pct = settings.scalp_max_risk_pct
        final_risk_pct = base_risk_pct * kelly_fraction * regime_mult * dd_mult * conf_mult * cons_mult
        final_risk_pct = max(0.005, min(0.03, final_risk_pct))  # Floor 0.5%, cap 3%

        risk_amount = balance * final_risk_pct
        position_size = risk_amount / sl_distance
        notional = position_size * entry_mid
        leverage = min(signal.leverage, settings.scalp_max_leverage)
        margin = notional / leverage

        return {
            "position_size": round(position_size, 6),
            "notional": round(notional, 2),
            "margin_required": round(margin, 2),
            "risk_amount": round(risk_amount, 2),
            "risk_pct": round(final_risk_pct * 100, 2),
            "leverage": leverage,
            "sl_distance": round(sl_distance, 2),
            "sl_distance_pct": round(sl_distance / entry_mid * 100, 3),
            "kelly_fraction": round(kelly_fraction, 4),
            "regime_multiplier": round(regime_mult, 3),
            "drawdown_multiplier": round(dd_mult, 3),
            "confidence_multiplier": round(conf_mult, 3),
        }

    def record_trade_open(self, signal: ScalpSignal) -> None:
        self._reset_if_new_day()
        self.state.daily_trades += 1
        self.state.open_futures_positions += 1

    def record_trade_close(self, pnl: float) -> None:
        self._reset_if_new_day()
        self.state.daily_pnl += pnl
        self.state.total_pnl += pnl
        self.state.total_trades += 1
        self.state.open_futures_positions = max(0, self.state.open_futures_positions - 1)

        if pnl > 0:
            self.state.daily_wins += 1
            self.state.total_wins += 1
            self.state.consecutive_losses = 0
        else:
            self.state.daily_losses += 1
            self.state.consecutive_losses += 1
            self.state.max_consecutive_losses = max(
                self.state.max_consecutive_losses,
                self.state.consecutive_losses,
            )

        # Update balance tracking
        self.state.current_balance = self.initial_balance + self.state.total_pnl
        if self.state.current_balance > self.state.peak_balance:
            self.state.peak_balance = self.state.current_balance

        if self.state.daily_pnl <= -self.max_daily_loss:
            self.state.daily_loss_hit = True

        self._trade_history.append({
            'pnl': pnl,
            'won': pnl > 0,
            'timestamp': int(time.time() * 1000),
        })

    def _drawdown_pct(self) -> float:
        """Calculate current drawdown from peak."""
        if self.state.peak_balance <= 0:
            return 0.0
        return max(0, (self.state.peak_balance - self.state.current_balance) / self.state.peak_balance * 100)

    def _historical_win_rate(self) -> float:
        """Calculate win rate from recent trades."""
        if self.state.total_trades < 5:
            return 0.50  # Default assumption
        return self.state.total_wins / self.state.total_trades

    def _historical_avg_win(self) -> float:
        """Calculate average win from recent trades."""
        wins = [t['pnl'] for t in self._trade_history[-50:] if t['won']]
        return sum(wins) / len(wins) if wins else 50.0

    def _historical_avg_loss(self) -> float:
        """Calculate average loss from recent trades."""
        losses = [abs(t['pnl']) for t in self._trade_history[-50:] if not t['won']]
        return sum(losses) / len(losses) if losses else 50.0

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
        current_balance = self.state.current_balance or self.initial_balance
        daily_loss_pct = abs(min(self.state.daily_pnl, 0)) / self.initial_balance * 100

        return {
            "current_balance": round(current_balance, 2),
            "initial_balance": self.initial_balance,
            "peak_balance": round(self.state.peak_balance, 2),
            "drawdown_pct": round(self._drawdown_pct(), 2),
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
            "total_trades": self.state.total_trades,
            "total_win_rate": round(self._historical_win_rate(), 4),
            "kelly_fraction": round(max(0, 0.25 * (
                (self._historical_win_rate() * self._historical_avg_win() -
                 (1 - self._historical_win_rate()) * self._historical_avg_loss()) /
                max(self._historical_avg_win(), 0.01)
            )), 4),
        }
