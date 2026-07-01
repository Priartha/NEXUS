"""
Ultra-fast v1 vs v2 comparison: Test on 1000 candles only
"""
import asyncio, sys, time
sys.path.insert(0, 'D:\\Trading Setup\\NEXUS')

from backend.models.types import Candle
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_psychology import detect_market_psychology
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.price_action_readability import assess_price_action_readability
from backend.analysis.regime_v2 import detect_market_regime as detect_regime_v2
from backend.analysis.regime import detect_market_regime as detect_regime_v1
from backend.analysis.signals import detect_trade_signals as detect_v1
from backend.analysis.signals_v2 import detect_trade_signals as detect_v2
from backend.analysis.swing_detector import detect_swings

async def fetch_binance_candles(symbol="BTCUSDT", interval="5m", limit=1000, start_time=None):
    import httpx
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
    if start_time:
        params["startTime"] = start_time
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=int(k[0]), open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5]), is_closed=True) for k in data]

def simulate_signals(candles, detect_fn, regime_fn, name, reward_multiple=2.0):
    lookback = 80
    all_results = []
    regime_counts = {}

    swings = []
    fvgs = []
    order_blocks = []
    liquidity = []
    liquidity_events = []

    for i in range(100, len(candles) - 20):
        window = candles[:i + 1]
        recent = window[-lookback:]

        swings = detect_swings(window)[-250:]
        fvgs = detect_fvgs(recent)
        order_blocks = detect_order_blocks(recent, swings)
        liquidity = detect_equal_levels(swings)

        for c in recent:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)

        metrics = compute_market_metrics(window, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(recent, liquidity, atr)[-80:]
        regime = regime_fn(window, metrics, liquidity_events)
        psychology = detect_market_psychology(window, liquidity_events, regime)
        readability = assess_price_action_readability(window, swings, liquidity, regime)

        if regime:
            regime_counts[regime.phase] = regime_counts.get(regime.phase, 0) + 1

        signals = detect_fn(
            candles=window, metrics=metrics, fvgs=fvgs, order_blocks=order_blocks,
            liquidity_events=liquidity_events, swings=swings, regime=regime,
            psychology=psychology, readability=readability,
            reward_multiple=reward_multiple,
        )

        for sig in signals:
            entry = sig.entry
            sl = sig.stop_loss
            tp = sig.exit_price
            side = sig.side

            hit_tp = False
            hit_sl = False
            exit_price = None
            exit_reason = "time_exit"

            for j in range(i + 1, min(i + 31, len(candles))):
                c = candles[j]
                if side == "buy":
                    if c.high >= tp:
                        hit_tp = True
                        exit_price = tp
                        exit_reason = "target_hit"
                        break
                    if c.low <= sl:
                        hit_sl = True
                        exit_price = sl
                        exit_reason = "stop_loss"
                        break
                else:
                    if c.low <= tp:
                        hit_tp = True
                        exit_price = tp
                        exit_reason = "target_hit"
                        break
                    if c.high >= sl:
                        hit_sl = True
                        exit_price = sl
                        exit_reason = "stop_loss"
                        break

            if exit_price is None:
                exit_price = candles[min(i + 12, len(candles) - 1)].close
                exit_reason = "time_exit"

            pnl = (exit_price - entry) if side == "buy" else (entry - exit_price)

            all_results.append({
                "side": side,
                "confidence": sig.confidence,
                "pnl": pnl,
                "exit_reason": exit_reason,
                "regime": regime.phase if regime else "unknown",
                "fg_label": psychology.fear_greed_label if psychology else "unknown",
                "readability_grade": readability.grade if readability else "unknown",
            })

    wins = [r for r in all_results if r["pnl"] > 0]
    losses = [r for r in all_results if r["pnl"] <= 0]
    total_pnl = sum(r["pnl"] for r in all_results)
    avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(r["pnl"] for r in losses) / len(losses)) if losses else 0

    return {
        "name": name,
        "total_signals": len(all_results),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(all_results) if all_results else 0,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": sum(r["pnl"] for r in wins) / abs(sum(r["pnl"] for r in losses)) if losses and sum(r["pnl"] for r in losses) != 0 else 999.99,
        "regime_counts": regime_counts,
        "results": all_results,
    }

async def main():
    print("=" * 80)
    print("NEXUS SIGNAL QUALITY: v1 vs v2 (1000 candles ~3.5 days)")
    print("=" * 80)

    print("\nFetching 1000 BTCUSDT 5m candles...")
    candles = await fetch_binance_candles("BTCUSDT", "5m", 1000)
    print(f"Loaded {len(candles)} candles")
    print(f"Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    print(f"Buy & Hold: {(candles[-1].close - candles[0].close) / candles[0].close * 100:+.2f}%")

    results = []

    # v1 with old regime
    print("\n[1/4] v1 (counter-trend) + old regime...")
    t0 = time.time()
    r1 = simulate_signals(candles, detect_v1, detect_regime_v1, "v1_old_regime", reward_multiple=3.0)
    print(f"  {time.time()-t0:.1f}s: {r1['total_signals']} signals, WR: {r1['win_rate']*100:.1f}%, PnL: {r1['total_pnl']:.2f}")
    results.append(r1)

    # v1 with new regime
    print("\n[2/4] v1 (counter-trend) + new regime...")
    t0 = time.time()
    r2 = simulate_signals(candles, detect_v1, detect_regime_v2, "v1_new_regime", reward_multiple=3.0)
    print(f"  {time.time()-t0:.1f}s: {r2['total_signals']} signals, WR: {r2['win_rate']*100:.1f}%, PnL: {r2['total_pnl']:.2f}")
    results.append(r2)

    # v2 with new regime, RR=2.0
    print("\n[3/4] v2 (trend-following) + new regime, RR=2.0...")
    t0 = time.time()
    r3 = simulate_signals(candles, detect_v2, detect_regime_v2, "v2_RR2.0", reward_multiple=2.0)
    print(f"  {time.time()-t0:.1f}s: {r3['total_signals']} signals, WR: {r3['win_rate']*100:.1f}%, PnL: {r3['total_pnl']:.2f}")
    results.append(r3)

    # v2 with new regime, RR=1.5
    print("\n[4/4] v2 (trend-following) + new regime, RR=1.5...")
    t0 = time.time()
    r4 = simulate_signals(candles, detect_v2, detect_regime_v2, "v2_RR1.5", reward_multiple=1.5)
    print(f"  {time.time()-t0:.1f}s: {r4['total_signals']} signals, WR: {r4['win_rate']*100:.1f}%, PnL: {r4['total_pnl']:.2f}")
    results.append(r4)

    # Results table
    print(f"\n{'=' * 90}")
    print(f"{'Engine':<25} {'Signals':>7} {'Win%':>6} {'PF':>6} {'AvgWin':>8} {'AvgLoss':>8} {'TotalPnL':>10}")
    print("-" * 90)
    for r in results:
        print(f"{r['name']:<25} {r['total_signals']:>7} {r['win_rate']*100:>5.1f}% {r['profit_factor']:>5.2f} ${r['avg_win']:>7.2f} ${r['avg_loss']:>7.2f} ${r['total_pnl']:>9.2f}")

    # Regime distribution
    print(f"\nRegime Distribution:")
    for r in results:
        print(f"  {r['name']}: {r['regime_counts']}")

    # Best performer details
    best = max(results, key=lambda r: r["total_pnl"])
    print(f"\n{'=' * 70}")
    print(f"BEST: {best['name']}")
    print(f"  Signals: {best['total_signals']}, Win Rate: {best['win_rate']*100:.1f}%")
    print(f"  Profit Factor: {best['profit_factor']:.2f}")
    print(f"  Avg Win: ${best['avg_win']:.2f}, Avg Loss: ${best['avg_loss']:.2f}")
    print(f"  Total PnL: ${best['total_pnl']:.2f}")

    # Exit reasons
    exit_reasons = {}
    for t in best["results"]:
        r = t["exit_reason"]
        if r not in exit_reasons:
            exit_reasons[r] = {"count": 0, "wins": 0, "pnl": 0}
        exit_reasons[r]["count"] += 1
        exit_reasons[r]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            exit_reasons[r]["wins"] += 1

    print(f"\n  Exit Reasons:")
    for reason, stats in sorted(exit_reasons.items(), key=lambda x: x[1]["count"], reverse=True):
        wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        print(f"    {reason}: {stats['count']} trades, WR: {wr:.1f}%, PnL: ${stats['pnl']:.2f}")

    # By side
    side_stats = {}
    for t in best["results"]:
        s = t["side"]
        if s not in side_stats:
            side_stats[s] = {"count": 0, "wins": 0, "pnl": 0}
        side_stats[s]["count"] += 1
        side_stats[s]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            side_stats[s]["wins"] += 1

    print(f"\n  By Side:")
    for side, stats in side_stats.items():
        wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        print(f"    {side}: {stats['count']} trades, WR: {wr:.1f}%, PnL: ${stats['pnl']:.2f}")

    # By confidence
    conf_buckets = {"0.55-0.60": [], "0.60-0.65": [], "0.65-0.70": [], "0.70-0.75": [], "0.75+": []}
    for t in best["results"]:
        c = t["confidence"]
        if c < 0.60:
            conf_buckets["0.55-0.60"].append(t)
        elif c < 0.65:
            conf_buckets["0.60-0.65"].append(t)
        elif c < 0.70:
            conf_buckets["0.65-0.70"].append(t)
        elif c < 0.75:
            conf_buckets["0.70-0.75"].append(t)
        else:
            conf_buckets["0.75+"].append(t)

    print(f"\n  By Confidence:")
    for bucket, bucket_trades in conf_buckets.items():
        if bucket_trades:
            wins = sum(1 for t in bucket_trades if t["pnl"] > 0)
            wr = wins / len(bucket_trades) * 100
            pnl = sum(t["pnl"] for t in bucket_trades)
            print(f"    {bucket}: {len(bucket_trades)} trades, WR: {wr:.1f}%, PnL: ${pnl:.2f}")

asyncio.run(main())
