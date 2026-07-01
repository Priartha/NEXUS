from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis.backtest import BacktestEngine
from scripts.validate_profitability import fetch_binance_candles


def score(result: dict) -> float:
    summary = result.get("combined", result)
    trades = float(summary.get("total_trades", 0) or 0)
    pf = min(float(summary.get("profit_factor", 0) or 0), 5.0)
    pnl = float(summary.get("total_pnl_pct", 0) or 0)
    dd = float(summary.get("max_drawdown_pct", 100) or 100)
    wr = float(summary.get("win_rate", 0) or 0)
    trade_quality = min(trades / 100, 1.0)
    return pf * 50 + pnl * 2 + wr * 35 + trade_quality * 10 - max(dd - 15, 0) * 2


def summarize(result: dict) -> dict:
    summary = result.get("combined", result)
    return {
        "trades": summary.get("total_trades", 0),
        "win_rate": summary.get("win_rate", 0),
        "profit_factor": summary.get("profit_factor", 0),
        "total_pnl_pct": summary.get("total_pnl_pct", 0),
        "max_drawdown_pct": summary.get("max_drawdown_pct", 0),
        "sharpe_ratio": summary.get("sharpe_ratio", 0),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--candles", type=int, default=8640)
    parser.add_argument("--output", default="data/official_profitability_sweep.json")
    parser.add_argument("--walk-forward", action="store_true")
    args = parser.parse_args()

    started = time.time()
    candles = await fetch_binance_candles(args.symbol, args.interval, args.candles)
    print(f"Loaded {len(candles)} {args.interval} candles for {args.symbol}", flush=True)

    configs: list[dict] = []
    for side_mode in ("normal", "invert"):
        for trailing_stop in (False, True):
            for max_hold_bars in (12, 50):
                for breakeven_threshold in (1.0, 999.0):
                    for tp_atr_multiplier in (0.0, 4.0):
                        for sl_atr_multiplier in (0.0, 2.0):
                            for avoid_reason_tokens in ([], ["CVD rising"]):
                                configs.append(
                                    {
                                        "signal_side_mode": side_mode,
                                        "trailing_stop": trailing_stop,
                                        "max_hold_bars": max_hold_bars,
                                        "breakeven_threshold": breakeven_threshold,
                                        "tp_atr_multiplier": tp_atr_multiplier,
                                        "sl_atr_multiplier": sl_atr_multiplier,
                                        "avoid_reason_tokens": avoid_reason_tokens,
                                    }
                                )

    rows: list[dict] = []
    total = len(configs)
    for idx, cfg in enumerate(configs, start=1):
        engine = BacktestEngine(
            initial_balance=10_000.0,
            position_size_pct=0.02,
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
            trailing_stop=cfg["trailing_stop"],
            signal_side_mode=cfg["signal_side_mode"],
            avoid_reason_tokens=cfg["avoid_reason_tokens"],
            tp_atr_multiplier=cfg["tp_atr_multiplier"],
            sl_atr_multiplier=cfg["sl_atr_multiplier"],
            slippage_pct=0.0001,
            commission_pct=0.0002,
            funding_rate_per_8h=0.0001,
        )
        result = engine.run(candles, symbol=args.symbol, timeframe=args.interval, walk_forward=args.walk_forward)
        row = {**cfg, **summarize(result)}
        row["score"] = round(score(result), 4)
        rows.append(row)
        if idx % 50 == 0 or idx == 1:
            best = max(rows, key=lambda item: item["score"])
            print(
                f"{idx:04d}/{total} best PF={best['profit_factor']:.2f} "
                f"PnL={best['total_pnl_pct']:.2f}% DD={best['max_drawdown_pct']:.2f}% "
                f"trades={best['trades']} cfg={best['signal_side_mode']} hold={best['max_hold_bars']} "
                f"tp={best['tp_atr_multiplier']} sl={best['sl_atr_multiplier']}",
                flush=True,
            )

    rows.sort(key=lambda item: (item["profit_factor"] >= 1.5, item["total_pnl_pct"] > 0, item["score"]), reverse=True)
    out = {
        "timestamp": int(time.time() * 1000),
        "elapsed_seconds": round(time.time() - started, 1),
        "symbol": args.symbol,
        "interval": args.interval,
        "candles": len(candles),
        "walk_forward": args.walk_forward,
        "configs_tested": total,
        "top": rows[:30],
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\nTOP 10")
    for rank, row in enumerate(rows[:10], start=1):
        print(
            f"{rank:02d}. PF={row['profit_factor']:.2f} PnL={row['total_pnl_pct']:.2f}% "
            f"DD={row['max_drawdown_pct']:.2f}% WR={row['win_rate']*100:.1f}% trades={row['trades']} "
            f"side={row['signal_side_mode']} trail={row['trailing_stop']} hold={row['max_hold_bars']} "
            f"be={row['breakeven_threshold']} tp={row['tp_atr_multiplier']} sl={row['sl_atr_multiplier']} "
            f"avoid={','.join(row['avoid_reason_tokens']) or '-'} score={row['score']:.2f}"
        )
    print(f"\nSaved {output}")


if __name__ == "__main__":
    asyncio.run(main())
