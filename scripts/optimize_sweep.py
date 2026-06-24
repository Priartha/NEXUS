"""Comprehensive parameter optimization sweep for NEXUS backtest."""
import asyncio, sys, json, math, time, logging, os
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.CRITICAL)
os.environ["NEXUS_REQUIRE_PROFITABILITY_VALIDATION"] = "false"
os.environ["NEXUS_MIN_CONFIDENCE"] = "0.0"

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch(symbol="BTCUSDT", interval="5m", limit=1500):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url); r.raise_for_status()
        d = r.json()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in d]


def run_bt(candles, **kw):
    params = dict(initial_balance=10000, position_size_pct=0.01, max_concurrent=1,
                  slippage_pct=0.0001, commission_pct=0.0002, max_hold_bars=10,
                  breakeven_threshold=0.8, trailing_stop=True, trailing_atr_multiplier=1.5,
                  tp_atr_multiplier=2.0, sl_atr_multiplier=0.0, require_regime_alignment=False)
    params.update(kw)
    engine = BacktestEngine(**params)
    return engine.run(candles, symbol="BTCUSDT", timeframe="5m")


def score(r):
    if r["total_trades"] < 5:
        return -9999
    pf = min(r["profit_factor"], 10)
    wr = r["win_rate"]
    pnl = min(r["total_pnl_pct"], 100)
    dd = r["max_drawdown_pct"]
    sharpe = max(min(r["sharpe_ratio"], 5), -5)
    cons = r["max_consecutive_losses"]
    return (pf * 25 + wr * 40 + pnl * 0.8 - dd * 1.5 + sharpe * 8 - cons * 3 +
            (r["total_trades"] / 100) * 5)


async def main():
    suppress_stderr()
    print("Fetching BTCUSDT 5m candles...", flush=True)
    candles = await fetch(limit=1500)
    print(f"Got {len(candles)} candles\n", flush=True)

    param_grid = {
        "position_size_pct": [0.005, 0.01, 0.015, 0.02],
        "max_hold_bars": [6, 10, 15, 20, 25, 30],
        "breakeven_threshold": [0.3, 0.5, 0.8, 1.0, 1.5],
        "trailing_stop": [True, False],
        "trailing_atr_multiplier": [1.0, 1.5, 2.0, 2.5],
        "tp_atr_multiplier": [1.5, 2.0, 2.5, 3.0],
    }

    keys = list(param_grid.keys())
    vals = list(param_grid.values())
    total = math.prod(len(v) for v in vals)
    print(f"Sweeping {total} configurations...\n", flush=True)

    header = f"{'Pos%':>5} {'Hold':>5} {'BE':>4} {'Trail':>6} {'TrailMul':>8} {'TPx':>5} | {'Trades':>7} {'WR%':>6} {'PF':>7} {'PnL%':>8} {'DD%':>7} {'Sharpe':>7} {'Score':>8}"
    print(header, flush=True)
    print("-" * len(header), flush=True)

    results = []
    for i, combo in enumerate(product(*vals)):
        kw = dict(zip(keys, combo))
        try:
            r = run_bt(candles, **kw)
            s = score(r)
            results.append((s, kw, r))
            print(f"{kw['position_size_pct']*100:>4.0f}% {kw['max_hold_bars']:>5} {kw['breakeven_threshold']:>4.1f} {str(kw['trailing_stop']):>6} {kw['trailing_atr_multiplier']:>8.1f} {kw['tp_atr_multiplier']:>5.1f} | {r['total_trades']:>7} {r['win_rate']*100:>5.1f}% {r['profit_factor']:>7.2f} {r['total_pnl_pct']:>7.2f}% {r['max_drawdown_pct']:>6.2f}% {r['sharpe_ratio']:>6.2f} {s:>8.1f}", flush=True)
        except Exception as e:
            print(f"{kw['position_size_pct']*100:>4.0f}% {kw['max_hold_bars']:>5} {kw['breakeven_threshold']:>4.1f} {str(kw['trailing_stop']):>6} {kw['trailing_atr_multiplier']:>8.1f} {kw['tp_atr_multiplier']:>5.1f} | ERROR: {e}", flush=True)

    results.sort(key=lambda x: -x[0])
    top = results[:5]

    print("\n" + "=" * len(header), flush=True)
    print("TOP 5 CONFIGURATIONS:", flush=True)
    print("=" * len(header), flush=True)
    for rank, (s, kw, r) in enumerate(top, 1):
        sig = {k: v for k, v in r.items() if k != "trades"}
        print(f"\n#{rank} (Score: {s:.1f})", flush=True)
        print(f"  Params: {json.dumps(kw, default=str)}", flush=True)
        print(f"  Trades: {r['total_trades']}  WR: {r['win_rate']*100:.1f}%  PF: {r['profit_factor']:.2f}")
        print(f"  PnL: ${r['total_pnl']:.2f} ({r['total_pnl_pct']:.2f}%)  DD: {r['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe: {r['sharpe_ratio']:.2f}  MaxConsLoss: {r['max_consecutive_losses']}")

    out = Path(__file__).resolve().parent.parent / "opt_sweep_results.json"
    with open(out, "w") as f:
        json.dump({
            "top_5": [
                {"score": s, "params": {k: v for k, v in kw.items()},
                 "result": {k: v for k, v in r.items() if k != "trades"}}
                for s, kw, r in top
            ],
            "all": [{k: v for k, v in r.items() if k != "trades"} for _, _, r in results],
        }, f, indent=2)
    print(f"\nResults saved to {out}", flush=True)

    best = top[0]
    print(f"\nRECOMMENDED PARAMS:", flush=True)
    print(json.dumps(best[1], indent=2, default=str), flush=True)


def suppress_stderr():
    import os as _os, sys as _sys
    try:
        devnull = _os.open(_os.devnull, _os.O_WRONLY)
        _os.dup2(devnull, 2)
        _os.close(devnull)
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
