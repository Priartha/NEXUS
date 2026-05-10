from __future__ import annotations

from backend.models.types import Candle, StructureLabel, StructureType, Swing


def detect_structure(swings: list[Swing], candles: list[Candle] | None = None) -> list[StructureLabel]:
    labels: list[StructureLabel] = []

    highs = [swing for swing in swings if swing.kind == "high"]
    lows = [swing for swing in swings if swing.kind == "low"]

    for i in range(1, len(highs)):
        previous, current = highs[i - 1], highs[i]
        kind = StructureType.HH if current.price > previous.price else StructureType.LH
        labels.append(StructureLabel(current.timestamp, current.price, kind, previous.price))

    for i in range(1, len(lows)):
        previous, current = lows[i - 1], lows[i]
        kind = StructureType.HL if current.price > previous.price else StructureType.LL
        labels.append(StructureLabel(current.timestamp, current.price, kind, previous.price))

    if candles:
        labels.extend(detect_bos_choch(swings, candles))

    return sorted(labels, key=lambda label: (label.timestamp, label.kind.value))


def detect_bos_choch(swings: list[Swing], candles: list[Candle]) -> list[StructureLabel]:
    labels: list[StructureLabel] = []
    ordered_swings = sorted(swings, key=lambda swing: swing.timestamp)
    swing_cursor = 0
    last_high: Swing | None = None
    last_low: Swing | None = None
    trend: str | None = None
    broken: set[tuple[str, int]] = set()

    for candle in sorted(candles, key=lambda item: item.timestamp):
        while swing_cursor < len(ordered_swings) and ordered_swings[swing_cursor].timestamp < candle.timestamp:
            swing = ordered_swings[swing_cursor]
            if swing.kind == "high":
                last_high = swing
            elif swing.kind == "low":
                last_low = swing
            swing_cursor += 1

        if last_high and candle.close > last_high.price and ("high", last_high.timestamp) not in broken:
            kind = StructureType.CHOCH if trend == "bearish" else StructureType.BOS
            labels.append(
                StructureLabel(
                    timestamp=candle.timestamp,
                    price=candle.close,
                    kind=kind,
                    broken_swing_price=last_high.price,
                    direction="bullish",
                )
            )
            trend = "bullish"
            broken.add(("high", last_high.timestamp))

        if last_low and candle.close < last_low.price and ("low", last_low.timestamp) not in broken:
            kind = StructureType.CHOCH if trend == "bullish" else StructureType.BOS
            labels.append(
                StructureLabel(
                    timestamp=candle.timestamp,
                    price=candle.close,
                    kind=kind,
                    broken_swing_price=last_low.price,
                    direction="bearish",
                )
            )
            trend = "bearish"
            broken.add(("low", last_low.timestamp))

    return labels

