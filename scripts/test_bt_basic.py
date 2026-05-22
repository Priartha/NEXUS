"""Minimal backtest test."""
import sys, asyncio, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle

async def fetch(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=60) as c:
        resp = await c.get(url)
        data = resp.json()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in data]

async def main():
    print("Fetching 1000 candles...")
    candles = await fetch(limit=1000)
    print(f"Got {len(candles)} candles")
    print(f"Period: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(candles[0].timestamp/1000))} to "
          f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(candles[-1].timestamp/1000))}")

    from backend.analysis.backtest import BacktestEngine

    configs = [
        # name, hold, trail, be, pos
        ("default", 10, True, 1.0, 0.02),
        ("hold15", 15, True, 1.0, 0.02),
        ("hold20", 20, True, 1.0, 0.02),
        ("hold30", 30, True, 1.0, 0.02),
        ("nt_hold10", 10, False, 1.0, 0.02),
        ("nt_hold20", 20, False, 1.0, 0.02),
        ("nt_hold30", 30, False, 1.0, 0.02),
        ("hold10_pos1", 10, True, 1.0, 0.01),
        ("hold20_pos1", 20, True, 1.0, 0.01),
        ("hold20_pos15", 20, True, 1.0, 0.015),
    ]

    print(f"\n{'Name':<12} {'Hold':>5} {'Trail':>6} {'BE':>4} {'Pos%':>5} {'Trades':>7} {'WR%':>6} {'PF':>7} {'PnL%':>8} {'DD%':>7} {'Sharpe':>7}")
    print("-" * 80)

    for name, hold, trail, be, pos in configs:
        engine = BacktestEngine(initial_balance=10000, position_size_pct=pos, max_concurrent=1,
                                slippage_pct=0.0001, commission_pct=0.0002, max_hold_bars=hold,
                                breakeven_threshold=be, trailing_stop=trail, trailing_atr_multiplier=1.0)
        r = engine.run(candles, symbol="BTCUSDT", timeframe="5m")
        print(f"{name:<12} {hold:>5} {str(trail):>6} {be:>4.1f} {pos*100:>4.0f}% {r['total_trades']:>7} "
              f"{r['win_rate']*100:>5.1f}% {r['profit_factor']:>7.2f} {r['total_pnl_pct']:>7.2f}% "
              f"{r['max_drawdown_pct']:>6.2f}% {r['sharpe_ratio']:>6.2f}")

        if r.get("trades"):
            reasons = {}
            for t in r["trades"]:
                reasons[t.get("close_reason","?")] = reasons.get(t.get("close_reason","?"),0) + 1
            print(f"  {'Exits:':>40} {reasons}")
        print()

if __name__ == "__main__":
    asyncio.run(main())
