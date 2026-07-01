import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch_candles(symbol="BTCUSDT", interval="5m", limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    
    return [Candle(
        timestamp=k[0], open=float(k[1]), high=float(k[2]),
        low=float(k[3]), close=float(k[4]), volume=float(k[5])
    ) for k in data]


async def main():
    print("Fetching 500 candles...")
    candles = await fetch_candles(limit=500)
    print(f"Fetched {len(candles)} candles")
    
    print("Running backtest...")
    engine = BacktestEngine(
        initial_balance=10000.0,
        position_size_pct=0.02,
        max_hold_bars=25,
        breakeven_threshold=1.0,
    )
    result = engine.run(candles, symbol="BTCUSDT", timeframe="5m")
    
    print(f"\nResults:")
    print(f"  Trades: {result['total_trades']}")
    print(f"  Win Rate: {result['win_rate']*100:.1f}%")
    print(f"  P&L: ${result['total_pnl']:.2f} ({result['total_pnl_pct']:.2f}%)")
    print(f"  Profit Factor: {result['profit_factor']:.2f}")
    print(f"  Max DD: {result['max_drawdown_pct']:.2f}%")


if __name__ == "__main__":
    asyncio.run(main())
