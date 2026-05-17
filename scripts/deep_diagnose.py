"""
Deep diagnostic: What's happening with each trade?
"""
import asyncio, sys, time
from datetime import datetime, timezone
sys.path.insert(0, 'D:\\Trading Setup\\NEXUS')

from backend.models.types import Candle
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_psychology import detect_market_psychology
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.price_action_readability import assess_price_action_readability
from backend.analysis.regime import detect_market_regime
from backend.analysis.signals import detect_trade_signals
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

async def main():
    print("Fetching 30 days of data...")
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
    candles = sorted(candles, key=lambda c: c.timestamp)
    print(f"Loaded {len(candles)} candles")
    
    # Run analysis and simulate trades
    print("\nSimulating trades with realistic exits...")
    lookback = 80
    trades = []
    
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
        regime = detect_market_regime(window, metrics, liquidity_events)
        psychology = detect_market_psychology(window, liquidity_events, regime)
        readability = assess_price_action_readability(window, swings, liquidity, regime)
        
        signals = detect_trade_signals(
            candles=window, metrics=metrics, fvgs=fvgs, order_blocks=order_blocks,
            liquidity_events=liquidity_events, swings=swings, regime=regime,
            psychology=psychology, readability=readability,
        )
        
        for sig in signals:
            entry = sig.entry
            sl = sig.stop_loss
            tp = sig.exit_price
            side = sig.side
            
            # Simulate next 50 candles
            hit_tp = False
            hit_sl = False
            exit_price = None
            exit_reason = "time_exit"
            bars_to_exit = 0
            
            for j in range(i + 1, min(i + 51, len(candles))):
                c = candles[j]
                bars_to_exit += 1
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
                exit_price = candles[min(i + 10, len(candles) - 1)].close
                exit_reason = "time_exit_10"
            
            pnl = (exit_price - entry) if side == "buy" else (entry - exit_price)
            pnl_pct = pnl / entry * 100
            
            trades.append({
                "side": side,
                "confidence": sig.confidence,
                "entry": entry,
                "exit": exit_price,
                "sl": sl,
                "tp": tp,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "exit_reason": exit_reason,
                "bars_held": bars_to_exit if exit_price else 10,
                "regime": regime.phase if regime else "unknown",
                "fg_label": psychology.fear_greed_label if psychology else "unknown",
                "readability_grade": readability.grade if readability else "unknown",
                "reason": sig.reason,
            })
    
    print(f"\nTotal trades: {len(trades)}")
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    print(f"Wins: {len(wins)} ({len(wins)/len(trades)*100:.1f}%)")
    print(f"Losses: {len(losses)} ({len(losses)/len(trades)*100:.1f}%)")
    print(f"Avg win: ${sum(t['pnl'] for t in wins)/len(wins):.2f}" if wins else "No wins")
    print(f"Avg loss: ${sum(t['pnl'] for t in losses)/len(losses):.2f}" if losses else "No losses")
    print(f"Total PnL: ${sum(t['pnl'] for t in trades):.2f}")
    
    # Exit reason breakdown
    print(f"\nExit reasons:")
    exit_reasons = {}
    for t in trades:
        r = t["exit_reason"]
        if r not in exit_reasons:
            exit_reasons[r] = {"count": 0, "wins": 0, "pnl": 0}
        exit_reasons[r]["count"] += 1
        exit_reasons[r]["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            exit_reasons[r]["wins"] += 1
    
    for r, stats in sorted(exit_reasons.items(), key=lambda x: x[1]["count"], reverse=True):
        wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
        print(f"  {r}: {stats['count']} trades, WR: {wr:.1f}%, PnL: ${stats['pnl']:.2f}")
    
    # By confidence level
    print(f"\nBy confidence level:")
    conf_buckets = {"0.65-0.70": [], "0.70-0.75": [], "0.75-0.80": [], "0.80-0.85": [], "0.85-0.90": [], "0.90+": []}
    for t in trades:
        c = t["confidence"]
        if c < 0.70:
            conf_buckets["0.65-0.70"].append(t)
        elif c < 0.75:
            conf_buckets["0.70-0.75"].append(t)
        elif c < 0.80:
            conf_buckets["0.75-0.80"].append(t)
        elif c < 0.85:
            conf_buckets["0.80-0.85"].append(t)
        elif c < 0.90:
            conf_buckets["0.85-0.90"].append(t)
        else:
            conf_buckets["0.90+"].append(t)
    
    for bucket, bucket_trades in conf_buckets.items():
        if bucket_trades:
            wins = sum(1 for t in bucket_trades if t["pnl"] > 0)
            wr = wins / len(bucket_trades) * 100
            pnl = sum(t["pnl"] for t in bucket_trades)
            print(f"  {bucket}: {len(bucket_trades)} trades, WR: {wr:.1f}%, PnL: ${pnl:.2f}")
    
    # By regime
    print(f"\nBy regime:")
    regime_trades = {}
    for t in trades:
        r = t["regime"]
        if r not in regime_trades:
            regime_trades[r] = []
        regime_trades[r].append(t)
    
    for r, r_trades in sorted(regime_trades.items(), key=lambda x: len(x[1]), reverse=True):
        wins = sum(1 for t in r_trades if t["pnl"] > 0)
        wr = wins / len(r_trades) * 100
        pnl = sum(t["pnl"] for t in r_trades)
        print(f"  {r}: {len(r_trades)} trades, WR: {wr:.1f}%, PnL: ${pnl:.2f}")
    
    # By psychology state
    print(f"\nBy psychology state:")
    fg_trades = {}
    for t in trades:
        fg = t["fg_label"]
        if fg not in fg_trades:
            fg_trades[fg] = []
        fg_trades[fg].append(t)
    
    for fg, fg_t in sorted(fg_trades.items(), key=lambda x: len(x[1]), reverse=True):
        wins = sum(1 for t in fg_t if t["pnl"] > 0)
        wr = wins / len(fg_t) * 100
        pnl = sum(t["pnl"] for t in fg_t)
        print(f"  {fg}: {len(fg_t)} trades, WR: {wr:.1f}%, PnL: ${pnl:.2f}")
    
    # By readability grade
    print(f"\nBy readability grade:")
    grade_trades = {}
    for t in trades:
        g = t["readability_grade"]
        if g not in grade_trades:
            grade_trades[g] = []
        grade_trades[g].append(t)
    
    for g, g_t in sorted(grade_trades.items()):
        wins = sum(1 for t in g_t if t["pnl"] > 0)
        wr = wins / len(g_t) * 100
        pnl = sum(t["pnl"] for t in g_t)
        print(f"  {g}: {len(g_t)} trades, WR: {wr:.1f}%, PnL: ${pnl:.2f}")
    
    # By side
    print(f"\nBy side:")
    side_trades = {}
    for t in trades:
        s = t["side"]
        if s not in side_trades:
            side_trades[s] = []
        side_trades[s].append(t)
    
    for s, s_t in side_trades.items():
        wins = sum(1 for t in s_t if t["pnl"] > 0)
        wr = wins / len(s_t) * 100
        pnl = sum(t["pnl"] for t in s_t)
        print(f"  {s}: {len(s_t)} trades, WR: {wr:.1f}%, PnL: ${pnl:.2f}")
    
    # Show worst trades
    print(f"\nWorst 5 trades:")
    sorted_trades = sorted(trades, key=lambda t: t["pnl"])
    for t in sorted_trades[:5]:
        print(f"  {t['side']} conf={t['confidence']:.2f} pnl=${t['pnl']:.2f} ({t['pnl_pct']:.2f}%) reason={t['reason'][:60]}")
    
    # Show best trades
    print(f"\nBest 5 trades:")
    for t in sorted_trades[-5:]:
        print(f"  {t['side']} conf={t['confidence']:.2f} pnl=${t['pnl']:.2f} ({t['pnl_pct']:.2f}%) reason={t['reason'][:60]}")

asyncio.run(main())
