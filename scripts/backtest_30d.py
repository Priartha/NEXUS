"""
30-Day Comprehensive Backtest
Fetches 30+ days of 5m data via pagination and runs optimized backtest.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle
import httpx


async def fetch_30d_candles(symbol="BTCUSDT", interval="5m", target_days=30):
    """Fetch 30+ days of candles via pagination."""
    all_candles = []
    end_time = None
    batch_size = 1000
    target_candles = target_days * 24 * 12 if interval == "5m" else target_days * 24 * 4

    print(f"  Target: ~{target_candles} candles ({target_days} days of {interval})")

    async with httpx.AsyncClient(timeout=30) as client:
        batch = 0
        while len(all_candles) < target_candles:
            batch += 1
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={batch_size}"
            if end_time:
                url += f"&endTime={end_time}"

            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  Batch {batch} failed: {e}")
                break

            if not data:
                break

            for k in data:
                all_candles.append(Candle(
                    timestamp=k[0],
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                ))

            if len(data) < batch_size:
                break

            end_time = data[0][0] - 1
            days_covered = (all_candles[-1].timestamp - all_candles[0].timestamp) / (1000 * 86400)
            print(f"  Batch {batch}: {len(all_candles)} candles ({days_covered:.1f} days)")
            await asyncio.sleep(0.3)

    return all_candles


def run_optimized_backtest(candles, symbol="BTCUSDT", timeframe="5m"):
    """Run backtest with optimized parameters."""
    configs = [
        {"name": "optimized", "max_hold": 25, "trailing": False, "be": 1.0, "risk": 0.02},
        {"name": "conservative", "max_hold": 25, "trailing": False, "be": 1.0, "risk": 0.01},
        {"name": "aggressive", "max_hold": 25, "trailing": False, "be": 1.0, "risk": 0.025},
        {"name": "long_hold", "max_hold": 50, "trailing": False, "be": 1.0, "risk": 0.02},
        {"name": "short_hold", "max_hold": 18, "trailing": False, "be": 1.0, "risk": 0.02},
    ]

    results = []
    for cfg in configs:
        engine = BacktestEngine(
            initial_balance=10000,
            position_size_pct=cfg["risk"],
            max_hold_bars=cfg["max_hold"],
            breakeven_threshold=cfg["be"],
            trailing_stop=cfg["trailing"],
        )
        result = engine.run(candles, symbol=symbol, timeframe=timeframe)
        results.append({**cfg, "result": result})

    return results


def print_results(results, candles):
    """Print formatted results."""
    days = (candles[-1].timestamp - candles[0].timestamp) / (1000 * 86400)

    print(f"\n{'='*100}")
    print(f"  30-DAY BACKTEST RESULTS ({days:.1f} days, {len(candles)} candles)")
    print(f"{'='*100}")
    print(f"  {'Name':<15} {'Trades':<7} {'WR%':<6} {'PF':<6} {'DD%':<7} {'Sharpe':<7} {'PnL%':<8} {'AvgW':<8} {'AvgL':<8} {'RR':<6}")
    print(f"  {'-'*85}")

    for r in results:
        res = r["result"]
        rr = res["avg_win"] / res["avg_loss"] if res["avg_loss"] > 0 else 0
        print(
            f"  {r['name']:<15} "
            f"{res['total_trades']:<7} "
            f"{res['win_rate']*100:<6.1f} "
            f"{res['profit_factor']:<6.2f} "
            f"{res['max_drawdown_pct']:<7.2f} "
            f"{res['sharpe_ratio']:<7.2f} "
            f"{res['total_pnl_pct']:<8.2f} "
            f"${res['avg_win']:<7.2f} "
            f"${res['avg_loss']:<7.2f} "
            f"{rr:<6.2f}"
        )

    # Best config
    best = max(results, key=lambda r: r["result"]["profit_factor"] if r["result"]["total_trades"] >= 10 else -1)
    res = best["result"]
    print(f"\n  BEST: {best['name']}")
    print(f"  Trades:{res['total_trades']} WR:{res['win_rate']*100:.1f}% PF:{res['profit_factor']:.2f} DD:{res['max_drawdown_pct']:.2f}% PnL:{res['total_pnl_pct']:.2f}%")

    # Exit reason breakdown
    trades = res.get("trades", [])
    if trades:
        reasons = {}
        for t in trades:
            reason = t.get("close_reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        print(f"\n  Exit Reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:20s}: {count} ({count/len(trades)*100:.1f}%)")

    return best


async def main():
    print("="*100)
    print("  NEXUS 30-DAY COMPREHENSIVE BACKTEST")
    print("="*100)

    # Fetch data
    print("\n[1/3] Fetching 30 days of 5m data...")
    candles = await fetch_30d_candles(symbol="BTCUSDT", interval="5m", target_days=30)
    print(f"\n  Fetched {len(candles)} candles")

    if len(candles) < 100:
        print("  Not enough data!")
        return

    days = (candles[-1].timestamp - candles[0].timestamp) / (1000 * 86400)
    print(f"  Period: {days:.1f} days")
    start = time.strftime("%Y-%m-%d", time.gmtime(candles[0].timestamp / 1000))
    end = time.strftime("%Y-%m-%d", time.gmtime(candles[-1].timestamp / 1000))
    print(f"  {start} to {end}")

    # Run backtest
    print(f"\n[2/3] Running optimized backtests...")
    results = run_optimized_backtest(candles, symbol="BTCUSDT", timeframe="5m")

    # Print results
    print(f"\n[3/3] Results:")
    best = print_results(results, candles)

    # Save
    output = {
        "period_days": days,
        "candle_count": len(candles),
        "start_date": start,
        "end_date": end,
        "configs": [
            {
                "name": r["name"],
                "max_hold": r["max_hold"],
                "trailing": r["trailing"],
                "risk": r["risk"],
                "results": {
                    "total_trades": r["result"]["total_trades"],
                    "win_rate": r["result"]["win_rate"],
                    "profit_factor": r["result"]["profit_factor"],
                    "max_drawdown_pct": r["result"]["max_drawdown_pct"],
                    "sharpe_ratio": r["result"]["sharpe_ratio"],
                    "total_pnl_pct": r["result"]["total_pnl_pct"],
                    "avg_win": r["result"]["avg_win"],
                    "avg_loss": r["result"]["avg_loss"],
                }
            }
            for r in results
        ],
        "best": best["name"],
        "timestamp": time.time(),
    }

    with open(Path(__file__).parent.parent / "backtest_30d_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved to backtest_30d_results.json")


if __name__ == "__main__":
    asyncio.run(main())
