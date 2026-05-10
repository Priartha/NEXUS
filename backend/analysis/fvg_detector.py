from __future__ import annotations

from backend.analysis.ids import stable_id
from backend.models.types import Candle, FVG


def detect_fvgs(candles: list[Candle], tolerance: float = 0.0) -> list[FVG]:
    fvgs: list[FVG] = []

    for i in range(1, len(candles) - 1):
        c0, c1, c2 = candles[i - 1], candles[i], candles[i + 1]

        bullish_gap = c2.low - c0.high
        if bullish_gap > tolerance:
            fvgs.append(
                FVG(
                    id=stable_id("fvg", "bullish", c1.timestamp, c0.high, c2.low),
                    top=c2.low,
                    bottom=c0.high,
                    timestamp=c1.timestamp,
                    direction="bullish",
                )
            )

        bearish_gap = c0.low - c2.high
        if bearish_gap > tolerance:
            fvgs.append(
                FVG(
                    id=stable_id("fvg", "bearish", c1.timestamp, c2.high, c0.low),
                    top=c0.low,
                    bottom=c2.high,
                    timestamp=c1.timestamp,
                    direction="bearish",
                )
            )

    return fvgs


def update_fvg_fills(fvgs: list[FVG], latest_candle: Candle) -> list[FVG]:
    for fvg in fvgs:
        if fvg.is_filled or latest_candle.timestamp <= fvg.timestamp:
            continue
        if fvg.direction == "bullish" and latest_candle.close < fvg.bottom:
            fvg.is_filled = True
            fvg.fill_timestamp = latest_candle.timestamp
        elif fvg.direction == "bearish" and latest_candle.close > fvg.top:
            fvg.is_filled = True
            fvg.fill_timestamp = latest_candle.timestamp
    return fvgs

