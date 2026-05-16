from __future__ import annotations

import math
import time
import uuid
from collections import deque
from typing import Any

from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_structure import detect_structure
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.regime import detect_market_regime
from backend.analysis.signals import detect_trade_signals
from backend.analysis.swing_detector import detect_swings
from backend.models.types import Candle


class BacktestEngine:
    """Walk-forward backtesting engine that replays historical candles through the analysis pipeline."""

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        position_size_pct: float = 0.02,
        max_concurrent: int = 1,
        slippage_pct: float = 0.0002,  # 0.02% slippage per trade
        commission_pct: float = 0.0004,  # 0.04% commission (round trip)
        max_hold_bars: int = 25,  # Max bars to hold a trade
        breakeven_threshold: float = 1.0,  # Move SL to breakeven after 1R profit
    ):
        self.initial_balance = float(initial_balance)
        self.position_size_pct = float(position_size_pct)
        self.max_concurrent = max_concurrent
        self.slippage_pct = float(slippage_pct)
        self.commission_pct = float(commission_pct)
        self.max_hold_bars = max_hold_bars
        self.breakeven_threshold = breakeven_threshold

    def run(
        self,
        candles: list[Candle],
        symbol: str = "BTC/USDT",
        timeframe: str = "5m",
    ) -> dict:
        candles = sorted(candles, key=lambda c: c.timestamp)
        results: list[dict] = []
        equity: list[dict] = []
        balance = self.initial_balance
        peak = balance
        peak_ts = candles[0].timestamp if candles else 0
        open_trades: list[dict] = []

        swings: list[Any] = []
        fvgs: list[Any] = []
        order_blocks: list[Any] = []
        liquidity: list[Any] = []
        liquidity_events: list[Any] = []
        metrics = None

        lookback = 80
        min_candles = max(lookback, 50)
        last_signal_ts = 0

        for i in range(min_candles, len(candles)):
            window = candles[:i + 1]
            recent = window[-lookback:]
            current = candles[i]

            swings = detect_swings(window)[-250:]
            fvgs = detect_fvgs(recent)
            order_blocks = detect_order_blocks(recent, swings)
            liquidity = detect_equal_levels(swings)

            for c in recent:
                fvgs = update_fvg_fills(fvgs, c)
                order_blocks = update_order_block_breakers(order_blocks, c)
                liquidity = check_liquidity_sweeps(liquidity, c)

            metrics = compute_market_metrics(window, swings)
            atr = metrics.atr14 if metrics else 0.0
            liquidity_events = detect_liquidity_events(recent, liquidity, atr)[-80:]
            structure = detect_structure(swings, window)
            regime = detect_market_regime(window, metrics, liquidity_events)

            # Detect signals with full ICT confluence
            signals = detect_trade_signals(
                candles=window,
                metrics=metrics,
                fvgs=fvgs,
                order_blocks=order_blocks,
                liquidity_events=liquidity_events,
                swings=swings,
            )

            # Filter: only new signals not already processed
            new_signals = [s for s in signals if s.timestamp > last_signal_ts]
            last_signal_ts = max((s.timestamp for s in signals), default=last_signal_ts)

            for sig in new_signals:
                if len([t for t in open_trades if t["status"] == "open"]) >= self.max_concurrent:
                    continue
                if sig.confidence < 0.50:
                    continue

                risk_per_trade = balance * self.position_size_pct
                risk_per_unit = abs(sig.entry - sig.stop_loss)
                quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0

                # Apply slippage to entry
                slippage = sig.entry * self.slippage_pct
                entry_with_slippage = sig.entry + slippage if sig.side == "buy" else sig.entry - slippage

                # Apply commission
                notional = entry_with_slippage * quantity
                commission = notional * self.commission_pct

                tp = sig.exit_price
                trade = {
                    "id": str(uuid.uuid4()),
                    "signal_id": sig.id,
                    "timestamp": sig.timestamp,
                    "side": sig.side,
                    "entry_price": round(entry_with_slippage, 2),
                    "raw_entry": sig.entry,
                    "stop_loss": sig.stop_loss,
                    "initial_sl": sig.stop_loss,
                    "take_profit": tp,
                    "quantity": quantity,
                    "status": "open",
                    "confidence": sig.confidence,
                    "reason": sig.reason,
                    "risk_reward": sig.risk_reward,
                    "slippage": round(slippage, 2),
                    "commission": round(commission, 2),
                    "bars_held": 0,
                }
                open_trades.append(trade)

            for trade in list(open_trades):
                if trade["status"] != "open":
                    continue
                side = trade["side"]
                entry = trade["entry_price"]
                sl = trade["stop_loss"]
                tp = trade["take_profit"]
                qty = trade["quantity"]
                bars_held = trade.get("bars_held", 0) + 1
                trade["bars_held"] = bars_held

                # ── Trailing stop: move to breakeven after 1R profit ──
                risk = abs(entry - trade.get("initial_sl", sl))
                if risk > 0:
                    if side == "buy":
                        profit_r = (current.high - entry) / risk
                        if profit_r >= self.breakeven_threshold:
                            trade["stop_loss"] = max(trade["stop_loss"], entry)
                            sl = trade["stop_loss"]
                    else:
                        profit_r = (entry - current.low) / risk
                        if profit_r >= self.breakeven_threshold:
                            trade["stop_loss"] = min(trade["stop_loss"], entry)
                            sl = trade["stop_loss"]

                # ── Time-based exit ──
                if bars_held >= self.max_hold_bars:
                    exit_price = current.close
                    pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                    pnl -= trade["commission"]
                    pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["pnl"] = round(pnl, 2)
                    trade["pnl_pct"] = round(pnl_pct, 4)
                    trade["close_reason"] = "time_exit"
                    balance += pnl
                    results.append(dict(trade))
                    continue

                if side == "buy":
                    hit_stop = current.low <= sl
                    hit_target = current.high >= tp
                else:
                    hit_stop = current.high >= sl
                    hit_target = current.low <= tp

                if hit_stop:
                    exit_price = sl
                    pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                    pnl -= trade["commission"]
                    pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["pnl"] = round(pnl, 2)
                    trade["pnl_pct"] = round(pnl_pct, 4)
                    trade["close_reason"] = "stop_loss"
                    balance += pnl
                    results.append(dict(trade))

                elif hit_target:
                    exit_price = tp
                    pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                    pnl -= trade["commission"]
                    pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["pnl"] = round(pnl, 2)
                    trade["pnl_pct"] = round(pnl_pct, 4)
                    trade["close_reason"] = "target_hit"
                    balance += pnl
                    results.append(dict(trade))

            if balance > peak:
                peak = balance
                peak_ts = current.timestamp
            dd = peak - balance
            dd_pct = dd / peak * 100 if peak > 0 else 0

            if i % 5 == 0 or i == len(candles) - 1:
                equity.append({
                    "timestamp": current.timestamp,
                    "account_balance": round(balance, 2),
                    "drawdown": round(dd, 2),
                    "drawdown_pct": round(dd_pct, 4),
                })

        total_pnl = balance - self.initial_balance
        total_pnl_pct = (total_pnl / self.initial_balance) * 100
        closed = [r for r in results if r.get("exit_price") is not None]
        wins = [r for r in closed if r.get("pnl", 0) > 0]
        losses = [r for r in closed if r.get("pnl", 0) <= 0]

        max_dd = max((e["drawdown_pct"] for e in equity), default=0)
        max_dd_val = max((e["drawdown"] for e in equity), default=0)
        avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(r["pnl"] for r in losses) / len(losses)) if losses else 0
        profit_factor = 0.0
        if wins and losses:
            gross_profit = sum(r["pnl"] for r in wins)
            gross_loss = abs(sum(r["pnl"] for r in losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        elif wins:
            profit_factor = float("inf")

        returns = [e["account_balance"] / self.initial_balance - 1 for e in equity]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_returns = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0
        sharpe = (avg_return / std_returns * math.sqrt(365)) if std_returns > 0 else 0

        # Consecutive losses analysis
        max_consecutive_losses = 0
        current_consecutive = 0
        for r in closed:
            if r.get("pnl", 0) <= 0:
                current_consecutive += 1
                max_consecutive_losses = max(max_consecutive_losses, current_consecutive)
            else:
                current_consecutive = 0

        return {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "timeframe": timeframe,
            "start_date": candles[0].timestamp if candles else 0,
            "end_date": candles[-1].timestamp if candles else 0,
            "candle_count": len(candles),
            "initial_balance": self.initial_balance,
            "final_balance": round(balance, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "total_trades": len(closed),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(closed), 4) if closed else 0,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.99,
            "max_drawdown": round(max_dd_val, 2),
            "max_drawdown_pct": round(max_dd, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_consecutive_losses": max_consecutive_losses,
            "slippage_pct": self.slippage_pct,
            "commission_pct": self.commission_pct,
            "trades": results,
            "equity_curve": equity,
        }
