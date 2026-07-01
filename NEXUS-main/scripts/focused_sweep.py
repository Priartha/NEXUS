"""Quick focused sweep: key 15m configs with full pipeline."""
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
    print("Fetching candles...")
    candles_15m = await fetch("BTCUSDT", "15m", 1000)
    candles_5m = await fetch("BTCUSDT", "5m", 1000)
    print(f"15m: {len(candles_15m)}, 5m: {len(candles_5m)}\n")

    # Focused configs
    configs = [
        # 15m configs
        {"tf":"15m","max_hold_bars":25,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":35,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":75,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":100,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":0.5,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":1.5,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":True,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":True,"breakeven_threshold":1.5,"position_size_pct":0.02},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.01},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.015},
        {"tf":"15m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.025},
        # 5m configs
        {"tf":"5m","max_hold_bars":25,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"5m","max_hold_bars":35,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"5m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"5m","max_hold_bars":25,"trailing_stop":True,"breakeven_threshold":1.0,"position_size_pct":0.02},
        {"tf":"5m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":0.5,"position_size_pct":0.02},
        {"tf":"5m","max_hold_bars":50,"trailing_stop":False,"breakeven_threshold":1.5,"position_size_pct":0.02},
    ]

    results = []
    for i, cfg in enumerate(configs):
        candles = candles_15m if cfg["tf"]=="15m" else candles_5m
        engine = BacktestEngine(
            initial_balance=10000, position_size_pct=cfg["position_size_pct"],
            max_hold_bars=cfg["max_hold_bars"], breakeven_threshold=cfg["breakeven_threshold"],
            trailing_stop=cfg["trailing_stop"],
        )
        try:
            r = engine.run(candles, symbol="BTCUSDT", timeframe=cfg["tf"])
            trades = r["total_trades"]
            results.append({**cfg, "trades": trades, "wr": r["win_rate"], "pf": r["profit_factor"],
                "dd": r["max_drawdown_pct"], "sharpe": r["sharpe_ratio"], "pnl": r["total_pnl_pct"],
                "avg_win": r["avg_win"], "avg_loss": r["avg_loss"], "final": r["final_balance"]})
            print(f"  {i+1:>2}/{len(configs)} | {cfg['tf']:<3} Hold={cfg['max_hold_bars']:>3} Trail={'Y' if cfg['trailing_stop'] else 'N':<1} BE={cfg['breakeven_threshold']:<4} Risk={cfg['position_size_pct']*100:.0f}% | T:{trades:>3} WR:{r['win_rate']*100:>5.1f}% PF:{r['profit_factor']:>5.2f} DD:{r['max_drawdown_pct']:>5.2f}% S:{r['sharpe_ratio']:>7.2f} PnL:{r['total_pnl_pct']:>7.2f}%")
        except Exception as e:
            print(f"  {i+1:>2}/{len(configs)} | {cfg['tf']:<3} ERROR: {e}")

    # Sort by score
    def score(r):
        t = r["trades"]
        if t < 5: return -1000
        return r["wr"]*50 + min(r["pf"],5.0)*10 - max(0,(r["dd"]-5.0))*3 + max(r["sharpe"],-5.0)*3 + min(r["pnl"],50.0)*0.5 + min(t/100.0,1.0)*10

    results.sort(key=score, reverse=True)

    print(f"\n{'='*110}")
    print(f"  ALL CONFIGS BY SCORE")
    print(f"{'='*110}")
    print(f"  {'#':<3} {'TF':<4} {'Hold':<5} {'Trail':<6} {'BE':<5} {'Risk%':<6} {'Score':<8} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<6} {'Sharpe':<7} {'PnL%':<8} {'AvgW':<8} {'AvgL':<8}")
    print(f"  {'-'*105}")
    for rank, r in enumerate(results, 1):
        s = score(r)
        print(f"  {rank:<3} {r['tf']:<4} {r['max_hold_bars']:<5} {'Y' if r['trailing_stop'] else 'N':<6} {r['breakeven_threshold']:<5.1f} {r['position_size_pct']*100:<6.1f} {s:<8.1f} {r['trades']:<7} {r['wr']*100:<6.1f} {r['pf']:<6.2f} {r['dd']:<6.2f} {r['sharpe']:<7.2f} {r['pnl']:<8.2f} ${r['avg_win']:<7.2f} ${r['avg_loss']:<7.2f}")

    best = results[0]
    print(f"\n{'='*110}")
    print(f"  BEST: {best['tf']} Hold={best['max_hold_bars']} Trail={'Y' if best['trailing_stop'] else 'N'} BE={best['breakeven_threshold']} Risk={best['position_size_pct']*100}%")
    print(f"  Score:{score(best):.1f} T:{best['trades']} WR:{best['wr']*100:.1f}% PF:{best['pf']:.2f} DD:{best['dd']:.2f}% S:{best['sharpe']:.2f} PnL:{best['pnl']:.2f}%")
    print(f"  AvgWin:${best['avg_win']:.2f} AvgLoss:${best['avg_loss']:.2f} RR:{best['avg_win']/best['avg_loss'] if best['avg_loss']>0 else 0:.2f}")
    print(f"{'='*110}")

    with open(Path(__file__).parent.parent/"focused_sweep_results.json","w") as f:
        json.dump({"all":results, "best":best}, f, indent=2)
    print(f"\nSaved to focused_sweep_results.json")


if __name__ == "__main__":
    asyncio.run(main())
