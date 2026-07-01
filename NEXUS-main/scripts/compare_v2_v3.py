"""Quick comparison: v2 vs v3 signal engines."""

import sys
import time
import httpx
import asyncio

sys.path.insert(0, "D:\\Trading Setup\\NEXUS")

from backend.models.types import Candle, MarketMetrics
from backend.analysis.regime_v2 import detect_market_regime as detect_regime
from backend.analysis.signals_v2 import detect_trade_signals as detect_v2
from backend.analysis.signals_v3 import detect_trade_signals as detect_v3

async def fetch_candles(symbol="BTCUSDT", interval="5m", limit=1000):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=int(k[0]), open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5]), is_closed=True) for k in data]

def compute_simple_metrics(candles):
    """Compute minimal MarketMetrics for regime detection."""
    if len(candles) < 15:
        return None
    
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    
    # Simple ATR
    atrs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i-1].close),
            abs(candles[i].low - candles[i-1].close)
        )
        atrs.append(tr)
    atr14 = sum(atrs[-14:]) / 14 if len(atrs) >= 14 else sum(atrs) / len(atrs)
    
    # Simple RSI
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - 100 / (1 + rs)
    
    # EMA20
    ema20 = closes[0]
    multiplier = 2 / 21
    for c in closes[1:]:
        ema20 = (c - ema20) * multiplier + ema20
    
    # EMA50
    ema50 = closes[0]
    multiplier = 2 / 51
    for c in closes[1:]:
        ema50 = (c - ema50) * multiplier + ema50
    
    # VWAP approximation (typical price * volume weighted)
    total_vp = sum((c.high + c.low + c.close) / 3 * c.volume for c in candles)
    total_vol = sum(c.volume for c in candles)
    vwap = total_vp / total_vol if total_vol > 0 else closes[-1]
    
    return MarketMetrics(
        timestamp=candles[-1].timestamp,
        atr14=atr14,
        ema20=ema20,
        ema50=ema50,
        rsi14=rsi,
        vwap=vwap,
        vwap_distance_pct=(closes[-1] - vwap) / vwap * 100 if vwap > 0 else 0,
        volume_zscore=0.0,
        realized_volatility=atr14 / closes[-1] * 100,
        parkinson_volatility=atr14 / closes[-1] * 100,
        garman_klass_volatility=atr14 / closes[-1] * 100,
        displacement_ratio=0.5,
        premium_discount=(closes[-1] - vwap) / vwap if vwap > 0 else 0,
        equilibrium=vwap,
        range_high=max(highs[-50:]),
        range_low=min(lows[-50:]),
        trend_score=0.0,
        volatility_score=atr14 / closes[-1] * 100,
        institutional_bias="neutral",
        bias_score=0.0,
        expected_move=atr14 * 1.5,
        expected_move_pct=atr14 / closes[-1] * 100 * 1.5,
    )

def backtest_engine(name, detect_fn, candles, regime_fn, reward_multiple=2.0):
    signals = []
    exits = []
    
    for i in range(200, len(candles)):
        window = candles[:i+1]
        metrics = compute_simple_metrics(window)
        regime = regime_fn(window, metrics, []) if metrics else None
        
        sigs = detect_fn(
            window,
            regime=regime,
            reward_multiple=reward_multiple,
        )
        
        if sigs:
            sig = sigs[0]
            entry = sig.entry
            sl = sig.stop_loss
            tp = sig.exit_price
            
            for j in range(i+1, min(i+50, len(candles))):
                bar = candles[j]
                if bar.low <= sl <= bar.high or bar.high >= sl >= bar.low:
                    exits.append({"side": sig.side, "pnl": -(entry - sl) if sig.side == "buy" else -(sl - entry), "reason": "stop"})
                    break
                elif bar.high >= tp >= bar.low or bar.low <= tp <= bar.high:
                    exits.append({"side": sig.side, "pnl": tp - entry if sig.side == "buy" else entry - tp, "reason": "target"})
                    break
            else:
                final = candles[min(i+49, len(candles)-1)]
                pnl = final.close - entry if sig.side == "buy" else entry - final.close
                exits.append({"side": sig.side, "pnl": pnl, "reason": "time"})
    
    wins = sum(1 for e in exits if e["pnl"] > 0)
    total = len(exits)
    win_rate = wins / total if total > 0 else 0
    total_pnl = sum(e["pnl"] for e in exits)
    avg_win = sum(e["pnl"] for e in exits if e["pnl"] > 0) / wins if wins > 0 else 0
    avg_loss = sum(e["pnl"] for e in exits if e["pnl"] < 0) / (total - wins) if (total - wins) > 0 else 0
    
    return {
        "name": name,
        "signals": len(exits),
        "win_rate": win_rate * 100,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": abs(sum(e["pnl"] for e in exits if e["pnl"] > 0) / sum(e["pnl"] for e in exits if e["pnl"] < 0)) if sum(e["pnl"] for e in exits if e["pnl"] < 0) != 0 else 999.99,
    }

async def main():
    print("Fetching 1000 BTCUSDT 5m candles...")
    candles = await fetch_candles()
    print(f"Loaded {len(candles)} candles")
    print(f"Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    bh = (candles[-1].close - candles[0].close) / candles[0].close * 100
    print(f"Buy & Hold: {bh:+.2f}%\n")
    
    print("=" * 80)
    print("NEXUS SIGNAL QUALITY: v2 vs v3 Comparison")
    print("=" * 80)
    
    results = []
    
    # v2 with RR=2.0
    print("\n[1/3] v2 (trend-only) + RR=2.0...")
    start = time.time()
    r = backtest_engine("v2_RR2.0", detect_v2, candles, detect_regime, reward_multiple=2.0)
    print(f"  {time.time()-start:.1f}s: {r['signals']} signals, WR: {r['win_rate']:.1f}%, PnL: {r['total_pnl']:.2f}")
    results.append(r)
    
    # v3 with RR=2.0 (trend) + RR=1.2 (range)
    print("\n[2/3] v3 (hybrid) + dynamic RR...")
    start = time.time()
    r = backtest_engine("v3_hybrid", detect_v3, candles, detect_regime, reward_multiple=2.0)
    print(f"  {time.time()-start:.1f}s: {r['signals']} signals, WR: {r['win_rate']:.1f}%, PnL: {r['total_pnl']:.2f}")
    results.append(r)
    
    # v3 with RR=1.5 for trend mode
    print("\n[3/3] v3 (hybrid) + RR=1.5 trend...")
    start = time.time()
    r = backtest_engine("v3_RR1.5", detect_v3, candles, detect_regime, reward_multiple=1.5)
    print(f"  {time.time()-start:.1f}s: {r['signals']} signals, WR: {r['win_rate']:.1f}%, PnL: {r['total_pnl']:.2f}")
    results.append(r)
    
    print("\n" + "=" * 80)
    print(f"{'Engine':<20} {'Signals':>8} {'Win%':>7} {'PF':>6} {'AvgWin':>9} {'AvgLoss':>9} {'TotalPnL':>10}")
    print("-" * 80)
    for r in results:
        print(f"{r['name']:<20} {r['signals']:>8} {r['win_rate']:>6.1f}% {r['profit_factor']:>6.2f} ${r['avg_win']:>8.2f} ${r['avg_loss']:>8.2f} ${r['total_pnl']:>9.2f}")
    
    best = max(results, key=lambda r: r['total_pnl'])
    print("\n" + "=" * 50)
    print(f"BEST: {best['name']}")
    print(f"  Signals: {best['signals']}, Win Rate: {best['win_rate']:.1f}%")
    print(f"  Profit Factor: {best['profit_factor']:.2f}")
    print(f"  Avg Win: ${best['avg_win']:.2f}, Avg Loss: ${best['avg_loss']:.2f}")
    print(f"  Total PnL: ${best['total_pnl']:.2f}")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
