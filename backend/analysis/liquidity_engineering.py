from __future__ import annotations

from backend.analysis.ids import stable_id
from backend.models.types import Candle, LiquidityEvent, LiquidityLevel


def detect_liquidity_events(
    candles: list[Candle],
    levels: list[LiquidityLevel],
    atr: float,
) -> list[LiquidityEvent]:
    events: dict[str, LiquidityEvent] = {}
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    atr_floor = max(atr, _median_range(ordered), 1.0)

    for candle in ordered:
        for level in levels:
            if level.swept or (level.last_touch_timestamp and candle.timestamp <= level.last_touch_timestamp):
                continue

            if level.kind == "equal_high" and candle.high > level.price and candle.close < level.price:
                event = _build_event(
                    candle=candle,
                    level=level,
                    side="buy_side",
                    sweep_price=candle.high,
                    sweep_depth=candle.high - level.price,
                    atr=atr_floor,
                )
                events[event.id] = event
            elif level.kind == "equal_low" and candle.low < level.price and candle.close > level.price:
                event = _build_event(
                    candle=candle,
                    level=level,
                    side="sell_side",
                    sweep_price=candle.low,
                    sweep_depth=level.price - candle.low,
                    atr=atr_floor,
                )
                events[event.id] = event

    return sorted(events.values(), key=lambda event: event.timestamp)


def _build_event(
    candle: Candle,
    level: LiquidityLevel,
    side: str,
    sweep_price: float,
    sweep_depth: float,
    atr: float,
) -> LiquidityEvent:
    candle_range = max(candle.high - candle.low, 1.0)
    body = abs(candle.close - candle.open)
    displacement = body / atr if atr else 0.0
    wick_ratio = (
        (candle.high - max(candle.open, candle.close)) / candle_range
        if side == "buy_side"
        else (min(candle.open, candle.close) - candle.low) / candle_range
    )
    depth_ratio = sweep_depth / atr if atr else 0.0
    touch_score = min(0.3, level.touch_count * 0.075)
    depth_score = min(0.24, depth_ratio * 0.16)
    wick_score = min(0.18, max(wick_ratio, 0.0) * 0.18)
    displacement_score = min(0.16, displacement * 0.08)
    engineered_score = min(0.95, 0.22 + touch_score + depth_score + wick_score + displacement_score)
    readable_side = "buy-side" if side == "buy_side" else "sell-side"
    direction_note = "bearish reversal pressure" if side == "buy_side" else "bullish reversal pressure"

    return LiquidityEvent(
        id=stable_id("liq-event", side, level.id, candle.timestamp, round(sweep_price, 2)),
        timestamp=candle.timestamp,
        side=side,
        swept_level=round(level.price, 2),
        sweep_price=round(sweep_price, 2),
        close_price=round(candle.close, 2),
        sweep_depth=round(sweep_depth, 2),
        displacement=round(displacement, 2),
        reclaimed=True,
        engineered_score=round(engineered_score, 2),
        reason=(
            f"{readable_side} sweep reclaimed the pool; "
            f"depth {depth_ratio:.2f} ATR, {level.touch_count} touches, {direction_note}"
        ),
    )


def _median_range(candles: list[Candle]) -> float:
    if not candles:
        return 1.0
    ranges = sorted(max(candle.high - candle.low, 0.0) for candle in candles[-20:])
    midpoint = len(ranges) // 2
    if len(ranges) % 2:
        return ranges[midpoint]
    return (ranges[midpoint - 1] + ranges[midpoint]) / 2
