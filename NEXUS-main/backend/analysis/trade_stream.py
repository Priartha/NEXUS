"""
Tick-Level Trade Stream — True CVD from Aggressive Buy/Sell Detection.

Binance WebSocket trade stream provides individual trade ticks with:
  - price, quantity, timestamp
  - `isBuyerMaker` flag (true = aggressive sell, false = aggressive buy)

This module converts raw trades into a true Cumulative Volume Delta (CVD)
using aggressive trade classification, NOT OHLCV candle approximation.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class TradeTick:
    timestamp: int
    price: float
    quantity: float
    quote_qty: float
    is_buyer_maker: bool  # True = sell, False = buy
    is_aggressive_buy: bool
    trade_id: int


@dataclass
class TrueCVD:
    timestamp: int
    delta: float  # aggressive buy - aggressive sell (this period)
    cumulative_delta: float
    buy_volume: float
    sell_volume: float
    total_volume: float
    buy_count: int
    sell_count: int
    total_count: int
    delta_ratio: float
    absorption_ratio: float
    bid_ask_ratio: float
    vpin: float  # Volume-synchronized probability of informed trading


class TrueOrderFlowTracker:
    """
    Tracks true tick-level order flow from Binance trade stream.

    Processes individual trades (not candles) to compute true CVD:
      - Aggressive buy = trade where isBuyerMaker == False
      - Aggressive sell = trade where isBuyerMaker == True

    Also computes VPIN (Volume-synchronized Probability of Informed Trading),
    which is a microstructure metric that predicts large moves.
    """

    def __init__(
        self,
        vpin_bucket_volume: float = 500_000,
        max_ticks: int = 100_000,
    ) -> None:
        self.vpin_bucket_volume = vpin_bucket_volume
        self._lock = Lock()

        # All raw ticks
        self._ticks: deque[TradeTick] = deque(maxlen=max_ticks)

        # CVD computation
        self._cumulative_delta: float = 0.0
        self._period_buys: float = 0.0
        self._period_sells: float = 0.0
        self._period_buy_count: int = 0
        self._period_sell_count: int = 0

        # VPIN buckets
        self._vpin_buckets: deque[float] = deque(maxlen=50)
        self._current_bucket_buy_vol: float = 0.0
        self._current_bucket_sell_vol: float = 0.0
        self._current_bucket_vol: float = 0.0

        # Recent CVD snapshots
        self._cvd_history: deque[TrueCVD] = deque(maxlen=1000)

        # Periodic snapshots (every N trades or every T seconds)
        self._last_snapshot_ts: int = 0
        self._snapshot_interval_ms: int = 60_000
        self._trades_since_snapshot: int = 0
        self._snapshot_trade_interval: int = 100

    def ingest_trade(self, trade: TradeTick) -> None:
        """Process a single trade tick."""
        with self._lock:
            self._ticks.append(trade)
            self._trades_since_snapshot += 1

            delta = trade.quantity if trade.is_aggressive_buy else -trade.quantity
            self._cumulative_delta += delta

            if trade.is_aggressive_buy:
                self._period_buys += trade.quote_qty
                self._period_buy_count += 1
                self._current_bucket_buy_vol += trade.quote_qty
            else:
                self._period_sells += trade.quote_qty
                self._period_sell_count += 1
                self._current_bucket_sell_vol += trade.quote_qty

            self._current_bucket_vol += trade.quote_qty

            # Check VPIN bucket completion
            if self._current_bucket_vol >= self.vpin_bucket_volume:
                if self._current_bucket_vol > 0:
                    imbalance = abs(self._current_bucket_buy_vol - self._current_bucket_sell_vol)
                    vpin = imbalance / self._current_bucket_vol
                    self._vpin_buckets.append(vpin)
                self._current_bucket_buy_vol = 0.0
                self._current_bucket_sell_vol = 0.0
                self._current_bucket_vol = 0.0

            # Check if we should snapshot
            now_ms = trade.timestamp
            do_snapshot = (
                self._trades_since_snapshot >= self._snapshot_trade_interval
                or (now_ms - self._last_snapshot_ts) >= self._snapshot_interval_ms
            )
            if do_snapshot and (self._period_buys > 0 or self._period_sells > 0):
                self._snapshot(now_ms)

    def ingest_raw(
        self,
        timestamp: int,
        price: float,
        quantity: float,
        quote_qty: float,
        is_buyer_maker: bool,
        trade_id: int,
    ) -> None:
        """Convenience: create TradeTick from raw fields and ingest."""
        tick = TradeTick(
            timestamp=timestamp,
            price=price,
            quantity=quantity,
            quote_qty=quote_qty,
            is_buyer_maker=is_buyer_maker,
            is_aggressive_buy=not is_buyer_maker,
            trade_id=trade_id,
        )
        self.ingest_trade(tick)

    def _snapshot(self, timestamp: int) -> None:
        """Record a CVD snapshot and reset period counters."""
        total_vol = self._period_buys + self._period_sells
        total_count = self._period_buy_count + self._period_sell_count
        delta_ratio = (self._period_buys - self._period_sells) / total_vol if total_vol > 0 else 0.0
        absorption = min(self._period_buys, self._period_sells) / total_vol if total_vol > 0 else 0.5
        bid_ask = self._period_buys / self._period_sells if self._period_sells > 0 else 1.0

        # VPIN
        vpin = float(np.mean(self._vpin_buckets)) if self._vpin_buckets else 0.5

        cvd = TrueCVD(
            timestamp=timestamp,
            delta=self._period_buys - self._period_sells,
            cumulative_delta=self._cumulative_delta,
            buy_volume=self._period_buys,
            sell_volume=self._period_sells,
            total_volume=total_vol,
            buy_count=self._period_buy_count,
            sell_count=self._period_sell_count,
            total_count=total_count,
            delta_ratio=round(delta_ratio, 4),
            absorption_ratio=round(absorption, 4),
            bid_ask_ratio=round(bid_ask, 4),
            vpin=round(vpin, 4),
        )
        self._cvd_history.append(cvd)
        self._last_snapshot_ts = timestamp
        self._trades_since_snapshot = 0
        self._period_buys = 0.0
        self._period_sells = 0.0
        self._period_buy_count = 0
        self._period_sell_count = 0

    def get_current_cvd(self) -> TrueCVD | None:
        """Get the most recent CVD snapshot."""
        return self._cvd_history[-1] if self._cvd_history else None

    def get_cvd_series(self, n: int = 100) -> list[TrueCVD]:
        """Get recent CVD snapshots."""
        return list(self._cvd_history)[-n:]

    def get_vpin(self) -> float:
        """Get current VPIN (volume-synchronized probability of informed trading)."""
        return float(np.mean(self._vpin_buckets)) if self._vpin_buckets else 0.5

    def detect_delta_divergence(self, price_series: list[float]) -> dict:
        """
        Detect divergence between price and true CVD delta.

        Returns: { divergence_type, strength, description }
        """
        if len(self._cvd_history) < 20 or len(price_series) < 20:
            return {"divergence": "none", "strength": 0.0}

        cvd_vals = np.array([c.cumulative_delta for c in list(self._cvd_history)[-20:]])
        prices = np.array(price_series[-20:])

        # Normalize
        cvd_norm = (cvd_vals - cvd_vals.min()) / max(cvd_vals.ptp(), 1e-10)
        price_norm = (prices - prices.min()) / max(prices.ptp(), 1e-10)

        # Check slope divergence
        price_slope = price_norm[-1] - price_norm[0]
        cvd_slope = cvd_norm[-1] - cvd_norm[0]

        if price_slope > 0.1 and cvd_slope < -0.1:
            return {"divergence": "bearish_regular", "strength": min(abs(price_slope - cvd_slope), 1.0) * 0.8, "description": "Price up, CVD down — distribution"}
        elif price_slope < -0.1 and cvd_slope > 0.1:
            return {"divergence": "bullish_regular", "strength": min(abs(price_slope - cvd_slope), 1.0) * 0.8, "description": "Price down, CVD up — accumulation"}
        elif price_slope > 0.05 and cvd_slope > price_slope * 1.5:
            return {"divergence": "bullish_hidden", "strength": 0.5, "description": "CVD accelerating faster than price — strong buying"}
        elif price_slope < -0.05 and cvd_slope < price_slope * 1.5:
            return {"divergence": "bearish_hidden", "strength": 0.5, "description": "CVD accelerating faster than price — strong selling"}

        return {"divergence": "none", "strength": 0.0}

    def get_state(self) -> dict:
        with self._lock:
            return {
                "total_ticks": len(self._ticks),
                "cvd_snapshots": len(self._cvd_history),
                "cumulative_delta": round(self._cumulative_delta, 4),
                "vpin_buckets": len(self._vpin_buckets),
                "vpin": self.get_vpin(),
                "last_cvd": {
                    "delta": round(self._cvd_history[-1].delta, 4),
                    "buy_vol": round(self._cvd_history[-1].buy_volume, 2),
                    "sell_vol": round(self._cvd_history[-1].sell_volume, 2),
                    "bid_ask_ratio": round(self._cvd_history[-1].bid_ask_ratio, 4),
                } if self._cvd_history else None,
            }


# Singleton
true_orderflow = TrueOrderFlowTracker()
