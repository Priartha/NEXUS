"""
Debug: Show exactly what happens with each v2 signal
"""
import asyncio, sys
sys.path.insert(0, 'D:\\Trading Setup\\NEXUS')

from backend.models.types import Candle
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_psychology import detect_market_psychology
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.price_action_readability import assess_price_action_readability
from backend.analysis.regime_v2 import detect_market_regime as detect_regime_v2
from backend.analysis.signals_v2 import detect_trade_signals as detect_v2
from backend.analysis.swing_detector import detect_swings

async def fetch_binance_candles(symbol="BTCUSDT", interval="5m", limit=1000, start_time=None):
    import httpx
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": min(limit, 1000)}
    if start_time:
        params["startTime"] = start_time
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    return [Candle(timestamp=int(k[0]), open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[5]), is_closed=True) for k in data]

async def main():
    print("Fetching 1000 candles...")
    candles = await fetch_binance_candles("BTCUSDT", "5m", 1000)
    print(f"Loaded {len(candles)} candles")
    print(f"Price: ${candles[0].close:.2f} -> ${candles[-1].close:.2f}")
    print(f"B&H: {(candles[-1].close - candles[0].close) / candles[0].close * 100:+.2f}%")

    lookback = 80
    swings = []
    fvgs = []
    order_blocks = []
    liquidity = []
    liquidity_events = []

    signal_count = 0

    for i in range(100, len(candles) - 30):
        window = candles[:i + 1]
        recent = window[-lookback:]

        swings = detect_swings(window)[-250:]
        fvgs = detect_fvgs(recent)
        order_blocks = detect_order_blocks(recent, swings)
        liquidity = detect_equal_levels(swings)

        for c in recent:
            fvgs = update_fvg_fills(fvgs, c)
            order_blocks = update_order_block_breakers(order_blocks, c)
            liquidity = check_liquidity_sweeps(liquidity, c)

        metrics = compute_market_metrics(window, swings)
        atr = metrics.atr14 if metrics else 0.0
        liquidity_events = detect_liquidity_events(recent, liquidity, atr)[-80:]
        regime = detect_regime_v2(window, metrics, liquidity_events)
        psychology = detect_market_psychology(window, liquidity_events, regime)
        readability = assess_price_action_readability(window, swings, liquidity, regime)

        signals = detect_v2(
            candles=window, metrics=metrics, fvgs=fvgs, order_blocks=order_blocks,
            liquidity_events=liquidity_events, swings=swings, regime=regime,
            psychology=psychology, readability=readability,
            reward_multiple=2.0,
        )

        for sig in signals:
            signal_count += 1
            entry = sig.entry
            sl = sig.stop_loss
            tp = sig.exit_price
            side = sig.side
            risk = abs(entry - sl)

            print(f"\nSignal #{signal_count}: {side.upper()}")
            print(f"  Entry: ${entry:.2f}, SL: ${sl:.2f}, TP: ${tp:.2f}")
            print(f"  Risk: ${risk:.2f} ({risk/entry*100:.2f}%)")
            print(f"  Confidence: {sig.confidence:.2f}")
            print(f"  Reason: {sig.reason}")
            print(f"  Regime: {regime.phase if regime else 'N/A'} ({regime.bias if regime else 'N/A'})")
            print(f"  FG: {psychology.fear_greed_label if psychology else 'N/A'}")
            print(f"  Grade: {readability.grade if readability else 'N/A'}")

            # Simulate next 30 candles
            for j in range(i + 1, min(i + 31, len(candles))):
                c = candles[j]
                bars = j - i
                if side == "buy":
                    if c.high >= tp:
                        print(f"  -> TARGET HIT at bar {bars}, price ${c.high:.2f}, PnL: +${tp - entry:.2f}")
                        break
                    if c.low <= sl:
                        print(f"  -> STOP HIT at bar {bars}, price ${c.low:.2f}, PnL: -${entry - sl:.2f}")
                        break
                else:
                    if c.low <= tp:
                        print(f"  -> TARGET HIT at bar {bars}, price ${c.low:.2f}, PnL: +${entry - tp:.2f}")
                        break
                    if c.high >= sl:
                        print(f"  -> STOP HIT at bar {bars}, price ${c.high:.2f}, PnL: -${sl - entry:.2f}")
                        break
            else:
                exit_price = candles[min(i + 12, len(candles) - 1)].close
                pnl = (exit_price - entry) if side == "buy" else (entry - exit_price)
                print(f"  -> TIME EXIT at bar 12, price ${exit_price:.2f}, PnL: ${pnl:.2f}")

            if signal_count >= 10:
                print("\n... (showing first 10 signals)")
                return

    if signal_count == 0:
        print("\nNo signals generated!")

asyncio.run(main())
