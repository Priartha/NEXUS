"""Quick sweep: test max_hold_bars and trailing on 15m with full pipeline."""
from __future__ import annotations
import asyncio, sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url); resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=k[0],open=float(k[1]),high=float(k[2]),low=float(k[3]),close=float(k[4]),volume=float(k[5])) for k in data]


async def main():
    print("Fetching 15m candles...")
    candles = await fetch("BTCUSDT", "15m", 1000)
    print(f"Got {len(candles)} candles\n")

    configs = []
    for mh in [25, 35, 50, 75, 100]:
        for trail in [False, True]:
            for be in [0.5, 1.0, 1.5]:
                for risk in [0.01, 0.015, 0.02, 0.025]:
                    configs.append({"max_hold_bars":mh, "trailing_stop":trail, "breakeven_threshold":be, "position_size_pct":risk})

    results = []
    for i, cfg in enumerate(configs):
        engine = BacktestEngine(
            initial_balance=10000, position_size_pct=cfg["position_size_pct"],
            max_hold_bars=cfg["max_hold_bars"], breakeven_threshold=cfg["breakeven_threshold"],
            trailing_stop=cfg["trailing_stop"],
        )
        try:
            r = engine.run(candles, symbol="BTCUSDT", timeframe="15m")
            trades = r["total_trades"]
            if trades >= 10:
                results.append({**cfg, "trades": trades, "wr": r["win_rate"], "pf": r["profit_factor"],
                    "dd": r["max_drawdown_pct"], "sharpe": r["sharpe_ratio"], "pnl": r["total_pnl_pct"]})
        except:
            pass

        if (i+1) % 50 == 0:
            print(f"  {i+1}/{len(configs)} done, {len(results)} valid")

    # Sort by profit factor
    results.sort(key=lambda x: x["pf"], reverse=True)

    print(f"\n{'='*100}")
    print(f"  TOP 20 CONFIGS (sorted by PF)")
    print(f"{'='*100}")
    print(f"  {'#':<3} {'Hold':<5} {'Trail':<6} {'BE':<5} {'Risk%':<6} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<6} {'Sharpe':<7} {'PnL%':<8}")
    print(f"  {'-'*75}")
    for rank, r in enumerate(results[:20], 1):
        print(f"  {rank:<3} {r['max_hold_bars']:<5} {'Y' if r['trailing_stop'] else 'N':<6} {r['breakeven_threshold']:<5.1f} {r['position_size_pct']*100:<6.1f} {r['trades']:<7} {r['wr']*100:<6.1f} {r['pf']:<6.2f} {r['dd']:<6.2f} {r['sharpe']:<7.2f} {r['pnl']:<8.2f}")

    # Also sort by score
    def score(r):
        if r["trades"] < 10: return -1000
        return r["wr"]*50 + min(r["pf"],5.0)*10 - max(0,(r["dd"]-5.0))*3 + max(r["sharpe"],-5.0)*3 + min(r["pnl"],50.0)*0.5 + min(r["trades"]/100.0,1.0)*10

    results.sort(key=score, reverse=True)
    print(f"\n{'='*100}")
    print(f"  TOP 10 BY COMPOSITE SCORE")
    print(f"{'='*100}")
    print(f"  {'#':<3} {'Hold':<5} {'Trail':<6} {'BE':<5} {'Risk%':<6} {'Score':<8} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<6} {'Sharpe':<7} {'PnL%':<8}")
    for rank, r in enumerate(results[:10], 1):
        s = score(r)
        print(f"  {rank:<3} {r['max_hold_bars']:<5} {'Y' if r['trailing_stop'] else 'N':<6} {r['breakeven_threshold']:<5.1f} {r['position_size_pct']*100:<6.1f} {s:<8.1f} {r['trades']:<7} {r['wr']*100:<6.1f} {r['pf']:<6.2f} {r['dd']:<6.2f} {r['sharpe']:<7.2f} {r['pnl']:<8.2f}")

    # Save
    with open(Path(__file__).parent.parent/"sweep_15m_results.json","w") as f:
        json.dump({"top_20_pf": results[:20], "top_10_score": results[:10], "total_tested": len(configs), "total_valid": len(results)}, f, indent=2)
    print(f"\nSaved to sweep_15m_results.json")


if __name__ == "__main__":
    asyncio.run(main())
