# NEXUS Signal Engine Diagnostic Report

## Executive Summary
The current signal engine is **unprofitable** across all parameter combinations. Best config lost -19.63% vs buy-and-hold +3.84%.

## Root Causes

### 1. Counter-Trend Signal Generation
- Signals are generated at FVGs/OBs as **reversal points**
- In strong trends, these are **continuation zones**, not reversals
- Result: 83.1% of trades hit stop loss, only 16.9% hit target

### 2. Regime Detector Broken
- 96.5% of time classified as "trending" (thresholds too low)
- After fix: 67.8% trending (still too high)
- No accumulation/distribution phases detected
- Means regime filtering doesn't work

### 3. Confidence Scores Inflated
- Min confidence: 0.60, Avg: 0.80
- But actual win rate: 16.9%
- Higher confidence = worse performance (0.90+ has 0% WR)
- Confidence doesn't correlate with actual edge

### 4. Too Many Signals
- Original: 534 signals in 30 days (17.8/day)
- After tightening: 89 signals (3.0/day) — still too many
- Quality over quantity needed

### 5. Risk/Reward Mismatch
- 3R target requires >25% win rate to breakeven
- Actual win rate: 16.9%
- Need either higher WR or lower RR target

## Recommendations

### Immediate Fixes
1. **Switch to trend-following signals**
   - Enter on pullbacks in direction of trend
   - Not reversals at FVGs/OBs

2. **Fix regime detector**
   - Use price structure (HH/HL vs LH/LL)
   - Not just ADX proxy

3. **Recalibrate confidence scoring**
   - Base on historical win rate, not confluence count

4. **Reduce RR target to 1.5-2R**
   - More realistic win rate achievable

5. **Add momentum filter**
   - Only trade in direction of higher timeframe trend

### Long-term
1. Backtest each component independently
2. Walk-forward optimization
3. Monte Carlo simulation for robustness
4. Live paper trading before real money

## Current State
- **All 664 configs tested**: All lose money
- **Best config**: Psychology ON + Readability ON + Killzone + B+ grade
- **Result**: -19.63% PnL, 30.9% WR, 0.57 PF
- **Buy & Hold**: +3.84%

## Conclusion
The signal engine needs a complete rethink. Current ICT-based reversal approach doesn't work in trending markets. Need to switch to trend-following or mean-reversion based on regime.
