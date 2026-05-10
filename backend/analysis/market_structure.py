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
    swing_highs: list[Swing] = []
    swing_lows: list[Swing] = []
    trend: str | None = None
    broken: set[tuple[str, int]] = set()

    for candle in sorted(candles, key=lambda item: item.timestamp):
        while swing_cursor < len(ordered_swings) and ordered_swings[swing_cursor].timestamp < candle.timestamp:
            swing = ordered_swings[swing_cursor]
            if swing.kind == "high":
                swing_highs.append(swing)
            elif swing.kind == "low":
                swing_lows.append(swing)
            swing_cursor += 1

        if swing_highs:
            highest_unbroken = max(
                (s for s in swing_highs if ("high", s.timestamp) not in broken),
                key=lambda s: s.price,
                default=None,
            )
            if highest_unbroken and candle.close > highest_unbroken.price:
                kind = StructureType.CHOCH if trend == "bearish" else StructureType.BOS
                labels.append(
                    StructureLabel(
                        timestamp=candle.timestamp,
                        price=candle.close,
                        kind=kind,
                        broken_swing_price=highest_unbroken.price,
                        direction="bullish",
                    )
                )
                trend = "bullish"
                broken.add(("high", highest_unbroken.timestamp))

        if swing_lows:
            lowest_unbroken = min(
                (s for s in swing_lows if ("low", s.timestamp) not in broken),
                key=lambda s: s.price,
                default=None,
            )
            if lowest_unbroken and candle.close < lowest_unbroken.price:
                kind = StructureType.CHOCH if trend == "bullish" else StructureType.BOS
                labels.append(
                    StructureLabel(
                        timestamp=candle.timestamp,
                        price=candle.close,
                        kind=kind,
                        broken_swing_price=lowest_unbroken.price,
                        direction="bearish",
                    )
                )
                trend = "bearish"
                broken.add(("low", lowest_unbroken.timestamp))

    return labels

