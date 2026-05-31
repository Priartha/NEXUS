from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from backend.analysis.backtest import BacktestEngine
from backend.config import settings
from backend.ingestion.binance import _binance_symbol, fetch_historical_candles
from backend.models.types import Candle


async def _fetch_window(symbol: str, interval: str, candles: int, base_url: str) -> list[Candle]:
    remaining = candles
    end_time: int | None = None
    batches: list[Candle] = []
    while remaining > 0:
        limit = min(1000, remaining)
        params_url = base_url
        if end_time is None:
            chunk = await fetch_historical_candles(params_url, symbol, interval, limit=limit)
        else:
            import httpx

            url = f"{params_url.rstrip('/')}/api/v3/klines"
            async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "NEXUS/1.0"}) as client:
                response = await client.get(
                    url,
                    params={"symbol": _binance_symbol(symbol), "interval": interval, "limit": limit, "endTime": end_time},
                )
                response.raise_for_status()
                body = response.json()
            chunk = [
                Candle(
                    timestamp=int(item[0]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    is_closed=True,
                )
                for item in body
            ]
        if not chunk:
            break
        batches.extend(chunk)
        remaining -= len(chunk)
        end_time = min(c.timestamp for c in chunk) - 1
        await asyncio.sleep(0.05)
        if len(chunk) < limit:
            break
    unique = {c.timestamp: c for c in batches}
    return [unique[ts] for ts in sorted(unique)][-candles:]


def _production_ready(summary: dict) -> tuple[bool, list[str]]:
    failures: list[str] = []
    trade_count = int(summary.get("total_trades", 0) or 0)
    win_rate = float(summary.get("win_rate", 0.0) or 0.0)
    profit_factor = float(summary.get("profit_factor", 0.0) or 0.0)
    max_drawdown_pct = float(summary.get("max_drawdown_pct", 100.0) or 100.0)
    if trade_count < settings.profitability_min_trades:
        failures.append(f"trade_count {trade_count} < {settings.profitability_min_trades}")
    if win_rate < settings.profitability_min_win_rate:
        failures.append(f"win_rate {win_rate:.4f} < {settings.profitability_min_win_rate:.4f}")
    if profit_factor < settings.profitability_min_profit_factor:
        failures.append(f"profit_factor {profit_factor:.4f} < {settings.profitability_min_profit_factor:.4f}")
    if max_drawdown_pct >= settings.profitability_max_drawdown_pct:
        failures.append(f"max_drawdown_pct {max_drawdown_pct:.4f} >= {settings.profitability_max_drawdown_pct:.4f}")
    return not failures, failures


async def main() -> int:
    parser = argparse.ArgumentParser(description="Validate NEXUS production profitability gate.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--candles", type=int, default=8640)
    parser.add_argument("--output", default=settings.profitability_validation_path)
    parser.add_argument("--walk-forward", action="store_true", default=True)
    args = parser.parse_args()

    candles = await _fetch_window(args.symbol, args.interval, args.candles, settings.market_data_rest_base_url)
    engine = BacktestEngine(max_candles=0)
    result = engine.run(candles, symbol=args.symbol, timeframe=args.interval, walk_forward=args.walk_forward)
    summary = result.get("combined", result)
    ready, failures = _production_ready(summary)
    artifact = {
        "candles": len(candles),
        "trade_count": int(summary.get("total_trades", 0) or 0),
        "win_rate": float(summary.get("win_rate", 0.0) or 0.0),
        "profit_factor": float(summary.get("profit_factor", 0.0) or 0.0),
        "sharpe_ratio": float(summary.get("sharpe_ratio", 0.0) or 0.0),
        "max_drawdown_pct": float(summary.get("max_drawdown_pct", 100.0) or 100.0),
        "final_balance": float(summary.get("final_balance", 0.0) or 0.0),
        "walk_forward": bool(result.get("walk_forward", False)),
        "production_ready": ready,
        "failures": failures,
        "thresholds": {
            "min_trades": settings.profitability_min_trades,
            "min_win_rate": settings.profitability_min_win_rate,
            "min_profit_factor": settings.profitability_min_profit_factor,
            "max_drawdown_pct": settings.profitability_max_drawdown_pct,
        },
        "validated_at_ms": int(time.time() * 1000),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact, indent=2))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
