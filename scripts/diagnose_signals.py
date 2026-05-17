"""
Diagnostic: Why is the signal engine losing money?
"""
import asyncio, sys, json, time
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
    
    # Price range
    print(f"\nPrice range: ${min(c.low for c in candles):.2f} - ${max(c.high for c in candles):.2f}")
    print(f"Start: {candles[0].close:.2f}, End: {candles[-1].close:.2f}")
    print(f"Buy & Hold: {(candles[-1].close - candles[0].close) / candles[0].close * 100:.2f}%")
    
    # Run analysis and collect signal stats
    print("\nAnalyzing signals...")
    lookback = 80
    all_signals = []
    regime_counts = {"trending": 0, "range_bound": 0, "consolidation": 0, "accumulation": 0, "distribution": 0}
    fg_counts = {}
    
    swings = []
    fvgs = []
    order_blocks = []
    liquidity = []
    liquidity_events = []
    
    for i in range(100, len(candles)):
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
        
        if regime:
            regime_counts[regime.phase] = regime_counts.get(regime.phase, 0) + 1
        
        psychology = detect_market_psychology(window, liquidity_events, regime)
        readability = assess_price_action_readability(window, swings, liquidity, regime)
        
        if psychology:
            fg = psychology.fear_greed_label
            fg_counts[fg] = fg_counts.get(fg, 0) + 1
        
        signals = detect_trade_signals(
            candles=window, metrics=metrics, fvgs=fvgs, order_blocks=order_blocks,
            liquidity_events=liquidity_events, swings=swings, regime=regime,
            psychology=psychology, readability=readability,
        )
        
        for sig in signals:
            all_signals.append({
                "timestamp": sig.timestamp,
                "side": sig.side,
                "confidence": sig.confidence,
                "entry": sig.entry,
                "stop_loss": sig.stop_loss,
                "target": sig.exit_price,
                "rr": sig.risk_reward,
                "reason": sig.reason,
                "regime": regime.phase if regime else "unknown",
                "fg_label": psychology.fear_greed_label if psychology else "unknown",
                "readability_grade": readability.grade if readability else "unknown",
            })
        
        if i % 1000 == 0:
            print(f"  Processed {i}/{len(candles)} candles, {len(all_signals)} signals so far")
    
    print(f"\nTotal signals generated: {len(all_signals)}")
    print(f"Signals per day: {len(all_signals) / 30:.1f}")
    
    # Signal distribution
    buy_signals = [s for s in all_signals if s["side"] == "buy"]
    sell_signals = [s for s in all_signals if s["side"] == "sell"]
    print(f"Buy signals: {len(buy_signals)} ({len(buy_signals)/len(all_signals)*100:.1f}%)")
    print(f"Sell signals: {len(sell_signals)} ({len(sell_signals)/len(all_signals)*100:.1f}%)")
    
    # Confidence distribution
    confs = [s["confidence"] for s in all_signals]
    print(f"\nConfidence stats:")
    print(f"  Min: {min(confs):.3f}, Max: {max(confs):.3f}, Avg: {sum(confs)/len(confs):.3f}")
    print(f"  >= 0.55: {sum(1 for c in confs if c >= 0.55)}")
    print(f"  >= 0.60: {sum(1 for c in confs if c >= 0.60)}")
    print(f"  >= 0.65: {sum(1 for c in confs if c >= 0.65)}")
    print(f"  >= 0.70: {sum(1 for c in confs if c >= 0.70)}")
    
    # Regime distribution
    print(f"\nRegime distribution:")
    for phase, count in sorted(regime_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {phase}: {count} ({count/len(candles)*100:.1f}%)")
    
    # FG distribution
    print(f"\nFear/Greed distribution:")
    for fg, count in sorted(fg_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {fg}: {count} ({count/len(candles)*100:.1f}%)")
    
    # Signal by regime
    print(f"\nSignals by regime:")
    regime_signals = {}
    for s in all_signals:
        r = s["regime"]
        regime_signals[r] = regime_signals.get(r, 0) + 1
    for r, count in sorted(regime_signals.items(), key=lambda x: x[1], reverse=True):
        print(f"  {r}: {count} signals")
    
    # Signal by FG
    print(f"\nSignals by Fear/Greed:")
    fg_signals = {}
    for s in all_signals:
        fg = s["fg_label"]
        fg_signals[fg] = fg_signals.get(fg, 0) + 1
    for fg, count in sorted(fg_signals.items(), key=lambda x: x[1], reverse=True):
        print(f"  {fg}: {count} signals")
    
    # Signal by readability
    print(f"\nSignals by Readability Grade:")
    grade_signals = {}
    for s in all_signals:
        g = s["readability_grade"]
        grade_signals[g] = grade_signals.get(g, 0) + 1
    for g, count in sorted(grade_signals.items()):
        print(f"  {g}: {count} signals")
    
    # Simulate trades with different exit strategies
    print(f"\n--- TRADE SIMULATION ---")
    
    # Check what would happen with each signal
    for exit_strategy in ["target", "stop_loss", "time_10"]:
        wins = 0
        losses = 0
        total_pnl = 0
        
        for sig in all_signals:
            idx = next((i for i, c in enumerate(candles) if c.timestamp == sig["timestamp"]), None)
            if idx is None or idx >= len(candles) - 20:
                continue
            
            entry = sig["entry"]
            sl = sig["stop_loss"]
            tp = sig["target"]
            side = sig["side"]
            
            # Simulate next 20 candles
            hit_tp = False
            hit_sl = False
            exit_price = None
            
            for j in range(idx + 1, min(idx + 21, len(candles))):
                c = candles[j]
                if side == "buy":
                    if c.high >= tp:
                        hit_tp = True
                        exit_price = tp
                        break
                    if c.low <= sl:
                        hit_sl = True
                        exit_price = sl
                        break
                else:
                    if c.low <= tp:
                        hit_tp = True
                        exit_price = tp
                        break
                    if c.high >= sl:
                        hit_sl = True
                        exit_price = sl
                        break
            
            if exit_price is None:
                exit_price = candles[min(idx + 10, len(candles) - 1)].close
            
            pnl = (exit_price - entry) if side == "buy" else (entry - exit_price)
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1
        
        total = wins + losses
        wr = wins / total * 100 if total > 0 else 0
        print(f"\n{exit_strategy}:")
        print(f"  Trades: {total}, Wins: {wins}, Losses: {losses}")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  Total PnL per unit: {total_pnl:.2f}")
        print(f"  Avg PnL per trade: {total_pnl/total:.2f}" if total > 0 else "  No trades")

asyncio.run(main())
