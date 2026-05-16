"""
Ultra-fast parameter sweep using pre-computed signals.

1. Generate signals once with default parameters
2. Test different exit/position management configs on the same signals
3. Much faster than recomputing analysis for each config
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle


def load_30d_data() -> list[Candle]:
    """Load 30-day historical data."""
    data_file = Path("historical_data_30d.json")
    if not data_file.exists():
        print("ERROR: historical_data_30d.json not found")
        sys.exit(1)
    
    with open(data_file) as f:
        raw = json.load(f)
    
    candles = []
    for k in raw:
        if isinstance(k, dict):
            candles.append(Candle(
                timestamp=k["timestamp"],
                open=float(k["open"]),
                high=float(k["high"]),
                low=float(k["low"]),
                close=float(k["close"]),
                volume=float(k["volume"]),
            ))
        else:
            candles.append(Candle(
                timestamp=k[0],
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            ))
    
    return candles


def load_signals() -> list[dict]:
    """Load pre-computed signals from file."""
    signal_file = Path("precomputed_signals.json")
    if not signal_file.exists():
        print("ERROR: precomputed_signals.json not found")
        print("Run: python scripts/precompute_signals.py first")
        sys.exit(1)
    
    with open(signal_file) as f:
        return json.load(f)


def backtest_with_signals(candles: list[Candle], signals: list[dict], config: dict) -> dict:
    """Backtest using pre-computed signals with different exit parameters."""
    # Config
    sl_mult = config.get("sl_multiplier", 1.0)  # Multiply original SL distance
    be_thresh = config.get("breakeven_threshold", 0.75)
    tp1_r = config.get("partial_tp1_r", 1.0)
    tp2_r = config.get("partial_tp2_r", 2.0)
    max_hold = config.get("max_hold_bars", 25)
    pos_size_pct = config.get("position_size_pct", 0.02)
    min_conf = config.get("min_confidence", 0.0)
    
    # Build candle lookup by timestamp
    candle_map = {c.timestamp: c for c in candles}
    sorted_timestamps = sorted(candle_map.keys())
    
    # State
    balance = 10000.0
    open_trades = []
    closed_trades = []
    
    # Sort signals by timestamp
    sorted_signals = sorted(signals, key=lambda s: s["timestamp"])
    
    for sig in sorted_signals:
        if sig["confidence"] < min_conf:
            continue
        
        entry_ts = sig["timestamp"]
        if entry_ts not in candle_map:
            continue
        
        # Calculate SL with multiplier
        original_sl = sig["stop_loss"]
        entry = sig["entry"]
        side = sig["side"]
        
        # Apply SL multiplier
        risk_distance = abs(entry - original_sl) * sl_mult
        if side == "buy":
            adjusted_sl = entry - risk_distance
        else:
            adjusted_sl = entry + risk_distance
        
        # TP levels
        tp1 = entry + (risk_distance * tp1_r) if side == "buy" else entry - (risk_distance * tp1_r)
        tp2 = entry + (risk_distance * tp2_r) if side == "buy" else entry - (risk_distance * tp2_r)
        
        # Position sizing
        risk_per_trade = balance * pos_size_pct
        risk_per_unit = abs(entry - adjusted_sl)
        quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0
        
        trade = {
            "id": f"t-{sig.get('id', 'unknown')}",
            "timestamp": entry_ts,
            "side": side,
            "entry": entry,
            "stop_loss": adjusted_sl,
            "initial_sl": adjusted_sl,
            "tp1": tp1,
            "tp2": tp2,
            "quantity": quantity,
            "remaining_qty": quantity,
            "status": "open",
            "confidence": sig["confidence"],
            "bars_held": 0,
            "tp1_hit": False,
            "total_pnl": 0.0,
        }
        
        open_trades.append(trade)
    
    # Process trades through candles
    for ts in sorted_timestamps:
        current = candle_map[ts]
        
        for trade in list(open_trades):
            if trade["status"] != "open":
                continue
            
            # Only process candles after entry
            if ts <= trade["timestamp"]:
                continue
            
            side = trade["side"]
            entry = trade["entry"]
            sl = trade["stop_loss"]
            tp1 = trade["tp1"]
            tp2 = trade["tp2"]
            qty = trade["remaining_qty"]
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held
            
            # Move to breakeven
            risk = abs(entry - trade.get("initial_sl", sl))
            if risk > 0 and not trade["tp1_hit"]:
                if side == "buy":
                    profit_r = (current.high - entry) / risk
                    if profit_r >= be_thresh:
                        trade["stop_loss"] = max(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
                else:
                    profit_r = (entry - current.low) / risk
                    if profit_r >= be_thresh:
                        trade["stop_loss"] = min(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
            
            # Check TP1
            if not trade["tp1_hit"]:
                if side == "buy" and current.high >= tp1:
                    pnl1 = (tp1 - entry) * (qty * 0.5)
                    trade["tp1_hit"] = True
                    trade["remaining_qty"] = qty * 0.5
                    trade["total_pnl"] += pnl1
                    balance += pnl1
                elif side == "sell" and current.low <= tp1:
                    pnl1 = (entry - tp1) * (qty * 0.5)
                    trade["tp1_hit"] = True
                    trade["remaining_qty"] = qty * 0.5
                    trade["total_pnl"] += pnl1
                    balance += pnl1
            
            # Time exit
            if bars_held >= max_hold:
                exit_price = current.close
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "time_exit"
                balance += remaining_pnl
                
                closed_trades.append(trade)
                open_trades.remove(trade)
                continue
            
            # Check SL/TP2
            if side == "buy":
                hit_sl = current.low <= sl
                hit_tp2 = current.high >= tp2
            else:
                hit_sl = current.high >= sl
                hit_tp2 = current.low <= tp2
            
            if hit_sl:
                exit_price = sl
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "stop_loss"
                balance += remaining_pnl
                
                closed_trades.append(trade)
                open_trades.remove(trade)
            
            elif hit_tp2:
                exit_price = tp2
                remaining_pnl = (exit_price - entry) * trade["remaining_qty"] if side == "buy" else (entry - exit_price) * trade["remaining_qty"]
                
                trade["status"] = "closed"
                trade["exit_price"] = exit_price
                trade["total_pnl"] += remaining_pnl
                trade["pnl"] = round(trade["total_pnl"], 2)
                trade["close_reason"] = "tp2_hit"
                balance += remaining_pnl
                
                closed_trades.append(trade)
                open_trades.remove(trade)
    
    # Calculate stats
    total_trades = len(closed_trades)
    winning = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losing = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    
    win_rate = len(winning) / total_trades if total_trades > 0 else 0
    total_pnl = balance - 10000.0
    total_pnl_pct = (total_pnl / 10000.0) * 100
    
    gross_profit = sum(t["pnl"] for t in winning)
    gross_loss = abs(sum(t["pnl"] for t in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.99 if gross_profit > 0 else 0)
    
    avg_win = gross_profit / len(winning) if winning else 0
    avg_loss = gross_loss / len(losing) if losing else 0
    
    # Max drawdown
    peak_bal = 10000.0
    max_dd = 0
    bal = 10000.0
    for t in sorted(closed_trades, key=lambda x: x["timestamp"]):
        bal += t.get("pnl", 0)
        if bal > peak_bal:
            peak_bal = bal
        dd = peak_bal - bal
        if dd > max_dd:
            max_dd = dd
    
    max_dd_pct = (max_dd / peak_bal * 100) if peak_bal > 0 else 0
    
    # Sharpe (simplified)
    returns = [t["pnl"] / 10000.0 for t in closed_trades]
    if returns:
        avg_ret = sum(returns) / len(returns)
        std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5
        sharpe = (avg_ret / std_ret) if std_ret > 0 else 0
    else:
        sharpe = 0
    
    return {
        "total_trades": total_trades,
        "winning_trades": len(winning),
        "losing_trades": len(losing),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "profit_factor": profit_factor,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "sharpe_ratio": sharpe,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_hold_bars": sum(t.get("bars_held", 0) for t in closed_trades) / total_trades if total_trades > 0 else 0,
        "exit_reasons": {
            "stop_loss": len([t for t in closed_trades if t.get("close_reason") == "stop_loss"]),
            "tp2_hit": len([t for t in closed_trades if t.get("close_reason") == "tp2_hit"]),
            "time_exit": len([t for t in closed_trades if t.get("close_reason") == "time_exit"]),
        },
    }


def main():
    """Run ultra-fast parameter sweep."""
    print("=" * 80)
    print("  NEXUS ULTRA-FAST PARAMETER SWEEP (30-DAY)")
    print("=" * 80)
    
    print("Loading 30-day data...")
    candles = load_30d_data()
    print(f"Loaded {len(candles)} candles")
    
    print("Loading pre-computed signals...")
    signals = load_signals()
    print(f"Loaded {len(signals)} signals")
    print()
    
    # Define exit/position management configs
    configs = [
        # SL multiplier tests
        {"name": "SL0.5", "sl_multiplier": 0.5, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        {"name": "SL1.0", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        {"name": "SL1.5", "sl_multiplier": 1.5, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        {"name": "SL2.0", "sl_multiplier": 2.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        
        # BE threshold tests
        {"name": "BE05", "sl_multiplier": 1.0, "breakeven_threshold": 0.5, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        {"name": "BE10", "sl_multiplier": 1.0, "breakeven_threshold": 1.0, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        {"name": "NoBE", "sl_multiplier": 1.0, "breakeven_threshold": 999.0, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        
        # TP tests
        {"name": "TP1.5", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 1.5, "max_hold_bars": 25},
        {"name": "TP2.5", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.5, "max_hold_bars": 25},
        {"name": "TP3.0", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 3.0, "max_hold_bars": 25},
        {"name": "NoTP1", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 999.0, "partial_tp2_r": 2.0, "max_hold_bars": 25},
        
        # Hold time tests
        {"name": "Hold12", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 12},
        {"name": "Hold36", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 36},
        {"name": "Hold50", "sl_multiplier": 1.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0, "max_hold_bars": 50},
        
        # Combined configs
        {"name": "Combo1", "sl_multiplier": 1.5, "breakeven_threshold": 0.5, "partial_tp1_r": 1.0, "partial_tp2_r": 2.5, "max_hold_bars": 36},
        {"name": "Combo2", "sl_multiplier": 2.0, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 3.0, "max_hold_bars": 50},
        {"name": "Combo3", "sl_multiplier": 0.5, "breakeven_threshold": 0.5, "partial_tp1_r": 1.0, "partial_tp2_r": 1.5, "max_hold_bars": 12},
    ]
    
    results = []
    
    for i, config in enumerate(configs):
        print(f"[{i+1}/{len(configs)}] {config['name']}")
        print(f"  (SL_mult={config['sl_multiplier']}x, BE={config['breakeven_threshold']}, "
              f"TP1={config['partial_tp1_r']}R, TP2={config['partial_tp2_r']}R, Hold={config['max_hold_bars']})...")
        
        start_time = time.time()
        try:
            result = backtest_with_signals(candles, signals, config)
            elapsed = time.time() - start_time
            
            results.append({
                "name": config["name"],
                "config": config,
                **result,
                "elapsed_seconds": round(elapsed, 1),
            })
            
            print(f"  Trades: {result['total_trades']}, Win%: {result['win_rate']*100:.1f}%, "
                  f"PF: {result['profit_factor']:.2f}")
            print(f"  P&L: ${result['total_pnl']:.2f} ({result['total_pnl_pct']:.2f}%), "
                  f"DD: {result['max_drawdown_pct']:.2f}%")
            print(f"  Exits: SL={result['exit_reasons']['stop_loss']}, "
                  f"TP2={result['exit_reasons']['tp2_hit']}, "
                  f"Time={result['exit_reasons']['time_exit']}")
            print(f"  Time: {elapsed:.1f}s")
            print()
        
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            print()
    
    # Sort by profit factor
    results.sort(key=lambda x: x["profit_factor"], reverse=True)
    
    # Print summary
    print("=" * 100)
    print("  SUMMARY")
    print("=" * 100)
    print(f"{'#':<3} {'Name':<10} {'Trades':<7} {'Win%':<7} {'PF':<7} {'P&L%':<8} {'DD%':<7} {'Sharpe':<8}")
    print("-" * 100)
    
    for i, r in enumerate(results):
        print(f"{i+1:<3} {r['name']:<10} {r['total_trades']:<7} {r['win_rate']*100:<7.1f} {r['profit_factor']:<7.2f} "
              f"{r['total_pnl_pct']:<8.2f} {r['max_drawdown_pct']:<7.2f} {r['sharpe_ratio']:<8.2f}")
    
    print("=" * 100)
    
    profitable = [r for r in results if r["profit_factor"] > 1.0]
    if profitable:
        print(f"\n  {len(profitable)} profitable config(s) found.")
        print(f"  Best: {profitable[0]['name']} (PF={profitable[0]['profit_factor']:.2f})")
    else:
        print(f"\n  No profitable configs found.")
        if results:
            print(f"  Best: {results[0]['name']} (PF={results[0]['profit_factor']:.2f})")
    
    # Save results
    output_file = Path("fast_sweep_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n  Saved to {output_file}")


if __name__ == "__main__":
    main()
