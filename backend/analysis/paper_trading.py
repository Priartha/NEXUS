"""
Paper Trading Engine for NEXUS - v3.0

NEW FEATURES:
- Slippage simulation (volume-based)
- Funding rate tracking for perpetual positions
- RiskManager integration (blocks trades that violate risk rules)
- Market impact estimation
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from backend.analysis.profitability_guard import evaluate_profitability_artifact
from backend.analysis.risk_manager import RiskManager
from backend.analysis.self_aware_agent import get_agent
from backend.models.types import Candle, TradeSignal
from backend.storage import repository as repo

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """Simulated trade execution with realistic costs and risk enforcement."""

    enabled: bool = True

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        max_concurrent: int = 1,
        min_confidence: float = 0.55,
        max_daily_trades: int = 5,
        max_daily_loss_pct: float = 0.03,
        cooldown_after_losses: int = 3,
        cooldown_minutes: int = 90,
        risk_per_trade_pct: float = 0.02,
        trailing_atr_multiplier: float = 2.0,
        breakeven_at_r: float = 1.5,
        slippage_pct: float = 0.0001,
        commission_pct: float = 0.0002,
        funding_rate_per_8h: float = 0.0001,
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
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct
        self.funding_rate_per_8h = funding_rate_per_8h
        self.risk_manager = RiskManager(initial_balance=initial_balance)

    def evaluate_signals(
        self,
        signals: list[TradeSignal],
        candle: Candle,
        symbol: str = "BTC/USDT",
        timeframe: str = "5m",
        mtf_confluence: dict | None = None,
    ) -> list[dict]:
        if not self.enabled:
            return []

        open_trades = repo.get_paper_trades(status="open")
        events: list[dict] = []

        exit_events = self._check_exits(open_trades, candle)
        events.extend(exit_events)

        open_trades = repo.get_paper_trades(status="open")

        gate = evaluate_profitability_artifact()
        if not gate.allowed:
            events.append({
                "type": "trade_blocked",
                "reason": "profitability_validation",
                "blockers": gate.blockers,
            })
            return events

        qualified = [s for s in signals if s.confidence >= self.min_confidence and s.status in ("open", "pending", "active")]
        if not qualified:
            return events

        open_count = len([t for t in open_trades if t["status"] == "open"])
        if open_count >= self.max_concurrent:
            return events

        # Prevent duplicate entries from the same signal
        open_signal_ids = {t.get("signal_id") for t in open_trades if t["status"] == "open"}
        qualified = [s for s in qualified if s.id not in open_signal_ids]
        if not qualified:
            return events

        now_ms = int(time.time() * 1000)
        day_ago_ms = now_ms - 24 * 60 * 60 * 1000
        today_trades = [t for t in repo.get_paper_trades(status="closed") if t.get("exit_timestamp", 0) >= day_ago_ms]
        if len(today_trades) >= self.max_daily_trades:
            return events

        if self._hit_daily_loss_limit():
            return events

        if self._is_in_cooldown():
            return events

        best = max(qualified, key=lambda s: s.confidence)

        current_balance = self._current_balance()
        risk_amount = current_balance * self.risk_per_trade_pct
        allowed, blockers = self.risk_manager.can_open_trade(
            signal_confidence=best.confidence,
            risk_amount=risk_amount,
            symbol=symbol,
        )
        if not allowed:
            events.append({
                "type": "trade_blocked",
                "reason": "risk_manager",
                "blockers": blockers,
                "signal_id": best.id,
            })
            return events

        balance = self._current_balance()
        risk_per_trade = balance * self.risk_per_trade_pct
        risk_per_unit = abs(best.entry - best.stop_loss)
        qty = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0.001

        slippage = self._compute_slippage(best.entry, qty, candle)
        entry_with_slippage = best.entry + slippage if best.side == "buy" else best.entry - slippage

        notional = entry_with_slippage * qty
        commission = notional * self.commission_pct

        trade = {
            "id": str(uuid.uuid4()),
            "signal_id": best.id,
            "symbol": symbol,
            "timeframe": timeframe,
            "side": best.side,
            "entry_price": round(entry_with_slippage, 2),
            "raw_entry": best.entry,
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
            "slippage_pct": round(slippage / best.entry * 100 if best.entry > 0 else 0, 4),
            "commission": round(commission, 2),
            "funding_rate": self.funding_rate_per_8h,
            "enriched_features": getattr(best, 'enriched_features', None),
        }
        repo.save_paper_trade(trade)
        events.append({"type": "trade_opened", "trade": trade})

        return events

    def _compute_slippage(self, entry: float, qty: float, candle: Candle) -> float:
        """FIX: Volume-based slippage simulation.
        Larger orders relative to candle volume get worse fills."""
        base_slippage = entry * self.slippage_pct

        if candle.volume > 0:
            volume_impact = min(qty / candle.volume, 0.1)
            slippage_multiplier = 1.0 + volume_impact * 5.0
        else:
            slippage_multiplier = 1.0

        candle_range = candle.high - candle.low
        if candle_range > 0 and entry > 0:
            range_pct = candle_range / entry
            range_multiplier = 1.0 + range_pct * 2.0
        else:
            range_multiplier = 1.0

        return base_slippage * slippage_multiplier * range_multiplier

    def _check_exits(self, open_trades: list[dict], candle: Candle) -> list[dict]:
        events: list[dict] = []
        now_ms = int(time.time() * 1000)
        for trade in open_trades:
            if trade["status"] != "open":
                continue
            side = trade["side"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp = trade["take_profit"]
            qty = trade["quantity"]
            atr = trade.get("atr_at_entry", 0) or abs(entry - trade.get("initial_stop", entry)) * 0.67

            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held
            repo.update_paper_trade(trade["id"], {"bars_held": bars_held})
            if bars_held <= 1:
                continue

            # ── TIME-BASED EXIT: enforce max hold ──
            hold_minutes = (now_ms - trade.get("opened_at", now_ms)) / 60000
            max_hold = trade.get("max_hold_minutes", 30)
            if hold_minutes > max_hold:
                exit_price = candle.close
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                commission = trade.get("commission", 0)
                funding_cost = self.funding_rate_per_8h * entry * qty
                pnl -= commission + funding_cost
                pnl_pct = pnl / (entry * qty) * 100 if entry * qty else 0
                repo.close_paper_trade(trade["id"], exit_price, round(pnl, 2), round(pnl_pct, 4), "max_hold_exceeded")
                self.risk_manager.record_trade_result(pnl)
                events.append({
                    "type": "trade_closed",
                    "trade_id": trade["id"],
                    "trade": {**trade, "exit_price": exit_price, "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 4)},
                    "exit_price": exit_price,
                    "pnl": round(pnl, 2),
                    "reason": "max_hold_exceeded",
                })
                continue

            funding_cost = self.funding_rate_per_8h * entry * qty

            if side == "buy":
                highest = max(trade.get("highest_price", entry), candle.high)
                trade["highest_price"] = highest
                # Wider trailing: use 2.0x ATR instead of 1.0x to avoid noise stops
                if self.trailing_atr_multiplier > 0 and highest > entry:
                    profit_r = (highest - entry) / max(abs(entry - trade.get("initial_stop", sl)), 1e-10)
                    if profit_r >= self.breakeven_at_r:
                        trailing_stop = highest - atr * max(self.trailing_atr_multiplier, 2.0)
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
                        trailing_stop = lowest + atr * max(self.trailing_atr_multiplier, 2.0)
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
                commission = trade.get("commission", 0)
                pnl -= commission + funding_cost
                pnl_pct = pnl / (entry * qty) * 100 if entry * qty else 0
                reason = "stop_loss" if hit_stop else "target_hit"
                repo.close_paper_trade(trade["id"], exit_price, round(pnl, 2), round(pnl_pct, 4), reason)

                try:
                    enriched_features = trade.get("enriched_features")
                    get_agent().record_trade_outcome(
                        signal={
                            "signal": side.upper(),
                            "entry": entry,
                            "pattern_type": f"{side}_{reason}",
                            "features": {
                                "atr_pct": trade.get("atr_at_entry", 0),
                                "confidence": trade.get("confidence", 0),
                                "risk_reward": trade.get("risk_reward", 0),
                                **(enriched_features if isinstance(enriched_features, dict) else {}),
                            },
                            "enriched_features": enriched_features if isinstance(enriched_features, dict) else None,
                            "regime": "unknown",
                            "reason": trade.get("reason", ""),
                        },
                        exit_price=exit_price,
                        won=pnl > 0,
                        pnl_pct=round(pnl_pct, 4),
                    )
                except Exception:
                    logger.exception("Failed to record AI agent trade outcome")

                try:
                    from backend.analysis.model_tracker import model_tracker
                    model_tracker.record_outcome(
                        signal_id=trade.get("signal_id", ""),
                        actual_direction=side,
                        actual_return=round(pnl_pct / 100.0, 4),
                        hold_period_bars=trade.get("bars_held", 0),
                    )
                except Exception:
                    logger.exception("Failed to record model tracker outcome")

                self.risk_manager.record_trade_result(pnl)

                events.append({
                    "type": "trade_closed",
                    "trade_id": trade["id"],
                    "trade": {
                        **trade,
                        "status": "closed",
                        "exit_price": exit_price,
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 4),
                        "close_reason": reason,
                    },
                    "exit_price": exit_price,
                    "pnl": round(pnl, 2),
                    "funding_cost": round(funding_cost, 2),
                    "reason": reason,
                })
        return events

    def _is_in_cooldown(self) -> bool:
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
        now_ms = int(time.time() * 1000)
        day_ago_ms = now_ms - 24 * 60 * 60 * 1000
        closed = [t for t in repo.get_paper_trades(status="closed") if t.get("exit_timestamp", 0) >= day_ago_ms]
        daily_pnl = sum(t.get("pnl", 0) for t in closed)
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
