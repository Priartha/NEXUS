"""
Orderbook analysis module for ICT Terminal.

Analyzes real-time orderbook data to detect:
- Bid/Ask imbalances and pressure signals
- Spread compression and expansion patterns
- Market depth anomalies and saturation levels
- Accumulation/Distribution patterns from orderbook structure
"""

from __future__ import annotations

from collections import deque
from backend.analysis.ids import stable_id
from backend.models.types import (
    Candle,
    OrderbookImbalance,
    OrderbookDepthLevel,
    OrderbookAccumulation,
    SpreadDynamics,
    OrderbookSnapshot,
    MarketQuote,
)


class OrderbookAnalyzer:
    """Tracks and analyzes orderbook patterns."""

    def __init__(self, history_size: int = 500):
        self.history: deque[OrderbookSnapshot] = deque(maxlen=history_size)
        self.imbalances: list[OrderbookImbalance] = []
        self.spread_dynamics: list[SpreadDynamics] = []
        self.depth_levels: list[OrderbookDepthLevel] = []
        self.accumulations: list[OrderbookAccumulation] = []

    def add_quote(self, quote: MarketQuote) -> None:
        """Add a new market quote to the analyzer."""
        if quote.bid is None or quote.ask is None:
            return
        
        spread = quote.ask - quote.bid
        snapshot = OrderbookSnapshot(
            timestamp=quote.timestamp,
            bid=quote.bid,
            ask=quote.ask,
            spread=spread,
            mid=(quote.bid + quote.ask) / 2.0,
            bid_qty=quote.bid_qty or 0.0,
            ask_qty=quote.ask_qty or 0.0,
        )
        self.history.append(snapshot)

    def detect_imbalances(self, lookback: int = 100) -> list[OrderbookImbalance]:
        """
        Detect bid/ask imbalances using quantity pressure at the best levels.
        
        During quiet periods the mid price barely moves between ticks, but the
        quantities at the best bid/ask change constantly. We measure the ratio of
        bid quantity to total quantity — when one side dominates, pressure is building.
        """
        if len(self.history) < 10:
            return []

        recent = list(self.history)[-lookback:]
        imbalances: list[OrderbookImbalance] = []
        window_size = max(10, len(recent) // 4)
        step = max(1, window_size // 2)

        for start in range(0, len(recent) - window_size + 1, step):
            window = recent[start:start + window_size]
            first, last = window[0], window[-1]

            mid_change = last.mid - first.mid
            price_move_pct = abs(mid_change) / first.mid if first.mid > 0 else 0

            avg_spread = sum(s.spread for s in window) / window_size
            full_avg_spread = sum(s.spread for s in recent) / len(recent)
            spread_tight = full_avg_spread > 0 and avg_spread < full_avg_spread * 0.9

            # Quantity pressure: ratio of bid qty to total qty over the window
            total_bid_qty = sum(s.bid_qty for s in window)
            total_ask_qty = sum(s.ask_qty for s in window)
            total_qty = total_bid_qty + total_ask_qty

            if total_qty == 0:
                continue

            bid_qty_ratio = total_bid_qty / total_qty
            ask_qty_ratio = 1.0 - bid_qty_ratio
            qty_dominance = max(bid_qty_ratio, ask_qty_ratio)

            # How much the balance shifted during the window
            first_half = window[:len(window)//2]
            second_half = window[len(window)//2:]
            bid_qty_first = sum(s.bid_qty for s in first_half)
            total_first = bid_qty_first + sum(s.ask_qty for s in first_half)
            bid_qty_second = sum(s.bid_qty for s in second_half)
            total_second = bid_qty_second + sum(s.ask_qty for s in second_half)
            ratio_shift = 0.0
            if total_first > 0 and total_second > 0:
                ratio_first = bid_qty_first / total_first
                ratio_second = bid_qty_second / total_second
                ratio_shift = abs(ratio_second - ratio_first)

            # Composite score: quantity dominance (50%), ratio shift (20%), price momentum (20%), spread tightness (10%)
            qty_score = qty_dominance
            shift_score = min(ratio_shift * 5, 1.0)
            price_score = min(price_move_pct * 5000, 1.0)
            tight_score = 0.15 if spread_tight else 0.0
            composite = qty_score * 0.5 + shift_score * 0.2 + price_score * 0.2 + tight_score * 0.1

            if composite < 0.45:
                continue

            if bid_qty_ratio > ask_qty_ratio:
                side = "buy"
                imbalance_ratio = 1.0 + (bid_qty_ratio - 0.5) * 2.0
            else:
                side = "sell"
                imbalance_ratio = 1.0 + (ask_qty_ratio - 0.5) * 2.0

            strength = min(composite, 1.0)
            duration_ms = last.timestamp - first.timestamp if last.timestamp > first.timestamp else 0

            imbalances.append(OrderbookImbalance(
                id=stable_id("ob_imb", side, round(last.mid, 2), last.timestamp, start),
                timestamp=last.timestamp,
                price_level=last.mid,
                imbalance_ratio=round(imbalance_ratio, 3),
                side=side,
                strength=round(strength, 3),
                duration_ms=duration_ms,
            ))

        return imbalances[-30:]

    def update_imbalances(
        self, 
        existing: list[OrderbookImbalance], 
        latest_quote: MarketQuote
    ) -> list[OrderbookImbalance]:
        """Update imbalance status based on new quote data."""
        if latest_quote.bid is None or latest_quote.ask is None:
            return existing
        
        current_mid = (latest_quote.bid + latest_quote.ask) / 2.0
        
        for imb in existing:
            if imb.status == "active":
                # Check if imbalance reversed
                if (imb.side == "buy" and current_mid > imb.price_level * 1.001) or \
                   (imb.side == "sell" and current_mid < imb.price_level * 0.999):
                    imb.status = "reversed"
                    imb.reversal_timestamp = latest_quote.timestamp
                    imb.reversal_price = current_mid
        
        return existing

    def detect_spread_dynamics(self, lookback: int = 50) -> list[SpreadDynamics]:
        """
        Detect spread compression, expansion, and anomalies.
        """
        if len(self.history) < 2:
            return []

        recent = list(self.history)[-lookback:]
        spreads = [snap.spread for snap in recent]
        
        avg_spread = sum(spreads) / len(spreads) if spreads else 0
        
        if avg_spread == 0:
            return []
        
        # Calculate standard deviation
        variance = sum((s - avg_spread) ** 2 for s in spreads) / len(spreads)
        std_spread = variance ** 0.5 if variance > 0 else 0.0001
        
        dynamics: list[SpreadDynamics] = []
        
        for snap in recent[-20:]:  # Analyze recent spreads
            if std_spread == 0:
                zscore = 0.0
            else:
                zscore = (snap.spread - avg_spread) / std_spread
            
            # Categorize spread dynamics
            if snap.spread < avg_spread * 0.75:
                status = "tight"
                anomaly_type = "compression" if zscore < -1 else None
            elif snap.spread > avg_spread * 1.25:
                status = "wide"
                anomaly_type = "expansion" if zscore > 1 else None
            else:
                status = "normal"
                anomaly_type = None
            
            dynamics.append(
                SpreadDynamics(
                    id=stable_id("ob_spd", status, round(snap.mid, 2), snap.timestamp),
                    timestamp=snap.timestamp,
                    spread=snap.spread,
                    spread_pct=round((snap.spread / snap.mid * 100), 6) if snap.mid > 0 else 0.0,
                    spread_zscore=zscore,
                    bid=snap.bid,
                    ask=snap.ask,
                    bid_ask_midpoint=snap.mid,
                    status=status,
                    anomaly_type=anomaly_type,
                )
            )
        
        return dynamics[-50:]

    def detect_depth_saturation(self, lookback: int = 30) -> list[OrderbookDepthLevel]:
        """
        Analyze orderbook depth levels for saturation patterns.
        
        Saturation indicates where orders are clustered and suggests
        potential support/resistance or sweep targets.
        """
        if len(self.history) < 2:
            return []

        recent = list(self.history)[-lookback:]
        mids = [snap.mid for snap in recent]
        spreads = [snap.spread for snap in recent]
        
        avg_mid = sum(mids) / len(mids) if mids else 0
        avg_spread = sum(spreads) / len(spreads) if spreads else 0.1
        
        depth_levels: list[OrderbookDepthLevel] = []
        
        # Analyze bid and ask side saturation at different tiers
        for tier in range(1, 6):  # Tier 1-5
            tier_depth = avg_spread * (0.5 + tier * 0.3)  # Calculate tier price offset
            
            # Bid side analysis
            bid_price = avg_mid - tier_depth
            bid_saturation = 0.0
            bid_touches = 0
            
            for snap in recent:
                if snap.bid > 0 and bid_price > 0 and abs(snap.bid - bid_price) / bid_price < 0.002:  # Within 0.2% of tier price
                    bid_saturation += 1.0
                    bid_touches += 1
            
            bid_saturation = bid_saturation / len(recent) if recent else 0
            
            depth_levels.append(
                OrderbookDepthLevel(
                    id=stable_id("ob_depth", "bid", round(bid_price, 2), tier),
                    timestamp=recent[-1].timestamp if recent else 0,
                    price_level=bid_price,
                    level_type="bid",
                    estimated_size=avg_spread * 100 * (1 + tier * 0.5),
                    order_count=max(1, int(10 * bid_saturation)),
                    depth_tier=tier,
                    saturation=bid_saturation,
                    touched_count=bid_touches,
                )
            )
            
            # Ask side analysis
            ask_price = avg_mid + tier_depth
            ask_saturation = 0.0
            ask_touches = 0
            
            for snap in recent:
                if snap.ask > 0 and abs(snap.ask - ask_price) / ask_price < 0.002:  # Within 0.2% of tier price
                    ask_saturation += 1.0
                    ask_touches += 1
            
            ask_saturation = ask_saturation / len(recent) if recent else 0
            
            depth_levels.append(
                OrderbookDepthLevel(
                    id=stable_id("ob_depth", "ask", round(ask_price, 2), tier),
                    timestamp=recent[-1].timestamp if recent else 0,
                    price_level=ask_price,
                    level_type="ask",
                    estimated_size=avg_spread * 100 * (1 + tier * 0.5),
                    order_count=max(1, int(10 * ask_saturation)),
                    depth_tier=tier,
                    saturation=ask_saturation,
                    touched_count=ask_touches,
                )
            )
        
        return depth_levels

    def detect_accumulation_distribution(
        self, 
        candles: list[Candle],
        lookback: int = 20
    ) -> list[OrderbookAccumulation]:
        """
        Detect accumulation/distribution patterns from orderbook and candle data.
        
        Accumulation: orderbook builds on bid side while price consolidates
        Distribution: orderbook builds on ask side while price consolidates
        """
        if not candles or len(self.history) < 2:
            return []

        recent_candles = candles[-lookback:] if len(candles) > lookback else candles
        recent_quotes = list(self.history)[-lookback:]
        
        accumulations: list[OrderbookAccumulation] = []
        
        # Analyze each candle period for accumulation/distribution
        for i in range(1, len(recent_candles)):
            candle = recent_candles[i]
            prev_candle = recent_candles[i - 1]
            
            # Detect consolidation pattern
            candle_range = candle.high - candle.low
            if candle_range == 0:
                continue
            
            body_size = abs(candle.close - candle.open)
            body_ratio = body_size / candle_range
            
            # Look for consolidation (small body relative to range)
            if body_ratio < 0.4:
                # Get quotes during this candle
                candle_quotes = [
                    q for q in recent_quotes 
                    if prev_candle.timestamp <= q.timestamp <= candle.timestamp
                ]
                
                # If no quotes for this candle, skip
                if not candle_quotes:
                    continue
                
                # Calculate bid/ask pressure during consolidation
                bid_prices = [q.bid for q in candle_quotes if q.bid and q.bid > 0]
                ask_prices = [q.ask for q in candle_quotes if q.ask and q.ask > 0]
                
                if not bid_prices or not ask_prices:
                    continue
                
                bid_avg = sum(bid_prices) / len(bid_prices)
                ask_avg = sum(ask_prices) / len(ask_prices)
                mid_avg = (bid_avg + ask_avg) / 2.0
                
                # Detect side pressure during consolidation
                bid_ask_ratio = bid_avg / ask_avg if ask_avg > 0 else 1.0
                
                if bid_ask_ratio > 1.002:  # Bid side stronger
                    side = "accumulation"
                    volume_ratio = bid_ask_ratio
                    confidence = min((bid_ask_ratio - 1.0) * 50, 0.95)
                elif bid_ask_ratio < 0.998:  # Ask side stronger
                    side = "distribution"
                    volume_ratio = ask_avg / bid_avg if bid_avg > 0 else 1.0
                    confidence = min((1.0 - bid_ask_ratio) * 50, 0.95)
                else:
                    continue
                
                # Only include meaningful patterns
                if confidence > 0.25:
                    accumulation = OrderbookAccumulation(
                        id=stable_id(
                            "ob_accum", 
                            side, 
                            round(candle.low, 2),
                            candle.timestamp
                        ),
                        timestamp=candle.timestamp,
                        price_range_low=candle.low,
                        price_range_high=candle.high,
                        side=side,
                        confidence=confidence,
                        volume_ratio=volume_ratio,
                        pattern_duration_ms=candle.timestamp - prev_candle.timestamp,
                        candle_touches=1,
                    )
                    accumulations.append(accumulation)
        
        return accumulations[-30:]

    def update_accumulation_status(
        self,
        existing: list[OrderbookAccumulation],
        latest_candle: Candle,
        latest_quote: MarketQuote,
    ) -> list[OrderbookAccumulation]:
        """Update accumulation patterns based on new price action."""
        if latest_quote.bid is None or latest_quote.ask is None:
            return existing
        
        current_mid = (latest_quote.bid + latest_quote.ask) / 2.0
        
        for accum in existing:
            if accum.status == "active":
                # Check if pattern completed/broken
                mid_price = (accum.price_range_low + accum.price_range_high) / 2.0
                
                if accum.side == "accumulation":
                    # Accumulation completes with upside breakout
                    if current_mid > accum.price_range_high * 1.001:
                        accum.status = "completed"
                        accum.completion_timestamp = latest_candle.timestamp
                        accum.completion_price = current_mid
                elif accum.side == "distribution":
                    # Distribution completes with downside breakdown
                    if current_mid < accum.price_range_low * 0.999:
                        accum.status = "completed"
                        accum.completion_timestamp = latest_candle.timestamp
                        accum.completion_price = current_mid
        
        return existing

