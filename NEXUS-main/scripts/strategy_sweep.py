"""
NEXUS Strategy Parameter Sweep

Tests multiple parameter combinations across different market conditions.
Outputs a ranked comparison table showing the best performing configurations.

Usage:
    python scripts/strategy_sweep.py [--candles 1000] [--timeframe 15m]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.backtest import BacktestEngine


def load_candles(timeframe: str = "15m", limit: int = 1000) -> list[Candle]:
    """Load candles from the database archive."""
    import sqlite3
    db_path = Path("data/nexus.db")
    if not db_path.exists():
        print("ERROR: Database not found at data/nexus.db")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT timestamp, open, high, low, close, volume FROM candle_archive "
            "WHERE timeframe = ? ORDER BY timestamp DESC LIMIT ?",
            (timeframe, limit),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print(f"ERROR: No candles found for timeframe '{timeframe}'")
        sys.exit(1)

    candles = [
        Candle(
            timestamp=r["timestamp"],
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["volume"]),
        )
        for r in rows
    ]
    return sorted(candles, key=lambda c: c.timestamp)


# ── Parameter Combinations ──────────────────────────────────────────────

PRESETS = {
    "current": {
        "name": "Current (Counter-Trend)",
        "desc": "Original settings with invert mode",
        "params": {
            "position_size_pct": 0.015,
            "max_hold_bars": 12,
            "breakeven_threshold": 1.0,
            "trailing_stop": False,
            "tp_atr_multiplier": 0,
            "signal_side_mode": "invert",
            "avoid_reason_tokens": ["CVD falling"],
            "require_regime_alignment": False,
        },
    },
    "trend_follow": {
        "name": "Trend Following",
        "desc": "Normal mode, ride the trend",
        "params": {
            "position_size_pct": 0.015,
            "max_hold_bars": 15,
            "breakeven_threshold": 1.0,
            "trailing_stop": True,
            "tp_atr_multiplier": 2.5,
            "signal_side_mode": "normal",
            "avoid_reason_tokens": [],
            "require_regime_alignment": False,
        },
    },
    "aggressive": {
        "name": "Aggressive Scalp",
        "desc": "Quick exits, tight risk",
        "params": {
            "position_size_pct": 0.02,
            "max_hold_bars": 8,
            "breakeven_threshold": 0.75,
            "trailing_stop": True,
            "tp_atr_multiplier": 2.0,
            "signal_side_mode": "normal",
            "avoid_reason_tokens": [],
            "require_regime_alignment": False,
        },
    },
    "conservative": {
        "name": "Conservative Trend",
        "desc": "Higher R:R, longer hold",
        "params": {
            "position_size_pct": 0.01,
            "max_hold_bars": 20,
            "breakeven_threshold": 1.5,
            "trailing_stop": True,
            "tp_atr_multiplier": 3.0,
            "signal_side_mode": "normal",
            "avoid_reason_tokens": ["CVD falling", "CVD rising"],
            "require_regime_alignment": True,
        },
    },
    "mean_revert": {
        "name": "Mean Reversion",
        "desc": "Counter-trend with wider TP",
        "params": {
            "position_size_pct": 0.015,
            "max_hold_bars": 15,
            "breakeven_threshold": 1.0,
            "trailing_stop": False,
            "tp_atr_multiplier": 2.0,
            "signal_side_mode": "invert",
            "avoid_reason_tokens": ["CVD falling"],
            "require_regime_alignment": False,
        },
    },
    "adaptive": {
        "name": "Adaptive Regime",
        "desc": "Only trade with regime alignment",
        "params": {
            "position_size_pct": 0.015,
            "max_hold_bars": 12,
            "breakeven_threshold": 1.0,
            "trailing_stop": True,
            "tp_atr_multiplier": 2.5,
            "signal_side_mode": "normal",
            "avoid_reason_tokens": [],
            "require_regime_alignment": True,
        },
    },
    "quick_flip": {
        "name": "Quick Flip",
        "desc": "Very short hold, breakeven fast",
        "params": {
            "position_size_pct": 0.02,
            "max_hold_bars": 6,
            "breakeven_threshold": 0.5,
            "trailing_stop": True,
            "tp_atr_multiplier": 1.5,
            "signal_side_mode": "normal",
            "avoid_reason_tokens": [],
            "require_regime_alignment": False,
        },
    },
    "sniper": {
        "name": "Sniper",
        "desc": "Highest quality signals only",
        "params": {
            "position_size_pct": 0.02,
            "max_hold_bars": 15,
            "breakeven_threshold": 1.0,
            "trailing_stop": True,
            "tp_atr_multiplier": 3.0,
            "signal_side_mode": "normal",
            "avoid_reason_tokens": ["CVD falling", "CVD rising"],
            "require_regime_alignment": True,
        },
    },
}


def run_backtest(candles: list[Candle], params: dict) -> dict:
    """Run a single backtest with given parameters."""
    engine = BacktestEngine(
        initial_balance=10_000.0,
        slippage_pct=0.0001,
        commission_pct=0.0002,
        **params,
    )
    result = engine.run(candles, symbol="BTCUSD", timeframe="15m")
    return result


def score_result(result: dict) -> float:
    """Score a backtest result for ranking (higher = better)."""
    trades = result.get("total_trades", 0)
    win_rate = result.get("win_rate", 0)
    pf = result.get("profit_factor", 0)
    pnl_pct = result.get("total_pnl_pct", 0)
    dd = result.get("max_drawdown_pct", 100)
    sharpe = result.get("sharpe_ratio", 0)

    # Require minimum trades for statistical relevance
    if trades < 5:
        return -999

    score = 0.0
    # Profit factor (up to 30 pts)
    score += min(pf, 5.0) * 6
    # PnL % (up to 25 pts)
    score += min(pnl_pct, 25)
    # Win rate (up to 20 pts)
    score += win_rate * 20
    # Sharpe ratio (up to 15 pts)
    score += min(sharpe, 3.0) * 5
    # Drawdown penalty (up to -10 pts)
    score -= dd * 2
    # Trade count bonus (up to 10 pts)
    score += min(trades, 20) * 0.5

    return round(score, 2)


def format_table(results: list[dict]) -> str:
    """Format results as an ASCII table."""
    header = f"{'Rank':<5} {'Preset':<22} {'Trades':<7} {'Win%':<7} {'PF':<8} {'PnL%':<9} {'MaxDD%':<8} {'Sharpe':<8} {'Score':<8}"
    sep = "-" * len(header)
    lines = [sep, header, sep]

    for i, r in enumerate(results, 1):
        line = (
            f"{i:<5} "
            f"{r['name']:<22} "
            f"{r['trades']:<7} "
            f"{r['win_rate']:<7.1f} "
            f"{r['pf']:<8.2f} "
            f"{r['pnl_pct']:<9.2f} "
            f"{r['dd']:<8.2f} "
            f"{r['sharpe']:<8.2f} "
            f"{r['score']:<8.1f}"
        )
        lines.append(line)

    lines.append(sep)
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NEXUS Strategy Parameter Sweep")
    parser.add_argument("--candles", type=int, default=1000, help="Number of candles to test")
    parser.add_argument("--timeframe", type=str, default="15m", help="Timeframe (5m, 15m, 1h)")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  NEXUS Strategy Parameter Sweep")
    print(f"  Timeframe: {args.timeframe} | Candles: {args.candles}")
    print(f"{'='*60}\n")

    # Load data
    print("Loading candle data...")
    candles = load_candles(args.timeframe, args.candles)
    print(f"Loaded {len(candles)} candles")

    if len(candles) < 100:
        print("ERROR: Need at least 100 candles for meaningful backtest")
        sys.exit(1)

    # Run sweep
    all_results = []
    for key, preset in PRESETS.items():
        print(f"\nTesting: {preset['name']} ({preset['desc']})")
        start = time.time()
        try:
            result = run_backtest(candles, preset["params"])
            elapsed = time.time() - start
            score = score_result(result)
            all_results.append({
                "key": key,
                "name": preset["name"],
                "desc": preset["desc"],
                "trades": result.get("total_trades", 0),
                "win_rate": result.get("win_rate", 0) * 100,
                "pf": result.get("profit_factor", 0),
                "pnl_pct": result.get("total_pnl_pct", 0),
                "dd": result.get("max_drawdown_pct", 0),
                "sharpe": result.get("sharpe_ratio", 0),
                "score": score,
                "pnl": result.get("total_pnl", 0),
                "avg_win": result.get("avg_win", 0),
                "avg_loss": result.get("avg_loss", 0),
                "max_consec_losses": result.get("max_consecutive_losses", 0),
                "elapsed": elapsed,
                "full_result": result,
            })
            print(f"  -> {result.get('total_trades', 0)} trades, "
                  f"PF={result.get('profit_factor', 0):.2f}, "
                  f"PnL={result.get('total_pnl_pct', 0):.2f}%, "
                  f"Score={score:.1f} ({elapsed:.1f}s)")
        except Exception as e:
            print(f"  -> FAILED: {e}")
            all_results.append({
                "key": key,
                "name": preset["name"],
                "desc": preset["desc"],
                "trades": 0,
                "win_rate": 0,
                "pf": 0,
                "pnl_pct": 0,
                "dd": 0,
                "sharpe": 0,
                "score": -999,
                "pnl": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "max_consec_losses": 0,
                "elapsed": 0,
                "full_result": {},
            })

    # Sort by score (best first)
    all_results.sort(key=lambda x: x["score"], reverse=True)

    # Print results
    print(f"\n\n{'='*60}")
    print("  RESULTS (Ranked by composite score)")
    print(f"{'='*60}\n")
    print(format_table(all_results))

    # Print winner details
    winner = all_results[0]
    if winner["score"] > 0:
        print(f"\n{'='*60}")
        print(f"  WINNER: {winner['name']}")
        print(f"{'='*60}")
        print(f"  {winner['desc']}")
        print(f"  Trades: {winner['trades']}")
        print(f"  Win Rate: {winner['win_rate']:.1f}%")
        print(f"  Profit Factor: {winner['pf']:.2f}")
        print(f"  Total PnL: {winner['pnl_pct']:.2f}% (${winner['pnl']:.2f})")
        print(f"  Max Drawdown: {winner['dd']:.2f}%")
        print(f"  Sharpe Ratio: {winner['sharpe']:.2f}")
        print(f"  Avg Win: ${winner['avg_win']:.2f}")
        print(f"  Avg Loss: ${winner['avg_loss']:.2f}")
        print(f"  Max Consecutive Losses: {winner['max_consec_losses']}")
        print(f"\n  OPTIMAL PARAMETERS:")
        params = PRESETS[winner["key"]]["params"]
        for k, v in params.items():
            print(f"    {k}: {v}")

    # Save results
    output_file = Path("data/sweep_results.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(
            {r["key"]: {k: v for k, v in r.items() if k != "full_result"} for r in all_results},
            f,
            indent=2,
        )
    print(f"\nResults saved to {output_file}")

    # Print comparison vs buy-and-hold
    first_ts = candles[0].timestamp
    last_ts = candles[-1].timestamp
    buy_hold_return = (candles[-1].close - candles[0].close) / candles[0].close * 100
    print(f"\n{'='*60}")
    print(f"  BENCHMARK: Buy & Hold")
    print(f"{'='*60}")
    print(f"  BTC Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    print(f"  Return: {buy_hold_return:.2f}%")
    print(f"  Best Strategy: {winner['pnl_pct']:.2f}% ({'BEATS' if winner['pnl_pct'] > buy_hold_return else 'LAGS'} buy & hold)")


if __name__ == "__main__":
    main()
