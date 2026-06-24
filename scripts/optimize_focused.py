"""Focused parameter sweep around best-known region."""
import asyncio, sys, json, math, logging, os
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
                  tp_atr_multiplier=2.0, sl_atr_multiplier=0.0, require_regime_alignment=False,
                  signal_side_mode="normal", avoid_reason_tokens=None, funding_rate_per_8h=-0.0001)
    params.update(kw)
    engine = BacktestEngine(**params)
    return engine.run(candles, symbol="BTCUSDT", timeframe="5m")

def score(r):
    if r["total_trades"] < 5: return -9999
    pf = min(r["profit_factor"], 10)
    wr = r["win_rate"]
    pnl = min(r["total_pnl_pct"], 100)
    dd = r["max_drawdown_pct"]
    sharpe = max(min(r["sharpe_ratio"], 5), -5)
    cons = r["max_consecutive_losses"]
    avg_win = r.get("avg_win", 0)
    avg_loss = r.get("avg_loss", 1)
    win_loss_ratio = avg_win / max(abs(avg_loss), 1)
    return (pf * 30 + wr * 35 + pnl * 1.0 - dd * 2.0 + sharpe * 10 - cons * 4 + win_loss_ratio * 3)

async def main():
    print("Fetching 1500 BTCUSDT 5m candles...", flush=True)
    candles = await fetch(limit=1500)
    print(f"Got {len(candles)} candles", flush=True)

    param_grid = {
        "position_size_pct": [0.005, 0.0075, 0.01, 0.015],
        "max_hold_bars": [4, 6, 8, 10, 12, 15],
        "breakeven_threshold": [0.3, 0.5, 0.8, 1.0],
        "trailing_atr_multiplier": [1.0, 1.5, 2.0, 2.5],
        "tp_atr_multiplier": [2.0, 2.5, 3.0, 3.5],
    }

    keys = list(param_grid.keys())
    vals = list(param_grid.values())
    total = math.prod(len(v) for v in vals)
    results = []

    print(f"Sweeping {total} configs (all with trailing_stop=True)...", flush=True)
    for i, combo in enumerate(product(*vals)):
        kw = dict(zip(keys, combo))
        kw["trailing_stop"] = True
        try:
            r = run_bt(candles, **kw)
            s = score(r)
            results.append((s, kw, r))
        except Exception as e:
            pass
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{total} done", flush=True)

    results.sort(key=lambda x: -x[0])
    top = results[:20]

    print("\n" + "=" * 100)
    print("TOP 20 CONFIGURATIONS (sorted by composite score)")
    print("=" * 100)
    hdr = f"{'#':>2} {'Pos%':>5} {'Hold':>5} {'BE':>4} {'TrailMult':>9} {'TPx':>5} | {'Trades':>7} {'WR%':>6} {'PF':>7} {'PnL%':>8} {'DD%':>7} {'Sharpe':>7} {'Score':>8}"
    print(hdr)
    print("-" * len(hdr))
    for rank, (s, kw, r) in enumerate(top, 1):
        print(f"{rank:>2} {kw['position_size_pct']*100:>4.0f}% {kw['max_hold_bars']:>5} {kw['breakeven_threshold']:>4.1f} {kw['trailing_atr_multiplier']:>9.1f} {kw['tp_atr_multiplier']:>5.1f} | {r['total_trades']:>7} {r['win_rate']*100:>5.1f}% {r['profit_factor']:>7.2f} {r['total_pnl_pct']:>7.2f}% {r['max_drawdown_pct']:>6.2f}% {r['sharpe_ratio']:>6.2f} {s:>8.1f}")

    print("\n" + "=" * 100)
    print("DETAILED TOP 5")
    print("=" * 100)
    for rank, (s, kw, r) in enumerate(top[:5], 1):
        print(f"\n  #{rank} (Score: {s:.1f})")
        print(f"  Params: {json.dumps(kw, default=str)}")
        print(f"  Trades: {r['total_trades']}  WR: {r['win_rate']*100:.1f}%  PF: {r['profit_factor']:.2f}")
        print(f"  PnL: ${r['total_pnl']:.2f} ({r['total_pnl_pct']:.2f}%)  DD: {r['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe: {r['sharpe_ratio']:.2f}  MaxConsLoss: {r['max_consecutive_losses']}")
        print(f"  AvgWin: ${r.get('avg_win',0):.2f}  AvgLoss: ${r.get('avg_loss',0):.2f}  WRatio: {r.get('avg_win',0)/max(abs(r.get('avg_loss',0)),1):.2f}")
        reasons = {}
        for t in r.get("trades", []):
            reasons[t.get("close_reason", "?")] = reasons.get(t.get("close_reason", "?"), 0) + 1
        if reasons:
            print(f"  Exits: {reasons}")

    out_path = Path(__file__).resolve().parent.parent / "opt_focused_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "top_20": [{"score": s, "params": kw,
                        "result": {k: v for k, v in r.items() if k != "trades"}}
                       for s, kw, r in top],
        }, f, indent=2)
    print(f"\nResults saved to {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
