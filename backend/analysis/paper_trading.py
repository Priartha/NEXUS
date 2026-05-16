from __future__ import annotations

import time
import uuid
from typing import Any

from backend.models.types import Candle, TradeSignal
from backend.storage import repository as repo


class PaperTradingEngine:
    """Simulated trade execution engine with strict quality gates.
    Only trades high-confidence setups, auto-pauses after losses.
    Features: ATR trailing stops, dynamic position sizing, max daily loss limit."""

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        max_concurrent: int = 1,
        min_confidence: float = 0.60,
        max_daily_trades: int = 5,
        max_daily_loss_pct: float = 0.03,
        cooldown_after_losses: int = 3,
        cooldown_minutes: int = 90,
        risk_per_trade_pct: float = 0.02,
        trailing_atr_multiplier: float = 1.0,
        breakeven_at_r: float = 1.0,
    ):
        self.initial_balance = initial_balance
        self.max_concurrent = max_concurrent
        self.min_confidence = min_confidence
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct
        self.cooldown_after_losses = cooldown_after_losses
        self.cooldown_minutes = cooldown_minutes
        self.risk_per_trade_pct = risk_per_trade_pct
        self.trailing_atr_multiplier = trailing_atr_multiplier
        self.breakeven_at_r = breakeven_at_r

    def evaluate_signals(
        self,
        signals: list[TradeSignal],
        candle: Candle,
        symbol: str = "BTC/USDT",
        timeframe: str = "5m",
    ) -> list[dict]:
        open_trades = repo.get_paper_trades(status="open")
        events: list[dict] = []

        # Check exits and trailing stops first
        exit_events = self._check_exits(open_trades, candle)
        events.extend(exit_events)

        # Refresh open trades after exits
        open_trades = repo.get_paper_trades(status="open")

        # Quality gate: skip if confidence below threshold
        qualified = [s for s in signals if s.confidence >= self.min_confidence and s.status in ("open", "pending")]
        if not qualified:
            return events

        # Quality gate: max concurrent positions
        open_count = len([t for t in open_trades if t["status"] == "open"])
        if open_count >= self.max_concurrent:
            return events

        # Quality gate: max daily trades
        now_ms = int(time.time() * 1000)
        day_ago_ms = now_ms - 24 * 60 * 60 * 1000
        today_trades = [t for t in repo.get_paper_trades(status="closed") if t.get("exit_timestamp", 0) >= day_ago_ms]
        if len(today_trades) >= self.max_daily_trades:
            return events

        # Quality gate: max daily loss limit
        if self._hit_daily_loss_limit():
            return events

        # Quality gate: cooldown after consecutive losses
        if self._is_in_cooldown():
            return events

        # Open new trade with strongest signal
        best = max(qualified, key=lambda s: s.confidence)
        balance = self._current_balance()
        risk_per_trade = balance * self.risk_per_trade_pct
        risk_per_unit = abs(best.entry - best.stop_loss)
        qty = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0.001

        trade = {
            "id": str(uuid.uuid4()),
            "signal_id": best.id,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": best.side,
            "entry_price": best.entry,
            "stop_loss": best.stop_loss,
            "initial_stop": best.stop_loss,
            "take_profit": best.exit_price,
            "quantity": round(qty, 6),
            "timestamp": best.timestamp,
            "opened_at": now_ms,
            "status": "open",
            "confidence": best.confidence,
            "risk_reward": best.risk_reward,
            "reason": best.reason,
            "highest_price": best.entry if best.side == "buy" else None,
            "lowest_price": best.entry if best.side == "sell" else None,
            "atr_at_entry": best.expected_move if best.expected_move else 0,
        }
        repo.save_paper_trade(trade)
        events.append({"type": "trade_opened", "trade": trade})

        return events

    def _check_exits(self, open_trades: list[dict], candle: Candle) -> list[dict]:
        """Check exits: stop loss, take profit, and ATR trailing stops."""
        events: list[dict] = []
        for trade in open_trades:
            if trade["status"] != "open":
                continue
            side = trade["side"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp = trade["take_profit"]
            qty = trade["quantity"]
            atr = trade.get("atr_at_entry", 0) or abs(entry - trade.get("initial_stop", entry)) * 0.67

            # Track highest/lowest for trailing
            if side == "buy":
                highest = max(trade.get("highest_price", entry), candle.high)
                trade["highest_price"] = highest
                # ATR trailing stop: move stop up as price moves in our favor
                if self.trailing_atr_multiplier > 0 and highest > entry:
                    profit_r = (highest - entry) / max(abs(entry - trade.get("initial_stop", sl)), 1e-10)
                    if profit_r >= self.breakeven_at_r:
                        trailing_stop = highest - atr * self.trailing_atr_multiplier
                        new_sl = max(sl, trailing_stop)
                        if new_sl > sl:
                            trade["stop_loss"] = new_sl
                            sl = new_sl
                            events.append({"type": "trailing_stop_updated", "trade_id": trade["id"], "new_sl": new_sl})

                hit_stop = candle.low <= sl
                hit_target = candle.high >= tp
            else:
                lowest = min(trade.get("lowest_price", entry), candle.low)
                trade["lowest_price"] = lowest
                if self.trailing_atr_multiplier > 0 and lowest < entry:
                    profit_r = (entry - lowest) / max(abs(entry - trade.get("initial_stop", sl)), 1e-10)
                    if profit_r >= self.breakeven_at_r:
                        trailing_stop = lowest + atr * self.trailing_atr_multiplier
                        new_sl = min(sl, trailing_stop)
                        if new_sl < sl:
                            trade["stop_loss"] = new_sl
                            sl = new_sl
                            events.append({"type": "trailing_stop_updated", "trade_id": trade["id"], "new_sl": new_sl})

                hit_stop = candle.high >= sl
                hit_target = candle.low <= tp

            if hit_stop or hit_target:
                exit_price = sl if hit_stop else tp
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                pnl_pct = pnl / (entry * qty) * 100 if entry * qty else 0
                reason = "stop_loss" if hit_stop else "target_hit"
                repo.close_paper_trade(trade["id"], exit_price, round(pnl, 2), round(pnl_pct, 4), reason)
                events.append({
                    "type": "trade_closed",
                    "trade_id": trade["id"],
                    "exit_price": exit_price,
                    "pnl": round(pnl, 2),
                    "reason": reason,
                })
        return events

    def _is_in_cooldown(self) -> bool:
        """Pause trading after N consecutive losses to prevent revenge trading."""
        closed = [t for t in repo.get_paper_trades(status="closed") if t.get("exit_timestamp")]
        if not closed:
            return False
        closed.sort(key=lambda t: t.get("exit_timestamp", 0), reverse=True)
        consecutive_losses = 0
        for t in closed:
            if t.get("pnl", 0) <= 0:
                consecutive_losses += 1
            else:
                break
        if consecutive_losses >= self.cooldown_after_losses:
            last_exit_ts = closed[0].get("exit_timestamp", 0)
            now_ms = int(time.time() * 1000)
            minutes_since = (now_ms - last_exit_ts) / (1000 * 60)
            return minutes_since < self.cooldown_minutes
        return False

    def _hit_daily_loss_limit(self) -> bool:
        """Stop trading if daily losses exceed threshold."""
        now_ms = int(time.time() * 1000)
        day_ago_ms = now_ms - 24 * 60 * 60 * 1000
        closed = [t for t in repo.get_paper_trades(status="closed") if t.get("exit_timestamp", 0) >= day_ago_ms]
        daily_pnl = sum(t.get("pnl", 0) for t in closed)
        balance = self._current_balance()
        max_loss = self.initial_balance * self.max_daily_loss_pct
        return daily_pnl <= -max_loss

    def _current_balance(self) -> float:
        stats = repo.get_paper_trade_stats()
        closed_pnl = stats["total_pnl"]
        open_trades = repo.get_paper_trades(status="open")
        open_risk = sum(
            abs(t["entry_price"] - t["stop_loss"]) * t["quantity"]
            for t in open_trades
        )
        return self.initial_balance + closed_pnl - open_risk
