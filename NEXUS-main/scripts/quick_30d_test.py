"""Quick fetch + test: gets data first, then runs backtest."""
from __future__ import annotations
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle
from backend.analysis.backtest import BacktestEngine


async def fetch_candles(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url); resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=k[0],open=float(k[1]),high=float(k[2]),low=float(k[3]),close=float(k[4]),volume=float(k[5])) for k in data]


async def main():
    print("Fetching 1000 5m candles...")
    candles = await fetch_candles("BTCUSDT", "5m", 1000)
    days = (candles[-1].timestamp - candles[0].timestamp) / (1000*86400)
    print(f"Got {len(candles)} candles ({days:.1f} days)\n")

    # Test optimized config
    print("Running optimized backtest...")
    engine = BacktestEngine(
        initial_balance=10000, position_size_pct=0.02,
        max_hold_bars=25, breakeven_threshold=1.0, trailing_stop=False,
    )
    result = engine.run(candles, symbol="BTCUSDT", timeframe="5m")

    print(f"\n{'='*60}")
    print(f"  OPTIMIZED BACKTEST (5m, {days:.1f} days)")
    print(f"{'='*60}")
    print(f"  Trades:       {result['total_trades']}")
    print(f"  Win Rate:     {result['win_rate']*100:.1f}%")
    print(f"  Profit Factor:{result['profit_factor']:.2f}")
    print(f"  Max DD:       {result['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe:       {result['sharpe_ratio']:.2f}")
    print(f"  PnL:          {result['total_pnl_pct']:.2f}%")
    print(f"  Avg Win:      ${result['avg_win']:.2f}")
    print(f"  Avg Loss:     ${result['avg_loss']:.2f}")

    # Exit reasons
    trades = result.get("trades", [])
    if trades:
        reasons = {}
        for t in trades:
            r = t.get("close_reason", "unknown")
            reasons[r] = reasons.get(r, 0) + 1
        print(f"\n  Exit Reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:20s}: {count} ({count/len(trades)*100:.1f}%)")

    verdict = "PROFITABLE" if result["profit_factor"] > 1.3 and result["win_rate"] > 0.40 else "NEEDS WORK"
    print(f"\n  VERDICT: [{verdict}]")


if __name__ == "__main__":
    asyncio.run(main())
