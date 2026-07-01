"""Test with zero friction to isolate signal quality."""
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

    configs = [
        {"name": "zero_friction", "slip": 0.0, "comm": 0.0},
        {"name": "futures_realistic", "slip": 0.0001, "comm": 0.0002},
        {"name": "default_config", "slip": 0.0001, "comm": 0.0002},
    ]

    for cfg in configs:
        t0 = time.time()
        engine = BacktestEngine(initial_balance=10000, position_size_pct=0.02,
            max_hold_bars=8, breakeven_threshold=1.0, trailing_stop=False,
            slippage_pct=cfg["slip"], commission_pct=cfg["comm"])
        result = engine.run(candles, symbol="BTCUSDT", timeframe="5m")
        elapsed = time.time() - t0

        rr = result["avg_win"] / result["avg_loss"] if result["avg_loss"] > 0 else 0
        expectancy = result["win_rate"] * result["avg_win"] - (1 - result["win_rate"]) * result["avg_loss"]
        print(f"  {cfg['name']:<20} | T:{result['total_trades']:>3} WR:{result['win_rate']*100:>5.1f}% PF:{result['profit_factor']:>5.2f} DD:{result['max_drawdown_pct']:>5.2f}% PnL:{result['total_pnl_pct']:>7.2f}% AvgW:${result['avg_win']:>7.2f} AvgL:${result['avg_loss']:>7.2f} RR:{rr:.2f} Exp:${expectancy:.2f} [{elapsed:.0f}s]")


if __name__ == "__main__":
    main()
