from __future__ import annotations

from backend.analysis.ids import stable_id
from backend.models.types import Candle, OrderBlock, Swing


def detect_order_blocks(candles: list[Candle], swings: list[Swing]) -> list[OrderBlock]:
    blocks: list[OrderBlock] = []
    swing_highs = sorted((s for s in swings if s.kind == "high"), key=lambda swing: swing.timestamp)
    swing_lows = sorted((s for s in swings if s.kind == "low"), key=lambda swing: swing.timestamp)
    used_breaks: set[tuple[str, int]] = set()

    for i in range(3, len(candles)):
        current = candles[i]
        recent = candles[i - 2 : i + 1]

        if all(candle.close > candle.open for candle in recent):
            broken_high = _latest_broken_swing(swing_highs, current, direction="bullish")
            if broken_high and ("high", broken_high.timestamp) not in used_breaks:
                source = _last_opposing_candle(candles, start=i - 3, bullish=True)
                if source:
                    blocks.append(_build_order_block(source, "bullish"))
                    used_breaks.add(("high", broken_high.timestamp))

        if all(candle.close < candle.open for candle in recent):
            broken_low = _latest_broken_swing(swing_lows, current, direction="bearish")
            if broken_low and ("low", broken_low.timestamp) not in used_breaks:
                source = _last_opposing_candle(candles, start=i - 3, bullish=False)
                if source:
                    blocks.append(_build_order_block(source, "bearish"))
                    used_breaks.add(("low", broken_low.timestamp))

    deduped: dict[str, OrderBlock] = {}
    for block in blocks:
        deduped[block.id] = block
    return list(deduped.values())


def update_order_block_breakers(blocks: list[OrderBlock], latest_candle: Candle) -> list[OrderBlock]:
    for block in blocks:
        if block.is_breaker or latest_candle.timestamp <= block.timestamp:
            continue
        if block.direction == "bullish" and latest_candle.close < block.bottom:
            block.is_breaker = True
            block.breaker_timestamp = latest_candle.timestamp
        elif block.direction == "bearish" and latest_candle.close > block.top:
            block.is_breaker = True
            block.breaker_timestamp = latest_candle.timestamp
    return blocks


def _latest_broken_swing(swings: list[Swing], candle: Candle, direction: str) -> Swing | None:
    candidates = [swing for swing in swings if swing.timestamp < candle.timestamp]
    for swing in reversed(candidates):
        if direction == "bullish" and candle.close > swing.price:
            return swing
        if direction == "bearish" and candle.close < swing.price:
            return swing
    return None


def _last_opposing_candle(candles: list[Candle], start: int, bullish: bool) -> Candle | None:
    stop = max(-1, start - 10)
    for index in range(start, stop, -1):
        candle = candles[index]
        if bullish and candle.close < candle.open:
            return candle
        if not bullish and candle.close > candle.open:
            return candle
    return None


def _build_order_block(candle: Candle, direction: str) -> OrderBlock:
    body_top = max(candle.open, candle.close)
    body_bottom = min(candle.open, candle.close)
    return OrderBlock(
        id=stable_id("ob", direction, candle.timestamp, body_top, body_bottom),
        top=body_top,
        bottom=body_bottom,
        timestamp=candle.timestamp,
        direction=direction,
    )

