"""Debug: check signal stop/target values."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.models.types import Candle
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.swing_detector import detect_swings
from backend.analysis.regime import detect_market_regime
from backend.analysis.signals import detect_trade_signals


def main():
    print("Loading candles...")
    with open(Path(__file__).parent.parent/"fetched_candles.json") as f:
        raw = json.load(f)
    candles = [Candle(timestamp=c["t"],open=c["o"],high=c["h"],low=c["l"],close=c["c"],volume=c["v"]) for c in raw]
    candles.sort(key=lambda c: c.timestamp)

    # Run through pipeline at a few points and check signals
    for idx in [500, 1000, 1500, 2000, 2500]:
        window = candles[:idx+1]
        recent = window[-80:]
        swings = detect_swings(window)[-250:]
        fvgs = detect_fvgs(recent)
        obs = detect_order_blocks(recent, swings)
        liq = detect_equal_levels(swings)
        for c in recent[-20:]:
            fvgs = update_fvg_fills(fvgs, c)
            obs = update_order_block_breakers(obs, c)
            liq = check_liquidity_sweeps(liq, c)
        metrics = compute_market_metrics(window, swings)
        atr = metrics.atr14 if metrics else 0
        liq_events = detect_liquidity_events(recent, liq, atr)[-80:]
        regime = detect_market_regime(window, metrics, liq_events)

        signals = detect_trade_signals(window, metrics, fvgs, obs, liq_events, swings, regime=regime)

        if signals:
            sig = signals[0]
            risk = abs(sig.entry - sig.stop_loss)
            reward = abs(sig.exit_price - sig.entry)
            print(f"  idx={idx} | {sig.side} | entry={sig.entry:.0f} | SL={sig.stop_loss:.0f} | TP={sig.exit_price:.0f} | risk={risk:.0f} | reward={reward:.0f} | RR={reward/risk:.2f} | conf={sig.confidence:.2f} | regime={regime.phase if regime else 'N/A'}")
        else:
            print(f"  idx={idx} | no signal | regime={regime.phase if regime else 'N/A'}")


if __name__ == "__main__":
    main()
