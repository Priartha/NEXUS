"""
Comprehensive parameter sweep for NEXUS optimized strategy.

Tests multiple combinations of:
- Stop loss multiplier (1.5x to 3.0x ATR)
- ADX threshold (15 to 30)
- Confidence threshold (0.50 to 0.70)
- Partial profit levels (1R, 1.5R, 2R)
- Breakeven threshold (0.5R to 1.0R)
- Signal cooldown (6 to 24 candles)

Uses 30-day historical data for robust testing.
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
from backend.analysis.improved_backtest import ImprovedBacktestEngine


def load_30d_data() -> list[Candle]:
    """Load 30-day historical data."""
    data_file = Path("historical_data_30d.json")
    if not data_file.exists():
        print("ERROR: historical_data_30d.json not found")
        print("Run: python scripts/fetch_30d_data.py first")
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


def run_backtest(candles: list[Candle], config: dict) -> dict:
    """Run backtest with given configuration."""
    engine = ImprovedBacktestEngine(
        initial_balance=10000.0,
        position_size_pct=0.02,
        max_concurrent=1,
        slippage_pct=0.0002,
        commission_pct=0.0004,
        max_hold_bars=config.get("max_hold_bars", 25),
        breakeven_threshold=config.get("breakeven_threshold", 0.75),
        partial_tp1_r=config.get("partial_tp1_r", 1.0),
        partial_tp2_r=config.get("partial_tp2_r", 2.0),
        stop_loss_multiplier=config["stop_loss_multiplier"],
        use_adx_filter=config.get("use_adx_filter", True),
        adx_threshold=config.get("adx_threshold", 20.0),
        use_limit_orders=config.get("use_limit_orders", True),
        min_confidence=config.get("min_confidence", 0.55),
        signal_cooldown_candles=config.get("signal_cooldown_candles", 12),
    )
    
    # Run analysis in chunks to avoid recomputing everything
    chunk_size = 80
    min_candles = 100
    
    for i in range(min_candles, len(candles), 1):
        chunk = candles[max(0, i - chunk_size):i]
        
        swings = detect_swings(candles[:i])[-100:]
        fvgs = detect_fvgs(chunk)
        order_blocks = detect_order_blocks(chunk, swings)
        liquidity = detect_equal_levels(swings)
        
        for c in chunk:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)
        
        metrics = compute_market_metrics(candles[:i], swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(chunk, liquidity, atr)[-40:]
        
        signals = detect_optimized_signals(
            candles=candles[:i],
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            last_signal_ts=engine.last_signal_ts,
            signal_cooldown_candles=config.get("signal_cooldown_candles", 12),
            min_confidence=config.get("min_confidence", 0.55),
            stop_loss_multiplier=config["stop_loss_multiplier"],
            use_adx_filter=config.get("use_adx_filter", True),
            adx_threshold=config.get("adx_threshold", 20.0),
            use_limit_orders=config.get("use_limit_orders", True),
        )
        
        for sig in signals:
            engine.process_signal(sig, candles[i])
        
        # Process candle for open trades
        if len(candles[:i]) > 0:
            engine.process_candle(candles[i])
    
    return engine.get_results()


def main():
    """Run comprehensive parameter sweep."""
    print("=" * 80)
    print("  NEXUS COMPREHENSIVE PARAMETER SWEEP (30-DAY)")
    print("=" * 80)
    
    # Load data
    print("Loading 30-day data...")
    candles = load_30d_data()
    print(f"Loaded {len(candles)} candles")
    print(f"Period: {datetime.fromtimestamp(candles[0].timestamp/1000)} to {datetime.fromtimestamp(candles[-1].timestamp/1000)}")
    print()
    
    # Define parameter combinations
    configs = [
        # Base configs
        {"name": "Base1", "stop_loss_multiplier": 1.5, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "Base2", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "Base3", "stop_loss_multiplier": 2.5, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "Base4", "stop_loss_multiplier": 3.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        
        # ADX variations
        {"name": "ADX15", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 15.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "ADX25", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 25.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "ADX30", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 30.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "NoADX", "stop_loss_multiplier": 2.0, "use_adx_filter": False, "adx_threshold": 0.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        
        # Confidence variations
        {"name": "Conf50", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.50, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "Conf60", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.60, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "Conf65", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.65, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "Conf70", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.70, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        
        # TP variations
        {"name": "TP1.5", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 1.5},
        {"name": "TP2.5", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.5},
        {"name": "TP3.0", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 3.0},
        
        # BE variations
        {"name": "BE05", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.5, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "BE10", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 1.0, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        
        # Cooldown variations
        {"name": "CD6", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 6, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "CD18", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 18, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "CD24", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": True, "min_confidence": 0.55, "signal_cooldown_candles": 24, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        
        # Market orders vs limit
        {"name": "Market", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": False, "min_confidence": 0.55, "signal_cooldown_candles": 12, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        
        # Combined best guesses
        {"name": "Combo1", "stop_loss_multiplier": 2.5, "use_adx_filter": True, "adx_threshold": 15.0, "use_limit_orders": True, "min_confidence": 0.60, "signal_cooldown_candles": 18, "breakeven_threshold": 0.5, "partial_tp1_r": 1.0, "partial_tp2_r": 2.0},
        {"name": "Combo2", "stop_loss_multiplier": 2.0, "use_adx_filter": True, "adx_threshold": 25.0, "use_limit_orders": True, "min_confidence": 0.65, "signal_cooldown_candles": 24, "breakeven_threshold": 0.75, "partial_tp1_r": 1.0, "partial_tp2_r": 2.5},
        {"name": "Combo3", "stop_loss_multiplier": 3.0, "use_adx_filter": True, "adx_threshold": 20.0, "use_limit_orders": False, "min_confidence": 0.60, "signal_cooldown_candles": 12, "breakeven_threshold": 0.5, "partial_tp1_r": 1.0, "partial_tp2_r": 3.0},
    ]
    
    results = []
    
    for i, config in enumerate(configs):
        print(f"[{i+1}/{len(configs)}] {config['name']}")
        print(f"  (SL={config['stop_loss_multiplier']}x, ADX={'Yes' if config['use_adx_filter'] else 'No'}, "
              f"LMT={'Yes' if config['use_limit_orders'] else 'No'}, Conf={config['min_confidence']})...")
        
        start_time = time.time()
        try:
            result = run_backtest(candles, config)
            elapsed = time.time() - start_time
            
            results.append({
                "name": config["name"],
                "config": config,
                "total_signals": result.get("total_signals", 0),
                "total_trades": result.get("total_trades", 0),
                "winning_trades": result.get("winning_trades", 0),
                "losing_trades": result.get("losing_trades", 0),
                "win_rate": result.get("win_rate", 0),
                "total_pnl": result.get("total_pnl", 0),
                "total_pnl_pct": result.get("total_pnl_pct", 0),
                "profit_factor": result.get("profit_factor", 0),
                "max_drawdown": result.get("max_drawdown", 0),
                "max_drawdown_pct": result.get("max_drawdown_pct", 0),
                "sharpe_ratio": result.get("sharpe_ratio", 0),
                "avg_win": result.get("avg_win", 0),
                "avg_loss": result.get("avg_loss", 0),
                "avg_hold_bars": result.get("avg_hold_bars", 0),
                "elapsed_seconds": round(elapsed, 1),
            })
            
            print(f"  Trades: {result.get('total_trades', 0)}, Win%: {result.get('win_rate', 0)*100:.1f}%, "
                  f"PF: {result.get('profit_factor', 0):.2f}")
            print(f"  P&L: ${result.get('total_pnl', 0):.2f} ({result.get('total_pnl_pct', 0):.2f}%), "
                  f"DD: {result.get('max_drawdown_pct', 0):.2f}%")
            print(f"  Time: {elapsed:.1f}s")
            print()
        
        except Exception as e:
            print(f"  ERROR: {e}")
            print()
    
    # Sort by profit factor
    results.sort(key=lambda x: x["profit_factor"], reverse=True)
    
    # Print summary
    print("=" * 100)
    print("  SUMMARY")
    print("=" * 100)
    print(f"{'#':<3} {'Name':<10} {'Trades':<7} {'Win%':<7} {'PF':<7} {'P&L%':<8} {'DD%':<7} {'Sharpe':<8} {'Time':<7}")
    print("-" * 100)
    
    for i, r in enumerate(results):
        print(f"{i+1:<3} {r['name']:<10} {r['total_trades']:<7} {r['win_rate']*100:<7.1f} {r['profit_factor']:<7.2f} "
              f"{r['total_pnl_pct']:<8.2f} {r['max_drawdown_pct']:<7.2f} {r['sharpe_ratio']:<8.2f} {r['elapsed_seconds']:<7.1f}")
    
    print("=" * 100)
    
    profitable = [r for r in results if r["profit_factor"] > 1.0]
    if profitable:
        print(f"\n  {len(profitable)} profitable config(s) found.")
        print(f"  Best: {profitable[0]['name']} (PF={profitable[0]['profit_factor']:.2f})")
    else:
        print(f"\n  No profitable configs found.")
        print(f"  Best: {results[0]['name']} (PF={results[0]['profit_factor']:.2f})")
    
    # Save results
    output_file = Path("comprehensive_sweep_results.json")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n  Saved to {output_file}")


if __name__ == "__main__":
    main()
