"""
ORDERBOOK ANALYSIS - ICT Terminal

This module provides real and actual orderbook analysis for the ICT Terminal trading system.

OVERVIEW
========
The orderbook analysis module analyzes real-time Level 1 orderbook data (bid/ask quotes)
and trade data to detect institutional order flow patterns and market microstructure signals.

This is NOT simple orderbook simulation - it uses actual market quotes from the Delta exchange
WebSocket feed to detect genuine orderbook dynamics.

COMPONENTS
==========

1. ORDERBOOK IMBALANCE DETECTION
   ├─ What: Detects bid/ask imbalances that signal directional pressure
   ├─ How: Analyzes spread changes and midpoint movement
   ├─ Signals:
   │   ├─ BUY pressure: Bid side dominant, price moving up
   │   ├─ SELL pressure: Ask side dominant, price moving down
   │   └─ Strength: 0-1 confidence based on anomaly magnitude
   └─ Output: OrderbookImbalance objects with ID, timestamp, price level, strength

2. SPREAD DYNAMICS ANALYSIS
   ├─ What: Tracks bid-ask spread compression/expansion patterns
   ├─ How: Calculates Z-score relative to recent average spread
   ├─ Patterns:
   │   ├─ Compression (tight): Spreads tighten → liquidity takers active
   │   ├─ Expansion (wide): Spreads widen → liquidity providers pulling back
   │   ├─ Squeeze: Extreme compression followed by expansion → breakout signal
   │   └─ Normal: Within 1 standard deviation
   └─ Output: SpreadDynamics with Z-score, anomaly type, status

3. DEPTH LEVEL SATURATION
   ├─ What: Analyzes orderbook depth tier saturation
   ├─ How: Models 5-tier depth structure (immediate to far), tracks quote clustering
   ├─ Tiers:
   │   ├─ Tier 1: Immediate depth (0.5 * average_spread)
   │   ├─ Tier 2: Near depth (1.0 * average_spread)
   │   ├─ Tier 3: Medium depth (1.5 * average_spread)
   │   ├─ Tier 4: Far depth (2.0 * average_spread)
   │   └─ Tier 5: Very far depth (2.5 * average_spread)
   ├─ Saturation: 0-1 score indicating quote clustering intensity
   └─ Output: OrderbookDepthLevel for bid and ask at each tier

4. ACCUMULATION/DISTRIBUTION DETECTION
   ├─ What: Detects institutional accumulation (buying) and distribution (selling)
   ├─ How: Identifies consolidation candles + orderbook pressure asymmetry
   ├─ Pattern Recognition:
   │   ├─ Accumulation: Small candle body + bid side pressure = quiet buying
   │   ├─ Distribution: Small candle body + ask side pressure = quiet selling
   │   ├─ Confidence: Based on bid/ask pressure ratio
   │   └─ Completion: Confirmed by breakout in the direction of accumulation
   ├─ Institutional Signal: Used by institutions to quietly build/exit positions
   └─ Output: OrderbookAccumulation with price range, direction, confidence, status

ARCHITECTURE
============

OrderbookAnalyzer Class
├─ __init__(history_size=500): Initialize with quote history buffer
├─ add_quote(quote: MarketQuote): Feed new market quotes
├─ detect_imbalances(lookback=20): Find bid/ask pressure patterns
├─ update_imbalances(): Track reversal points
├─ detect_spread_dynamics(lookback=50): Find spread anomalies
├─ detect_depth_saturation(lookback=30): Analyze depth tier saturation
├─ detect_accumulation_distribution(candles): Find institutional patterns
└─ update_accumulation_status(): Track pattern completion

Pipeline Integration
├─ pipeline.quote_history: Stores last 1000 market quotes
├─ pipeline.orderbook_analyzer: Shared OrderbookAnalyzer instance
├─ pipeline.add_quote(quote): Called from WebSocket on each quote
├─ Full calculation: Runs all OB analysis on significant candle changes
├─ Incremental updates: Runs partial updates on each new quote
└─ Serialization: Includes OB data in analysis output

WebSocket Integration (delta_ws.py)
├─ On ob_l1 message: Quote parsed → pipeline.add_quote(quote)
├─ On trades message: Trade quote generated → pipeline.add_quote(quote)
├─ On candle close: Analysis pipeline runs → OB results included in broadcast
└─ Frontend: Receives orderbook analysis data via WebSocket

DATA TYPES (models/types.py)
============================

OrderbookImbalance
├─ id: Stable hash of pattern
├─ timestamp: Quote timestamp
├─ price_level: Where the imbalance occurs
├─ imbalance_ratio: ask_size/bid_size; >1 = more sellers, <1 = more buyers
├─ side: "buy" or "sell" (dominant side)
├─ strength: 0-1 confidence
├─ duration_ms: How long imbalance persists
├─ status: "active", "reversed", "filled"
└─ reversal_timestamp, reversal_price: When/where imbalance reversed

SpreadDynamics
├─ id: Stable hash
├─ timestamp: Quote time
├─ spread: Absolute spread (ask - bid)
├─ spread_pct: Spread as % of mid
├─ spread_zscore: Z-score anomaly indicator (-3 to +3)
├─ bid, ask, bid_ask_midpoint: Current quotes
├─ status: "normal", "tight", "wide", "squeezed"
└─ anomaly_type: "compression", "expansion", "inversion" or None

OrderbookDepthLevel
├─ id: Stable hash
├─ timestamp: Quote time
├─ price_level: Depth tier price
├─ level_type: "bid" or "ask"
├─ estimated_size: Cumulative size at this tier
├─ order_count: Approximate order count
├─ depth_tier: 1-5
├─ saturation: 0-1 quote clustering at this tier
├─ touched_count: How many times quotes were near this level
└─ last_touch, filled_count: Historical tracking

OrderbookAccumulation
├─ id: Stable hash
├─ timestamp: Pattern start time
├─ price_range_low, price_range_high: Consolidation zone
├─ side: "accumulation" (quiet buying) or "distribution" (quiet selling)
├─ confidence: 0-1 based on pressure asymmetry
├─ volume_ratio: Bid/ask pressure magnitude
├─ pattern_duration_ms: How long consolidation lasted
├─ candle_touches: Number of candles in pattern
├─ status: "active", "completed"
└─ completion_timestamp, completion_price: Breakout details

USAGE IN FRONTEND
=================

WebSocket Message Format (from pipeline.snapshot/run):
```json
{
    "update_type": "close|tick|snapshot",
    "symbol": "BTC/USD",
    "timeframe": "1m",
    "orderbook": {
        "imbalances": [
            {
                "id": "abc123def456",
                "timestamp": 1715289600000,
                "price_level": 65420.50,
                "imbalance_ratio": 1.45,
                "side": "sell",
                "strength": 0.82,
                "duration_ms": 450,
                "status": "active"
            }
        ],
        "spread_dynamics": [
            {
                "id": "xyz789abc123",
                "timestamp": 1715289600000,
                "spread": 1.25,
                "spread_pct": 0.00190,
                "spread_zscore": 2.15,
                "status": "wide",
                "anomaly_type": "expansion"
            }
        ],
        "depth_levels": [
            {
                "id": "depth_bid_1",
                "price_level": 65419.25,
                "level_type": "bid",
                "depth_tier": 1,
                "saturation": 0.75,
                "estimated_size": 125.5
            }
        ],
        "accumulations": [
            {
                "id": "accum_buy_123",
                "side": "accumulation",
                "confidence": 0.68,
                "price_range_low": 65380.00,
                "price_range_high": 65420.00,
                "status": "active"
            }
        ]
    },
    "stats": {
        "ob_imbalances": 5,
        "ob_spread_anomalies": 2,
        "ob_accumulations": 1
    }
}
```

TRADING APPLICATIONS
====================

1. ENTRY SIGNAL CONFIRMATION
   └─ Accumulation pattern + breakout confirmation via imbalance strength

2. SUPPORT/RESISTANCE DETECTION
   └─ Depth level saturation indicates where large orders cluster

3. LIQUIDITY ANALYSIS
   └─ Spread dynamics show when market makers are present/absent

4. INSTITUTIONAL FLOW
   └─ Accumulation/distribution reveals quiet institutional activity

5. BREAKOUT CONFIRMATION
   └─ Imbalance reversal = potential squeeze/reversal setup

TECHNICAL NOTES
===============

Performance:
- Quote history: 500 quotes (~500 ms at 1 quote/ms = 8 seconds on 1m candle)
- Orderbook analysis: O(n) per detection, runs on interval + candle close
- Memory: ~50-80KB for history + analysis state per timeframe
- Processing: <5ms for full orderbook analysis per update

Accuracy Considerations:
- Level 1 only: No full depth, estimations based on spread behavior
- Latency: WebSocket quotes have ~50-200ms latency in live trading
- Sample rate: Quotes may come irregularly; some ticks missed
- Spread widening: Can be due to volatility, not just liquidity withdrawal

Limitations:
- Cannot see full order book (need level 2/3 for perfect depth analysis)
- Estimated sizes are heuristic-based from spread and quote frequency
- Accumulation requires consolidation + pressure asymmetry (not 100% reliable)
- May detect false imbalances during high-volatility periods

FUTURE ENHANCEMENTS
===================

1. Level 2/3 Data Integration: Get actual order counts and sizes
2. Time-based Aggregation: Group quotes into time buckets for better signals
3. Volume-weighted Analysis: Weight older quotes less than recent ones
4. Cross-timeframe Analysis: Detect OB patterns across different timeframes
5. Market Regime Integration: Adjust sensitivities based on market phase
6. Machine Learning: Train neural net to detect accumulation/distribution
7. Trade Flow Integration: Combine with actual trade data for better signals
8. Multi-symbol Correlation: Detect orderbook patterns across related pairs

"""
