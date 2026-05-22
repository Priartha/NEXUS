"""Optimize NEXUS backtest exit settings on the local candle archive."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


def load_candles(symbol: str, timeframe: str, limit: int) -> list[Candle]:
    db_path = ROOT / "data" / "nexus.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT timestamp, open, high, low, close, volume, is_closed
            FROM candle_archive
            WHERE symbol=? AND timeframe=?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, timeframe, limit),
        ).fetchall()
    finally:
        conn.close()

    candles = [
        Candle(
            timestamp=row["timestamp"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            is_closed=bool(row["is_closed"]),
        )
        for row in reversed(rows)
    ]
    if len(candles) < 80:
        raise SystemExit(f"Need at least 80 candles, found {len(candles)}")
    return candles


def score_result(result: dict) -> float:
    trades = result["total_trades"]
    pf = min(float(result["profit_factor"]), 5.0)
    pnl = float(result["total_pnl_pct"])
    dd = float(result["max_drawdown_pct"])
    trade_quality = min(trades / 10, 1.0)
    return pf * 50 + pnl * 3 - dd * 2 + trade_quality * 10


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--candles", type=int, default=500)
    parser.add_argument("--output", default="optimization_results.json")
    args = parser.parse_args()

    candles = load_candles(args.symbol, args.timeframe, args.candles)
    print(f"Loaded {len(candles)} {args.timeframe} candles for {args.symbol}")

    configs: list[dict] = []
    for side_mode in ("normal", "invert"):
        for trailing_stop in (False, True):
            for max_hold_bars in (4, 6, 8, 10, 12, 16, 20):
                for breakeven_threshold in (0.5, 0.75, 1.0, 1.5):
                    for avoid_reason_tokens in ([], ["CVD rising"]):
                        configs.append(
                            {
                                "signal_side_mode": side_mode,
                                "trailing_stop": trailing_stop,
                                "max_hold_bars": max_hold_bars,
                                "breakeven_threshold": breakeven_threshold,
                                "avoid_reason_tokens": avoid_reason_tokens,
                            }
                        )

    results: list[dict] = []
    started = time.time()
    for idx, cfg in enumerate(configs, start=1):
        engine = BacktestEngine(
            initial_balance=10_000,
            position_size_pct=0.02,
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
            trailing_stop=cfg["trailing_stop"],
            signal_side_mode=cfg["signal_side_mode"],
            avoid_reason_tokens=cfg["avoid_reason_tokens"],
        )
        result = engine.run(candles, symbol=args.symbol, timeframe=args.timeframe)
        row = {
            **cfg,
            "candle_count": result["candle_count"],
            "total_trades": result["total_trades"],
            "win_rate": result["win_rate"],
            "profit_factor": result["profit_factor"],
            "total_pnl_pct": result["total_pnl_pct"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "sharpe_ratio": result["sharpe_ratio"],
            "avoid_reason_tokens": cfg["avoid_reason_tokens"],
        }
        row["score"] = round(score_result(row), 4)
        results.append(row)
        print(
            f"{idx:03d}/{len(configs)} {cfg['signal_side_mode']:<6} "
            f"trail={str(cfg['trailing_stop']):<5} hold={cfg['max_hold_bars']:<2} "
            f"be={cfg['breakeven_threshold']:<4} avoid={','.join(cfg['avoid_reason_tokens']) or '-':<10} "
            f"trades={row['total_trades']:<2} "
            f"WR={row['win_rate'] * 100:>5.1f}% PF={row['profit_factor']:>5.2f} "
            f"PnL={row['total_pnl_pct']:>7.2f}% DD={row['max_drawdown_pct']:>5.2f}% "
            f"score={row['score']:>7.2f}",
            flush=True,
        )

    results.sort(key=lambda item: (item["profit_factor"] > 1.0, item["score"]), reverse=True)
    out = {
        "timestamp": int(time.time() * 1000),
        "elapsed_seconds": round(time.time() - started, 1),
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "candles": len(candles),
        "configs_tested": len(configs),
        "top": results[:20],
    }
    output_path = ROOT / args.output
    output_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\nTOP 10")
    for rank, row in enumerate(results[:10], start=1):
        print(
            f"{rank:02d}. {row['signal_side_mode']} trail={row['trailing_stop']} "
            f"hold={row['max_hold_bars']} be={row['breakeven_threshold']} "
            f"avoid={','.join(row['avoid_reason_tokens']) or '-'} "
            f"trades={row['total_trades']} WR={row['win_rate'] * 100:.1f}% "
            f"PF={row['profit_factor']:.2f} PnL={row['total_pnl_pct']:.2f}% "
            f"DD={row['max_drawdown_pct']:.2f}% score={row['score']:.2f}"
        )
    print(f"\nSaved {output_path}")


if __name__ == "__main__":
    main()
