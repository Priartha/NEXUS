"""Check if strategy is profitable - simplified fast test."""
import sys, asyncio, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle
from backend.analysis.backtest import BacktestEngine


async def fetch(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=60) as c:
        resp = await c.get(url)
        data = resp.json()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in data]


def run_bt(candles, timeframe="5m", **kw):
    params = dict(initial_balance=10000, position_size_pct=0.02, max_concurrent=1,
                  slippage_pct=0.0001, commission_pct=0.0002, max_hold_bars=30,
                  breakeven_threshold=1.0, trailing_stop=False, trailing_atr_multiplier=1.0)
    params.update(kw)
    engine = BacktestEngine(**params)
    return engine.run(candles, symbol="BTCUSDT", timeframe=timeframe)


async def main():
    print("=== NEXUS PROFITABILITY CHECK ===\n")
    print("Fetching 5m data...")
    c5 = await fetch(limit=1000)
    print("5m: %d candles (%s - %s)" % (len(c5),
        time.strftime("%m/%d %H:%M", time.gmtime(c5[0].timestamp/1000)),
        time.strftime("%m/%d %H:%M", time.gmtime(c5[-1].timestamp/1000))))

    print("\nFetching 15m data...")
    c15 = await fetch(interval="15m", limit=1000)
    print("15m: %d candles (%s - %s)" % (len(c15),
        time.strftime("%m/%d %H:%M", time.gmtime(c15[0].timestamp/1000)),
        time.strftime("%m/%d %H:%M", time.gmtime(c15[-1].timestamp/1000))))

    configs = [
        ("5m_h10_nt",  c5,  "5m",  10, False),
        ("5m_h20_nt",  c5,  "5m",  20, False),
        ("5m_h30_nt",  c5,  "5m",  30, False),
        ("5m_h40_nt",  c5,  "5m",  40, False),
        ("5m_h50_nt",  c5,  "5m",  50, False),
        ("5m_h30_t",   c5,  "5m",  30, True),
        ("15m_h20_nt", c15, "15m", 20, False),
        ("15m_h30_nt", c15, "15m", 30, False),
        ("15m_h40_nt", c15, "15m", 40, False),
        ("15m_h60_nt", c15, "15m", 60, False),
        ("15m_h30_t",  c15, "15m", 30, True),
    ]

    print()
    hdr = "%-16s %3s %5s %6s %7s %6s %7s %8s %7s %7s" % ("Name","TF","Hold","Trail","Trades","WR%","PF","PnL%","DD%","Sharpe")
    print(hdr)
    print("-" * 75)

    results = []
    for name, candles, tf, hold, trail in configs:
        t0 = time.time()
        r = run_bt(candles, timeframe=tf, max_hold_bars=hold, trailing_stop=trail)
        results.append((name, r))
        print("%-16s %3s %5d %6s %7d %5.1f%% %7.2f %7.2f%% %6.2f%% %7.2f  [%ds]" % (
            name, tf, hold, str(trail), r['total_trades'],
            r['win_rate']*100, r['profit_factor'], r['total_pnl_pct'],
            r['max_drawdown_pct'], r['sharpe_ratio'], time.time()-t0))

    print("\n" + "=" * 75)
    best = max(results, key=lambda x: x[1]['profit_factor'] if x[1]['total_trades'] >= 5 and x[1]['profit_factor'] < 999 else 0)
    best_name, best_r = best
    print("BEST: %s" % best_name)
    print("  Trades: %d  WR: %.1f%%  PF: %.2f" % (best_r['total_trades'], best_r['win_rate']*100, best_r['profit_factor']))
    print("  PnL: %.2f%%  DD: %.2f%%  Sharpe: %.2f" % (best_r['total_pnl_pct'], best_r['max_drawdown_pct'], best_r['sharpe_ratio']))

    if best_r['profit_factor'] >= 1.5 and best_r['win_rate'] >= 0.35:
        print("\nVERDICT: PROFITABLE (PF >= 1.5)")
    elif best_r['profit_factor'] >= 1.0:
        print("\nVERDICT: MARGINALLY PROFITABLE (PF = %.2f)" % best_r['profit_factor'])
    else:
        print("\nVERDICT: NOT PROFITABLE (PF = %.2f)" % best_r['profit_factor'])

    profitable = [(n, r) for n, r in results if r['profit_factor'] >= 1.5 and r['win_rate'] >= 0.35 and r['total_trades'] >= 5]
    if profitable:
        print("\nProfitable configs (%d):" % len(profitable))
        for n, r in profitable:
            print("  + %s: WR=%.1f%% PF=%.2f PnL=%.2f%% DD=%.2f%%" % (n, r['win_rate']*100, r['profit_factor'], r['total_pnl_pct'], r['max_drawdown_pct']))

    with open(Path(__file__).resolve().parent.parent/"profit_check.json","w") as f:
        json.dump({"best": best_name, "results": {n: {k:v for k,v in r.items() if k!="trades"} for n,r in results}}, f, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
