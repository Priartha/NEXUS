"""
Backtest: v1 (old) vs v2 (new trend-following) signal engine
"""
import asyncio, sys, time, json
from dataclasses import dataclass
sys.path.insert(0, 'D:\\Trading Setup\\NEXUS')

from backend.models.types import Candle
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_psychology import detect_market_psychology
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.price_action_readability import assess_price_action_readability
from backend.analysis.swing_detector import detect_swings

# Import both engines
from backend.analysis.signals import detect_trade_signals as detect_v1
from backend.analysis.signals_v2 import detect_trade_signals as detect_v2
from backend.analysis.regime_v2 import detect_market_regime as detect_regime_v2
from backend.analysis.regime import detect_market_regime as detect_regime_v1

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

async def fetch_30d():
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (30 * 24 * 60 * 60 * 1000)
    all_candles = []
    current = start_ms
    while current < now_ms:
        batch = await fetch_binance_candles("BTCUSDT", "5m", 1000, current)
        if not batch:
            break
        all_candles.extend(batch)
        current = batch[-1].timestamp + 60000
        await asyncio.sleep(0.2)
    seen = set()
    candles = []
    for c in all_candles:
        if c.timestamp not in seen:
            seen.add(c.timestamp)
            candles.append(c)
    return sorted(candles, key=lambda c: c.timestamp)

def run_backtest(candles, detect_fn, regime_fn, name, reward_multiple=2.0):
    lookback = 80
    initial_balance = 10_000.0
    balance = initial_balance
    peak = balance
    open_trades = []
    closed_trades = []
    equity = []

    swings = []
    fvgs = []
    order_blocks = []
    liquidity = []
    liquidity_events = []

    for i in range(100, len(candles)):
        window = candles[:i + 1]
        recent = window[-lookback:]
        current = candles[i]

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

        signals = detect_fn(
            candles=window, metrics=metrics, fvgs=fvgs, order_blocks=order_blocks,
            liquidity_events=liquidity_events, swings=swings, regime=regime,
            psychology=psychology, readability=readability,
            reward_multiple=reward_multiple,
        )

        for sig in signals:
            if len([t for t in open_trades if t["status"] == "open"]) >= 1:
                continue
            if sig.confidence < 0.55:
                continue

            risk_per_trade = balance * 0.02
            risk_per_unit = abs(sig.entry - sig.stop_loss)
            quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0
            if quantity <= 0:
                continue

            slippage = sig.entry * 0.0001
            entry_with_slippage = sig.entry + slippage if sig.side == "buy" else sig.entry - slippage
            commission = entry_with_slippage * quantity * 0.0002

            open_trades.append({
                "id": sig.id,
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry_price": round(entry_with_slippage, 2),
                "stop_loss": sig.stop_loss,
                "initial_sl": sig.stop_loss,
                "take_profit": sig.exit_price,
                "quantity": quantity,
                "status": "open",
                "confidence": sig.confidence,
                "commission": round(commission, 2),
                "bars_held": 0,
            })

        for trade in list(open_trades):
            if trade["status"] != "open":
                continue

            side = trade["side"]
            entry = trade["entry_price"]
            sl = trade["stop_loss"]
            tp = trade["take_profit"]
            qty = trade["quantity"]
            bars_held = trade.get("bars_held", 0) + 1
            trade["bars_held"] = bars_held

            # Trailing stop at 1R
            risk = abs(entry - trade.get("initial_sl", sl))
            if risk > 0:
                if side == "buy":
                    profit_r = (current.high - entry) / risk
                    if profit_r >= 1.0:
                        trade["stop_loss"] = max(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]
                else:
                    profit_r = (entry - current.low) / risk
                    if profit_r >= 1.0:
                        trade["stop_loss"] = min(trade["stop_loss"], entry)
                        sl = trade["stop_loss"]

            # Time exit
            if bars_held >= 12:
                exit_price = current.close
                pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                pnl -= trade["commission"]
                trade.update({
                    "status": "closed", "exit_price": exit_price,
                    "pnl": round(pnl, 2), "close_reason": "time_exit",
                })
                balance += pnl
                closed_trades.append(dict(trade))
                continue

            # SL / TP
            if side == "buy":
                hit_stop = current.low <= sl
                hit_target = current.high >= tp
            else:
                hit_stop = current.high >= sl
                hit_target = current.low <= tp

            if hit_stop:
                pnl = (sl - entry) * qty if side == "buy" else (entry - sl) * qty
                pnl -= trade["commission"]
                trade.update({
                    "status": "closed", "exit_price": sl,
                    "pnl": round(pnl, 2), "close_reason": "stop_loss",
                })
                balance += pnl
                closed_trades.append(dict(trade))
            elif hit_target:
                pnl = (tp - entry) * qty if side == "buy" else (entry - tp) * qty
                pnl -= trade["commission"]
                trade.update({
                    "status": "closed", "exit_price": tp,
                    "pnl": round(pnl, 2), "close_reason": "target_hit",
                })
                balance += pnl
                closed_trades.append(dict(trade))

        if balance > peak:
            peak = balance
        dd = (peak - balance) / peak * 100 if peak > 0 else 0

        if i % 100 == 0 or i == len(candles) - 1:
            equity.append({"timestamp": current.timestamp, "balance": round(balance, 2), "drawdown_pct": round(dd, 2)})

    wins = [t for t in closed_trades if t.get("pnl", 0) > 0]
    losses = [t for t in closed_trades if t.get("pnl", 0) <= 0]
    total_pnl = balance - initial_balance
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.99 if gross_profit > 0 else 0)
    max_dd = max((e["drawdown_pct"] for e in equity), default=0)

    bh_return = (candles[-1].close - candles[100].close) / candles[100].close * 100

    return {
        "name": name,
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_balance * 100, 2),
        "final_balance": round(balance, 2),
        "total_trades": len(closed_trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / len(closed_trades), 4) if closed_trades else 0,
        "profit_factor": round(pf, 4) if pf != 999.99 else 999.99,
        "max_drawdown_pct": round(max_dd, 2),
        "buy_hold_return_pct": round(bh_return, 2),
        "trades": closed_trades,
    }

async def main():
    print("=" * 80)
    print("NEXUS SIGNAL ENGINE: v1 (old) vs v2 (trend-following pullbacks)")
    print("=" * 80)

    print("\nFetching 30 days of BTCUSDT 5m data...")
    candles = await fetch_30d()
    print(f"Loaded {len(candles)} candles ({len(candles) * 5 / 60 / 24:.1f} days)")
    print(f"Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    print(f"Buy & Hold: {(candles[-1].close - candles[0].close) / candles[0].close * 100:+.2f}%")

    results = []

    # Test v1 with old regime
    print("\n[1/4] Testing v1 (old counter-trend) with old regime detector...")
    t0 = time.time()
    r1 = run_backtest(candles, detect_v1, detect_regime_v1, "v1_old_regime", reward_multiple=3.0)
    print(f"  Done in {time.time()-t0:.1f}s: {r1['total_trades']} trades, PnL: {r1['total_pnl_pct']:+.2f}%, WR: {r1['win_rate']*100:.1f}%")
    results.append(r1)

    # Test v1 with new regime
    print("\n[2/4] Testing v1 (old counter-trend) with new regime detector...")
    t0 = time.time()
    r2 = run_backtest(candles, detect_v1, detect_regime_v2, "v1_new_regime", reward_multiple=3.0)
    print(f"  Done in {time.time()-t0:.1f}s: {r2['total_trades']} trades, PnL: {r2['total_pnl_pct']:+.2f}%, WR: {r2['win_rate']*100:.1f}%")
    results.append(r2)

    # Test v2 with new regime, RR=2.0
    print("\n[3/4] Testing v2 (trend-following pullbacks) with RR=2.0...")
    t0 = time.time()
    r3 = run_backtest(candles, detect_v2, detect_regime_v2, "v2_RR2.0", reward_multiple=2.0)
    print(f"  Done in {time.time()-t0:.1f}s: {r3['total_trades']} trades, PnL: {r3['total_pnl_pct']:+.2f}%, WR: {r3['win_rate']*100:.1f}%")
    results.append(r3)

    # Test v2 with new regime, RR=1.5
    print("\n[4/4] Testing v2 (trend-following pullbacks) with RR=1.5...")
    t0 = time.time()
    r4 = run_backtest(candles, detect_v2, detect_regime_v2, "v2_RR1.5", reward_multiple=1.5)
    print(f"  Done in {time.time()-t0:.1f}s: {r4['total_trades']} trades, PnL: {r4['total_pnl_pct']:+.2f}%, WR: {r4['win_rate']*100:.1f}%")
    results.append(r4)

    # Results table
    print(f"\n{'=' * 100}")
    print(f"{'Engine':<25} {'Trades':>6} {'Win%':>6} {'PF':>6} {'PnL%':>8} {'MaxDD%':>7} {'B&H%':>8}")
    print("-" * 100)
    for r in results:
        print(f"{r['name']:<25} {r['total_trades']:>6} {r['win_rate']*100:>5.1f}% {r['profit_factor']:>5.2f} {r['total_pnl_pct']:>+7.2f}% {r['max_drawdown_pct']:>6.1f}% {r['buy_hold_return_pct']:>+7.2f}%")

    # Detailed breakdown for best performer
    best = max(results, key=lambda r: r["total_pnl_pct"])
    print(f"\n{'=' * 70}")
    print(f"BEST: {best['name']}")
    print(f"  PnL: ${best['total_pnl']:.2f} ({best['total_pnl_pct']:.2f}%)")
    print(f"  Win Rate: {best['win_rate']*100:.1f}%")
    print(f"  Profit Factor: {best['profit_factor']:.2f}")
    print(f"  Max Drawdown: {best['max_drawdown_pct']:.1f}%")
    print(f"  Trades: {best['total_trades']}")

    # Exit reason breakdown
    exit_reasons = {}
    for t in best["trades"]:
        r = t.get("close_reason", "unknown")
        if r not in exit_reasons:
            exit_reasons[r] = {"count": 0, "wins": 0, "pnl": 0}
        exit_reasons[r]["count"] += 1
        exit_reasons[r]["pnl"] += t.get("pnl", 0)
        if t.get("pnl", 0) > 0:
            exit_reasons[r]["wins"] += 1

    print(f"\n  Exit Reasons:")
    for reason, stats in sorted(exit_reasons.items(), key=lambda x: x[1]["count"], reverse=True):
        wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        print(f"    {reason}: {stats['count']} trades, WR: {wr:.1f}%, PnL: ${stats['pnl']:.2f}")

    # By side
    side_stats = {}
    for t in best["trades"]:
        s = t["side"]
        if s not in side_stats:
            side_stats[s] = {"count": 0, "wins": 0, "pnl": 0}
        side_stats[s]["count"] += 1
        side_stats[s]["pnl"] += t.get("pnl", 0)
        if t.get("pnl", 0) > 0:
            side_stats[s]["wins"] += 1

    print(f"\n  By Side:")
    for side, stats in side_stats.items():
        wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        print(f"    {side}: {stats['count']} trades, WR: {wr:.1f}%, PnL: ${stats['pnl']:.2f}")

    # By confidence
    conf_buckets = {"0.55-0.60": [], "0.60-0.65": [], "0.65-0.70": [], "0.70-0.75": [], "0.75+": []}
    for t in best["trades"]:
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

    # Save results
    output = {
        "timestamp": int(time.time() * 1000),
        "candle_count": len(candles),
        "results": [
            {
                "name": r["name"],
                "pnl_pct": r["total_pnl_pct"],
                "win_rate": r["win_rate"],
                "profit_factor": r["profit_factor"],
                "max_dd": r["max_drawdown_pct"],
                "trades": r["total_trades"],
            }
            for r in results
        ],
    }
    with open("v1_vs_v2_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to v1_vs_v2_results.json")

asyncio.run(main())
