"""
Pre-compute signals from 30-day data for fast parameter sweeping.

Generates signals once using default parameters, then saves them to a file
for use by ultra_fast_sweep.py.
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.optimized_signals import detect_optimized_signals
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.swing_detector import detect_swings


def load_30d_data() -> list[Candle]:
    """Load 30-day historical data."""
    data_file = Path("historical_data_30d.json")
    if not data_file.exists():
        print("ERROR: historical_data_30d.json not found")
        sys.exit(1)
    
    with open(data_file) as f:
        raw = json.load(f)
    
    candles = []
    for k in raw:
        if isinstance(k, dict):
            candles.append(Candle(
                timestamp=k["timestamp"],
                open=float(k["open"]),
                high=float(k["high"]),
                low=float(k["low"]),
                close=float(k["close"]),
                volume=float(k["volume"]),
            ))
        else:
            candles.append(Candle(
                timestamp=k[0],
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
            ))
    
    return candles


def main():
    """Pre-compute signals from 30-day data."""
    print("=" * 80)
    print("  PRE-COMPUTING SIGNALS (30-DAY)")
    print("=" * 80)
    
    print("Loading 30-day data...")
    candles = load_30d_data()
    print(f"Loaded {len(candles)} candles")
    print(f"Period: {datetime.fromtimestamp(candles[0].timestamp/1000)} to {datetime.fromtimestamp(candles[-1].timestamp/1000)}")
    print()
    
    # Generate signals
    all_signals = []
    last_signal_ts = 0
    chunk_size = 80
    min_candles = 100
    cooldown = 12
    
    print("Generating signals...")
    start_time = time.time()
    
    for i in range(min_candles, len(candles)):
        chunk = candles[max(0, i - chunk_size):i]
        all_candles = candles[:i]
        
        # Analysis
        swings = detect_swings(all_candles)[-100:]
        fvgs = detect_fvgs(chunk)
        order_blocks = detect_order_blocks(chunk, swings)
        liquidity = detect_equal_levels(swings)
        
        for c in chunk:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)
        
        metrics = compute_market_metrics(all_candles, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(chunk, liquidity, atr)[-40:]
        
        # Generate signals
        signals = detect_optimized_signals(
            candles=all_candles,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity_events=liquidity_events,
            swings=swings,
            last_signal_ts=last_signal_ts,
            signal_cooldown_candles=cooldown,
            min_confidence=0.55,
            stop_loss_multiplier=2.0,
            use_adx_filter=True,
            adx_threshold=20.0,
            use_limit_orders=True,
        )
        
        for sig in signals:
            all_signals.append({
                "id": sig.id,
                "timestamp": sig.timestamp,
                "side": sig.side,
                "entry": sig.entry,
                "stop_loss": sig.stop_loss,
                "tp": sig.tp if hasattr(sig, 'tp') else None,
                "confidence": sig.confidence,
                "reason": sig.reason,
                "adx": sig.adx if hasattr(sig, 'adx') else None,
            })
            last_signal_ts = sig.timestamp
        
        # Progress
        if i % 1000 == 0:
            elapsed = time.time() - start_time
            print(f"  Processed {i}/{len(candles)} candles, {len(all_signals)} signals found ({elapsed:.1f}s)")
    
    elapsed = time.time() - start_time
    print(f"\nDone! Generated {len(all_signals)} signals in {elapsed:.1f}s")
    
    # Save signals
    output_file = Path("precomputed_signals.json")
    with open(output_file, "w") as f:
        json.dump(all_signals, f, indent=2, default=str)
    
    print(f"Saved to {output_file}")
    
    # Print summary
    buy_signals = [s for s in all_signals if s["side"] == "buy"]
    sell_signals = [s for s in all_signals if s["side"] == "sell"]
    print(f"\nSignal Summary:")
    print(f"  Total: {len(all_signals)}")
    print(f"  Buy: {len(buy_signals)}")
    print(f"  Sell: {len(sell_signals)}")
    print(f"  Avg Confidence: {sum(s['confidence'] for s in all_signals) / len(all_signals):.2f}" if all_signals else "  Avg Confidence: N/A")


if __name__ == "__main__":
    main()
