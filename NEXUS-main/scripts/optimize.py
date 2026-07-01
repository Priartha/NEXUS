"""
NEXUS Parameter Optimization Script.
Runs each config in a subprocess so settings are loaded fresh.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PARAM_GRID = [
    {"name": "Aggressive",     "conf": 0.30, "edge": 0.03, "vol": 0.40, "rrr": 1.5, "px": 0.70, "bars": 6},
    {"name": "Balanced",       "conf": 0.30, "edge": 0.05, "vol": 0.50, "rrr": 2.0, "px": 0.65, "bars": 8},
    {"name": "Conservative",   "conf": 0.35, "edge": 0.05, "vol": 0.50, "rrr": 2.0, "px": 0.65, "bars": 8},
    {"name": "HighRRR",        "conf": 0.35, "edge": 0.05, "vol": 0.60, "rrr": 2.5, "px": 0.60, "bars": 12},
    {"name": "HighRRR-Strict", "conf": 0.35, "edge": 0.07, "vol": 0.60, "rrr": 3.0, "px": 0.60, "bars": 12},
    {"name": "Medium-Fast",    "conf": 0.40, "edge": 0.05, "vol": 0.50, "rrr": 2.0, "px": 0.65, "bars": 8},
    {"name": "TripleGuard",    "conf": 0.40, "edge": 0.08, "vol": 0.60, "rrr": 2.5, "px": 0.60, "bars": 12},
    {"name": "OriginalDefault","conf": 0.45, "edge": 0.08, "vol": 0.80, "rrr": 1.5, "px": 0.70, "bars": 6},
]


def _worker_code(params: dict) -> str:
    return f"""
import json, sys, time
sys.path.insert(0, r"{ROOT}")

import os
os.environ["NEXUS_SCALP_MIN_CONFLUENCE"] = "{params['conf']}"
os.environ["NEXUS_SCALP_MIN_DIRECTIONAL_EDGE"] = "{params['edge']}"
os.environ["NEXUS_SCALP_MIN_VOLUME_IMPULSE"] = "{params['vol']}"
os.environ["NEXUS_SCALP_MIN_RRR"] = "{params['rrr']}"
os.environ["NEXUS_SCALP_PARTIAL_EXIT"] = "{params['px']}"

# Import NOW so settings are built with our env vars
from dotenv import load_dotenv
load_dotenv(r"{ROOT / '.env'}")
import sqlite3
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle

DB = r"{ROOT / 'data' / 'nexus.db'}"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
rows = db.execute(
    "SELECT timestamp, open, high, low, close, volume FROM candle_archive WHERE timeframe='5m' ORDER BY timestamp DESC LIMIT 1000"
).fetchall()
db.close()
candles = sorted([Candle(timestamp=r['timestamp'], open=r['open'], high=r['high'], low=r['low'], close=r['close'], volume=r['volume'], is_closed=True) for r in rows], key=lambda c: c.timestamp)

engine = BacktestEngine(
    initial_balance=10_000.0, position_size_pct=0.02, max_concurrent=1,
    slippage_pct=0.0001, commission_pct=0.0002,
    max_hold_bars={params['bars']}, breakeven_threshold=1.0,
    trailing_stop=True, trailing_atr_multiplier=1.5, funding_rate_per_8h=0.0001,
)
t0 = time.time()
result = engine.run(candles, symbol="BTCUSD", timeframe="5m")
elapsed = time.time() - t0

summary = dict(
    trades=result.get("total_trades", 0),
    win_rate=result.get("win_rate", 0),
    profit_factor=result.get("profit_factor", 0) or 0,
    sharpe=result.get("sharpe_ratio", 0) or 0,
    dd=result.get("max_drawdown_pct", 0) or 0,
    pnl=result.get("total_pnl", 0),
    final_balance=result.get("final_balance", 0),
    elapsed=round(elapsed, 1),
)
print(json.dumps(summary))
"""


def main():
    for p in PARAM_GRID:
        name = p["name"]
        label = f"[{name}] conf={p['conf']} edge={p['edge']} vol={p['vol']} rrr={p['rrr']} px={p['px']} bars={p['bars']}"
        print(label, flush=True)
        code = _worker_code(p)
        t0 = time.time()
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=180,
            cwd=str(ROOT),
        )
        elapsed = time.time() - t0
        if proc.returncode != 0:
            print(f"  FAILED: {proc.stderr.strip()[:200]}", flush=True)
            continue
        try:
            s = json.loads(proc.stdout.strip().split("\n")[-1])
            score = s["profit_factor"] * 20 + s["sharpe"] * 10 + s["win_rate"] * 5
            if s.get("dd", 0) > 15:
                score *= 0.5
            print(f"  Trades={s['trades']} WR={s['win_rate']:.1%} PF={s['profit_factor']:.2f} Sharpe={s['sharpe']:.2f} DD={s['dd']:.1f}% Pnl=${s['pnl']:.0f} Score={score:.1f} ({s['elapsed']}s)", flush=True)
        except Exception as e:
            print(f"  PARSE ERR: {e} | stdout: {proc.stdout[:200]}", flush=True)


if __name__ == "__main__":
    main()
