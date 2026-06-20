from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from backend.analysis.backtest import BacktestEngine
from backend.config import settings
from backend.ingestion.binance import fetch_historical_candles


def summarize(result: dict) -> dict:
    summary = result.get("combined", result)
    return {
        "trades": int(summary.get("total_trades", 0) or 0),
        "win_rate": float(summary.get("win_rate", 0.0) or 0.0),
        "profit_factor": float(summary.get("profit_factor", 0.0) or 0.0),
        "total_pnl_pct": float(summary.get("total_pnl_pct", 0.0) or 0.0),
        "max_drawdown_pct": float(summary.get("max_drawdown_pct", 100.0) or 100.0),
        "final_balance": float(summary.get("final_balance", 0.0) or 0.0),
    }


def score(row: dict) -> float:
    return (
        min(row["profit_factor"], 4.0) * 40
        + row["win_rate"] * 50
        + min(row["trades"] / 100, 1.0) * 15
        + row["total_pnl_pct"]
        - max(row["max_drawdown_pct"] - settings.profitability_max_drawdown_pct, 0) * 4
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Small targeted profitability probe.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--candles", type=int, default=1000)
    parser.add_argument("--output", default="data/targeted_profitability_probe.json")
    parser.add_argument("--config-index", type=int, default=0, help="1-based candidate index; 0 runs all")
    args = parser.parse_args()

    candles = await fetch_historical_candles(
        settings.market_data_rest_base_url,
        args.symbol,
        args.interval,
        limit=args.candles,
    )

    base = {
        "position_size_pct": 0.02,
        "max_hold_bars": 6,
        "trailing_stop": True,
        "breakeven_threshold": 1.0,
        "tp_atr_multiplier": 0.0,
        "sl_atr_multiplier": 0.0,
        "avoid_reason_tokens": [],
    }
    variants = [
        {},
        {"position_size_pct": 0.015},
        {"position_size_pct": 0.01},
        {"max_hold_bars": 12},
        {"max_hold_bars": 12, "trailing_stop": False},
        {"trailing_stop": False},
        {"breakeven_threshold": 0.75},
        {"tp_atr_multiplier": 2.0},
        {"sl_atr_multiplier": 1.5},
        {"tp_atr_multiplier": 2.0, "sl_atr_multiplier": 1.5},
        {"avoid_reason_tokens": ["CVD rising"]},
        {"avoid_reason_tokens": ["CVD rising"], "max_hold_bars": 12, "trailing_stop": False},
        {"signal_side_mode": "invert"},
        {"signal_side_mode": "invert", "max_hold_bars": 12, "trailing_stop": False},
    ]
    configs = [{**base, **variant} for variant in variants]
    if args.config_index:
        if args.config_index < 1 or args.config_index > len(configs):
            raise SystemExit(f"--config-index must be between 1 and {len(configs)}")
        configs = [configs[args.config_index - 1]]

    rows: list[dict] = []
    for idx, cfg in enumerate(configs, start=1):
        engine = BacktestEngine(
            initial_balance=10_000.0,
            position_size_pct=cfg["position_size_pct"],
            max_hold_bars=cfg["max_hold_bars"],
            trailing_stop=cfg["trailing_stop"],
            breakeven_threshold=cfg["breakeven_threshold"],
            tp_atr_multiplier=cfg["tp_atr_multiplier"],
            sl_atr_multiplier=cfg["sl_atr_multiplier"],
            avoid_reason_tokens=cfg["avoid_reason_tokens"],
            slippage_pct=0.0001,
            commission_pct=0.0002,
            funding_rate_per_8h=0.0001,
        )
        row = {**cfg, **summarize(engine.run(candles, args.symbol, args.interval, walk_forward=True))}
        row["score"] = round(score(row), 4)
        rows.append(row)
        print(
            f"{idx}/{len(configs)} trades={row['trades']} WR={row['win_rate']:.3f} "
            f"PF={row['profit_factor']:.3f} DD={row['max_drawdown_pct']:.2f} cfg={cfg}",
            flush=True,
        )

    rows.sort(key=lambda item: item["score"], reverse=True)
    out = {"candles": len(candles), "top": rows[:20]}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, indent=2), encoding="utf-8")
    for rank, row in enumerate(rows[:10], start=1):
        print(
            f"{rank:02d}. trades={row['trades']} WR={row['win_rate']:.3f} "
            f"PF={row['profit_factor']:.3f} PnL={row['total_pnl_pct']:.2f}% "
            f"DD={row['max_drawdown_pct']:.2f} score={row['score']:.2f} cfg={row}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
