from __future__ import annotations

import argparse
import asyncio
from collections import Counter

from backend.analysis.backtest import BacktestEngine
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.regime_v2 import detect_market_regime
from backend.analysis.swing_detector import detect_swings
from backend.analysis.unified_scalp import UnifiedScalpEngine
from backend.config import settings
from backend.ingestion.binance import fetch_historical_candles


async def main() -> int:
    parser = argparse.ArgumentParser(description="Count production signal blockers.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--candles", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    candles = await fetch_historical_candles(
        settings.market_data_rest_base_url,
        args.symbol,
        args.interval,
        limit=args.candles,
    )

    scalp = UnifiedScalpEngine()
    scalp._use_candle_timestamp_for_cooldown = True
    scalp._cur_funding = settings.futures_default_funding

    lookback = 80
    min_candles = max(lookback, 50)
    blockers: Counter[str] = Counter()
    signals = 0
    regimes: Counter[str] = Counter()

    for i in range(min_candles, len(candles)):
        window = candles[max(0, i + 1 - 500): i + 1]
        recent = window[-lookback:]
        swings = detect_swings(window)[-250:]
        fvgs = detect_fvgs(recent)
        obs = detect_order_blocks(recent, swings)
        liquidity = detect_equal_levels(swings)
        for c in recent:
            fvgs = update_fvg_fills(fvgs, c)
            obs = update_order_block_breakers(obs, c)
            liquidity = check_liquidity_sweeps(liquidity, c)
        metrics = compute_market_metrics(window, swings)
        liq_events = detect_liquidity_events(recent, liquidity, metrics.atr14 if metrics else 0.0)[-80:]
        regime = detect_market_regime(window, metrics, liq_events)
        if regime:
            regimes[regime.phase] += 1

        previous_oi = scalp._cur_oi or 500_000_000.0
        scalp._cur_oi = previous_oi * (1.001 if i % 3 == 0 else 0.9995)
        scalp._oi_hist.append((candles[i].timestamp, scalp._cur_oi))

        ctx = scalp.compute(
            candles=window,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=obs,
            swings=swings,
            regime=regime,
            liquidity_events=liq_events,
            timeframe=args.interval,
        )
        signals += len(ctx.signals)
        if ctx.trade_blocked_reasons:
            blockers.update(ctx.trade_blocked_reasons)

    engine = BacktestEngine(max_candles=0)
    result = engine.run(candles, symbol=args.symbol, timeframe=args.interval, walk_forward=True)
    summary = result.get("combined", result)

    print(f"candles={len(candles)} signals={signals}")
    print(
        "backtest "
        f"trades={summary.get('total_trades', 0)} "
        f"win_rate={summary.get('win_rate', 0):.4f} "
        f"profit_factor={summary.get('profit_factor', 0):.4f} "
        f"max_drawdown_pct={summary.get('max_drawdown_pct', 0):.4f}"
    )
    print("regimes:")
    for name, count in regimes.most_common():
        print(f"  {name}: {count}")
    print("blockers:")
    for reason, count in blockers.most_common(args.limit):
        print(f"  {count:5d}  {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
