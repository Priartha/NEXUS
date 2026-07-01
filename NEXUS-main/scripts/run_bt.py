"""Quick backtest runner - standalone."""
import asyncio, sys, json, time, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch(symbol="BTCUSDT", interval="5m", limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in data]


def run_bt(candles, **kw):
    params = dict(
        initial_balance=10000, position_size_pct=0.02, max_concurrent=1,
        slippage_pct=0.0001, commission_pct=0.0002, max_hold_bars=10,
        breakeven_threshold=1.0, trailing_stop=True, trailing_atr_multiplier=1.0
    )
    params.update(kw)
    engine = BacktestEngine(**params)
    return engine.run(candles, symbol="BTCUSDT", timeframe=params.pop("timeframe", "5m"))


def print_r(r):
    print(f"  Candles: {r['candle_count']}  Period: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['start_date']/1000))} - {time.strftime('%Y-%m-%d %H:%M', time.gmtime(r['end_date']/1000))}")
    print(f"  Initial: ${r['initial_balance']:,.0f}  Final: ${r['final_balance']:,.2f}  P&L: ${r['total_pnl']:,.2f} ({r['total_pnl_pct']:.2f}%)")
    print(f"  Trades: {r['total_trades']}  Win: {r['winning_trades']}  Loss: {r['losing_trades']}  WR: {r['win_rate']*100:.1f}%")
    print(f"  AvgWin: ${r['avg_win']:,.2f}  AvgLoss: ${r['avg_loss']:,.2f}  PF: {r['profit_factor']:.2f}")
    print(f"  MaxDD: ${r['max_drawdown']:,.2f} ({r['max_drawdown_pct']:.2f}%)  Sharpe: {r['sharpe_ratio']:.2f}  MaxConsLoss: {r['max_consecutive_losses']}")
    if r.get("trades"):
        reasons = {}
        for t in r["trades"]:
            reasons[t.get("close_reason","?")] = reasons.get(t.get("close_reason","?"),0) + 1
        print(f"  Exits: {reasons}")


async def main():
    print("Fetching BTCUSDT 5m candles...")
    candles = await fetch(limit=1000)
    print(f"Got {len(candles)} candles\n")

    configs = [
        # (max_hold, trail, be_threshold, pos_size, commissions)
        (10, True, 1.0, 0.02),
        (15, True, 1.0, 0.02),
        (20, True, 1.0, 0.02),
        (30, True, 1.0, 0.02),
        (10, False, 1.0, 0.02),
        (15, False, 1.0, 0.02),
        (20, False, 1.0, 0.02),
        (30, False, 1.0, 0.02),
        (10, True, 0.8, 0.02),
        (20, True, 0.8, 0.02),
        (10, True, 1.5, 0.02),
        (20, True, 1.5, 0.02),
        (10, True, 1.0, 0.015),
        (10, True, 1.0, 0.01),
        (10, False, 1.0, 0.01),
    ]

    print(f"{'Hold':>5} {'Trail':>6} {'BE':>4} {'Pos%':>5} {'Trades':>7} {'WR%':>6} {'PF':>7} {'PnL%':>8} {'DD%':>7} {'Sharpe':>7} {'Score':>7}")
    print("-" * 80)

    results = []
    for hold, trail, be, pos in configs:
        try:
            r = run_bt(candles, max_hold_bars=hold, trailing_stop=trail, breakeven_threshold=be, position_size_pct=pos)
            t = r['total_trades']
            score = r['win_rate']*50 + min(r['profit_factor'],5)*10 - max(0,(r['max_drawdown_pct']-10))*2 + max(r['sharpe_ratio'],-3)*5 + min(r['total_pnl_pct'],50)*0.5
            if t < 3: score = -999
            results.append((score, hold, trail, be, pos, r))
            print(f"{hold:>5} {str(trail):>6} {be:>4.1f} {pos*100:>4.0f}% {r['total_trades']:>7} {r['win_rate']*100:>5.1f}% {r['profit_factor']:>7.2f} {r['total_pnl_pct']:>7.2f}% {r['max_drawdown_pct']:>6.2f}% {r['sharpe_ratio']:>6.2f} {score:>7.1f}")
        except Exception as e:
            print(f"{hold:>5} {str(trail):>6} {be:>4.1f} {pos*100:>4.0f}% ERROR: {e}")

    results.sort(key=lambda x: -x[0])
    best = results[0]

    print("\n" + "="*80)
    print(f"BEST: Hold={best[2]} Trail={best[3]} BE={best[4]} Pos={best[5]*100}%")
    print("="*80)
    print_r(best[6])

    # Save
    with open(Path(__file__).parent.parent/"bt_results.json","w") as f:
        json.dump({"best_params": {"hold":best[2],"trail":best[3],"be":best[4],"pos":best[5]},
                   "best_result": {k:v for k,v in best[6].items() if k!="trades"},
                   "all": [{k:v for k,v in r[6].items() if k!="trades"} for r in results]}, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
