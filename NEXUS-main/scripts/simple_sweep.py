"""
Simple parameter sweep for NEXUS strategy.

Generates signals with different parameters and backtests them.
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.optimized_signals import detect_optimized_signals
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.swing_detector import detect_swings


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


def simple_backtest(candles: list[Candle], config: dict) -> dict:
    """Simple backtest that generates signals and tracks trades."""
    # Config
    sl_mult = config["stop_loss_multiplier"]
    use_adx = config.get("use_adx_filter", True)
    adx_thresh = config.get("adx_threshold", 20.0)
    use_limit = config.get("use_limit_orders", True)
    min_conf = config.get("min_confidence", 0.55)
    cooldown = config.get("signal_cooldown_candles", 12)
    be_thresh = config.get("breakeven_threshold", 0.75)
    tp1_r = config.get("partial_tp1_r", 1.0)
    tp2_r = config.get("partial_tp2_r", 2.0)
    max_hold = config.get("max_hold_bars", 25)
    pos_size_pct = config.get("position_size_pct", 0.02)
    
    # State
    balance = 10000.0
    open_trades = []
    closed_trades = []
    last_signal_ts = 0
    total_signals = 0
    
    chunk_size = 80
    min_candles = 100
    
    for i in range(min_candles, len(candles)):
        current = candles[i]
        chunk = candles[max(0, i - chunk_size):i]
        all_candles = candles[:i]
        
        # Analysis
        swings = detect_swings(all_candles)[-100:]
        fvgs = detect_fvgs(chunk)
        order_blocks = detect_order_blocks(chunk, swings)
        liquidity = detect_equal_levels(swings)
        
        for c in chunk:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)
        
        metrics = compute_market_metrics(all_candles, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(chunk, liquidity, atr)[-40:]
        
        # Generate signals
        signals = detect_optimized_signals(
            candles=all_candles,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            last_signal_ts=last_signal_ts,
            signal_cooldown_candles=cooldown,
            min_confidence=min_conf,
            stop_loss_multiplier=sl_mult,
            use_adx_filter=use_adx,
            adx_threshold=adx_thresh,
            use_limit_orders=use_limit,
        )
        
        for sig in signals:
            total_signals += 1
            
            if len([t for t in open_trades if t.get("status") == "open"]) >= 1:
                continue
            
            if sig.confidence < min_conf:
                continue
            
            # Position sizing
            risk_per_trade = balance * pos_size_pct
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0
            
            # TP levels
            risk = abs(sig.entry - sig.stop_loss)
            tp1 = sig.entry + (risk * tp1_r) if sig.side == "buy" else sig.entry - (risk * tp1_r)
            tp2 = sig.entry + (risk * tp2_r) if sig.side == "buy" else sig.entry - (risk * tp2_r)
            
            trade = {
                "id": f"t-{total_signals}",
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry": sig.entry,
                "stop_loss": sig.stop_loss,
                "initial_sl": sig.stop_loss,
                "tp1": tp1,
                "tp2": tp2,
                "quantity": quantity,
                "remaining_qty": quantity,
                "status": "open",
                "confidence": sig.confidence,
                "bars_held": 0,
                "tp1_hit": False,
                "total_pnl": 0.0,
            }
            
            open_trades.append(trade)
            last_signal_ts = sig.timestamp
        
        # Process open trades
        for trade in list(open_trades):
            if trade["status"] != "open":
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
        "total_signals": total_signals,
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
    """Run parameter sweep."""
    print("=" * 80)
    print("  NEXUS PARAMETER SWEEP (30-DAY)")
    print("=" * 80)
    
    print("Loading 30-day data...")
    candles = load_30d_data()
    print(f"Loaded {len(candles)} candles")
    print(f"Period: {datetime.fromtimestamp(candles[0].timestamp/1000)} to {datetime.fromtimestamp(candles[-1].timestamp/1000)}")
    print()
    
    # Define configs
    configs = [
        {"name": "SL1.5", "stop_loss_multiplier": 1.5, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "SL2.0", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "SL2.5", "stop_loss_multiplier": 2.5, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "SL3.0", "stop_loss_multiplier": 3.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "ADX15", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 15.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "ADX25", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 25.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "NoADX", "stop_loss_multiplier": 2.0, "use_adx_filter": False, "adx_threshold": 0.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "Conf60", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.60, "signal_cooldown_candles": 12},
        {"name": "Conf65", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.65, "signal_cooldown_candles": 12},
        {"name": "Market", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": False, "min_confidence": 0.55, "signal_cooldown_candles": 12},
        {"name": "Combo1", "stop_loss_multiplier": 2.5, "use_adx_filter": True, "adx_threshold": 15.0, "use_limit_orders": True, "min_confidence": 0.60, "signal_cooldown_candles": 18},
        {"name": "Combo2", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 25.0, "use_limit_orders": True, "min_confidence": 0.65, "signal_cooldown_candles": 24},
    ]
    
    results = []
    
    for i, config in enumerate(configs):
        print(f"[{i+1}/{len(configs)}] {config['name']}")
        print(f"  (SL={config['stop_loss_multiplier']}x, ADX={'Yes' if config['use_adx_filter'] else 'No'}, "
              f"LMT={'Yes' if config['use_limit_orders'] else 'No'}, Conf={config['min_confidence']})...")
        
        start_time = time.time()
        try:
            result = simple_backtest(candles, config)
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
    output_file = Path("sweep_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n  Saved to {output_file}")


if __name__ == "__main__":
    main()
