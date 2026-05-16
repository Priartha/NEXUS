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
    """Fetch historical candles from Binance."""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    candles = []
    for k in data:
        candles.append(Candle(
            timestamp=k[0],
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
        ))
    return candles


def run_backtest(
    candles: list[Candle],
    symbol: str = "BTCUSDT",
    timeframe: str = "5m",
    initial_balance: float = 10_000.0,
    position_size_pct: float = 0.02,
    max_concurrent: int = 1,
    slippage_pct: float = 0.0002,
    commission_pct: float = 0.0004,
    max_hold_bars: int = 25,
    breakeven_threshold: float = 1.0,
) -> dict:
    """Run backtest with given parameters."""
    engine = BacktestEngine(
        initial_balance=initial_balance,
        position_size_pct=position_size_pct,
        max_concurrent=max_concurrent,
        slippage_pct=slippage_pct,
        commission_pct=commission_pct,
        max_hold_bars=max_hold_bars,
        breakeven_threshold=breakeven_threshold,
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


async def quick_test(candles: list[Candle]) -> None:
    """Quick test with different timeframes and parameters."""
    print("\n" + "=" * 80)
    print("  QUICK PARAMETER TEST")
    print("=" * 80)
    print(f"  {'TF':<5} {'PosSz%':<7} {'Hold':<6} {'BE':<5} {'Trades':<7} {'Win%':<7} {'PF':<7} {'P&L%':<8} {'DD%':<7}")
    print("-" * 80)
    
    results = []
    
    # Test different timeframes
    for tf, interval in [("5m", "5m"), ("15m", "15m"), ("1h", "1h")]:
        candles_tf = await fetch_binance_candles(symbol="BTCUSDT", interval=interval, limit=1000)
        if len(candles_tf) < 100:
            continue
        
        # Test different parameters
        for pos_sz in [0.01, 0.02]:
            for hold in [12, 25]:
                for be in [0.5, 1.0]:
                    result = run_backtest(
                        candles_tf,
                        symbol="BTCUSDT",
                        timeframe=tf,
                        position_size_pct=pos_sz,
                        max_hold_bars=hold,
                        breakeven_threshold=be,
                    )
                    
                    print(
                        f"  {tf:<5} "
                        f"{pos_sz*100:<7.1f} "
                        f"{hold:<6} "
                        f"{be:<5.1f} "
                        f"{result['total_trades']:<7} "
                        f"{result['win_rate']*100:<7.1f} "
                        f"{result['profit_factor']:<7.2f} "
                        f"{result['total_pnl_pct']:<8.2f} "
                        f"{result['max_drawdown_pct']:<7.2f}"
                    )
                    
                    results.append({
                        "timeframe": tf,
                        "position_size_pct": pos_sz,
                        "max_hold_bars": hold,
                        "breakeven_threshold": be,
                        "total_trades": result["total_trades"],
                        "win_rate": result["win_rate"],
                        "profit_factor": result["profit_factor"],
                        "total_pnl_pct": result["total_pnl_pct"],
                        "max_drawdown_pct": result["max_drawdown_pct"],
                    })
    
    print("=" * 80)
    
    # Find best configuration
    profitable = [r for r in results if r["profit_factor"] > 1.0]
    if profitable:
        best = max(profitable, key=lambda r: r["profit_factor"])
        print(f"\n  BEST PROFITABLE CONFIG:")
        print(f"    Timeframe: {best['timeframe']}")
        print(f"    Position Size: {best['position_size_pct']*100}%")
        print(f"    Max Hold Bars: {best['max_hold_bars']}")
        print(f"    Breakeven Threshold: {best['breakeven_threshold']}")
        print(f"    Profit Factor: {best['profit_factor']:.2f}")
        print(f"    Win Rate: {best['win_rate']*100:.1f}%")
        print(f"    P&L: {best['total_pnl_pct']:.2f}%")
        print(f"    Max DD: {best['max_drawdown_pct']:.2f}%")
    else:
        print("\n  No profitable configurations found in this test period.")
    
    # Save results
    output_path = Path(__file__).parent.parent / "quick_test_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "results": results,
            "best_config": best if profitable else None,
            "timestamp": time.time(),
        }, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")


async def main():
    print("Fetching historical data from Binance...")
    
    # Fetch 5m candles
    candles_5m = await fetch_binance_candles(symbol="BTCUSDT", interval="5m", limit=1000)
    print(f"Fetched {len(candles_5m)} 5m candles")
    
    if len(candles_5m) < 100:
        print("Not enough candles for backtest")
        return
    
    # Run default backtest
    print("\nRunning default backtest...")
    result = run_backtest(candles_5m)
    print_results(result)
    
    # Run quick test
    await quick_test(candles_5m)


if __name__ == "__main__":
    asyncio.run(main())
