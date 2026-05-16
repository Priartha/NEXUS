from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch_binance_candles(
    symbol: str = "BTCUSDT",
    interval: str = "5m",
    limit: int = 1000,
) -> list[Candle]:
    """Fetch historical candles from Binance with pagination for large datasets."""
    all_candles = []
    end_time = None
    batch_size = min(limit, 1000)

    async with httpx.AsyncClient(timeout=30) as client:
        while len(all_candles) < limit:
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={batch_size}"
            if end_time:
                url += f"&endTime={end_time}"
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
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
            await asyncio.sleep(0.2)

    return all_candles[:limit]


def run_backtest(
    candles: list[Candle],
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    initial_balance: float = 10_000.0,
    position_size_pct: float = 0.02,
    max_concurrent: int = 1,
    slippage_pct: float = 0.0001,
    commission_pct: float = 0.0002,
    max_hold_bars: int = 10,
    breakeven_threshold: float = 1.0,
    trailing_stop: bool = False,
    trailing_atr_multiplier: float = 1.0,
) -> dict:
    """Run backtest with optimized parameters."""
    engine = BacktestEngine(
        initial_balance=initial_balance,
        position_size_pct=position_size_pct,
        max_concurrent=max_concurrent,
        slippage_pct=slippage_pct,
        commission_pct=commission_pct,
        max_hold_bars=max_hold_bars,
        breakeven_threshold=breakeven_threshold,
        trailing_stop=trailing_stop,
        trailing_atr_multiplier=trailing_atr_multiplier,
    )
    return engine.run(candles, symbol=symbol, timeframe=timeframe)


def print_results(result: dict) -> None:
    """Print backtest results in a readable format."""
    print("\n" + "=" * 60)
    print("  NEXUS BACKTEST RESULTS")
    print("=" * 60)

    print(f"\n  Symbol:           {result['symbol']}")
    print(f"  Timeframe:        {result['timeframe']}")
    print(f"  Candles:          {result['candle_count']}")
    
    start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(result["start_date"] / 1000))
    end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(result["end_date"] / 1000))
    print(f"  Period:           {start} to {end}")

    print(f"\n  Initial Balance:  ${result['initial_balance']:,.2f}")
    print(f"  Final Balance:    ${result['final_balance']:,.2f}")
    print(f"  Total P&L:        ${result['total_pnl']:,.2f} ({result['total_pnl_pct']:.2f}%)")

    print(f"\n  Total Trades:     {result['total_trades']}")
    print(f"  Winning Trades:   {result['winning_trades']}")
    print(f"  Losing Trades:    {result['losing_trades']}")
    print(f"  Win Rate:         {result['win_rate'] * 100:.1f}%")

    print(f"\n  Avg Win:          ${result['avg_win']:,.2f}")
    print(f"  Avg Loss:         ${result['avg_loss']:,.2f}")
    print(f"  Profit Factor:    {result['profit_factor']:.2f}")

    print(f"\n  Max Drawdown:     ${result['max_drawdown']:,.2f} ({result['max_drawdown_pct']:.2f}%)")
    print(f"  Sharpe Ratio:     {result['sharpe_ratio']:.2f}")
    print(f"  Max Cons. Losses: {result['max_consecutive_losses']}")

    print(f"\n  Slippage:         {result['slippage_pct'] * 100:.2f}%")
    print(f"  Commission:       {result['commission_pct'] * 100:.2f}%")

    # Trade breakdown
    trades = result.get("trades", [])
    if trades:
        reasons = {}
        for t in trades:
            reason = t.get("close_reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        
        print(f"\n  Exit Reasons:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    {reason:20s}: {count}")

    # Profitability verdict
    print(f"\n  {'=' * 60}")
    if result["profit_factor"] > 1.5 and result["win_rate"] > 0.45:
        print("  VERDICT: [PROFITABLE] Strategy shows strong edge")
    elif result["profit_factor"] > 1.0 and result["win_rate"] > 0.40:
        print("  VERDICT: [MARGINALLY PROFITABLE] Needs optimization")
    else:
        print("  VERDICT: [NOT PROFITABLE] Strategy needs significant improvement")
    print(f"  {'=' * 60}\n")


async def parameter_sweep(candles: list[Candle]) -> list[dict]:
    """Test multiple parameter combinations."""
    print("\nRunning parameter sweep...")

    configs = [
        {"position_size_pct": 0.01, "max_hold_bars": 25, "breakeven_threshold": 1.0, "trailing_stop": False},
        {"position_size_pct": 0.015, "max_hold_bars": 25, "breakeven_threshold": 1.0, "trailing_stop": False},
        {"position_size_pct": 0.02, "max_hold_bars": 25, "breakeven_threshold": 1.0, "trailing_stop": False},
        {"position_size_pct": 0.025, "max_hold_bars": 25, "breakeven_threshold": 1.0, "trailing_stop": False},
        {"position_size_pct": 0.02, "max_hold_bars": 18, "breakeven_threshold": 1.0, "trailing_stop": False},
        {"position_size_pct": 0.02, "max_hold_bars": 35, "breakeven_threshold": 1.0, "trailing_stop": False},
        {"position_size_pct": 0.02, "max_hold_bars": 25, "breakeven_threshold": 0.8, "trailing_stop": False},
        {"position_size_pct": 0.02, "max_hold_bars": 25, "breakeven_threshold": 1.5, "trailing_stop": False},
        {"position_size_pct": 0.02, "max_hold_bars": 25, "breakeven_threshold": 1.0, "trailing_stop": True},
        {"position_size_pct": 0.02, "max_hold_bars": 25, "breakeven_threshold": 0.8, "trailing_stop": True},
    ]

    results = []
    for i, cfg in enumerate(configs):
        print(f"  Config {i+1}/{len(configs)}: {cfg}")
        result = run_backtest(
            candles,
            position_size_pct=cfg["position_size_pct"],
            max_hold_bars=cfg["max_hold_bars"],
            breakeven_threshold=cfg["breakeven_threshold"],
            trailing_stop=cfg["trailing_stop"],
        )
        results.append({
            "config": cfg,
            "total_pnl": result["total_pnl"],
            "total_pnl_pct": result["total_pnl_pct"],
            "win_rate": result["win_rate"],
            "profit_factor": result["profit_factor"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "sharpe_ratio": result["sharpe_ratio"],
            "total_trades": result["total_trades"],
        })

    results.sort(key=lambda r: r["profit_factor"], reverse=True)

    print("\n" + "=" * 90)
    print("  PARAMETER SWEEP RESULTS (sorted by Profit Factor)")
    print("=" * 90)
    print(f"  {'#':<3} {'PosSz%':<7} {'HoldBars':<9} {'BE':<5} {'Trail':<6} {'P&L%':<10} {'Win%':<7} {'PF':<7} {'DD%':<7} {'Sharpe':<7} {'Trades':<7}")
    print("-" * 90)

    for i, r in enumerate(results):
        cfg = r["config"]
        print(
            f"  {i+1:<3} "
            f"{cfg['position_size_pct']*100:<7.1f} "
            f"{cfg['max_hold_bars']:<9} "
            f"{cfg['breakeven_threshold']:<5.1f} "
            f"{'Y' if cfg['trailing_stop'] else 'N':<6} "
            f"{r['total_pnl_pct']:<10.2f} "
            f"{r['win_rate']*100:<7.1f} "
            f"{r['profit_factor']:<7.2f} "
            f"{r['max_drawdown_pct']:<7.2f} "
            f"{r['sharpe_ratio']:<7.2f} "
            f"{r['total_trades']:<7}"
        )

    print("=" * 90)

    best = results[0]
    print(f"\n  BEST: PosSz={best['config']['position_size_pct']*100}%, "
          f"HoldBars={best['config']['max_hold_bars']}, "
          f"BE={best['config']['breakeven_threshold']}, "
          f"Trail={'Y' if best['config']['trailing_stop'] else 'N'}")
    print(f"  P&L: {best['total_pnl_pct']:.2f}%, PF: {best['profit_factor']:.2f}, "
          f"WR: {best['win_rate']*100:.1f}%, Sharpe: {best['sharpe_ratio']:.2f}")

    return results


async def main():
    print("Fetching historical data from Binance...")

    # Fetch 5m candles as primary (1000 candles = ~3.5 days)
    candles_5m = await fetch_binance_candles(symbol="BTCUSDT", interval="5m", limit=1000)
    print(f"Fetched {len(candles_5m)} 5m candles")

    if len(candles_5m) < 100:
        print("Not enough candles for backtest")
        return

    # Run default backtest with optimized config
    print("\nRunning optimized backtest (5m, no trailing, 25 bar hold)...")
    result = run_backtest(candles_5m, timeframe="5m", trailing_stop=False, max_hold_bars=25)
    print_results(result)

    # Also test 15m for comparison
    print("\n\nFetching 15m data for comparison...")
    candles_15m = await fetch_binance_candles(symbol="BTCUSDT", interval="15m", limit=1000)
    print(f"Fetched {len(candles_15m)} 15m candles")

    result_15m = None
    if len(candles_15m) >= 100:
        print("\nRunning 15m backtest (75 bar hold)...")
        result_15m = run_backtest(candles_15m, timeframe="15m", trailing_stop=False, max_hold_bars=75)
        print_results(result_15m)

    # Run parameter sweep
    print("\n\n")
    await parameter_sweep(candles_5m)

    # Save results
    output = {
        "5m_optimized": result,
        "15m_comparison": result_15m,
        "timestamp": time.time(),
    }

    output_path = Path(__file__).parent.parent / "backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
