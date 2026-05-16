"""
Test simplified signals with improved exit strategy.
Uses 30-day historical data for robust testing.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.simplified_signals import detect_simplified_signals
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.regime import detect_market_regime
from backend.analysis.swing_detector import detect_swings
from backend.analysis.improved_backtest import ImprovedBacktestEngine


def load_candles(n=None):
    """Load candles from cached file."""
    data_path = Path(__file__).parent.parent / "historical_data_30d.json"
    
    if not data_path.exists():
        print("No cached data found. Run fetch_30d_data.py first.")
        return []
    
    print("Loading cached 30-day data...")
    with open(data_path) as f:
        data = json.load(f)
    
    if n:
        data = data[-n:]
    
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


def generate_signals(candles, use_htf_filter=True, min_confidence=0.45):
    """Generate signals using simplified logic."""
    print("  Generating signals...", end=" ", flush=True)
    
    all_signals = []
    lookback = 80
    min_candles = max(lookback, 50)
    
    for i in range(min_candles, len(candles)):
        window = candles[:i + 1]
        recent = window[-lookback:]
        
        # Run analysis
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
        
        # Detect signals
        signals = detect_simplified_signals(
            candles=window,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            use_htf_filter=use_htf_filter,
            min_confidence=min_confidence,
        )
        
        for sig in signals:
            all_signals.append({
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry": sig.entry,
                "stop_loss": sig.stop_loss,
                "confidence": sig.confidence,
                "reason": sig.reason,
                "id": sig.id,
            })
    
    print(f"Generated {len(all_signals)} signals")
    return all_signals


def run_backtest(candles, signals, pos_sz=0.02, hold=25, be=0.75, tp1=1.0, tp2=2.0, conf_sizing=True):
    """Run improved backtest."""
    engine = ImprovedBacktestEngine(
        initial_balance=10000.0,
        position_size_pct=pos_sz,
        max_concurrent=1,
        max_hold_bars=hold,
        breakeven_threshold=be,
        partial_tp1_r=tp1,
        partial_tp2_r=tp2,
        confidence_sizing=conf_sizing,
    )
    return engine.run(candles, signals, symbol="BTCUSDT", timeframe="5m")


def print_results(result, name=""):
    """Print backtest results."""
    print(f"\n  [{name}]")
    print(f"    Trades: {result['total_trades']}")
    print(f"    Win Rate: {result['win_rate']*100:.1f}%")
    print(f"    P&L: ${result['total_pnl']:.2f} ({result['total_pnl_pct']:.2f}%)")
    print(f"    Profit Factor: {result['profit_factor']:.2f}")
    print(f"    Max DD: {result['max_drawdown_pct']:.2f}%")
    print(f"    Avg Win: ${result['avg_win']:.2f}")
    print(f"    Avg Loss: ${result['avg_loss']:.2f}")
    
    # Exit reasons
    trades = result.get("trades", [])
    if trades:
        reasons = {}
        for t in trades:
            reason = t.get("close_reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        
        print(f"    Exits: {', '.join([f'{k}: {v}' for k, v in sorted(reasons.items(), key=lambda x: -x[1])])}")


def main():
    print("=" * 80)
    print("  SIMPLIFIED SIGNALS + IMPROVED EXITS TEST")
    print("=" * 80)
    
    candles = load_candles()
    if not candles or len(candles) < 100:
        print("Not enough candles")
        return
    
    start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[0].timestamp / 1000))
    end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[-1].timestamp / 1000))
    print(f"Period: {start} to {end}")
    print(f"Candles: {len(candles)}")
    
    # Test configurations
    configs = [
        # Simplified with HTF filter
        {"use_htf": True, "min_conf": 0.45, "pos_sz": 0.02, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "conf_sizing": True, "name": "SIMP+HTF Default"},
        {"use_htf": True, "min_conf": 0.40, "pos_sz": 0.02, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "conf_sizing": True, "name": "SIMP+HTF Relaxed"},
        {"use_htf": True, "min_conf": 0.50, "pos_sz": 0.02, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "conf_sizing": True, "name": "SIMP+HTF Strict"},
        
        # Without HTF filter
        {"use_htf": False, "min_conf": 0.45, "pos_sz": 0.02, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "conf_sizing": True, "name": "SIMP No HTF"},
        
        # Different exit strategies
        {"use_htf": True, "min_conf": 0.45, "pos_sz": 0.02, "hold": 12, "be": 0.5, "tp1": 1.0, "tp2": 1.5, "conf_sizing": True, "name": "SIMP Quick Exit"},
        {"use_htf": True, "min_conf": 0.45, "pos_sz": 0.02, "hold": 50, "be": 1.0, "tp1": 1.0, "tp2": 3.0, "conf_sizing": True, "name": "SIMP Wide Exit"},
        
        # Without confidence sizing
        {"use_htf": True, "min_conf": 0.45, "pos_sz": 0.02, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "conf_sizing": False, "name": "SIMP Fixed Size"},
    ]
    
    results = []
    for i, cfg in enumerate(configs):
        print(f"\n[{i+1}/{len(configs)}] {cfg['name']}")
        
        # Generate signals
        signals = generate_signals(
            candles,
            use_htf_filter=cfg["use_htf"],
            min_confidence=cfg["min_conf"],
        )
        
        if not signals:
            print("  No signals generated")
            continue
        
        # Run backtest
        result = run_backtest(
            candles,
            signals,
            pos_sz=cfg["pos_sz"],
            hold=cfg["hold"],
            be=cfg["be"],
            tp1=cfg["tp1"],
            tp2=cfg["tp2"],
            conf_sizing=cfg["conf_sizing"],
        )
        
        print_results(result, cfg["name"])
        
        results.append({
            "name": cfg["name"],
            "config": cfg,
            "total_signals": len(signals),
            "total_trades": result["total_trades"],
            "win_rate": result["win_rate"],
            "profit_factor": result["profit_factor"],
            "total_pnl_pct": result["total_pnl_pct"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "sharpe_ratio": result["sharpe_ratio"],
        })
    
    # Summary
    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  {'#':<3} {'Name':<25} {'Signals':<8} {'Trades':<7} {'Win%':<7} {'PF':<7} {'P&L%':<8} {'DD%':<7}")
    print("-" * 80)
    
    for i, r in enumerate(results):
        print(
            f"  {i+1:<3} "
            f"{r['name']:<25} "
            f"{r['total_signals']:<8} "
            f"{r['total_trades']:<7} "
            f"{r['win_rate']*100:<7.1f} "
            f"{r['profit_factor']:<7.2f} "
            f"{r['total_pnl_pct']:<8.2f} "
            f"{r['max_drawdown_pct']:<7.2f}"
        )
    
    print("=" * 80)
    
    # Find best profitable config
    profitable = [r for r in results if r["profit_factor"] > 1.0 and r["total_trades"] >= 5]
    if profitable:
        best = max(profitable, key=lambda r: r["profit_factor"])
        print(f"\n  BEST PROFITABLE CONFIG: {best['name']}")
        print(f"    Signals: {best['total_signals']}")
        print(f"    Trades: {best['total_trades']}")
        print(f"    Win Rate: {best['win_rate']*100:.1f}%")
        print(f"    Profit Factor: {best['profit_factor']:.2f}")
        print(f"    P&L: {best['total_pnl_pct']:.2f}%")
        print(f"    Max DD: {best['max_drawdown_pct']:.2f}%")
    else:
        print("\n  No profitable configurations with >= 5 trades found.")
        best = max(results, key=lambda r: r["profit_factor"])
        print(f"  Best attempt: {best['name']}")
        print(f"    PF: {best['profit_factor']:.2f}, P&L: {best['total_pnl_pct']:.2f}%, Trades: {best['total_trades']}")
    
    # Save results
    output_path = Path(__file__).parent.parent / "simplified_test_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "results": results,
            "best_config": best if profitable else None,
            "timestamp": time.time(),
        }, f, indent=2, default=str)
    
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    main()
