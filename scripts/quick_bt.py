"""Quick backtest runner — minimal, no stderr noise."""
import asyncio, sys, logging, os, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.disable(logging.CRITICAL)
for k in list(os.environ.keys()):
    if k.startswith("NEXUS_"): del os.environ[k]
os.environ["NEXUS_REQUIRE_PROFITABILITY_VALIDATION"] = "false"

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle

async def main():
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=500"
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url); r.raise_for_status()
        candles = [Candle(timestamp=k[0], open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5])) for k in r.json()]
    print(f"Got {len(candles)} candles", flush=True)

    configs = [
        ("Base", dict()),
        ("Aggr", dict(position_size_pct=0.01)),
        ("Loose", dict(max_hold_bars=10, breakeven_threshold=0.5)),
        ("Tight", dict(max_hold_bars=4, breakeven_threshold=0.2, tp_atr_multiplier=2.0)),
        ("NoTrail", dict(trailing_stop=False, trailing_atr_multiplier=1.5)),
        ("Align", dict(require_regime_alignment=True)),
        ("Pos075", dict(position_size_pct=0.0075)),
        ("Wide", dict(max_hold_bars=15, breakeven_threshold=0.8, tp_atr_multiplier=3.0)),
    ]

    for name, kw in configs:
        params = dict(initial_balance=10000, position_size_pct=0.005, max_concurrent=1,
                      slippage_pct=0.0001, commission_pct=0.0002, max_hold_bars=6,
                      breakeven_threshold=0.3, trailing_stop=True, trailing_atr_multiplier=1.0,
                      tp_atr_multiplier=2.5, sl_atr_multiplier=0.0, require_regime_alignment=False)
        params.update(kw)
        t0 = time.time()
        r = BacktestEngine(**params).run(candles, timeframe="5m")
        t = time.time() - t0
        print(f"{name} [{t:.0f}s]: {r['total_trades']}t WR={r['win_rate']*100:.1f}% PF={r['profit_factor']:.3f} PnL={r['total_pnl_pct']:.2f}% DD={r['max_drawdown_pct']:.2f}% Sharpe={r['sharpe_ratio']:.3f}", flush=True)

    print("\nDONE", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
