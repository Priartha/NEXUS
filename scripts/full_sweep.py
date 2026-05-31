"""
Quick sweep of top 4 presets with all available candles.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.backtest import BacktestEngine
import sqlite3


def load_all_candles(timeframe: str = "5m") -> list[Candle]:
    conn = sqlite3.connect("data/nexus.db")
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM candle_archive "
            "WHERE timeframe = ? ORDER BY timestamp",
            (timeframe,),
        ).fetchall()
    finally:
        conn.close()
    return [
        Candle(timestamp=r["timestamp"], open=float(r["open"]), high=float(r["high"]),
               low=float(r["low"]), close=float(r["close"]), volume=float(r["volume"]))
        for r in rows
    ]


PRESETS = {
    "quick_flip": {
        "name": "Quick Flip",
        "desc": "Optimized winner: 6-bar hold, 0.5R BE, trailing, normal mode",
        "params": {
            "position_size_pct": 0.02, "max_hold_bars": 6, "breakeven_threshold": 0.5,
            "trailing_stop": True, "tp_atr_multiplier": 1.5, "signal_side_mode": "normal",
            "avoid_reason_tokens": [], "require_regime_alignment": False,
        },
    },
    "trend_follow": {
        "name": "Trend Following",
        "desc": "Longer hold, higher TP, normal mode",
        "params": {
            "position_size_pct": 0.015, "max_hold_bars": 15, "breakeven_threshold": 1.0,
            "trailing_stop": True, "tp_atr_multiplier": 2.5, "signal_side_mode": "normal",
            "avoid_reason_tokens": [], "require_regime_alignment": False,
        },
    },
    "aggressive": {
        "name": "Aggressive Scalp",
        "desc": "Fast exits, 0.75R BE",
        "params": {
            "position_size_pct": 0.02, "max_hold_bars": 8, "breakeven_threshold": 0.75,
            "trailing_stop": True, "tp_atr_multiplier": 2.0, "signal_side_mode": "normal",
            "avoid_reason_tokens": [], "require_regime_alignment": False,
        },
    },
    "current_old": {
        "name": "Current (Old/Counter-Trend)",
        "desc": "Original invert mode — baseline comparison",
        "params": {
            "position_size_pct": 0.015, "max_hold_bars": 12, "breakeven_threshold": 1.0,
            "trailing_stop": False, "tp_atr_multiplier": 0, "signal_side_mode": "invert",
            "avoid_reason_tokens": ["CVD falling"], "require_regime_alignment": False,
        },
    },
}


def score_result(r: dict) -> float:
    trades = r.get("total_trades", 0)
    if trades < 3:
        return -999
    wr = r.get("win_rate", 0)
    pf = r.get("profit_factor", 0)
    pnl = r.get("total_pnl_pct", 0)
    dd = r.get("max_drawdown_pct", 100)
    sh = r.get("sharpe_ratio", 0)
    score = min(pf, 5.0) * 6 + min(pnl, 30) + wr * 20 + min(sh, 3.0) * 5 - dd * 2 + min(trades, 30) * 0.5
    return round(score, 2)


def main():
    candles = load_all_candles("5m")
    n = len(candles)
    print(f"\n{'='*65}")
    print(f"  NEXUS Full Sweep — {n} candles (~{n*5/1440:.0f} days)")
    print(f"{'='*65}\n")

    all_results = []
    for key, preset in PRESETS.items():
        print(f"[{preset['name']}] Running...", end=" ", flush=True)
        t0 = time.time()
        try:
            engine = BacktestEngine(
                initial_balance=10_000.0, slippage_pct=0.0001, commission_pct=0.0002,
                **preset["params"],
            )
            result = engine.run(candles, symbol="BTCUSD", timeframe="5m")
            elapsed = time.time() - t0
            score = score_result(result)
            entry = {
                "key": key, "name": preset["name"], "desc": preset["desc"],
                "trades": result.get("total_trades", 0),
                "win_rate": result.get("win_rate", 0) * 100,
                "pf": result.get("profit_factor", 0),
                "pnl_pct": result.get("total_pnl_pct", 0),
                "pnl": result.get("total_pnl", 0),
                "dd": result.get("max_drawdown_pct", 0),
                "sharpe": result.get("sharpe_ratio", 0),
                "score": score,
                "avg_win": result.get("avg_win", 0),
                "avg_loss": result.get("avg_loss", 0),
                "max_consec": result.get("max_consecutive_losses", 0),
                "elapsed": elapsed,
                "params": preset["params"],
            }
            all_results.append(entry)
            print(f"{result.get('total_trades',0)} trades | WR {entry['win_rate']:.1f}% | "
                  f"PF {entry['pf']:.2f} | PnL {entry['pnl_pct']:.2f}% | "
                  f"DD {entry['dd']:.2f}% | Score {score:.1f} ({elapsed:.0f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"FAILED: {e} ({elapsed:.0f}s)")
            all_results.append({"key": key, "name": preset["name"], "trades": 0, "score": -999, "elapsed": elapsed})

    all_results.sort(key=lambda x: x.get("score", -999), reverse=True)

    print(f"\n{'='*65}")
    print(f"  RANKED RESULTS")
    print(f"{'='*65}\n")
    hdr = f"{'#':<3} {'Preset':<22} {'Trades':>6} {'WR%':>6} {'PF':>7} {'PnL%':>8} {'MaxDD%':>7} {'Sharpe':>7} {'Score':>7}"
    print(hdr)
    print("-" * len(hdr))
    for i, r in enumerate(all_results, 1):
        if r.get("trades", 0) == 0:
            print(f"{i:<3} {r['name']:<22} {'--':>6} {'--':>6} {'--':>7} {'--':>8} {'--':>7} {'--':>7} {'--':>7}")
        else:
            print(f"{i:<3} {r['name']:<22} {r['trades']:>6} {r['win_rate']:>5.1f}% {r['pf']:>7.2f} "
                  f"{r['pnl_pct']:>7.2f}% {r['dd']:>6.2f}% {r['sharpe']:>7.2f} {r['score']:>7.1f}")
    print("-" * len(hdr))

    w = all_results[0]
    if w.get("trades", 0) > 0:
        print(f"\n{'='*65}")
        print(f"  WINNER: {w['name']}")
        print(f"{'='*65}")
        print(f"  Trades: {w['trades']}  |  Win Rate: {w['win_rate']:.1f}%  |  PF: {w['pf']:.2f}")
        print(f"  PnL: {w['pnl_pct']:.2f}% (${w['pnl']:.2f})  |  Max DD: {w['dd']:.2f}%")
        print(f"  Sharpe: {w['sharpe']:.2f}  |  Avg Win: ${w['avg_win']:.2f}  |  Avg Loss: ${w['avg_loss']:.2f}")
        print(f"  Max Consec Losses: {w['max_consec']}")
        print(f"\n  PARAMETERS:")
        for k, v in w["params"].items():
            print(f"    {k}: {v}")

    first_close = candles[0].close
    last_close = candles[-1].close
    bh = (last_close - first_close) / first_close * 100
    print(f"\n{'='*65}")
    print(f"  BENCHMARK: Buy & Hold BTC")
    print(f"{'='*65}")
    print(f"  ${first_close:.2f} -> ${last_close:.2f}  |  Return: {bh:.2f}%")
    best_pnl = all_results[0].get("pnl_pct", 0) if all_results else 0
    print(f"  Best Strategy: {best_pnl:.2f}%  |  {'BEATS' if best_pnl > bh else 'LAGS'} buy & hold by {best_pnl - bh:.2f}%")

    Path("data").mkdir(exist_ok=True)
    with open("data/full_sweep_results.json", "w") as f:
        json.dump([{k: v for k, v in r.items()} for r in all_results], f, indent=2, default=str)
    print(f"\nResults saved to data/full_sweep_results.json\n")


if __name__ == "__main__":
    main()
