"""Minimal parameter sweep — runs fast, finds best parameters for backtest."""
import asyncio, sys, json, logging, os
from pathlib import Path

# Suppress stderr noise from momentum/funding prints
class _NullWriter:
    def write(self, *a, **kw): pass
    def flush(self, *a, **kw): pass
sys.stderr = _NullWriter()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.disable(logging.CRITICAL)
for k in list(os.environ.keys()):
    if k.startswith("NEXUS_"):
        del os.environ[k]
os.environ["NEXUS_REQUIRE_PROFITABILITY_VALIDATION"] = "false"

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch(limit=500):
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url); r.raise_for_status()
    return [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in r.json()]


logging.getLogger().addHandler(logging.NullHandler())


def score(r):
    if r["total_trades"] < 3: return -9999
    pf = min(r["profit_factor"], 10)
    wr = r["win_rate"]
    pnl = min(r["total_pnl_pct"], 100)
    dd = r["max_drawdown_pct"]
    sharpe = max(min(r["sharpe_ratio"], 5), -5)
    cons = r["max_consecutive_losses"]
    return pf * 35 + wr * 30 + pnl * 0.8 - dd * 2.5 + sharpe * 10 - cons * 5


async def main():
    print("Fetching data...", flush=True)
    candles = await fetch(1000)
    print(f"Got {len(candles)} candles\n", flush=True)

    # Quick timing test
    import time as _t
    _t0 = _t.time()
    BacktestEngine(initial_balance=10000, position_size_pct=0.005,
                   max_hold_bars=6, breakeven_threshold=0.3,
                   trailing_stop=True, trailing_atr_multiplier=1.0,
                   tp_atr_multiplier=2.5, sl_atr_multiplier=0.0,
                   max_concurrent=1, slippage_pct=0.0001,
                   commission_pct=0.0002,
                   require_regime_alignment=False).run(candles, timeframe="5m")
    print(f"Single backtest: {_t.time()-_t0:.1f}s", flush=True)

    configs = [
        # pos, hold, be, trail, trail_mult, tp_mult
        (0.005, 4, 0.3, True, 1.0, 2.5),
        (0.005, 6, 0.3, True, 1.0, 2.5),
        (0.005, 8, 0.5, True, 1.5, 2.5),
        (0.005, 6, 0.5, True, 1.5, 3.0),
        (0.005, 4, 0.3, True, 2.0, 2.0),
        (0.005, 10, 0.5, True, 1.0, 2.5),
        (0.0075, 6, 0.3, True, 1.0, 2.5),
        (0.0075, 6, 0.5, True, 1.5, 2.5),
        (0.0075, 8, 0.5, True, 1.0, 2.0),
        (0.0075, 10, 0.8, True, 1.5, 2.0),
        (0.01, 6, 0.3, True, 1.0, 2.5),
        (0.01, 6, 0.5, True, 1.0, 3.0),
        (0.01, 8, 0.5, True, 1.5, 3.0),
        (0.01, 10, 0.8, True, 1.5, 2.5),
        (0.01, 12, 0.8, True, 1.0, 2.0),
        (0.01, 6, 0.8, True, 2.0, 2.5),
        (0.015, 6, 0.5, True, 1.0, 2.5),
        (0.015, 8, 0.5, True, 1.5, 2.0),
        (0.015, 10, 0.8, True, 1.5, 2.5),
        (0.015, 12, 1.0, True, 2.0, 2.0),
        (0.005, 6, 0.3, False, 1.5, 2.5),
        (0.01, 6, 0.3, False, 1.5, 2.5),
        (0.005, 15, 0.5, True, 1.0, 2.5),
        (0.005, 20, 0.5, True, 1.0, 2.5),
        (0.005, 30, 0.5, True, 1.0, 2.5),
    ]

    hdr = f"{'#':>2} {'Pos%':>5} {'Hold':>5} {'BE':>4} {'Trail':>5} {'TMult':>6} {'TPx':>5} | {'Trds':>5} {'WR%':>5} {'PF':>6} {'PnL%':>7} {'DD%':>6} {'Score':>7}"
    print(hdr)
    print("-" * len(hdr))

    results = []
    for i, (pos, hold, be, trail, tmult, tp) in enumerate(configs, 1):
        try:
            r = BacktestEngine(initial_balance=10000, position_size_pct=pos,
                               max_hold_bars=hold, breakeven_threshold=be,
                               trailing_stop=trail, trailing_atr_multiplier=tmult,
                               tp_atr_multiplier=tp, sl_atr_multiplier=0.0,
                               max_concurrent=1, slippage_pct=0.0001,
                               commission_pct=0.0002,
                               require_regime_alignment=False).run(candles, timeframe="5m")
            s = score(r)
            results.append((s, (pos, hold, be, trail, tmult, tp), r))
            print(f"{i:>2} {pos*100:>4.0f}% {hold:>5} {be:>4.1f} {str(trail):>5} {tmult:>6.1f} {tp:>5.1f} | {r['total_trades']:>5} {r['win_rate']*100:>4.1f}% {r['profit_factor']:>6.2f} {r['total_pnl_pct']:>6.2f}% {r['max_drawdown_pct']:>5.2f}% {s:>7.1f}", flush=True)
        except Exception as e:
            print(f"{i:>2} {pos*100:>4.0f}% {hold:>5} {be:>4.1f} {str(trail):>5} {tmult:>6.1f} {tp:>5.1f} | ERROR: {e}", flush=True)

    results.sort(key=lambda x: -x[0])
    print("\n" + "=" * len(hdr))
    print("TOP 5")
    print("=" * len(hdr))
    for rank, (s, params, r) in enumerate(results[:5], 1):
        print(f"\n#{rank} (Score: {s:.1f})")
        print(f"  pos={params[0]}, hold={params[1]}, be={params[2]}, trail={params[3]}, tmult={params[4]}, tp={params[5]}")
        print(f"  Trades: {r['total_trades']}  WR: {r['win_rate']*100:.1f}%  PF: {r['profit_factor']:.2f}")
        print(f"  PnL: ${r['total_pnl']:.2f} ({r['total_pnl_pct']:.2f}%)  DD: {r['max_drawdown_pct']:.2f}%  Sharpe: {r['sharpe_ratio']:.2f}")
        if r.get("trades"):
            reasons = {}
            for t in r["trades"]:
                reasons[t.get("close_reason","?")] = reasons.get(t.get("close_reason","?"), 0) + 1
            print(f"  Exit distribution: {reasons}")

    best = results[0]
    best_params = {
        "position_size_pct": best[1][0],
        "max_hold_bars": best[1][1],
        "breakeven_threshold": best[1][2],
        "trailing_stop": best[1][3],
        "trailing_atr_multiplier": best[1][4],
        "tp_atr_multiplier": best[1][5],
        "sl_atr_multiplier": 0.0,
        "require_regime_alignment": True,
    }
    print(f"\nRECOMMENDED BACKTEST PARAMS:")
    print(json.dumps(best_params, indent=2, default=str))

    out = Path(__file__).resolve().parent.parent / "opt_results.json"
    with open(out, "w") as f:
        json.dump({"best_params": best_params, "best_result": {k: v for k, v in best[2].items() if k != "trades"}}, f, indent=2)
    print(f"\nSaved to {out}")

if __name__ == "__main__":
    asyncio.run(main())
