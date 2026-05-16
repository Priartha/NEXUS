"""
Test strict signals with improved exits.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.strict_signals import detect_strict_signals
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.swing_detector import detect_swings
from backend.analysis.improved_backtest import ImprovedBacktestEngine


def load_sample(n=2000):
    """Load sample of candles."""
    data_path = Path(__file__).parent.parent / "historical_data_30d.json"
    
    if not data_path.exists():
        print("No cached data found.")
        return []
    
    print(f"Loading {n} candles...")
    with open(data_path) as f:
        data = json.load(f)
    
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


def generate_signals(candles, min_conf=0.55, cooldown=12):
    """Generate strict signals."""
    print(f"  Generating strict signals (min_conf={min_conf}, cooldown={cooldown})...", end=" ", flush=True)
    
    all_signals = []
    lookback = 80
    min_candles = max(lookback, 50)
    last_signal_ts = 0
    
    for i in range(min_candles, len(candles)):
        window = candles[:i + 1]
        recent = window[-lookback:]
        
        swings = detect_swings(window)[-100:]
        fvgs = detect_fvgs(recent)
        order_blocks = detect_order_blocks(recent, swings)
        liquidity = detect_equal_levels(swings)
        
        for c in recent[-20:]:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)
        
        metrics = compute_market_metrics(window, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(recent, liquidity, atr)[-40:]
        
        signals = detect_strict_signals(
            candles=window,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            last_signal_ts=last_signal_ts,
            signal_cooldown_candles=cooldown,
            min_confidence=min_conf,
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
            last_signal_ts = sig.timestamp
    
    print(f"{len(all_signals)} signals")
    return all_signals


def run_bt(candles, signals, hold=25, be=0.75, tp1=1.0, tp2=2.0):
    """Run backtest."""
    engine = ImprovedBacktestEngine(
        initial_balance=10000.0,
        position_size_pct=0.02,
        max_concurrent=1,
        max_hold_bars=hold,
        breakeven_threshold=be,
        partial_tp1_r=tp1,
        partial_tp2_r=tp2,
        confidence_sizing=True,
    )
    return engine.run(candles, signals, symbol="BTCUSDT", timeframe="5m")


def main():
    print("=" * 80)
    print("  STRICT SIGNALS TEST (7-DAY SAMPLE)")
    print("=" * 80)
    
    candles = load_sample(n=2000)
    if not candles:
        return
    
    start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[0].timestamp / 1000))
    end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[-1].timestamp / 1000))
    print(f"Period: {start} to {end}")
    
    # Test configs
    configs = [
        {"min_conf": 0.55, "cooldown": 12, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "name": "STRICT Default"},
        {"min_conf": 0.50, "cooldown": 12, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "name": "STRICT Relaxed"},
        {"min_conf": 0.60, "cooldown": 12, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "name": "STRICT Strict"},
        {"min_conf": 0.55, "cooldown": 24, "hold": 25, "be": 0.75, "tp1": 1.0, "tp2": 2.0, "name": "STRICT 2h Cooldown"},
        {"min_conf": 0.55, "cooldown": 12, "hold": 12, "be": 0.5, "tp1": 1.0, "tp2": 1.5, "name": "STRICT Quick"},
        {"min_conf": 0.55, "cooldown": 12, "hold": 50, "be": 1.0, "tp1": 1.0, "tp2": 3.0, "name": "STRICT Wide"},
    ]
    
    results = []
    for i, cfg in enumerate(configs):
        print(f"\n[{i+1}/{len(configs)}] {cfg['name']}")
        
        signals = generate_signals(
            candles,
            min_conf=cfg["min_conf"],
            cooldown=cfg["cooldown"],
        )
        
        if not signals:
            print("  No signals")
            continue
        
        result = run_bt(
            candles,
            signals,
            hold=cfg["hold"],
            be=cfg["be"],
            tp1=cfg["tp1"],
            tp2=cfg["tp2"],
        )
        
        print(f"  Trades: {result['total_trades']}, Win%: {result['win_rate']*100:.1f}%, PF: {result['profit_factor']:.2f}")
        print(f"  P&L: ${result['total_pnl']:.2f} ({result['total_pnl_pct']:.2f}%), DD: {result['max_drawdown_pct']:.2f}%")
        
        # Exit breakdown
        trades = result.get("trades", [])
        if trades:
            reasons = {}
            for t in trades:
                r = t.get("close_reason", "unknown")
                reasons[r] = reasons.get(r, 0) + 1
            print(f"  Exits: {', '.join([f'{k}: {v}' for k, v in sorted(reasons.items(), key=lambda x: -x[1])])}")
        
        results.append({
            "name": cfg["name"],
            "signals": len(signals),
            "trades": result["total_trades"],
            "win_rate": result["win_rate"],
            "pf": result["profit_factor"],
            "pnl_pct": result["total_pnl_pct"],
            "dd_pct": result["max_drawdown_pct"],
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
            f"{r['signals']:<8} "
            f"{r['trades']:<7} "
            f"{r['win_rate']*100:<7.1f} "
            f"{r['pf']:<7.2f} "
            f"{r['pnl_pct']:<8.2f} "
            f"{r['dd_pct']:<7.2f}"
        )
    
    print("=" * 80)
    
    # Best profitable
    profitable = [r for r in results if r["pf"] > 1.0 and r["trades"] >= 3]
    if profitable:
        best = max(profitable, key=lambda r: r["pf"])
        print(f"\n  BEST: {best['name']}")
        print(f"    PF: {best['pf']:.2f}, Win%: {best['win_rate']*100:.1f}%, P&L: {best['pnl_pct']:.2f}%")
    else:
        print("\n  No profitable configs found.")
        best = max(results, key=lambda r: r["pf"])
        print(f"  Best: {best['name']} (PF={best['pf']:.2f})")
    
    # Save
    output_path = Path(__file__).parent.parent / "strict_test_results.json"
    with open(output_path, "w") as f:
        json.dump({"results": results, "best": best, "timestamp": time.time()}, f, indent=2)
    print(f"\n  Saved to {output_path}")


if __name__ == "__main__":
    main()
