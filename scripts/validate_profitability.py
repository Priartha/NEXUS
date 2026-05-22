from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.analysis.backtest import BacktestEngine
from backend.analysis.profitability_guard import write_validation
from backend.models.types import Candle


BINANCE_URL = "https://api.binance.com/api/v3/klines"


async def fetch_binance_candles(symbol: str = "BTCUSDT", interval: str = "5m", total: int = 8640) -> list[Candle]:
    candles: list[Candle] = []
    end_time: int | None = None
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "NEXUS/1.0"}) as client:
        while len(candles) < total:
            limit = min(1000, total - len(candles))
            params: dict[str, int | str] = {"symbol": symbol, "interval": interval, "limit": limit}
            if end_time is not None:
                params["endTime"] = end_time
            response = await client.get(BINANCE_URL, params=params)
            response.raise_for_status()
            rows = response.json()
            if not rows:
                break
            batch = [
                Candle(
                    timestamp=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                    is_closed=True,
                )
                for row in rows
            ]
            candles = batch + candles
            end_time = int(rows[0][0]) - 1
            if len(rows) < limit:
                break
    dedup = {c.timestamp: c for c in candles}
    return sorted(dedup.values(), key=lambda c: c.timestamp)[-total:]


async def main() -> None:
    candles = await fetch_binance_candles()
    engine = BacktestEngine(
        initial_balance=10_000.0,
        position_size_pct=0.02,
        max_hold_bars=6,
        slippage_pct=0.0001,
        commission_pct=0.0002,
        trailing_stop=True,
        breakeven_threshold=1.0,
        funding_rate_per_8h=0.0001,
    )
    result = engine.run(candles, symbol="BTCUSDT", timeframe="5m", walk_forward=True)
    summary = result.get("combined", result)
    metrics = {
        "candles": len(candles),
        "trade_count": summary.get("total_trades", result.get("total_trades", 0)),
        "win_rate": summary.get("win_rate", result.get("win_rate", 0)),
        "profit_factor": summary.get("profit_factor", result.get("profit_factor", 0)),
        "sharpe_ratio": summary.get("sharpe_ratio", result.get("sharpe_ratio", 0)),
        "max_drawdown_pct": summary.get("max_drawdown_pct", result.get("max_drawdown_pct", 0)),
        "final_balance": summary.get("final_balance", result.get("final_balance", 0)),
        "buy_hold_return_pct": result.get("benchmark_buy_hold", {}).get("total_return_pct"),
        "regime_performance": result.get("regime_performance", {}),
        "walk_forward": bool(result.get("walk_forward")),
    }
    metrics = write_validation(metrics)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
