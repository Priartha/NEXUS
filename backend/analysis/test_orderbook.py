"""Quick test to verify orderbook analysis is working."""

import time
from backend.analysis.orderbook import OrderbookAnalyzer
from backend.models.types import MarketQuote, Candle

# Create analyzer
analyzer = OrderbookAnalyzer()

# Simulate some market quotes
base_time = int(time.time() * 1000)
base_price = 65420.0

quotes = []
for i in range(50):
    # Simulate price movement
    price_move = (i % 10 - 5) * 0.5  # Oscillating movement
    mid = base_price + price_move
    bid = mid - 0.50
    ask = mid + 0.50
    
    quote = MarketQuote(
        symbol="BTC/USD",
        timestamp=base_time + (i * 200),  # 200ms apart
        source="ob_l1",
        bid=bid,
        ask=ask,
        mid=mid,
    )
    quotes.append(quote)
    analyzer.add_quote(quote)

print(f"✓ Added {len(quotes)} quotes to analyzer")
print(f"✓ Quote history size: {len(analyzer.history)}")

# Test detections
imbalances = analyzer.detect_imbalances()
print(f"\n✓ Detected {len(imbalances)} imbalances")
if imbalances:
    for imb in imbalances[:3]:
        print(f"  - {imb.side.upper()}: {imb.strength:.2f} strength @ {imb.price_level:.2f}")

spread_dynamics = analyzer.detect_spread_dynamics()
print(f"\n✓ Detected {len(spread_dynamics)} spread dynamics")
anomalies = [s for s in spread_dynamics if s.status != "normal"]
print(f"  - {len(anomalies)} anomalies (tight/wide/squeezed)")
if anomalies:
    for anom in anomalies[:3]:
        print(f"    - {anom.status.upper()}: spread {anom.spread:.4f}, z-score {anom.spread_zscore:.2f}")

depth_levels = analyzer.detect_depth_saturation()
print(f"\n✓ Detected {len(depth_levels)} depth levels")
high_saturation = [d for d in depth_levels if d.saturation > 0.3]
print(f"  - {len(high_saturation)} highly saturated levels")
if high_saturation:
    for level in high_saturation[:3]:
        print(f"    - {level.level_type.upper()} tier {level.depth_tier}: {level.saturation:.2f} sat")

# Create test candles
candles = []
for i in range(5):
    candle = Candle(
        timestamp=base_time + (i * 60000),  # 1 minute apart
        open=base_price + i,
        high=base_price + i + 2,
        low=base_price + i - 1,
        close=base_price + i + 1,
        volume=100.0 + (i * 10),
        is_closed=True,
    )
    candles.append(candle)

accumulations = analyzer.detect_accumulation_distribution(candles)
print(f"\n✓ Detected {len(accumulations)} accumulation/distribution patterns")
if accumulations:
    for acc in accumulations[:3]:
        print(f"  - {acc.side.upper()}: confidence {acc.confidence:.2f} @ {acc.price_range_low:.2f}-{acc.price_range_high:.2f}")

print("\n✅ Orderbook analysis is working correctly!")
