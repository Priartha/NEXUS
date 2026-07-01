"""Detailed backtest analysis of v3 engine."""

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
    url = "https://api.binance.com/api/v3/klines"
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
    
    all_candles = []
    current_start = start_time
    
    while current_start < end_time:
        params = {"symbol": symbol, "interval": interval, "limit": 1000, "startTime": current_start}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        
        if not data:
            break
            
        candles = [Candle(timestamp=int(k[0]), open=float(k[1]), high=float(k[2]),
                          low=float(k[3]), close=float(k[4]), volume=float(k[5]), is_closed=True) for k in data]
        all_candles.extend(candles)
        current_start = candles[-1].timestamp + 1
    
    return all_candles

def compute_simple_metrics(candles):
    if len(candles) < 15:
        return None
    
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    
    atrs = []
    for i in range(1, len(candles)):
        tr = max(candles[i].high - candles[i].low, abs(candles[i].high - candles[i-1].close), abs(candles[i].low - candles[i-1].close))
        atrs.append(tr)
    atr14 = sum(atrs[-14:]) / 14 if len(atrs) >= 14 else sum(atrs) / len(atrs)
    
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-14:]) / 14
    avg_loss = sum(losses[-14:]) / 14
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - 100 / (1 + rs)
    
    ema20 = closes[0]
    for c in closes[1:]:
        ema20 = (c - ema20) * (2/21) + ema20
    
    ema50 = closes[0]
    for c in closes[1:]:
        ema50 = (c - ema50) * (2/51) + ema50
    
    total_vp = sum((c.high + c.low + c.close) / 3 * c.volume for c in candles)
    total_vol = sum(c.volume for c in candles)
    vwap = total_vp / total_vol if total_vol > 0 else closes[-1]
    
    return MarketMetrics(
        timestamp=candles[-1].timestamp, atr14=atr14, ema20=ema20, ema50=ema50, rsi14=rsi,
        vwap=vwap, vwap_distance_pct=(closes[-1] - vwap) / vwap * 100 if vwap > 0 else 0,
        volume_zscore=0.0, realized_volatility=atr14 / closes[-1] * 100,
        parkinson_volatility=atr14 / closes[-1] * 100, garman_klass_volatility=atr14 / closes[-1] * 100,
        displacement_ratio=0.5, premium_discount=(closes[-1] - vwap) / vwap if vwap > 0 else 0,
        equilibrium=vwap, range_high=max(highs[-50:]), range_low=min(lows[-50:]),
        trend_score=0.0, volatility_score=atr14 / closes[-1] * 100,
        institutional_bias="neutral", bias_score=0.0, expected_move=atr14 * 1.5,
        expected_move_pct=atr14 / closes[-1] * 100 * 1.5,
    )

async def main():
    print("Fetching 30 days of BTCUSDT 5m candles...")
    candles = await fetch_candles_30d()
    print(f"Loaded {len(candles)} candles")
    print(f"Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    bh = (candles[-1].close - candles[0].close) / candles[0].close * 100
    print(f"Buy & Hold: {bh:+.2f}%\n")
    
    # Run backtest
    all_exits = []
    regime_counts = {"trending": 0, "range_bound": 0, "consolidation": 0, "accumulation": 0, "distribution": 0}
    
    print("Running backtest...")
    for i in range(200, len(candles) - 50, 1):  # Step by 1 for accurate count
        window = candles[:i+1]
        metrics = compute_simple_metrics(window)
        regime = detect_regime(window, metrics, []) if metrics else None
        
        if regime:
            regime_counts[regime.phase] = regime_counts.get(regime.phase, 0) + 1
        
        sigs = detect_v3(window, regime=regime, reward_multiple=1.5)
        
        if sigs:
            sig = sigs[0]
            entry, sl, tp = sig.entry, sig.stop_loss, sig.exit_price
            
            for j in range(i+1, min(i+50, len(candles))):
                bar = candles[j]
                if sig.side == "buy":
                    if bar.low <= sl:
                        all_exits.append({
                            "side": "buy", "pnl": -(entry - sl), "reason": "stop",
                            "confidence": sig.confidence, "rr": sig.risk_reward,
                            "entry_bar": i, "exit_bar": j, "bars_held": j - i,
                            "regime": regime.phase if regime else "unknown"
                        })
                        break
                    elif bar.high >= tp:
                        all_exits.append({
                            "side": "buy", "pnl": tp - entry, "reason": "target",
                            "confidence": sig.confidence, "rr": sig.risk_reward,
                            "entry_bar": i, "exit_bar": j, "bars_held": j - i,
                            "regime": regime.phase if regime else "unknown"
                        })
                        break
                else:
                    if bar.high >= sl:
                        all_exits.append({
                            "side": "sell", "pnl": -(sl - entry), "reason": "stop",
                            "confidence": sig.confidence, "rr": sig.risk_reward,
                            "entry_bar": i, "exit_bar": j, "bars_held": j - i,
                            "regime": regime.phase if regime else "unknown"
                        })
                        break
                    elif bar.low <= tp:
                        all_exits.append({
                            "side": "sell", "pnl": entry - tp, "reason": "target",
                            "confidence": sig.confidence, "rr": sig.risk_reward,
                            "entry_bar": i, "exit_bar": j, "bars_held": j - i,
                            "regime": regime.phase if regime else "unknown"
                        })
                        break
            else:
                final = candles[min(i+49, len(candles)-1)]
                pnl = final.close - entry if sig.side == "buy" else entry - final.close
                all_exits.append({
                    "side": sig.side, "pnl": pnl, "reason": "time",
                    "confidence": sig.confidence, "rr": sig.risk_reward,
                    "entry_bar": i, "exit_bar": min(i+49, len(candles)-1), "bars_held": min(49, len(candles)-1 - i),
                    "regime": regime.phase if regime else "unknown"
                })
    
    # Calculate stats
    wins = [e for e in all_exits if e["pnl"] > 0]
    losses = [e for e in all_exits if e["pnl"] <= 0]
    
    total_signals = len(all_exits)
    win_count = len(wins)
    win_rate = win_count / total_signals if total_signals > 0 else 0
    total_pnl = sum(e["pnl"] for e in all_exits)
    avg_win = sum(e["pnl"] for e in wins) / win_count if win_count > 0 else 0
    avg_loss = sum(e["pnl"] for e in losses) / len(losses) if losses else 0
    gross_profit = sum(e["pnl"] for e in wins)
    gross_loss = abs(sum(e["pnl"] for e in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999.99
    
    # By side
    buy_signals = [e for e in all_exits if e["side"] == "buy"]
    sell_signals = [e for e in all_exits if e["side"] == "sell"]
    buy_wr = sum(1 for e in buy_signals if e["pnl"] > 0) / len(buy_signals) if buy_signals else 0
    sell_wr = sum(1 for e in sell_signals if e["pnl"] > 0) / len(sell_signals) if sell_signals else 0
    
    # By exit reason
    stop_exits = [e for e in all_exits if e["reason"] == "stop"]
    target_exits = [e for e in all_exits if e["reason"] == "target"]
    time_exits = [e for e in all_exits if e["reason"] == "time"]
    
    # By confidence bucket
    high_conf = [e for e in all_exits if e["confidence"] >= 0.70]
    med_conf = [e for e in all_exits if 0.55 <= e["confidence"] < 0.70]
    low_conf = [e for e in all_exits if e["confidence"] < 0.55]
    
    # By regime
    by_regime = {}
    for e in all_exits:
        r = e["regime"]
        if r not in by_regime:
            by_regime[r] = []
        by_regime[r].append(e)
    
    # By RR
    high_rr = [e for e in all_exits if e["rr"] >= 1.5]
    med_rr = [e for e in all_exits if 1.0 <= e["rr"] < 1.5]
    low_rr = [e for e in all_exits if e["rr"] < 1.0]
    
    # Avg bars held
    avg_bars = sum(e["bars_held"] for e in all_exits) / total_signals if total_signals > 0 else 0
    avg_bars_wins = sum(e["bars_held"] for e in wins) / win_count if win_count > 0 else 0
    avg_bars_losses = sum(e["bars_held"] for e in losses) / len(losses) if losses else 0
    
    print("\n" + "=" * 70)
    print("NEXUS v3 - DETAILED 30 DAY BACKTEST")
    print("=" * 70)
    print(f"\nPeriod: 30 days ({len(candles)} candles)")
    print(f"Buy & Hold: {bh:+.2f}%")
    
    print(f"\n{'Metric':<30} {'Value':>15}")
    print("-" * 45)
    print(f"{'Total Signals':<30} {total_signals:>15}")
    print(f"{'Win Rate':<30} {win_rate * 100:>14.1f}%")
    print(f"{'Profit Factor':<30} {profit_factor:>15.2f}")
    print(f"{'Total PnL':<30} ${total_pnl:>14.2f}")
    print(f"{'Avg Win':<30} ${avg_win:>14.2f}")
    print(f"{'Avg Loss':<30} ${avg_loss:>14.2f}")
    print(f"{'Avg Win/Loss Ratio':<30} {abs(avg_win / avg_loss) if avg_loss != 0 else 0:>14.2f}")
    print(f"{'Gross Profit':<30} ${gross_profit:>14.2f}")
    print(f"{'Gross Loss':<30} ${gross_loss:>14.2f}")
    print(f"{'Avg Bars Held':<30} {avg_bars:>14.1f}")
    print(f"{'Avg Bars (Wins)':<30} {avg_bars_wins:>14.1f}")
    print(f"{'Avg Bars (Losses)':<30} {avg_bars_losses:>14.1f}")
    
    print(f"\n{'By Side:':<30}")
    print(f"  {'Buy Signals':<28} {len(buy_signals):>5} (WR: {buy_wr * 100:.1f}%, PnL: ${sum(e['pnl'] for e in buy_signals):.2f})")
    print(f"  {'Sell Signals':<28} {len(sell_signals):>5} (WR: {sell_wr * 100:.1f}%, PnL: ${sum(e['pnl'] for e in sell_signals):.2f})")
    
    print(f"\n{'By Exit Reason:':<30}")
    print(f"  {'Stop Loss':<28} {len(stop_exits):>5} ({len(stop_exits)/total_signals*100:.1f}%, WR: {sum(1 for e in stop_exits if e['pnl'] > 0) / len(stop_exits) * 100 if stop_exits else 0:.1f}%)")
    print(f"  {'Target Hit':<28} {len(target_exits):>5} ({len(target_exits)/total_signals*100:.1f}%, WR: {sum(1 for e in target_exits if e['pnl'] > 0) / len(target_exits) * 100 if target_exits else 0:.1f}%)")
    print(f"  {'Time Exit':<28} {len(time_exits):>5} ({len(time_exits)/total_signals*100:.1f}%, WR: {sum(1 for e in time_exits if e['pnl'] > 0) / len(time_exits) * 100 if time_exits else 0:.1f}%)")
    
    print(f"\n{'By Confidence:':<30}")
    print(f"  {'High (>=0.70)':<28} {len(high_conf):>5} (WR: {sum(1 for e in high_conf if e['pnl'] > 0) / len(high_conf) * 100 if high_conf else 0:.1f}%)")
    print(f"  {'Medium (0.55-0.70)':<28} {len(med_conf):>5} (WR: {sum(1 for e in med_conf if e['pnl'] > 0) / len(med_conf) * 100 if med_conf else 0:.1f}%)")
    print(f"  {'Low (<0.55)':<28} {len(low_conf):>5} (WR: {sum(1 for e in low_conf if e['pnl'] > 0) / len(low_conf) * 100 if low_conf else 0:.1f}%)")
    
    print(f"\n{'By RR Multiple:':<30}")
    print(f"  {'High (>=1.5)':<28} {len(high_rr):>5} (WR: {sum(1 for e in high_rr if e['pnl'] > 0) / len(high_rr) * 100 if high_rr else 0:.1f}%)")
    print(f"  {'Medium (1.0-1.5)':<28} {len(med_rr):>5} (WR: {sum(1 for e in med_rr if e['pnl'] > 0) / len(med_rr) * 100 if med_rr else 0:.1f}%)")
    print(f"  {'Low (<1.0)':<28} {len(low_rr):>5} (WR: {sum(1 for e in low_rr if e['pnl'] > 0) / len(low_rr) * 100 if low_rr else 0:.1f}%)")
    
    print(f"\n{'By Regime:':<30}")
    for phase, exits in by_regime.items():
        wr = sum(1 for e in exits if e["pnl"] > 0) / len(exits) * 100 if exits else 0
        pnl = sum(e["pnl"] for e in exits)
        print(f"  {phase:<28} {len(exits):>5} (WR: {wr:.1f}%, PnL: ${pnl:.2f})")
    
    print(f"\n{'Regime Distribution (checked):':<30}")
    for phase, count in regime_counts.items():
        print(f"  {phase:<28} {count:>5}")
    
    # Show first 5 winning and losing trades
    print(f"\n{'Sample Winning Trades:':<30}")
    for e in wins[:5]:
        print(f"  {e['side'].upper()} | Conf: {e['confidence']:.2f} | RR: {e['rr']:.2f} | PnL: ${e['pnl']:.2f} | Bars: {e['bars_held']} | Regime: {e['regime']}")
    
    print(f"\n{'Sample Losing Trades:':<30}")
    for e in losses[:5]:
        print(f"  {e['side'].upper()} | Conf: {e['confidence']:.2f} | RR: {e['rr']:.2f} | PnL: ${e['pnl']:.2f} | Bars: {e['bars_held']} | Regime: {e['regime']}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
