import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


async def fetch_candles(symbol="BTCUSDT", interval="5m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    
    return [Candle(
        timestamp=k[0], open=float(k[1]), high=float(k[2]),
        low=float(k[3]), close=float(k[4]), volume=float(k[5])
    ) for k in data]


def run_bt(candles, pos_sz=0.02, hold=25, be=1.0):
    engine = BacktestEngine(
        initial_balance=10000.0,
        position_size_pct=pos_sz,
        max_hold_bars=hold,
        breakeven_threshold=be,
    )
    return engine.run(candles, symbol="BTCUSDT", timeframe="5m")


async def main():
    print("=== NEXUS PROFITABILITY ANALYSIS ===\n")
    
    # Fetch data
    print("Fetching 1000 5m candles...")
    candles = await fetch_candles(limit=1000)
    print(f"Fetched {len(candles)} candles")
    
    start = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[0].timestamp / 1000))
    end = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[-1].timestamp / 1000))
    print(f"Period: {start} to {end}")
    
    # Test different configs
    configs = [
        {"pos_sz": 0.01, "hold": 12, "be": 0.5},
        {"pos_sz": 0.01, "hold": 12, "be": 1.0},
        {"pos_sz": 0.01, "hold": 25, "be": 0.5},
        {"pos_sz": 0.01, "hold": 25, "be": 1.0},
        {"pos_sz": 0.02, "hold": 12, "be": 0.5},
        {"pos_sz": 0.02, "hold": 12, "be": 1.0},
        {"pos_sz": 0.02, "hold": 25, "be": 0.5},
        {"pos_sz": 0.02, "hold": 25, "be": 1.0},
    ]
    
    print("\nRunning backtests...")
    results = []
    for i, cfg in enumerate(configs):
        print(f"  Config {i+1}/{len(configs)}...", end=" ", flush=True)
        result = run_bt(candles, cfg["pos_sz"], cfg["hold"], cfg["be"])
        results.append({**cfg, **result})
        print(f"Trades: {result['total_trades']}, PF: {result['profit_factor']:.2f}")
    
    # Summary
    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    print(f"  {'#':<3} {'PosSz%':<7} {'Hold':<6} {'BE':<5} {'Trades':<7} {'Win%':<7} {'PF':<7} {'P&L%':<8} {'DD%':<7}")
    print("-" * 80)
    
    for i, r in enumerate(results):
        print(
            f"  {i+1:<3} "
            f"{r['pos_sz']*100:<7.1f} "
            f"{r['hold']:<6} "
            f"{r['be']:<5.1f} "
            f"{r['total_trades']:<7} "
            f"{r['win_rate']*100:<7.1f} "
            f"{r['profit_factor']:<7.2f} "
            f"{r['total_pnl_pct']:<8.2f} "
            f"{r['max_drawdown_pct']:<7.2f}"
        )
    
    print("=" * 80)
    
    # Analysis
    profitable = [r for r in results if r["profit_factor"] > 1.0]
    if profitable:
        best = max(profitable, key=lambda r: r["profit_factor"])
        print(f"\n  BEST CONFIG: #{results.index(best)+1}")
        print(f"    Profit Factor: {best['profit_factor']:.2f}")
        print(f"    Win Rate: {best['win_rate']*100:.1f}%")
        print(f"    P&L: {best['total_pnl_pct']:.2f}%")
        print(f"    Max DD: {best['max_drawdown_pct']:.2f}%")
        print(f"    Trades: {best['total_trades']}")
    else:
        print("\n  No profitable configurations found.")
        best = max(results, key=lambda r: r["profit_factor"])
        print(f"  Best attempt: PF={best['profit_factor']:.2f}, P&L={best['total_pnl_pct']:.2f}%")
    
    # Recommendations
    print("\n" + "=" * 80)
    print("  RECOMMENDATIONS")
    print("=" * 80)
    
    avg_trades = sum(r["total_trades"] for r in results) / len(results)
    avg_pf = sum(r["profit_factor"] for r in results) / len(results)
    avg_wr = sum(r["win_rate"] for r in results) / len(results)
    
    print(f"\n  Average across all configs:")
    print(f"    Trades: {avg_trades:.1f}")
    print(f"    Profit Factor: {avg_pf:.2f}")
    print(f"    Win Rate: {avg_wr*100:.1f}%")
    
    if avg_trades < 5:
        print(f"\n  [ISSUE] Too few trades ({avg_trades:.1f} avg)")
        print(f"  -> Signal generation is too restrictive")
        print(f"  -> Lower confidence threshold or add more signal types")
    
    if avg_pf < 1.2:
        print(f"\n  [ISSUE] Low profit factor ({avg_pf:.2f} avg)")
        print(f"  -> Improve entry/exit logic")
        print(f"  -> Add regime filtering")
        print(f"  -> Consider dynamic take profit based on volatility")
    
    if avg_wr < 0.45:
        print(f"\n  [ISSUE] Low win rate ({avg_wr*100:.1f}% avg)")
        print(f"  -> Tighten stop losses")
        print(f"  -> Improve signal quality filters")
        print(f"  -> Add trend confirmation")
    
    print(f"\n  Next steps:")
    print(f"  1. Fetch more data (30+ days) for robust testing")
    print(f"  2. Add regime filtering (only trade in trending markets)")
    print(f"  3. Implement dynamic take profit (ATR-based)")
    print(f"  4. Add volume profile confirmation")
    print(f"  5. Test on multiple symbols for diversification")
    
    # Save results
    output = {
        "results": results,
        "best_config": best if profitable else None,
        "timestamp": time.time(),
    }
    output_path = Path(__file__).parent.parent / "profitability_analysis.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
