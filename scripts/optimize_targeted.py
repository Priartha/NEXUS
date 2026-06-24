"""Quick targeted backtest runner — runs exactly the configs specified."""
import asyncio, sys, json, logging, os, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

class _NullWriter:
    def write(self, *a, **kw): pass
    def flush(self, *a, **kw): pass
sys.stderr = _NullWriter()

logging.disable(logging.CRITICAL)
for k in list(os.environ.keys()):
    if k.startswith("NEXUS_"): del os.environ[k]
os.environ["NEXUS_REQUIRE_PROFITABILITY_VALIDATION"] = "false"

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle

async def fetch(limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url); r.raise_for_status()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in r.json()]

def run(candles, **kw):
    params = dict(initial_balance=10000, position_size_pct=0.005, max_concurrent=1,
                  slippage_pct=0.0001, commission_pct=0.0002, max_hold_bars=6,
                  breakeven_threshold=0.3, trailing_stop=True, trailing_atr_multiplier=1.0,
                  tp_atr_multiplier=2.5, sl_atr_multiplier=0.0, require_regime_alignment=False,
                  signal_side_mode="normal", avoid_reason_tokens=None, funding_rate_per_8h=-0.0001)
    params.update(kw)
    engine = BacktestEngine(**params)
    return engine.run(candles, symbol="BTCUSDT", timeframe="5m")

def print_result(label, r):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  Trades: {r['total_trades']}  Win: {r['winning_trades']}  Loss: {r['losing_trades']}")
    print(f"  Win Rate: {r['win_rate']*100:.1f}%  Profit Factor: {r['profit_factor']:.3f}")
    print(f"  P&L: ${r['total_pnl']:.2f} ({r['total_pnl_pct']:.2f}%)  Max DD: {r['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe: {r['sharpe_ratio']:.3f}  Max Consec Losses: {r['max_consecutive_losses']}")
    print(f"  Avg Win: ${r['avg_win']:.2f}  Avg Loss: ${r['avg_loss']:.2f}")
    if r.get("trades"):
        reasons = {}
        for t in r["trades"]:
            reasons[t.get("close_reason","?")] = reasons.get(t.get("close_reason","?"), 0) + 1
        print(f"  Exits: {reasons}")
    print()

async def main():
    print("Fetching BTCUSDT 5m data...", flush=True)
    c = await fetch(1000)
    print(f"Got {len(c)} candles\n", flush=True)

    configs = [
        ("Best from sweep (0.5%, hold=6, be=0.3, trail, tmult=1.0, tp=2.5)", dict(
            position_size_pct=0.005, max_hold_bars=6, breakeven_threshold=0.3,
            trailing_stop=True, trailing_atr_multiplier=1.0, tp_atr_multiplier=2.5)),
        ("Variant: hold=4, tighter", dict(
            position_size_pct=0.005, max_hold_bars=4, breakeven_threshold=0.3,
            trailing_stop=True, trailing_atr_multiplier=1.0, tp_atr_multiplier=2.5)),
        ("Variant: hold=10, wider", dict(
            position_size_pct=0.005, max_hold_bars=10, breakeven_threshold=0.5,
            trailing_stop=True, trailing_atr_multiplier=1.5, tp_atr_multiplier=2.5)),
        ("Variant: 1.0% pos, tight", dict(
            position_size_pct=0.01, max_hold_bars=6, breakeven_threshold=0.3,
            trailing_stop=True, trailing_atr_multiplier=1.0, tp_atr_multiplier=2.5)),
        ("Variant: 1.0% pos, hold=8, be=0.5", dict(
            position_size_pct=0.01, max_hold_bars=8, breakeven_threshold=0.5,
            trailing_stop=True, trailing_atr_multiplier=1.5, tp_atr_multiplier=2.5)),
        ("Variant: no trailing stop", dict(
            position_size_pct=0.005, max_hold_bars=6, breakeven_threshold=0.3,
            trailing_stop=False, trailing_atr_multiplier=1.5, tp_atr_multiplier=2.5)),
        ("Variant: require_regime_alignment", dict(
            position_size_pct=0.005, max_hold_bars=6, breakeven_threshold=0.3,
            trailing_stop=True, trailing_atr_multiplier=1.0, tp_atr_multiplier=2.5,
            require_regime_alignment=True)),
        ("Variant: 0.75% pos, hold=6", dict(
            position_size_pct=0.0075, max_hold_bars=6, breakeven_threshold=0.3,
            trailing_stop=True, trailing_atr_multiplier=1.0, tp_atr_multiplier=2.5)),
    ]

    results = []
    for label, kw in configs:
        t0 = time.time()
        r = run(c, **kw)
        elapsed = time.time() - t0
        print_result(f"{label}  [{elapsed:.0f}s]", r)
        results.append((label, kw, r))

    # Score and rank
    def score(r):
        if r["total_trades"] < 3: return -9999
        return (min(r["profit_factor"],10)*35 + r["win_rate"]*30 +
                min(r["total_pnl_pct"],100)*0.8 - r["max_drawdown_pct"]*2.5 +
                max(min(r["sharpe_ratio"],5),-5)*10 - r["max_consecutive_losses"]*5)

    results.sort(key=lambda x: -score(x[2]))
    best = results[0]
    print(f"\n{'='*60}")
    print(f"  BEST OVERALL (Score: {score(best[2]):.1f})")
    print(f"{'='*60}")
    print(f"  {best[0]}")
    print(f"  Params: {json.dumps(best[1], indent=4, default=str)}")
    r = best[2]
    print(f"  Trades: {r['total_trades']}  WR: {r['win_rate']*100:.1f}%  PF: {r['profit_factor']:.3f}")
    print(f"  PnL: ${r['total_pnl']:.2f} ({r['total_pnl_pct']:.2f}%)  DD: {r['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe: {r['sharpe_ratio']:.3f}  MaxConsLoss: {r['max_consecutive_losses']}")

    with open(Path(__file__).resolve().parent.parent / "opt_best.json", "w") as f:
        json.dump({"best": {"label": best[0], "params": best[1],
                            "result": {k: v for k, v in best[2].items() if k != "trades"}},
                   "all": [{"label": l, "params": p, "result": {k: v for k, v in r.items() if k != "trades"}}
                           for l, p, r in results]}, f, indent=2)
    print(f"\nResults saved to opt_best.json")

if __name__ == "__main__":
    asyncio.run(main())
