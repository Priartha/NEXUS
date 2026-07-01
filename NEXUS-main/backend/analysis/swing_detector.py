from __future__ import annotations

from backend.models.types import Candle, Swing


def detect_swings(candles: list[Candle], n: int = 2) -> list[Swing]:
    swings: list[Swing] = []

    if len(candles) < (2 * n) + 1:
        return swings

    for i in range(n, len(candles) - n):
        candle = candles[i]

        is_swing_high = all(
            candles[i - offset].high < candle.high and candles[i + offset].high < candle.high
            for offset in range(1, n + 1)
        )
        if is_swing_high:
            swings.append(Swing(timestamp=candle.timestamp, price=candle.high, kind="high", index=i))

        is_swing_low = all(
            candles[i - offset].low > candle.low and candles[i + offset].low > candle.low
            for offset in range(1, n + 1)
        )
        if is_swing_low:
            swings.append(Swing(timestamp=candle.timestamp, price=candle.low, kind="low", index=i))

    return sorted(swings, key=lambda swing: (swing.timestamp, swing.kind))

