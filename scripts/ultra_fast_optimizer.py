"""
Ultra-fast optimizer: tests signal thresholds only (no full ICT pipeline).
Uses simplified signal logic to find best parameters, then applies to full pipeline.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import math
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.models.types import Candle


async def fetch(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url); resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=k[0],open=float(k[1]),high=float(k[2]),low=float(k[3]),close=float(k[4]),volume=float(k[5])) for k in data]


def sma(data, period):
    return [sum(data[i-period+1:i+1])/period if i>=period-1 else 0.0 for i in range(len(data))]

def atr(candles, period=14):
    if len(candles)<2: return 0.0
    r = [max(c.high-c.low,abs(c.high-p.close),abs(c.low-p.close)) for p,c in zip(candles[-(period+1):],candles[-(period+1):][1:])]
    return sum(r)/len(r) if r else 0.0

def rsi(closes, period=14):
    if len(closes)<period+1: return 50.0
    g,l = [],[]
    for i in range(1,len(closes)):
        d=closes[i]-closes[i-1]; g.append(max(d,0.0)); l.append(max(-d,0.0))
    ag,al=sum(g[:period])/period,sum(l[:period])/period
    for i in range(period,len(closes)-1): ag=(ag*(period-1)+g[i])/period; al=(al*(period-1)+l[i])/period
    rs=ag/al if al>0 else 100.0
    return 100.0-100.0/(1.0+rs)


def simple_bt(candles, cfg):
    """Fast simplified backtest using SMA/RSI/ATR only."""
    candles = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in candles]
    n = len(candles)
    if n < 100: return None

    s20 = sma(closes, 20); s50 = sma(closes, 50)
    a = atr(candles, 14)

    balance = 10000.0; peak = 10000.0
    results = []; equity = []
    open_trade = None

    for i in range(80, n):
        current = candles[i]
        trend = (s20[i]-s50[i])/s50[i]*100 if s50[i]>0 else 0
        r = rsi(closes[:i+1], 14)
        pb = (closes[i]-s20[i])/s20[i]*100 if s20[i]>0 else 0

        # Entry logic
        if open_trade is None:
            # Buy signal
            if (trend > cfg["min_trend"] and
                cfg["pb_lo"] < pb < cfg["pb_hi"] and
                cfg["rsi_lo"] < r < cfg["rsi_hi"]):
                entry = current.close
                stop = s50[i] if s50[i] < entry else entry - a*cfg["atr_mult"]
                risk = abs(entry-stop)
                if risk >= a*0.5:
                    tp = entry + risk*cfg["rr"]
                    qty = (balance*cfg["risk_pct"])/risk
                    slip = entry*0.0002
                    comm = (entry+slip)*qty*0.0004
                    open_trade = {"side":"buy","entry":entry+slip,"stop":stop,"tp":tp,
                        "qty":qty,"comm":comm,"bars":0,"initial_sl":stop}

            # Sell signal
            elif (trend < -cfg["min_trend"] and
                  cfg["pb_lo_sell"] < pb < cfg["pb_hi_sell"] and
                  cfg["rsi_lo_sell"] < r < cfg["rsi_hi_sell"]):
                entry = current.close
                stop = s50[i] if s50[i] > entry else entry + a*cfg["atr_mult"]
                risk = abs(entry-stop)
                if risk >= a*0.5:
                    tp = entry - risk*cfg["rr"]
                    qty = (balance*cfg["risk_pct"])/risk
                    slip = entry*0.0002
                    comm = (entry-slip)*qty*0.0004
                    open_trade = {"side":"sell","entry":entry-slip,"stop":stop,"tp":tp,
                        "qty":qty,"comm":comm,"bars":0,"initial_sl":stop}
        else:
            t = open_trade
            t["bars"] += 1

            # Trailing stop
            if cfg["trailing"]:
                if t["side"]=="buy":
                    trail = current.high - a*cfg["trail_atr"]
                    t["stop"] = max(t["stop"], trail)
                    if (current.high-t["entry"])/abs(t["entry"]-t["initial_sl"]) >= cfg["be_thresh"]:
                        t["stop"] = max(t["stop"], t["entry"])
                else:
                    trail = current.low + a*cfg["trail_atr"]
                    t["stop"] = min(t["stop"], trail)
                    if (t["entry"]-current.low)/abs(t["entry"]-t["initial_sl"]) >= cfg["be_thresh"]:
                        t["stop"] = min(t["stop"], t["entry"])

            closed = False
            # Time exit
            if t["bars"] >= cfg["max_hold"]:
                ep = current.close
                pnl = (ep-t["entry"])*t["qty"] if t["side"]=="buy" else (t["entry"]-ep)*t["qty"]
                pnl -= t["comm"]
                results.append({"pnl":pnl,"reason":"time"}); balance += pnl; closed = True
            # SL
            elif (t["side"]=="buy" and current.low <= t["stop"]) or (t["side"]=="sell" and current.high >= t["stop"]):
                pnl = (t["stop"]-t["entry"])*t["qty"] if t["side"]=="buy" else (t["entry"]-t["stop"])*t["qty"]
                pnl -= t["comm"]
                results.append({"pnl":pnl,"reason":"sl"}); balance += pnl; closed = True
            # TP
            elif (t["side"]=="buy" and current.high >= t["tp"]) or (t["side"]=="sell" and current.low <= t["tp"]):
                pnl = (t["tp"]-t["entry"])*t["qty"] if t["side"]=="buy" else (t["entry"]-t["tp"])*t["qty"]
                pnl -= t["comm"]
                results.append({"pnl":pnl,"reason":"tp"}); balance += pnl; closed = True

            if closed:
                open_trade = None

        if balance > peak: peak = balance
        dd = (peak-balance)/peak*100 if peak>0 else 0
        if i%10==0: equity.append({"balance":balance,"dd":dd})

    wins = [r for r in results if r["pnl"]>0]
    losses = [r for r in results if r["pnl"]<=0]
    t_count = len(results)
    if t_count < 5: return None

    wr = len(wins)/t_count
    gp = sum(r["pnl"] for r in wins); gl = abs(sum(r["pnl"] for r in losses))
    pf = gp/gl if gl>0 else 999.99
    dd_max = max(e["dd"] for e in equity)
    rets = [e["balance"]/10000-1 for e in equity]
    avg_r = sum(rets)/len(rets); std_r = (sum((x-avg_r)**2 for x in rets)/len(rets))**0.5
    sharpe = (avg_r/std_r*math.sqrt(365)) if std_r>0 else 0

    return {"trades":t_count,"win_rate":wr,"profit_factor":round(pf,4),"max_dd":round(dd_max,4),
        "sharpe":round(sharpe,4),"pnl_pct":round((balance-10000)/10000*100,4),
        "avg_win":round(gp/len(wins),2) if wins else 0,"avg_loss":round(gl/len(losses),2) if losses else 0,
        "final_balance":round(balance,2)}


def score(r):
    if r["trades"]<10: return -1000
    return r["win_rate"]*50 + min(r["profit_factor"],5.0)*10 - max(0,(r["max_dd"]-5.0))*3 + max(r["sharpe"],-5.0)*3 + min(r["pnl_pct"],50.0)*0.5 + min(r["trades"]/100.0,1.0)*10


# ── Test configs ──
CONFIGS = [
    # name, min_trend, pb_lo, pb_hi, pb_lo_sell, pb_hi_sell, rsi_lo, rsi_hi, rsi_lo_sell, rsi_hi_sell, rr, atr_mult, trailing, trail_atr, be_thresh, max_hold, risk_pct
    ("original",     0.25, -2.5, 0.5,  -0.5, 2.5,  25, 60, 40, 75,  3.0, 1.5, True,  1.0, 1.0, 25, 0.02),
    ("relaxed_1",    0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 1.5, True,  1.0, 1.0, 25, 0.02),
    ("relaxed_2",    0.10, -5.0, 1.5,  -1.5, 5.0,  15, 70, 30, 85,  2.0, 2.0, True,  1.0, 0.8, 25, 0.02),
    ("moderate",     0.20, -3.0, 0.5,  -0.5, 3.0,  25, 60, 40, 75,  3.0, 1.5, True,  1.0, 1.0, 25, 0.02),
    ("tight_rr",     0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.0, 1.0, True,  0.8, 0.8, 25, 0.02),
    ("high_rr",      0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  3.5, 1.5, True,  1.0, 1.0, 25, 0.02),
    ("no_trail",     0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 1.5, False, 1.0, 1.0, 25, 0.02),
    ("short_hold",   0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 1.5, True,  0.8, 0.5, 12, 0.02),
    ("long_hold",    0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 1.5, True,  1.5, 1.0, 50, 0.02),
    ("low_risk",     0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 1.5, True,  1.0, 1.0, 25, 0.01),
    ("high_risk",    0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 1.5, True,  1.0, 1.0, 25, 0.025),
    ("very_loose",   0.10, -6.0, 2.0,  -2.0, 6.0,  10, 75, 25, 90,  2.0, 2.0, True,  1.0, 0.5, 35, 0.02),
    ("tight_conf",   0.20, -2.0, 0.5,  -0.5, 2.0,  30, 55, 45, 70,  3.0, 1.0, True,  0.8, 1.0, 25, 0.02),
    ("wide_atr",     0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 2.0, True,  1.5, 1.0, 35, 0.02),
    ("partial_be",   0.15, -4.0, 1.0,  -1.0, 4.0,  20, 65, 35, 80,  2.5, 1.5, True,  1.0, 0.5, 25, 0.02),
]


async def main():
    print("="*80)
    print("  NEXUS ULTRA-FAST OPTIMIZER")
    print("="*80)

    print("\nFetching data...")
    async with httpx.AsyncClient(timeout=30) as client:
        data = {}
        for tf in ["5m","15m","1h"]:
            try:
                url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={tf}&limit=1000"
                resp = await client.get(url); resp.raise_for_status()
                klines = resp.json()
                data[tf] = [Candle(timestamp=k[0],open=float(k[1]),high=float(k[2]),low=float(k[3]),close=float(k[4]),volume=float(k[5])) for k in klines]
                print(f"  {tf}: {len(data[tf])} candles")
            except Exception as e:
                print(f"  {tf}: FAILED - {e}")

    all_results = []
    total = len(CONFIGS)*len(data)
    idx = 0

    print(f"\nTesting {len(CONFIGS)} configs × {len(data)} timeframes = {total} combos\n")

    for tf, candles in data.items():
        if len(candles)<100: continue
        print(f"\n{'='*60}\n  {tf} ({len(candles)} candles)\n{'='*60}")

        for cfg_tuple in CONFIGS:
            idx += 1
            name,mt,pblo,pbhi,pblos,pbhis,rsilo,rsihi,rsilos,rsihis,rr,am,tr,ta,bt,mh,rp = cfg_tuple
            cfg = {"min_trend":mt,"pb_lo":pblo,"pb_hi":pbhi,"pb_lo_sell":pblos,"pb_hi_sell":pbhis,
                "rsi_lo":rsilo,"rsi_hi":rsihi,"rsi_lo_sell":rsilos,"rsi_hi_sell":rsihis,
                "rr":rr,"atr_mult":am,"trailing":tr,"trail_atr":ta,"be_thresh":bt,"max_hold":mh,"risk_pct":rp}
            try:
                result = simple_bt(candles, cfg)
                if result:
                    s = score(result)
                    all_results.append({"score":s,"timeframe":tf,"name":name,"cfg":cfg,"results":result})
                    print(f"  {idx:>3}/{total} | {name:<15} | Trades:{result['trades']:>3} WR:{result['win_rate']*100:>5.1f}% PF:{result['profit_factor']:>5.2f} DD:{result['max_dd']:>5.2f}% Sharpe:{result['sharpe']:>6.2f} PnL:{result['pnl_pct']:>7.2f}% | Score:{s:.1f}")
            except Exception as e:
                print(f"  {idx:>3}/{total} | {name:<15} | ERROR: {e}")

    all_results.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'='*80}")
    print(f"  TOP CONFIGURATIONS")
    print(f"{'='*80}")
    print(f"  {'#':<3} {'TF':<5} {'Name':<16} {'Score':<7} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<6} {'Sharpe':<7} {'PnL%':<8}")
    print(f"  {'-'*65}")
    for rank, r in enumerate(all_results, 1):
        res = r["results"]
        print(f"  {rank:<3} {r['timeframe']:<5} {r['name']:<16} {r['score']:<7.1f} {res['trades']:<7} {res['win_rate']*100:<6.1f} {res['profit_factor']:<6.2f} {res['max_dd']:<6.2f} {res['sharpe']:<7.2f} {res['pnl_pct']:<8.2f}")

    if all_results:
        best = all_results[0]
        res = best["results"]
        print(f"\n{'='*80}")
        print(f"  WINNER: {best['name']} on {best['timeframe']}")
        print(f"  Score:{best['score']:.1f} Trades:{res['trades']} WR:{res['win_rate']*100:.1f}% PF:{res['profit_factor']:.2f} DD:{res['max_dd']:.2f}% Sharpe:{res['sharpe']:.2f} PnL:{res['pnl_pct']:.2f}%")
        print(f"{'='*80}")

        # Save
        output = {"best":{"name":best["name"],"timeframe":best["timeframe"],"cfg":best["cfg"],"results":res,"score":best["score"]},
            "all":[{"rank":i+1,"name":r["name"],"timeframe":r["timeframe"],"score":r["score"],"results":r["results"]} for i,r in enumerate(all_results)],
            "timestamp":time.time()}
        with open(Path(__file__).parent.parent/"optimization_results.json","w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nSaved to optimization_results.json")


if __name__ == "__main__":
    asyncio.run(main())
