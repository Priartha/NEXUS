"""Full 30-day backtest of v3 signal engine."""

import sys
import time
import httpx
import asyncio
from datetime import datetime, timedelta

sys.path.insert(0, "D:\\Trading Setup\\NEXUS")

from backend.models.types import Candle, MarketMetrics
from backend.analysis.regime_v2 import detect_market_regime as detect_regime
from backend.analysis.signals import detect_trade_signals as detect_v3

async def fetch_candles_30d(symbol="BTCUSDT", interval="5m"):
    """Fetch 30 days of 5m candles (8640 candles)."""
    url = "https://api.binance.com/api/v3/klines"
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
    
    all_candles = []
    current_start = start_time
    
    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": 1000,
            "startTime": current_start
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        
        if not data:
            break
            
        candles = [Candle(timestamp=int(k[0]), open=float(k[1]), high=float(k[2]),
                          low=float(k[3]), close=float(k[4]), volume=float(k[5]), is_closed=True) for k in data]
        all_candles.extend(candles)
        
        # Move start time forward
        current_start = candles[-1].timestamp + 1
        
        print(f"  Fetched {len(all_candles)} candles so far...")
    
    return all_candles

def compute_simple_metrics(candles):
    """Compute minimal MarketMetrics for regime detection."""
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

def backtest_30d(candles):
    """Run full backtest on 30 days of data."""
    exits = []
    regime_counts = {"trending": 0, "range_bound": 0, "consolidation": 0, "accumulation": 0, "distribution": 0}
    
    print(f"\nStarting backtest on {len(candles)} candles...")
    start_time = time.time()
    
    for i in range(200, len(candles) - 50, 10):  # Step by 10 for speed
        window = candles[:i+1]
        metrics = compute_simple_metrics(window)
        regime = detect_regime(window, metrics, []) if metrics else None
        
        if regime:
            regime_counts[regime.phase] = regime_counts.get(regime.phase, 0) + 1
        
        sigs = detect_v3(window, regime=regime, reward_multiple=2.0)
        
        if sigs:
            sig = sigs[0]
            entry = sig.entry
            sl = sig.stop_loss
            tp = sig.exit_price
            
            for j in range(i+1, min(i+50, len(candles))):
                bar = candles[j]
                if sig.side == "buy":
                    if bar.low <= sl:
                        exits.append({"side": "buy", "pnl": -(entry - sl), "reason": "stop", "confidence": sig.confidence})
                        break
                    elif bar.high >= tp:
                        exits.append({"side": "buy", "pnl": tp - entry, "reason": "target", "confidence": sig.confidence})
                        break
                else:
                    if bar.high >= sl:
                        exits.append({"side": "sell", "pnl": -(sl - entry), "reason": "stop", "confidence": sig.confidence})
                        break
                    elif bar.low <= tp:
                        exits.append({"side": "sell", "pnl": entry - tp, "reason": "target", "confidence": sig.confidence})
                        break
            else:
                final = candles[min(i+49, len(candles)-1)]
                pnl = final.close - entry if sig.side == "buy" else entry - final.close
                exits.append({"side": sig.side, "pnl": pnl, "reason": "time", "confidence": sig.confidence})
        
        if (i - 200) % 1000 == 0:
            elapsed = time.time() - start_time
            progress = (i - 200) / (len(candles) - 250) * 100
            print(f"  Progress: {progress:.1f}% ({len(exits)} signals so far) [{elapsed:.1f}s]")
    
    elapsed = time.time() - start_time
    print(f"\nBacktest completed in {elapsed:.1f}s")
    
    # Calculate stats
    wins = [e for e in exits if e["pnl"] > 0]
    losses = [e for e in exits if e["pnl"] <= 0]
    
    total_signals = len(exits)
    win_count = len(wins)
    win_rate = win_count / total_signals if total_signals > 0 else 0
    total_pnl = sum(e["pnl"] for e in exits)
    avg_win = sum(e["pnl"] for e in wins) / win_count if win_count > 0 else 0
    avg_loss = sum(e["pnl"] for e in losses) / len(losses) if losses else 0
    
    gross_profit = sum(e["pnl"] for e in wins)
    gross_loss = abs(sum(e["pnl"] for e in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.99
    
    # By side
    buy_signals = [e for e in exits if e["side"] == "buy"]
    sell_signals = [e for e in exits if e["side"] == "sell"]
    buy_wr = sum(1 for e in buy_signals if e["pnl"] > 0) / len(buy_signals) if buy_signals else 0
    sell_wr = sum(1 for e in sell_signals if e["pnl"] > 0) / len(sell_signals) if sell_signals else 0
    
    # By exit reason
    stop_exits = [e for e in exits if e["reason"] == "stop"]
    target_exits = [e for e in exits if e["reason"] == "target"]
    time_exits = [e for e in exits if e["reason"] == "time"]
    
    # By confidence bucket
    high_conf = [e for e in exits if e["confidence"] >= 0.70]
    med_conf = [e for e in exits if 0.55 <= e["confidence"] < 0.70]
    low_conf = [e for e in exits if e["confidence"] < 0.55]
    
    print("\n" + "=" * 70)
    print("NEXUS v3 - 30 DAY BACKTEST RESULTS")
    print("=" * 70)
    print(f"\nPeriod: 30 days ({len(candles)} candles)")
    print(f"Buy & Hold: {(candles[-1].close - candles[0].close) / candles[0].close * 100:+.2f}%")
    
    print(f"\n{'Metric':<30} {'Value':>15}")
    print("-" * 45)
    print(f"{'Total Signals':<30} {total_signals:>15}")
    print(f"{'Win Rate':<30} {win_rate * 100:>14.1f}%")
    print(f"{'Profit Factor':<30} {profit_factor:>15.2f}")
    print(f"{'Total PnL':<30} ${total_pnl:>14.2f}")
    print(f"{'Avg Win':<30} ${avg_win:>14.2f}")
    print(f"{'Avg Loss':<30} ${avg_loss:>14.2f}")
    print(f"{'Gross Profit':<30} ${gross_profit:>14.2f}")
    print(f"{'Gross Loss':<30} ${gross_loss:>14.2f}")
    
    print(f"\n{'By Side:':<30}")
    print(f"  {'Buy Signals':<28} {len(buy_signals):>5} (WR: {buy_wr * 100:.1f}%)")
    print(f"  {'Sell Signals':<28} {len(sell_signals):>5} (WR: {sell_wr * 100:.1f}%)")
    
    print(f"\n{'By Exit Reason:':<30}")
    print(f"  {'Stop Loss':<28} {len(stop_exits):>5} ({len(stop_exits)/total_signals*100:.1f}%)")
    print(f"  {'Target Hit':<28} {len(target_exits):>5} ({len(target_exits)/total_signals*100:.1f}%)")
    print(f"  {'Time Exit':<28} {len(time_exits):>5} ({len(time_exits)/total_signals*100:.1f}%)")
    
    print(f"\n{'By Confidence:':<30}")
    print(f"  {'High (>=0.70)':<28} {len(high_conf):>5} (WR: {sum(1 for e in high_conf if e['pnl'] > 0) / len(high_conf) * 100 if high_conf else 0:.1f}%)")
    print(f"  {'Medium (0.55-0.70)':<28} {len(med_conf):>5} (WR: {sum(1 for e in med_conf if e['pnl'] > 0) / len(med_conf) * 100 if med_conf else 0:.1f}%)")
    print(f"  {'Low (<0.55)':<28} {len(low_conf):>5} (WR: {sum(1 for e in low_conf if e['pnl'] > 0) / len(low_conf) * 100 if low_conf else 0:.1f}%)")
    
    print(f"\n{'Regime Distribution:':<30}")
    for phase, count in regime_counts.items():
        print(f"  {phase:<28} {count:>5}")
    
    print("\n" + "=" * 70)

async def main():
    print("Fetching 30 days of BTCUSDT 5m candles...")
    candles = await fetch_candles_30d()
    print(f"Loaded {len(candles)} candles")
    print(f"Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    
    backtest_30d(candles)

if __name__ == "__main__":
    asyncio.run(main())
