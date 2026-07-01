from __future__ import annotations

from collections import deque
from typing import Iterable

from backend.engine.candle_aggregator import floor_timestamp
from backend.models.types import Candle


class CandleStore:
    def __init__(self, symbol: str, timeframe: str, max_candles: int = 500):
        self.symbol = symbol
        self.timeframe = timeframe
        self.candles: deque[Candle] = deque(maxlen=max_candles)
        self.live_candle: Candle | None = None

    def seed(self, historical: Iterable[Candle], now_ms: int | None = None) -> None:
        ordered = sorted(historical, key=lambda candle: candle.timestamp)
        self.candles.clear()
        self.live_candle = None
        current_open = floor_timestamp(now_ms, self.timeframe) if now_ms is not None else None

        for candle in ordered:
            if current_open is not None and candle.timestamp >= current_open:
                candle.is_closed = False
                self.live_candle = candle
            else:
                candle.is_closed = True
                self.candles.append(candle)

        if now_ms is None and ordered:
            self.live_candle = self.candles.pop()
            self.live_candle.is_closed = False

    def update_tick(self, price: float, qty: float, timestamp: int) -> bool:
        candle_open_ts = floor_timestamp(timestamp, self.timeframe)

        if self.live_candle is None:
            self.live_candle = Candle(
                timestamp=candle_open_ts,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=qty,
            )
            return False

        if candle_open_ts > self.live_candle.timestamp:
            self.live_candle.is_closed = True
            self.candles.append(self.live_candle)
            self.live_candle = Candle(
                timestamp=candle_open_ts,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=qty,
            )
            return True
        if candle_open_ts < self.live_candle.timestamp:
            return False

        candle = self.live_candle
        candle.high = max(candle.high, price)
        candle.low = min(candle.low, price)
        candle.close = price
        candle.volume += qty
        return False

    def get_closed_candles(self) -> list[Candle]:
        return list(self.candles)

    def get_chart_candles(self) -> list[Candle]:
        candles = list(self.candles)
        if self.live_candle is not None:
            candles.append(self.live_candle)
        return candles

    def latest_closed(self) -> Candle | None:
        if not self.candles:
            return None
        return self.candles[-1]

