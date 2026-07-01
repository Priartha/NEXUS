"""
Quick optimization test with 30-day data.
Tests key configurations to find profitable parameters.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from scripts.comprehensive_optimization import run_optimized_backtest, print_results


def load_candles():
    """Load candles from cached file."""
    data_path = Path(__file__).parent.parent / "historical_data_30d.json"
    
    if not data_path.exists():
        print("No cached data found. Run fetch_30d_data.py first.")
        return []
    
    print("Loading cached 30-day data...")
    with open(data_path) as f:
        data = json.load(f)
    
    candles = [Candle(
        timestamp=d["timestamp"],
        open=d["open"],
        high=d["high"],
        low=d["low"],
        close=d["close"],
        volume=d["volume"],
    ) for d in data]
    
    print(f"Loaded {len(candles)} candles")
    return candles


def main():
    candles = load_candles()
    
    if not candles or len(candles) < 100:
        print("Not enough candles")
        return
    
    print("\n" + "=" * 80)
    print("  QUICK OPTIMIZATION TEST (30-DAY DATA)")
    print("=" * 80)
    
    # Test key configurations
    configs = [
        # Standard signals
        {"reward_multiple": 2.0, "max_hold_bars": 25, "breakeven_threshold": 1.0,
         "min_confidence": 0.50, "min_confluence": 0.45, "regime_filter": False,
         "use_relaxed_signals": False, "name": "STD Default"},
        
        # Relaxed signals
        {"reward_multiple": 2.0, "max_hold_bars": 25, "breakeven_threshold": 1.0,
         "min_confidence": 0.40, "min_confluence": 0.35, "regime_filter": False,
         "use_relaxed_signals": True, "name": "RLX Default"},
        {"reward_multiple": 1.5, "max_hold_bars": 25, "breakeven_threshold": 0.5,
         "min_confidence": 0.40, "min_confluence": 0.35, "regime_filter": False,
         "use_relaxed_signals": True, "name": "RLX Quick"},
        {"reward_multiple": 2.5, "max_hold_bars": 25, "breakeven_threshold": 1.5,
         "min_confidence": 0.40, "min_confluence": 0.35, "regime_filter": False,
         "use_relaxed_signals": True, "name": "RLX Wide"},
        
        # With regime filter
        {"reward_multiple": 2.0, "max_hold_bars": 25, "breakeven_threshold": 1.0,
         "min_confidence": 0.40, "min_confluence": 0.35, "regime_filter": True,
         "use_relaxed_signals": True, "name": "REG Default"},
        {"reward_multiple": 1.5, "max_hold_bars": 12, "breakeven_threshold": 0.5,
         "min_confidence": 0.40, "min_confluence": 0.35, "regime_filter": True,
         "use_relaxed_signals": True, "name": "REG Quick"},
        
        # Different hold periods
        {"reward_multiple": 2.0, "max_hold_bars": 12, "breakeven_threshold": 0.5,
         "min_confidence": 0.40, "min_confluence": 0.35, "regime_filter": False,
         "use_relaxed_signals": True, "name": "RLX Short"},
        {"reward_multiple": 2.0, "max_hold_bars": 50, "breakeven_threshold": 1.0,
         "min_confidence": 0.40, "min_confluence": 0.35, "regime_filter": False,
         "use_relaxed_signals": True, "name": "RLX Long"},
    ]
    
    print(f"\nTesting {len(configs)} configurations on {len(candles)} candles...\n")
    
    results = []
    for i, cfg in enumerate(configs):
        print(f"  [{i+1}/{len(configs)}] {cfg['name']}...", end=" ", flush=True)
        
        result = run_optimized_backtest(
            candles,
            reward_multiple=cfg["reward_multiple"],
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
            min_confidence=cfg["min_confidence"],
            min_confluence=cfg["min_confluence"],
            regime_filter=cfg["regime_filter"],
            use_relaxed_signals=cfg["use_relaxed_signals"],
        )
        
        results.append({
            "name": cfg["name"],
            "config": cfg,
            "total_pnl": result["total_pnl"],
            "total_pnl_pct": result["total_pnl_pct"],
            "win_rate": result["win_rate"],
            "profit_factor": result["profit_factor"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "sharpe_ratio": result["sharpe_ratio"],
            "total_trades": result["total_trades"],
        })
        
        print(f"Trades: {result['total_trades']}, PF: {result['profit_factor']:.2f}")
    
    # Print summary
    print("\n" + "=" * 80)
    print("  RESULTS SUMMARY")
    print("=" * 80)
    print(f"  {'#':<3} {'Name':<20} {'Trades':<7} {'Win%':<7} {'PF':<7} {'P&L%':<8} {'DD%':<7}")
    print("-" * 80)
    
    for i, r in enumerate(results):
        print(
            f"  {i+1:<3} "
            f"{r['name']:<20} "
            f"{r['total_trades']:<7} "
            f"{r['win_rate']*100:<7.1f} "
            f"{r['profit_factor']:<7.2f} "
            f"{r['total_pnl_pct']:<8.2f} "
            f"{r['max_drawdown_pct']:<7.2f}"
        )
    
    print("=" * 80)
    
    # Find best profitable config
    profitable = [r for r in results if r["profit_factor"] > 1.0 and r["total_trades"] >= 10]
    if profitable:
        best = max(profitable, key=lambda r: r["profit_factor"])
        print(f"\n  BEST PROFITABLE CONFIG: {best['name']}")
        print(f"    Profit Factor: {best['profit_factor']:.2f}")
        print(f"    Win Rate: {best['win_rate']*100:.1f}%")
        print(f"    P&L: {best['total_pnl_pct']:.2f}%")
        print(f"    Max DD: {best['max_drawdown_pct']:.2f}%")
        print(f"    Trades: {best['total_trades']}")
        
        # Run detailed backtest with best config
        print(f"\n  Running detailed backtest with best config...")
        cfg = best["config"]
        detailed_result = run_optimized_backtest(
            candles,
            reward_multiple=cfg["reward_multiple"],
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
            min_confidence=cfg["min_confidence"],
            min_confluence=cfg["min_confluence"],
            regime_filter=cfg["regime_filter"],
            use_relaxed_signals=cfg["use_relaxed_signals"],
        )
        print_results(detailed_result)
    else:
        print("\n  No profitable configurations with >= 10 trades found.")
        best = max(results, key=lambda r: r["profit_factor"])
        print(f"  Best attempt: {best['name']}")
        print(f"    PF: {best['profit_factor']:.2f}, P&L: {best['total_pnl_pct']:.2f}%, Trades: {best['total_trades']}")
    
    # Save results
    output_path = Path(__file__).parent.parent / "quick_optimization_30d.json"
    with open(output_path, "w") as f:
        json.dump({
            "results": results,
            "best_config": best if profitable else None,
            "timestamp": time.time(),
        }, f, indent=2, default=str)
    
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    main()
