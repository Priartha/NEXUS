"""
Improved backtest engine with partial profit taking and dynamic exits.

Features:
1. Partial profit taking: 50% at 1R, 50% at 2R
2. Dynamic breakeven: Move SL to BE at 0.75R
3. Time-based exit with trailing
4. Better position sizing based on confidence
"""

from __future__ import annotations

import math
import uuid
from typing import Any

from backend.models.types import Candle


class ImprovedBacktestEngine:
    """Backtest engine with partial profit taking and improved exits."""

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        position_size_pct: float = 0.02,
        max_concurrent: int = 1,
        slippage_pct: float = 0.0002,
        commission_pct: float = 0.0004,
        max_hold_bars: int = 25,
        breakeven_threshold: float = 0.75,  # Move to BE at 0.75R
        partial_tp1_r: float = 1.0,  # Take 50% at 1R
        partial_tp2_r: float = 2.0,  # Take 50% at 2R
        confidence_sizing: bool = True,  # Size positions based on confidence
    ):
        self.initial_balance = float(initial_balance)
        self.position_size_pct = float(position_size_pct)
        self.max_concurrent = max_concurrent
        self.slippage_pct = float(slippage_pct)
        self.commission_pct = float(commission_pct)
        self.max_hold_bars = max_hold_bars
        self.breakeven_threshold = breakeven_threshold
        self.partial_tp1_r = partial_tp1_r
        self.partial_tp2_r = partial_tp2_r
        self.confidence_sizing = confidence_sizing

    def run(
        self,
        candles: list[Candle],
        signals: list[dict],  # Pre-computed signals
        symbol: str = "BTC/USDT",
        timeframe: str = "5m",
    ) -> dict:
        """Run backtest with pre-computed signals."""
        candles = sorted(candles, key=lambda c: c.timestamp)
        
        # Build signal lookup by timestamp
        signal_map = {}
        for sig in signals:
            ts = sig["timestamp"]
            if ts not in signal_map:
                signal_map[ts] = []
            signal_map[ts].append(sig)
        
        results = []
        equity = []
        balance = self.initial_balance
        peak = balance
        open_trades = []

        min_candles = 80
        last_signal_ts = 0

        for i in range(min_candles, len(candles)):
            current = candles[i]
            
            # Check for new signals
            if current.timestamp in signal_map:
                for sig in signal_map[current.timestamp]:
                    if sig["timestamp"] <= last_signal_ts:
                        continue
                    
                    if len([t for t in open_trades if t["status"] == "open"]) >= self.max_concurrent:
                        continue
                    
                    if sig["confidence"] < 0.40:
                        continue
                    
                    # Position sizing based on confidence
                    if self.confidence_sizing:
                        size_multiplier = sig["confidence"] / 0.50  # Scale around 50% confidence
                        size_multiplier = max(0.5, min(size_multiplier, 1.0))  # Clamp 0.5x to 1.0x (never exceed base risk)
                    else:
                        size_multiplier = 1.0
                    
                    risk_per_trade = balance * self.position_size_pct * size_multiplier
                    risk_per_unit = abs(sig["entry"] - sig["stop_loss"])
                    quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0
                    
                    # Apply slippage
                    slippage = sig["entry"] * self.slippage_pct
                    entry_with_slippage = sig["entry"] + slippage if sig["side"] == "buy" else sig["entry"] - slippage
                    
                    # Apply commission
                    notional = entry_with_slippage * quantity
                    commission = notional * self.commission_pct
                    
                    # Calculate partial TP levels
                    risk = abs(entry_with_slippage - sig["stop_loss"])
                    tp1 = entry_with_slippage + (risk * self.partial_tp1_r) if sig["side"] == "buy" else entry_with_slippage - (risk * self.partial_tp1_r)
                    tp2 = entry_with_slippage + (risk * self.partial_tp2_r) if sig["side"] == "buy" else entry_with_slippage - (risk * self.partial_tp2_r)
                    
                    trade = {
                        "id": str(uuid.uuid4()),
                        "signal_id": sig.get("id", ""),
                        "timestamp": sig["timestamp"],
                        "side": sig["side"],
                        "entry_price": round(entry_with_slippage, 2),
                        "stop_loss": sig["stop_loss"],
                        "initial_sl": sig["stop_loss"],
                        "tp1": round(tp1, 2),
                        "tp2": round(tp2, 2),
                        "quantity": quantity,
                        "remaining_qty": quantity,
                        "status": "open",
                        "confidence": sig["confidence"],
                        "reason": sig.get("reason", ""),
                        "slippage": round(slippage, 2),
                        "commission": round(commission, 2),
                        "bars_held": 0,
                        "tp1_hit": False,
                        "tp1_pnl": 0.0,
                        "total_pnl": 0.0,
                    }
                    open_trades.append(trade)
                    last_signal_ts = max(last_signal_ts, sig["timestamp"])
            
            # Process open trades
            for trade in list(open_trades):
                if trade["status"] != "open":
                    continue
                
                side = trade["side"]
                entry = trade["entry_price"]
                sl = trade["stop_loss"]
                tp1 = trade["tp1"]
                tp2 = trade["tp2"]
                qty = trade["remaining_qty"]
                bars_held = trade.get("bars_held", 0) + 1
                trade["bars_held"] = bars_held
                
                # Move to breakeven after 0.75R profit
                risk = abs(entry - trade.get("initial_sl", sl))
                if risk > 0 and not trade["tp1_hit"]:
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
                
                # Check TP1 (50% position)
                if not trade["tp1_hit"]:
                    half_commission = trade["commission"] * 0.5
                    if side == "buy" and current.high >= tp1:
                        # Close 50% at TP1
                        pnl1 = (tp1 - entry) * (qty * 0.5) - half_commission
                        trade["tp1_hit"] = True
                        trade["tp1_pnl"] = pnl1
                        trade["remaining_qty"] = qty * 0.5
                        trade["total_pnl"] += pnl1
                        balance += pnl1
                    elif side == "sell" and current.low <= tp1:
                        pnl1 = (entry - tp1) * (qty * 0.5) - half_commission
                        trade["tp1_hit"] = True
                        trade["tp1_pnl"] = pnl1
                        trade["remaining_qty"] = qty * 0.5
                        trade["total_pnl"] += pnl1
                        balance += pnl1
                
                # Time-based exit
                if bars_held >= self.max_hold_bars:
                    exit_price = current.close
                    remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                    remaining_pnl -= trade["commission"] * 0.5
                    
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["total_pnl"] += remaining_pnl
                    trade["pnl"] = round(trade["total_pnl"], 2)
                    trade["close_reason"] = "time_exit"
                    balance += remaining_pnl
                    results.append(dict(trade))
                    continue
                
                # Check stop loss (for remaining position)
                if side == "buy":
                    hit_stop = current.low <= sl
                    hit_tp2 = current.high >= tp2
                else:
                    hit_stop = current.high >= sl
                    hit_tp2 = current.low <= tp2
                
                if hit_stop:
                    exit_price = sl
                    remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                    remaining_pnl -= trade["commission"]
                    
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["total_pnl"] += remaining_pnl
                    trade["pnl"] = round(trade["total_pnl"], 2)
                    trade["close_reason"] = "stop_loss"
                    balance += remaining_pnl
                    results.append(dict(trade))
                
                elif hit_tp2:
                    exit_price = tp2
                    remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                    remaining_pnl -= trade["commission"]
                    
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["total_pnl"] += remaining_pnl
                    trade["pnl"] = round(trade["total_pnl"], 2)
                    trade["close_reason"] = "tp2_hit"
                    balance += remaining_pnl
                    results.append(dict(trade))
            
            # Update equity
            if balance > peak:
                peak = balance
            dd = peak - balance
            dd_pct = dd / peak * 100 if peak > 0 else 0
            
            if i % 10 == 0 or i == len(candles) - 1:
                equity.append({
                    "timestamp": current.timestamp,
                    "account_balance": round(balance, 2),
                    "drawdown": round(dd, 2),
                    "drawdown_pct": round(dd_pct, 4),
                })
        
        # Calculate final metrics
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
        sharpe = (avg_return / std_returns * math.sqrt(105120)) if std_returns > 0 else 0
        
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
            "partial_tp1_r": self.partial_tp1_r,
            "partial_tp2_r": self.partial_tp2_r,
            "breakeven_threshold": self.breakeven_threshold,
            "confidence_sizing": self.confidence_sizing,
        }
