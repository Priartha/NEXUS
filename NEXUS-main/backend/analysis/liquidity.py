from __future__ import annotations

from backend.analysis.ids import stable_id
from backend.models.types import Candle, LiquidityLevel, Swing


def detect_equal_levels(swings: list[Swing], tolerance_pct: float = 0.001) -> list[LiquidityLevel]:
    levels: list[LiquidityLevel] = []
    highs = [swing for swing in swings if swing.kind == "high"]
    lows = [swing for swing in swings if swing.kind == "low"]

    for group, kind in ((highs, "equal_high"), (lows, "equal_low")):
        visited: set[int] = set()
        for i, base in enumerate(group):
            if i in visited:
                continue
            touches = [base]
            for j in range(i + 1, len(group)):
                other = group[j]
                if abs(base.price - other.price) / base.price <= tolerance_pct:
                    touches.append(other)
                    visited.add(j)

            if len(touches) >= 2:
                avg_price = sum(swing.price for swing in touches) / len(touches)
                first_ts = min(swing.timestamp for swing in touches)
                last_ts = max(swing.timestamp for swing in touches)
                levels.append(
                    LiquidityLevel(
                        id=stable_id("liq", kind, round(avg_price, 2), first_ts, len(touches)),
                        price=avg_price,
                        kind=kind,
                        touch_count=len(touches),
                        first_touch_timestamp=first_ts,
                        last_touch_timestamp=last_ts,
                    )
                )

    return levels


def check_liquidity_sweeps(levels: list[LiquidityLevel], latest_candle: Candle) -> list[LiquidityLevel]:
    for level in levels:
        if level.swept:
            continue
        if level.last_touch_timestamp and latest_candle.timestamp <= level.last_touch_timestamp:
            continue
        if level.kind == "equal_high" and latest_candle.high > level.price and latest_candle.close < level.price:
            level.swept = True
            level.sweep_timestamp = latest_candle.timestamp
        elif level.kind == "equal_low" and latest_candle.low < level.price and latest_candle.close > level.price:
            level.swept = True
            level.sweep_timestamp = latest_candle.timestamp
    return levels
