from __future__ import annotations

import uuid
from typing import Any

from backend.models.types import Candle, TradeSignal
from backend.storage import repository as repo


class PaperTradingEngine:
    """Simulated trade execution engine that tracks positions, P&L, and risk in real-time."""

    def __init__(self, initial_balance: float = 10_000.0, max_concurrent: int = 3):
        self.initial_balance = initial_balance
        self.max_concurrent = max_concurrent

    def evaluate_signals(self, signals: list[TradeSignal], candle: Candle,
                         symbol: str = "BTC/USDT", timeframe: str = "5m") -> list[dict]:
        open_trades = repo.get_paper_trades(status="open")
        events: list[dict] = []
        balance = self._current_balance()

        for sig in signals:
            if sig.status not in ("open", "pending"):
                continue
            if len([t for t in open_trades if t["status"] == "open"]) >= self.max_concurrent:
                continue

            risk_per_trade = balance * 0.02
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            qty = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0.001

            trade = {
                "id": str(uuid.uuid4()),
                "signal_id": sig.id,
                "symbol": symbol,
                "timeframe": timeframe,
                "side": sig.side,
                "entry_price": sig.entry,
                "stop_loss": sig.stop_loss,
                "take_profit": sig.exit_price,
                "quantity": round(qty, 6),
                "timestamp": sig.timestamp,
                "opened_at": sig.timestamp,
                "status": "open",
                "confidence": sig.confidence,
                "risk_reward": sig.risk_reward,
                "reason": sig.reason,
            }
            repo.save_paper_trade(trade)
            events.append({"type": "trade_opened", "trade": trade})

        for trade in open_trades:
            if trade["status"] != "open":
                continue
            side = trade["side"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp = trade["take_profit"]
            qty = trade["quantity"]

            if side == "buy":
                hit_stop = candle.low <= sl
                hit_target = candle.high >= tp
            else:
                hit_stop = candle.high >= sl
                hit_target = candle.low <= tp

            if hit_stop or hit_target:
                exit_price = sl if hit_stop else tp
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                pnl_pct = pnl / (entry * qty) * 100 if entry * qty else 0
                reason = "stop_loss" if hit_stop else "target_hit"
                repo.close_paper_trade(trade["id"], exit_price, round(pnl, 2),
                                       round(pnl_pct, 4), reason)
                events.append({
                    "type": "trade_closed",
                    "trade_id": trade["id"],
                    "exit_price": exit_price,
                    "pnl": round(pnl, 2),
                    "reason": reason,
                })

        return events

    def _current_balance(self) -> float:
        stats = repo.get_paper_trade_stats()
        closed_pnl = stats["total_pnl"]
        open_trades = repo.get_paper_trades(status="open")
        open_risk = sum(
            abs(t["entry_price"] - t["stop_loss"]) * t["quantity"]
            for t in open_trades
        )
        return self.initial_balance + closed_pnl - open_risk
