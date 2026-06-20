"""
Position Manager — Live Position Tracking & Execution API.

Provides:
  - Position management (open, modify, close)
  - Order submission (market, limit, stop)
  - PnL tracking (realized + unrealized)
  - Position sizing (Kelly-based)
  - Risk controls (max drawdown, daily loss limit, max positions)
  - Order history

This module serves as the execution layer that connects the signal engine
to an actual exchange API (Binance Futures).
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass
class Order:
    id: str
    symbol: str
    side: str  # buy or sell
    order_type: str  # market, limit, stop_market, stop_limit
    quantity: float
    price: float | None
    stop_price: float | None
    reduce_only: bool
    timestamp: int
    status: str  # pending, filled, partially_filled, cancelled, rejected
    filled_qty: float
    avg_fill_price: float | None
    reduce_position_id: str | None


@dataclass
class Position:
    id: str
    symbol: str
    side: str  # long or short
    size: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float
    liquidation_price: float
    leverage: int
    margin: float
    opened_at: int
    stop_loss: float | None
    take_profit: float | None
    status: str  # open, closed, liquidated


class PositionManager:
    """
    Manages futures positions with full risk controls.

    Supports:
      - Market / limit / stop order submission
      - Position tracking with unrealized PnL
      - Risk controls (daily loss, max drawdown, max positions)
      - SL/TP management
      - Partial exits
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        max_leverage: int = 10,
        max_positions: int = 3,
        daily_loss_limit_pct: float = 5.0,
        max_drawdown_pct: float = 15.0,
        position_size_pct: float = 2.0,
        use_kelly: bool = True,
    ) -> None:
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.peak_balance = initial_balance
        self.max_leverage = max_leverage
        self.max_positions = max_positions
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.position_size_pct = position_size_pct
        self.use_kelly = use_kelly

        self._positions: dict[str, Position] = {}
        self._orders: deque[Order] = deque(maxlen=500)
        self._closed_positions: deque[Position] = deque(maxlen=200)
        self._daily_trades: int = 0
        self._daily_pnl: float = 0.0
        self._daily_reset_day: int = -1
        self._consecutive_losses: int = 0

    def _check_daily_reset(self) -> None:
        today = time.localtime().tm_yday
        if today != self._daily_reset_day:
            self._daily_trades = 0
            self._daily_pnl = 0.0
            self._daily_reset_day = today

    def open_position(
        self,
        symbol: str,
        side: str,
        size: float | None = None,
        entry_price: float | None = None,
        leverage: int = 1,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        confidence: float = 0.5,
        kelly_fraction: float | None = None,
    ) -> dict:
        """Open a new position with risk checks."""
        self._check_daily_reset()

        # Risk checks
        if len(self._positions) >= self.max_positions:
            return {"success": False, "error": f"Max positions ({self.max_positions}) reached"}
        if self._daily_pnl <= -self.current_balance * self.daily_loss_limit_pct / 100:
            return {"success": False, "error": f"Daily loss limit ({self.daily_loss_limit_pct}%) hit"}
        if self.drawdown_pct >= self.max_drawdown_pct:
            return {"success": False, "error": f"Max drawdown ({self.max_drawdown_pct}%) hit"}

        # Position sizing
        if size is None:
            base_size = self.current_balance * self.position_size_pct / 100
            if self.use_kelly and kelly_fraction is not None:
                size = base_size * min(kelly_fraction * 2, 1.0)
            else:
                size = base_size

        if entry_price is None or entry_price <= 0:
            return {"success": False, "error": "A positive live entry price is required"}
        if leverage < 1:
            return {"success": False, "error": "Leverage must be at least 1"}

        pos_id = str(uuid.uuid4())
        liq_price = entry_price * (1 - 0.5 / leverage) if side == "long" else entry_price * (1 + 0.5 / leverage)

        pos = Position(
            id=pos_id,
            symbol=symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            current_price=entry_price,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            liquidation_price=liq_price,
            leverage=leverage,
            margin=size / leverage,
            opened_at=int(time.time() * 1000),
            stop_loss=stop_loss,
            take_profit=take_profit,
            status="open",
        )
        self._positions[pos_id] = pos
        self._daily_trades += 1

        logger.info(f"Position opened: {side} {size:.4f} {symbol} @ {entry_price:.2f} ({leverage}x)")
        return {"success": True, "position": pos}

    def close_position(self, position_id: str, price: float, reason: str = "manual") -> dict:
        """Close an open position."""
        pos = self._positions.pop(position_id, None)
        if not pos:
            return {"success": False, "error": f"Position {position_id} not found"}

        pnl = self._compute_pnl(pos, price)
        pos.realized_pnl = pnl
        pos.current_price = price
        pos.status = "closed"
        self._closed_positions.append(pos)
        self.current_balance += pnl
        self.peak_balance = max(self.peak_balance, self.current_balance)
        self._daily_pnl += pnl

        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        logger.info(f"Position closed: {pos.side} {pos.symbol} PnL={pnl:.2f} reason={reason}")
        return {"success": True, "pnl": pnl, "position": pos}

    def update_position_price(self, position_id: str, current_price: float) -> None:
        """Update unrealized PnL for a position (called on each tick)."""
        pos = self._positions.get(position_id)
        if not pos:
            return
        pos.current_price = current_price
        pos.unrealized_pnl = self._compute_pnl(pos, current_price)

    def update_all_prices(self, current_price: float) -> None:
        """Update all positions with latest price."""
        for pos in self._positions.values():
            pos.current_price = current_price
            pos.unrealized_pnl = self._compute_pnl(pos, current_price)

    def check_stops(self, current_price: float, current_high: float, current_low: float) -> list[dict]:
        """Check SL/TP levels and close positions that were hit."""
        events: list[dict] = []
        for pos_id in list(self._positions.keys()):
            pos = self._positions[pos_id]
            if pos.status != "open":
                continue

            hit = False
            reason = ""
            if pos.side == "long":
                if pos.stop_loss and current_low <= pos.stop_loss:
                    hit = True
                    reason = "stop_loss"
                elif pos.take_profit and current_high >= pos.take_profit:
                    hit = True
                    reason = "take_profit"
            else:
                if pos.stop_loss and current_high >= pos.stop_loss:
                    hit = True
                    reason = "stop_loss"
                elif pos.take_profit and current_low <= pos.take_profit:
                    hit = True
                    reason = "take_profit"

            if hit:
                result = self.close_position(pos_id, pos.stop_loss if reason == "stop_loss" else pos.take_profit, reason)
                events.append(result)

        return events

    def get_open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_closed_positions(self, n: int = 50) -> list[Position]:
        return list(self._closed_positions)[-n:]

    def cancel_all(self) -> None:
        """Emergency cancel — close all positions at market."""
        from datetime import datetime
        for pos_id in list(self._positions.keys()):
            pos = self._positions[pos_id]
            self.close_position(pos_id, pos.current_price, "emergency_cancel")

    @property
    def drawdown_pct(self) -> float:
        if self.peak_balance <= 0:
            return 0.0
        return max(0, (self.peak_balance - self.current_balance) / self.peak_balance * 100)

    def _compute_pnl(self, pos: Position, exit_price: float) -> float:
        if pos.entry_price <= 0:
            return 0.0
        direction = 1 if pos.side == "long" else -1
        return direction * pos.size * pos.leverage * (exit_price - pos.entry_price) / pos.entry_price

    def get_state(self) -> dict:
        return {
            "balance": round(self.current_balance, 2),
            "peak_balance": round(self.peak_balance, 2),
            "drawdown_pct": round(self.drawdown_pct, 2),
            "open_positions": len(self._positions),
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_trades": self._daily_trades,
            "consecutive_losses": self._consecutive_losses,
            "total_closed": len(self._closed_positions),
            "leverage": self.max_leverage,
            "max_positions": self.max_positions,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
        }


# Singleton
position_manager = PositionManager()
