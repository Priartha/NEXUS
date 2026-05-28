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
from backend.engine.candle_aggregator import timeframe_to_ms
from backend.models.types import Candle


def symbol_aliases(symbol: str) -> list[str]:
    normalized = symbol.replace("/", "").replace("-", "").upper()
    aliases = [symbol]
    if normalized in {"BTCUSDT", "BTCUSD"}:
        aliases.extend(["BTCUSD", "BTCUSDT", "BTC/USDT"])
    aliases.append(normalized)
    return list(dict.fromkeys(aliases))


def _rows_to_candles(rows: list[sqlite3.Row]) -> list[Candle]:
    return [
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


def _aggregate_candles(candles: list[Candle], timeframe: str, limit: int) -> list[Candle]:
    target_ms = timeframe_to_ms(timeframe)
    buckets: dict[int, list[Candle]] = {}
    for candle in candles:
        bucket = candle.timestamp - (candle.timestamp % target_ms)
        buckets.setdefault(bucket, []).append(candle)

    aggregated: list[Candle] = []
    for bucket in sorted(buckets):
        group = sorted(buckets[bucket], key=lambda item: item.timestamp)
        if len(group) < 2:
            continue
        aggregated.append(
            Candle(
                timestamp=bucket,
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=sum(item.volume for item in group),
                is_closed=all(item.is_closed for item in group),
            )
        )
    return aggregated[-limit:]


def _median_step_ms(rows: list[sqlite3.Row]) -> int:
    timestamps = sorted(int(row["timestamp"]) for row in rows)
    steps = [
        timestamps[idx] - timestamps[idx - 1]
        for idx in range(1, len(timestamps))
        if timestamps[idx] > timestamps[idx - 1]
    ]
    if not steps:
        return timeframe_to_ms("5m")
    return sorted(steps)[len(steps) // 2]


def load_candles(symbol: str, timeframe: str, limit: int) -> list[Candle]:
    db_path = ROOT / "data" / "nexus.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        available = conn.execute(
            """
            SELECT symbol, timeframe, COUNT(*) AS count
            FROM candle_archive
            GROUP BY symbol, timeframe
            ORDER BY count DESC
            """
        ).fetchall()

        for alias in symbol_aliases(symbol):
            rows = conn.execute(
                """
                SELECT timestamp, open, high, low, close, volume, is_closed
                FROM candle_archive
                WHERE symbol=? AND timeframe=?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (alias, timeframe, limit),
            ).fetchall()
            candles = _rows_to_candles(rows)
            if len(candles) >= 80:
                if alias != symbol:
                    print(f"Resolved archive symbol {symbol} -> {alias}")
                return candles

        target_ms = timeframe_to_ms(timeframe)
        if target_ms > timeframe_to_ms("1m"):
            for alias in symbol_aliases(symbol):
                sample_rows = conn.execute(
                    """
                    SELECT timestamp
                    FROM candle_archive
                    WHERE symbol=? AND timeframe='5m'
                    ORDER BY timestamp DESC
                    LIMIT 200
                    """,
                    (alias,),
                ).fetchall()
                source_step_ms = max(_median_step_ms(sample_rows), timeframe_to_ms("1m"))
                ratio = max(target_ms // source_step_ms, 1)
                source_limit = (limit + 2) * ratio
                rows = conn.execute(
                    """
                    SELECT timestamp, open, high, low, close, volume, is_closed
                    FROM candle_archive
                    WHERE symbol=? AND timeframe='5m'
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (alias, source_limit),
                ).fetchall()
                source_candles = _rows_to_candles(rows)
                candles = _aggregate_candles(source_candles, timeframe, limit)
                if len(candles) >= 80:
                    print(f"Built {timeframe} archive from {alias} 5m candles")
                    return candles
    finally:
        conn.close()

    summary = ", ".join(f"{row['symbol']} {row['timeframe']}={row['count']}" for row in available[:8])
    raise SystemExit(
        f"Need at least 80 candles for {symbol} {timeframe}; available archive: {summary or 'empty'}"
    )


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
    parser.add_argument("--exhaustive", action="store_true", help="Run the full parameter grid instead of focused candidates.")
    args = parser.parse_args()

    candles = load_candles(args.symbol, args.timeframe, args.candles)
    print(f"Loaded {len(candles)} {args.timeframe} candles for {args.symbol}")

    configs: list[dict] = [
        {"signal_side_mode": "normal", "trailing_stop": True, "max_hold_bars": 6, "breakeven_threshold": 1.0, "avoid_reason_tokens": [], "tp_atr_multiplier": 0.0, "require_regime_alignment": False},
        {"signal_side_mode": "normal", "trailing_stop": False, "max_hold_bars": 12, "breakeven_threshold": 1.0, "avoid_reason_tokens": ["CVD rising"], "tp_atr_multiplier": 0.0, "require_regime_alignment": False},
        {"signal_side_mode": "invert", "trailing_stop": False, "max_hold_bars": 12, "breakeven_threshold": 1.0, "avoid_reason_tokens": [], "tp_atr_multiplier": 0.0, "require_regime_alignment": False},
        {"signal_side_mode": "invert", "trailing_stop": False, "max_hold_bars": 12, "breakeven_threshold": 1.0, "avoid_reason_tokens": ["CVD falling"], "tp_atr_multiplier": 0.0, "require_regime_alignment": False},
        {"signal_side_mode": "normal", "trailing_stop": True, "max_hold_bars": 10, "breakeven_threshold": 0.5, "avoid_reason_tokens": [], "tp_atr_multiplier": 0.0, "require_regime_alignment": False},
        {"signal_side_mode": "invert", "trailing_stop": True, "max_hold_bars": 10, "breakeven_threshold": 0.5, "avoid_reason_tokens": ["CVD rising"], "tp_atr_multiplier": 0.0, "require_regime_alignment": False},
        {"signal_side_mode": "normal", "trailing_stop": False, "max_hold_bars": 12, "breakeven_threshold": 1.0, "avoid_reason_tokens": ["CVD rising"], "tp_atr_multiplier": 0.0, "require_regime_alignment": True},
        {"signal_side_mode": "normal", "trailing_stop": False, "max_hold_bars": 50, "breakeven_threshold": 1.0, "avoid_reason_tokens": [], "tp_atr_multiplier": 4.0, "require_regime_alignment": False},
        {"signal_side_mode": "invert", "trailing_stop": False, "max_hold_bars": 50, "breakeven_threshold": 1.0, "avoid_reason_tokens": [], "tp_atr_multiplier": 4.0, "require_regime_alignment": False},
    ]
    if args.exhaustive:
        configs = []
    for side_mode in (() if not args.exhaustive else ("normal", "invert")):
        for trailing_stop in (False, True):
            for max_hold_bars in (6, 8, 10, 12, 16, 20, 30, 50):
                for breakeven_threshold in (0.5, 0.75, 1.0, 1.5):
                    for avoid_reason_tokens in ([], ["CVD rising"], ["CVD falling"]):
                        for tp_atr_multiplier in (0.0, 2.0, 3.0, 4.0):
                            configs.append(
                                {
                                    "signal_side_mode": side_mode,
                                    "trailing_stop": trailing_stop,
                                    "max_hold_bars": max_hold_bars,
                                    "breakeven_threshold": breakeven_threshold,
                                    "avoid_reason_tokens": avoid_reason_tokens,
                                    "tp_atr_multiplier": tp_atr_multiplier,
                                    "require_regime_alignment": False,
                                }
                            )
    for max_hold_bars in (10, 12, 16, 20):
        for avoid_reason_tokens in ([], ["CVD rising"], ["CVD falling"]):
            configs.append(
                {
                    "signal_side_mode": "normal",
                    "trailing_stop": False,
                    "max_hold_bars": max_hold_bars,
                    "breakeven_threshold": 1.0,
                    "avoid_reason_tokens": avoid_reason_tokens,
                    "tp_atr_multiplier": 0.0,
                    "require_regime_alignment": True,
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
            tp_atr_multiplier=cfg["tp_atr_multiplier"],
            require_regime_alignment=cfg["require_regime_alignment"],
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
            "tp_atr_multiplier": cfg["tp_atr_multiplier"],
            "require_regime_alignment": cfg["require_regime_alignment"],
        }
        row["score"] = round(score_result(row), 4)
        results.append(row)
        print(
            f"{idx:03d}/{len(configs)} {cfg['signal_side_mode']:<6} "
            f"trail={str(cfg['trailing_stop']):<5} hold={cfg['max_hold_bars']:<2} "
            f"be={cfg['breakeven_threshold']:<4} avoid={','.join(cfg['avoid_reason_tokens']) or '-':<10} "
            f"tp={cfg['tp_atr_multiplier']:<3} regime={str(cfg['require_regime_alignment']):<5} "
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
            f"tp={row['tp_atr_multiplier']} regime={row['require_regime_alignment']} "
            f"trades={row['total_trades']} WR={row['win_rate'] * 100:.1f}% "
            f"PF={row['profit_factor']:.2f} PnL={row['total_pnl_pct']:.2f}% "
            f"DD={row['max_drawdown_pct']:.2f}% score={row['score']:.2f}"
        )
    print(f"\nSaved {output_path}")


if __name__ == "__main__":
    main()
