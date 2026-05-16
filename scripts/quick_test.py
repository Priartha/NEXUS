"""Quick single-config test on fetched data."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.backtest import BacktestEngine


def main():
    print("Loading candles...")
    with open(Path(__file__).parent.parent/"fetched_candles.json") as f:
        raw = json.load(f)
    candles = [Candle(timestamp=c["t"],open=c["o"],high=c["h"],low=c["l"],close=c["c"],volume=c["v"]) for c in raw]
    candles.sort(key=lambda c: c.timestamp)
    days = (candles[-1].timestamp - candles[0].timestamp) / (1000*86400)
    print(f"{len(candles)} candles, {days:.1f} days\n")

    t0 = time.time()
    engine = BacktestEngine(initial_balance=10000, position_size_pct=0.02,
        max_hold_bars=10, breakeven_threshold=1.0, trailing_stop=False,
        slippage_pct=0.0001, commission_pct=0.0002)
    result = engine.run(candles, symbol="BTCUSDT", timeframe="5m")
    elapsed = time.time() - t0

    print(f"Time: {elapsed:.0f}s")
    print(f"Trades: {result['total_trades']}")
    print(f"WR: {result['win_rate']*100:.1f}%")
    print(f"PF: {result['profit_factor']:.2f}")
    print(f"DD: {result['max_drawdown_pct']:.2f}%")
    print(f"PnL: {result['total_pnl_pct']:.2f}%")
    print(f"AvgWin: ${result['avg_win']:.2f}")
    print(f"AvgLoss: ${result['avg_loss']:.2f}")

    trades = result.get("trades", [])
    if trades:
        reasons = {}
        for t in trades:
            r = t.get("close_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
        print(f"\nExit Reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason:20s}: {count} ({count/len(trades)*100:.1f}%)")

    v = "PROFITABLE" if result["profit_factor"] > 1.0 and result["win_rate"] > 0.40 else "NOT PROFITABLE"
    print(f"\nVERDICT: [{v}]")


if __name__ == "__main__":
    main()
