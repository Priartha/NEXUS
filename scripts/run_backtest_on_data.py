"""Step 2: Run backtest on pre-fetched data."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.backtest import BacktestEngine


def main():
    print("Loading fetched candles...")
    with open(Path(__file__).parent.parent/"fetched_candles.json") as f:
        raw = json.load(f)

    candles = [Candle(timestamp=c["t"],open=c["o"],high=c["h"],low=c["l"],close=c["c"],volume=c["v"]) for c in raw]
    candles.sort(key=lambda c: c.timestamp)

    days = (candles[-1].timestamp - candles[0].timestamp) / (1000*86400)
    print(f"Loaded {len(candles)} candles ({days:.1f} days)")
    print(f"Period: {time.strftime('%Y-%m-%d', time.gmtime(candles[0].timestamp/1000))} to {time.strftime('%Y-%m-%d', time.gmtime(candles[-1].timestamp/1000))}")

    configs = [
        {"name": "optimized", "max_hold": 10, "trailing": False, "be": 1.0, "risk": 0.02},
        {"name": "conservative", "max_hold": 10, "trailing": False, "be": 1.0, "risk": 0.01},
        {"name": "aggressive", "max_hold": 10, "trailing": False, "be": 1.0, "risk": 0.025},
        {"name": "long_hold", "max_hold": 20, "trailing": False, "be": 1.0, "risk": 0.02},
        {"name": "short_hold", "max_hold": 6, "trailing": False, "be": 1.0, "risk": 0.02},
    ]

    print(f"\nRunning backtests...\n")
    results = []
    for i, cfg in enumerate(configs):
        t0 = time.time()
        engine = BacktestEngine(
            initial_balance=10000, position_size_pct=cfg["risk"],
            max_hold_bars=cfg["max_hold"], breakeven_threshold=cfg["be"],
            trailing_stop=cfg["trailing"],
        )
        result = engine.run(candles, symbol="BTCUSDT", timeframe="5m")
        elapsed = time.time() - t0
        results.append({**cfg, "result": result})
        print(f"  {i+1}/{len(configs)} | {cfg['name']:<15} | T:{result['total_trades']:>3} WR:{result['win_rate']*100:>5.1f}% PF:{result['profit_factor']:>5.2f} DD:{result['max_drawdown_pct']:>5.2f}% PnL:{result['total_pnl_pct']:>7.2f}% [{elapsed:.0f}s]")

    print(f"\n{'='*90}")
    print(f"  BACKTEST RESULTS ({days:.1f} days, {len(candles)} candles)")
    print(f"{'='*90}")
    print(f"  {'Name':<15} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<7} {'Sharpe':<7} {'PnL%':<8} {'AvgW':<8} {'AvgL':<8}")
    print(f"  {'-'*75}")

    for r in results:
        res = r["result"]
        print(
            f"  {r['name']:<15} "
            f"{res['total_trades']:<7} "
            f"{res['win_rate']*100:<6.1f} "
            f"{res['profit_factor']:<6.2f} "
            f"{res['max_drawdown_pct']:<7.2f} "
            f"{res['sharpe_ratio']:<7.2f} "
            f"{res['total_pnl_pct']:<8.2f} "
            f"${res['avg_win']:<7.2f} "
            f"${res['avg_loss']:<7.2f}"
        )

    valid = [r for r in results if r["result"]["total_trades"] >= 10]
    if valid:
        best = max(valid, key=lambda r: r["result"]["profit_factor"])
        res = best["result"]
        print(f"\n  BEST: {best['name']}")
        print(f"  T:{res['total_trades']} WR:{res['win_rate']*100:.1f}% PF:{res['profit_factor']:.2f} DD:{res['max_drawdown_pct']:.2f}% PnL:{res['total_pnl_pct']:.2f}%")

        trades = res.get("trades", [])
        if trades:
            reasons = {}
            for t in trades:
                reason = t.get("close_reason", "unknown")
                reasons[reason] = reasons.get(reason, 0) + 1
            print(f"\n  Exit Reasons:")
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"    {reason:20s}: {count} ({count/len(trades)*100:.1f}%)")

    # Save
    output = {
        "days": days, "candles": len(candles),
        "start": time.strftime('%Y-%m-%d', time.gmtime(candles[0].timestamp/1000)),
        "end": time.strftime('%Y-%m-%d', time.gmtime(candles[-1].timestamp/1000)),
        "configs": [{"name": r["name"], "trades": r["result"]["total_trades"],
            "wr": r["result"]["win_rate"], "pf": r["result"]["profit_factor"],
            "dd": r["result"]["max_drawdown_pct"], "sharpe": r["result"]["sharpe_ratio"],
            "pnl": r["result"]["total_pnl_pct"]} for r in results],
        "timestamp": time.time()
    }
    with open(Path(__file__).parent.parent/"backtest_10d_results.json","w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to backtest_10d_results.json")


if __name__ == "__main__":
    main()
