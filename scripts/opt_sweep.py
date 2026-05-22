"""Sweep TP/SL multipliers - focused."""
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
                  slippage_pct=0.0001, commission_pct=0.0002, max_hold_bars=40,
                  breakeven_threshold=1.0, trailing_stop=False)
    params.update(kw)
    engine = BacktestEngine(**params)
    return engine.run(candles, symbol="BTCUSDT", timeframe=timeframe)


async def main():
    print("Fetching data...")
    c15 = await fetch(interval="15m", limit=1000)
    c5 = await fetch(limit=1000)
    t0 = time.time()
    rows = []

    # Configs: (tf_name, candles, hold, tp_atr, sl_atr, trail)
    configs = [
        # 15m - varying TP
        ("15m", c15, 30, 3, 2, False),
        ("15m", c15, 30, 4, 2, False),
        ("15m", c15, 30, 5, 2, False),
        ("15m", c15, 40, 3, 2, False),
        ("15m", c15, 40, 4, 2, False),
        ("15m", c15, 40, 5, 2, False),
        ("15m", c15, 50, 3, 2, False),
        ("15m", c15, 50, 4, 2, False),
        ("15m", c15, 50, 5, 2, False),
        # 5m - varying TP
        ("5m", c5, 30, 3, 2, False),
        ("5m", c5, 40, 3, 2, False),
        ("5m", c5, 40, 4, 2, False),
        ("5m", c5, 50, 3, 2, False),
        # 15m - with trailing
        ("15m", c15, 40, 4, 2, True),
        ("15m", c15, 30, 4, 2, True),
        # 15m - varying SL
        ("15m", c15, 40, 4, 1.5, False),
        ("15m", c15, 40, 3, 1.5, False),
    ]

    print("\n%-6s %5s %4s %4s %7s %7s %6s %7s %8s %7s %7s" % ("TF","Hold","TP(A)","SL(A)","Trail","Trades","WR%","PF","PnL%","DD%","Sharpe"))
    print("-" * 85)

    for tf_name, candles, hold, tp_atr, sl_atr, trail in configs:
        r = run_bt(candles, timeframe=tf_name, max_hold_bars=hold,
                   tp_atr_multiplier=tp_atr, sl_atr_multiplier=sl_atr,
                   trailing_stop=trail)
        rows.append((tf_name, hold, tp_atr, sl_atr, trail, r))
        print("%-6s %5d %4d %4.1f %7s %7d %5.1f%% %7.2f %7.2f%% %6.2f%% %7.2f" % (
            tf_name, hold, tp_atr, sl_atr, str(trail)[0],
            r['total_trades'], r['win_rate']*100, r['profit_factor'],
            r['total_pnl_pct'], r['max_drawdown_pct'], r['sharpe_ratio']))

    print("\n" + "=" * 85)
    scored = []
    for tf_name, hold, tp_atr, sl_atr, trail, r in rows:
        if r['total_trades'] < 3:
            continue
        s = r['profit_factor']*10 + r['win_rate']*5 - max(0,(r['max_drawdown_pct']-10))*2 + min(r['total_pnl_pct'],30)*0.5
        if r['profit_factor'] >= 1.5 and r['win_rate'] >= 0.35:
            s += 20
        scored.append((s, tf_name, hold, tp_atr, sl_atr, trail, r))

    scored.sort(key=lambda x: -x[0])
    print("\nRANKED:")
    print("%-6s %5s %4s %4s %7s %7s %6s %7s %8s %7s %7s %6s" % ("TF","Hold","TP(A)","SL(A)","Trail","Trades","WR%","PF","PnL%","DD%","Sharpe","Score"))
    for s, tf_name, hold, tp_atr, sl_atr, trail, r in scored:
        print("%-6s %5d %4d %4.1f %7s %7d %5.1f%% %7.2f %7.2f%% %6.2f%% %7.2f %6.1f" % (
            tf_name, hold, tp_atr, sl_atr, str(trail)[0],
            r['total_trades'], r['win_rate']*100, r['profit_factor'],
            r['total_pnl_pct'], r['max_drawdown_pct'], r['sharpe_ratio'], s))

    best = scored[0]
    _, tf_name, hold, tp_atr, sl_atr, trail, best_r = best
    print("\n=== BEST CONFIG ===")
    print("  TF=%s Hold=%d TP=%dATR SL=%.1fATR Trail=%s" % (tf_name, hold, tp_atr, sl_atr, str(trail)))
    print("  Trades: %d  WR: %.1f%%  PF: %.2f  PnL: %.2f%%  DD: %.2f%%" % (
        best_r['total_trades'], best_r['win_rate']*100, best_r['profit_factor'],
        best_r['total_pnl_pct'], best_r['max_drawdown_pct']))

    pf = best_r['profit_factor']
    if pf >= 1.5:
        print("  VERDICT: PROFITABLE!")
    elif pf >= 1.0:
        print("  VERDICT: MARGINALLY PROFITABLE (PF=%.2f)" % pf)
    else:
        print("  VERDICT: NOT PROFITABLE (PF=%.2f)" % pf)

    print("\nElapsed: %ds" % (time.time()-t0))


if __name__ == "__main__":
    asyncio.run(main())
