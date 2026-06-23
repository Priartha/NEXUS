# NEXUS Research Summary

## Overview
Exhaustive analysis of automated scalping strategies for BTCUSDT using
the user's Delta Exchange CSV trade history as ground truth.

## Data Sources
- `fetched_candles.json`: 3000 BTCUSDT 5m candles (Jun 10-20) — out-of-sample
- `fetched_candles_may.json`: 2865 BTCUSDT 5m candles (May 19-29) — in-sample
- `Delta-TransactionLog-OrderHistory.csv`: 18 BTCUSD closed trades (May 19-28)
- `Delta-TransactionLog-AssetHistory (3).csv`: 79 BTCUSD cashflows (May 19-Jun 20)

## User Profile (from 79 CSV trades)
- Win rate: 65.8% (52W / 27L)
- Profit factor: 2.44
- Avg win: +$0.35 | Avg loss: -$0.25
- Avg hold: ~18 min (~3.6 bars on 5m)
- Best hours (IST): 0, 2-4, 7-9, 11, 14, 16, 20, 22-23
- Worst hours: 1, 15, 17-19, 21
- Style: Small scalps, tight stops, quick exits

## Key Finding: Discretionary Edge
The user's CSV trades show 73% WR (11W/4L) in the OrderHistory subset
with full entry data. However, NO rule-based approach could replicate
this edge across any tested configuration or timeframe. The edge is
**discretionary** — the user selects entry timing based on factors not
captured by velocity, volume, or trend rules.

## Approaches Tested

### 1. Momentum v1 (original code)
- Additive scoring: velocity + volume + ATR
- Results: ~44% WR across all tests
- Root cause: Anti-persistent 5m BTC, additive scoring inflated noise

### 2. Momentum v2 (multiplicative rewrite)
- Velocity-dominant scoring (v × v/ATR × vol_ratio)
- SMA50 trend filter, breakout detection
- Results: ~40% WR regardless of threshold tuning (0.50-0.93)

### 3. Counter-trend (buy the dip)
- Entry on negative velocity (price falling)
- Positive velocity = rally sell
- Results: 43.4% WR, 0.56 PF (99 trades, too noisy)

### 4. Trend-aware
- Hourly SMA50 trend + counter-trade in trend direction
- Results: 29% WR, 0.35 PF (31 trades)

### 5. Full config sweep (5m)
- 64 configs: trend_follow + counter_trend
- Velocity thresholds: 0.03-0.10%
- Volume thresholds: 1.2-1.5x
- SL: 1.0-1.5x ATR | TP: 1.5-3.0x ATR
- Result: **ALL negative net PnL in June out-of-sample**

### 6. 15m timeframe
- 11,200 configs swept
- Max profitable: 8 trades/10.4 days, 50% WR, 2.24 PF
- All configs produce <5-8 trades — statistically insignificant
- 0 profitable configs with >=5 trades under relaxed constraints

### 7. 30m timeframe
- 11,200 configs swept
- Max profitable: 5 trades/10.5 days, 80% WR, 8.94 PF
- Same issue: too few trades for statistical confidence

## Conclusions
1. **5m BTCUSDT is anti-persistent** — price reverses within 1-2 bars,
   making momentum strategies unprofitable regardless of parameters.
2. **Higher timeframes reduce noise but kill frequency** — 15m produces
   at most 5-8 profitable trades per 10 days.
3. **The user has a genuine discretionary edge** (73% WR in OrderHistory)
   that cannot be replicated with velocity/volume/trend rules.
4. **NEXUS is best used as a research/scanner tool** to surface potential
   setups for manual evaluation, not for auto-trading.

## Scanner Tool
`backend/analysis/scanner.py` — analyzes latest candle and detects:
- Velocity (ROC1/3/5 weighted)
- Volume ratio
- ATR/volatility
- Hourly SMA50 trend
- Known patterns (momentum breakout, dip buy, rally sell, etc.)
- IST hour quality

Usage:
```python
from backend.analysis.scanner import load_candles, scan_candle_data, print_scan
candles = load_candles("fetched_candles.json")
result = scan_candle_data(candles)
print_scan(result)
```

## Pattern Rules (for reference / manual use)
These patterns came from CSV trade analysis but are NOT reliable enough
for automated trading:

| Pattern | Entry | Confirmation | Notes |
|---------|-------|-------------|-------|
| Counter-trend dip buy | vel < -0.05% | vol > 1.2x, ATR > 0.08% | User's pattern in May |
| Counter-trend rally sell | vel > 0.05% | vol > 1.2x, ATR > 0.08% | Opposite pattern |
| With-trend momentum buy | vel > 0.08% | vol > 1.3x, uptrend | Standard trend-follow |
| With-trend momentum sell | vel < -0.08% | vol > 1.3x, downtrend | Standard trend-follow |

## Files
- `backend/analysis/scanner.py` — Scanner tool
- `backend/analysis/momentum.py` — v2 momentum detector
- `backend/analysis/unified_scalp.py` — Unified scalping engine (v2 config)
- `backend/analysis/backtest.py` — Backtest engine
- `data/trader_style_profile.json` — User profile from CSV
