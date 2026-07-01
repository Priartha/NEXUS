"""Debug v3 signals to understand why win rate is so low."""

import sys
import httpx
import asyncio

sys.path.insert(0, "D:\\Trading Setup\\NEXUS")

from backend.models.types import Candle, MarketMetrics
from backend.analysis.regime_v2 import detect_market_regime as detect_regime
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
    if len(candles) < 15:
        return None
    
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    
    atrs = []
    for i in range(1, len(candles)):
        tr = max(
            candles[i].high - candles[i].low,
            abs(candles[i].high - candles[i-1].close),
            abs(candles[i].low - candles[i-1].close)
        )
        atrs.append(tr)
    atr14 = sum(atrs[-14:]) / 14 if len(atrs) >= 14 else sum(atrs) / len(atrs)
    
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
    
    ema20 = closes[0]
    multiplier = 2 / 21
    for c in closes[1:]:
        ema20 = (c - ema20) * multiplier + ema20
    
    ema50 = closes[0]
    multiplier = 2 / 51
    for c in closes[1:]:
        ema50 = (c - ema50) * multiplier + ema50
    
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

async def main():
    print("Fetching 1000 BTCUSDT 5m candles...")
    candles = await fetch_candles()
    print(f"Loaded {len(candles)} candles")
    print(f"Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    bh = (candles[-1].close - candles[0].close) / candles[0].close * 100
    print(f"Buy & Hold: {bh:+.2f}%\n")
    
    # Find all signals
    signal_indices = []
    
    for idx in range(200, len(candles) - 50):
        window = candles[:idx+1]
        metrics = compute_simple_metrics(window)
        regime = detect_regime(window, metrics, []) if metrics else None
        
        sigs = detect_v3(window, regime=regime, reward_multiple=1.5)
        
        if sigs:
            signal_indices.append(idx)
    
    print(f"Found {len(signal_indices)} signals at indices: {signal_indices[:20]}...")
    
    # Show first 10 signals in detail
    for idx in signal_indices[:10]:
        window = candles[:idx+1]
        metrics = compute_simple_metrics(window)
        regime = detect_regime(window, metrics, []) if metrics else None
        
        sigs = detect_v3(window, regime=regime, reward_multiple=1.5)
        
        if sigs:
            sig = sigs[0]
            print(f"\n{'='*60}")
            print(f"Index {idx}: {sig.side.upper()} signal")
            print(f"  Entry: ${sig.entry:.2f}")
            print(f"  SL: ${sig.stop_loss:.2f}")
            print(f"  TP: ${sig.exit_price:.2f}")
            print(f"  Confidence: {sig.confidence:.3f}")
            print(f"  RR: {sig.risk_reward:.2f}")
            print(f"  Reason: {sig.reason}")
            if regime:
                print(f"  Regime: {regime.phase} ({regime.bias})")
            
            # Simulate exit
            entry = sig.entry
            sl = sig.stop_loss
            tp = sig.exit_price
            
            for j in range(idx+1, min(idx+50, len(candles))):
                bar = candles[j]
                if sig.side == "buy":
                    if bar.low <= sl:
                        pnl = -(entry - sl)
                        print(f"  -> STOP HIT at bar {j}, price ${bar.low:.2f}, PnL: ${pnl:.2f}")
                        break
                    elif bar.high >= tp:
                        pnl = tp - entry
                        print(f"  -> TARGET HIT at bar {j}, price ${bar.high:.2f}, PnL: ${pnl:.2f}")
                        break
                else:
                    if bar.high >= sl:
                        pnl = -(sl - entry)
                        print(f"  -> STOP HIT at bar {j}, price ${bar.high:.2f}, PnL: ${pnl:.2f}")
                        break
                    elif bar.low <= tp:
                        pnl = entry - tp
                        print(f"  -> TARGET HIT at bar {j}, price ${bar.low:.2f}, PnL: ${pnl:.2f}")
                        break
            else:
                final = candles[min(idx+49, len(candles)-1)]
                pnl = final.close - entry if sig.side == "buy" else entry - final.close
                print(f"  -> TIME EXIT at bar {min(idx+49, len(candles)-1)}, price ${final.close:.2f}, PnL: ${pnl:.2f}")

if __name__ == "__main__":
    asyncio.run(main())
