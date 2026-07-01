from __future__ import annotations

import logging
from collections import deque
from typing import Any

import numpy as np

from backend.models.types import Candle, DeltaAnalysis, VolumeAnalysis

logger = logging.getLogger(__name__)


class GenuineVolumeAnalyzer:
    """
    Volume and delta analysis with automatic fallback.

    PRIMARY: Pulls tick-level data from TrueOrderFlowTracker when available.
    FALLBACK: Computes from candle OHLCV data when tick stream is absent.
    This ensures the panel always shows live metrics.
    """

    def __init__(
        self,
        max_samples: int = 500,
        large_trade_multiplier: float = 3.0,
    ) -> None:
        self._max_samples = max_samples
        self._large_trade_multiplier = large_trade_multiplier

        self._volume_snapshots: deque[VolumeAnalysis] = deque(maxlen=max_samples)
        self._delta_snapshots: deque[DeltaAnalysis] = deque(maxlen=max_samples)

        # Rolling windows for derivative computation
        self._candle_deltas: deque[float] = deque(maxlen=40)
        self._candle_volumes: deque[float] = deque(maxlen=40)
        self._candle_closes: deque[float] = deque(maxlen=40)

        # Cumulative delta (candle-based fallback)
        self._cumulative_delta: float = 0.0

    def compute(self, candles: list[Candle] | None = None) -> tuple[VolumeAnalysis, DeltaAnalysis]:
        """Compute volume and delta analysis. Uses tick data when available, falls back to candles."""
        now_ms = int(candles[-1].timestamp) if candles else 0

        # Try tick-level data first
        try:
            from backend.analysis.trade_stream import true_orderflow
            current_cvd = true_orderflow.get_current_cvd()
        except Exception:
            current_cvd = None

        if current_cvd is not None and current_cvd.total_volume > 0:
            return self._compute_from_ticks(current_cvd, candles, now_ms)

        # Fallback: compute from candle data
        return self._compute_from_candles(candles, now_ms)

    def _compute_from_ticks(
        self, current_cvd: Any, candles: list[Candle] | None, now_ms: int
    ) -> tuple[VolumeAnalysis, DeltaAnalysis]:
        """Compute metrics from tick-level TrueOrderFlow data."""
        from backend.analysis.trade_stream import true_orderflow

        total_buy = current_cvd.buy_volume
        total_sell = current_cvd.sell_volume
        total_vol = current_cvd.total_volume
        buy_count = current_cvd.buy_count
        sell_count = current_cvd.sell_count

        buy_sell_ratio = total_buy / total_sell if total_sell > 0 else 1.0
        vol_delta = total_buy - total_sell
        vol_delta_pct = vol_delta / total_vol if total_vol > 0 else 0.0
        absorption = min(total_buy, total_sell) / total_vol if total_vol > 0 else 0.5
        vpin = true_orderflow.get_vpin()
        bid_ask_ratio = current_cvd.bid_ask_ratio

        avg_trade_size = total_vol / max(buy_count + sell_count, 1)
        large_trades = 0
        total_trades_count = 0
        try:
            for tick in list(true_orderflow._ticks)[-200:]:
                total_trades_count += 1
                if tick.quote_qty > avg_trade_size * self._large_trade_multiplier:
                    large_trades += 1
        except Exception:
            pass
        large_trade_ratio = large_trades / max(total_trades_count, 1)

        volume_analysis = VolumeAnalysis(
            timestamp=now_ms,
            total_buy_volume=round(total_buy, 4),
            total_sell_volume=round(total_sell, 4),
            total_volume=round(total_vol, 4),
            buy_sell_ratio=round(buy_sell_ratio, 4),
            volume_delta=round(vol_delta, 4),
            volume_delta_pct=round(vol_delta_pct, 4),
            vpin=round(vpin, 4),
            absorption_ratio=round(absorption, 4),
            bid_ask_ratio=round(bid_ask_ratio, 4),
            large_trade_ratio=round(large_trade_ratio, 4),
            avg_trade_size=round(avg_trade_size, 4),
            buy_count=buy_count,
            sell_count=sell_count,
        )

        cumulative_delta = current_cvd.cumulative_delta
        last_delta = current_cvd.delta
        agg_buy_count = current_cvd.buy_count
        agg_sell_count = current_cvd.sell_count

        self._candle_deltas.append(last_delta)
        self._candle_volumes.append(total_vol)

        delta_momentum, delta_acceleration = self._compute_momentum(list(self._candle_deltas))
        cvd_slope = getattr(current_cvd, 'delta_ratio', 0.0)
        cvd_trend = self._compute_trend(list(self._candle_deltas))
        delta_extreme = self._is_extreme(last_delta, cumulative_delta, self._candle_deltas)
        div_type, div_strength = self._detect_delta_divergence(candles)
        delta_balance = sum(list(self._candle_deltas)[-10:]) if self._candle_deltas else 0.0

        delta_analysis = DeltaAnalysis(
            timestamp=now_ms,
            cumulative_delta=round(cumulative_delta, 4),
            delta_momentum=round(delta_momentum, 4),
            delta_acceleration=round(delta_acceleration, 4),
            last_delta=round(last_delta, 4),
            delta_divergence_type=div_type,
            delta_divergence_strength=round(div_strength, 4),
            delta_extreme=delta_extreme,
            aggressive_buy_count=agg_buy_count,
            aggressive_sell_count=agg_sell_count,
            delta_balance=round(delta_balance, 4),
            cvd_slope=round(cvd_slope, 4),
            cvd_trend=cvd_trend,
        )

        self._volume_snapshots.append(volume_analysis)
        self._delta_snapshots.append(delta_analysis)
        return volume_analysis, delta_analysis

    def _compute_from_candles(self, candles: list[Candle] | None, now_ms: int) -> tuple[VolumeAnalysis, DeltaAnalysis]:
        """Fallback: compute volume/delta metrics from candle OHLCV data."""
        if not candles or len(candles) < 2:
            return VolumeAnalysis(timestamp=now_ms), DeltaAnalysis(timestamp=now_ms)

        recent = candles[-40:]

        # Compute candle-based deltas: green candle volume = buy pressure, red = sell pressure
        candle_deltas: list[float] = []
        buy_vol_total = 0.0
        sell_vol_total = 0.0
        for c in recent:
            if c.close >= c.open:
                delta = c.volume
                buy_vol_total += c.volume
            else:
                delta = -c.volume
                sell_vol_total += c.volume
            candle_deltas.append(delta)

        total_vol = buy_vol_total + sell_vol_total
        net_delta = sum(candle_deltas)
        self._cumulative_delta += candle_deltas[-1] if candle_deltas else 0
        buy_sell_ratio = buy_vol_total / sell_vol_total if sell_vol_total > 0 else 1.0
        vol_delta_pct = net_delta / total_vol if total_vol > 0 else 0.0
        absorption = min(buy_vol_total, sell_vol_total) / total_vol if total_vol > 0 else 0.5

        # VPIN approximation from volume buckets
        vpin = self._compute_vpin_approx(recent)

        # Bid/ask ratio approximated from candle direction
        bullish_candles = sum(1 for c in recent if c.close > c.open)
        bearish_candles = len(recent) - bullish_candles
        bid_ask_ratio = bullish_candles / max(bearish_candles, 1)

        avg_candle_vol = total_vol / max(len(recent), 1)
        large_candles = sum(1 for c in recent if c.volume > avg_candle_vol * self._large_trade_multiplier)
        large_trade_ratio = large_candles / max(len(recent), 1)

        volume_analysis = VolumeAnalysis(
            timestamp=now_ms,
            total_buy_volume=round(buy_vol_total, 4),
            total_sell_volume=round(sell_vol_total, 4),
            total_volume=round(total_vol, 4),
            buy_sell_ratio=round(buy_sell_ratio, 4),
            volume_delta=round(net_delta, 4),
            volume_delta_pct=round(vol_delta_pct, 4),
            vpin=round(vpin, 4),
            absorption_ratio=round(absorption, 4),
            bid_ask_ratio=round(bid_ask_ratio, 4),
            large_trade_ratio=round(large_trade_ratio, 4),
            avg_trade_size=round(avg_candle_vol, 4),
            buy_count=bullish_candles,
            sell_count=bearish_candles,
        )

        # Track for momentum
        last_delta = candle_deltas[-1] if candle_deltas else 0.0
        self._candle_deltas.append(last_delta)
        self._candle_volumes.append(total_vol)
        self._candle_closes.append(recent[-1].close)

        delta_momentum, delta_acceleration = self._compute_momentum(list(self._candle_deltas))
        cvd_trend = self._compute_trend(list(self._candle_deltas))
        delta_extreme = self._is_extreme(last_delta, self._cumulative_delta, self._candle_deltas)
        div_type, div_strength = self._detect_delta_divergence(candles)
        delta_balance = sum(list(self._candle_deltas)[-10:]) if self._candle_deltas else 0.0

        delta_analysis = DeltaAnalysis(
            timestamp=now_ms,
            cumulative_delta=round(self._cumulative_delta, 4),
            delta_momentum=round(delta_momentum, 4),
            delta_acceleration=round(delta_acceleration, 4),
            last_delta=round(last_delta, 4),
            delta_divergence_type=div_type,
            delta_divergence_strength=round(div_strength, 4),
            delta_extreme=delta_extreme,
            aggressive_buy_count=bullish_candles,
            aggressive_sell_count=bearish_candles,
            delta_balance=round(delta_balance, 4),
            cvd_slope=round(float(np.mean(candle_deltas[-5:]) if len(candle_deltas) >= 5 else 0), 4),
            cvd_trend=cvd_trend,
        )

        self._volume_snapshots.append(volume_analysis)
        self._delta_snapshots.append(delta_analysis)
        return volume_analysis, delta_analysis

    def _compute_vpin_approx(self, candles: list[Candle]) -> float:
        """Approximate VPIN from candle data using rolling volume buckets."""
        if len(candles) < 5:
            return 0.5
        imbalances: list[float] = []
        bucket_vol = 0.0
        bucket_buy = 0.0
        bucket_sell = 0.0
        target_vol = sum(c.volume for c in candles) / 5
        for c in candles:
            bucket_vol += c.volume
            if c.close >= c.open:
                bucket_buy += c.volume
            else:
                bucket_sell += c.volume
            if bucket_vol >= target_vol and bucket_vol > 0:
                imbalances.append(abs(bucket_buy - bucket_sell) / bucket_vol)
                bucket_vol = 0.0
                bucket_buy = 0.0
                bucket_sell = 0.0
        if bucket_vol > 0:
            imbalances.append(abs(bucket_buy - bucket_sell) / bucket_vol)
        return float(np.mean(imbalances)) if imbalances else 0.5

    def _compute_momentum(self, values: list[float]) -> tuple[float, float]:
        if len(values) < 5:
            return 0.0, 0.0
        recent = values[-5:]
        momentum = (recent[-1] - recent[0]) / max(len(recent), 1)
        acceleration = 0.0
        if len(values) >= 10:
            first = values[-10:-5]
            second = values[-5:]
            m1 = (first[-1] - first[0]) / max(len(first), 1) if first else 0
            m2 = (second[-1] - second[0]) / max(len(second), 1) if second else 0
            acceleration = m2 - m1
        return momentum, acceleration

    def _compute_trend(self, values: list[float]) -> str:
        if len(values) < 10:
            return "neutral"
        older = sum(values[:-5]) / max(len(values[:-5]), 1)
        newer = sum(values[-5:]) / 5
        if newer > older * 1.2:
            return "increasing"
        elif newer < older * 0.8:
            return "decreasing"
        return "neutral"

    def _is_extreme(self, last_val: float, cumulative: float, window: deque) -> bool:
        if abs(cumulative) < 1e-8 or len(window) < 3:
            return False
        avg = abs(cumulative / max(len(window), 1))
        return avg > 0 and abs(last_val) / max(avg, 1e-8) > 3.0

    def _detect_delta_divergence(self, candles: list[Candle] | None) -> tuple[str, float]:
        """Detect divergence between cumulative delta and price movement."""
        if not candles or len(candles) < 20 or len(self._candle_deltas) < 10:
            return "none", 0.0

        prices = np.array([c.close for c in candles[-20:]])
        deltas = np.array(list(self._candle_deltas)[-20:])

        if len(prices) < 10 or len(deltas) < 10:
            return "none", 0.0

        p_range = prices.max() - prices.min() if prices.max() != prices.min() else 1e-10
        d_range = deltas.max() - deltas.min() if deltas.max() != deltas.min() else 1e-10
        prices_norm = (prices - prices.min()) / p_range
        deltas_norm = (deltas - deltas.min()) / d_range

        price_slope = prices_norm[-1] - prices_norm[0]
        delta_slope = deltas_norm[-1] - deltas_norm[0]

        if price_slope > 0.15 and delta_slope < -0.15:
            strength = min(abs(price_slope - delta_slope) * 0.5, 1.0)
            return "bearish_regular", strength
        elif price_slope < -0.15 and delta_slope > 0.15:
            strength = min(abs(price_slope - delta_slope) * 0.5, 1.0)
            return "bullish_regular", strength
        elif price_slope > 0.05 and delta_slope > price_slope * 1.5:
            return "bullish_hidden", 0.5
        elif price_slope < -0.05 and delta_slope < price_slope * 1.5:
            return "bearish_hidden", 0.5

        return "none", 0.0

    def get_latest_volume(self) -> VolumeAnalysis | None:
        return self._volume_snapshots[-1] if self._volume_snapshots else None

    def get_latest_delta(self) -> DeltaAnalysis | None:
        return self._delta_snapshots[-1] if self._delta_snapshots else None

    def get_state(self) -> dict:
        return {
            "volume_snapshots": len(self._volume_snapshots),
            "delta_snapshots": len(self._delta_snapshots),
            "latest_volume": {
                "vpin": self._volume_snapshots[-1].vpin if self._volume_snapshots else None,
                "buy_sell_ratio": self._volume_snapshots[-1].buy_sell_ratio if self._volume_snapshots else None,
                "large_trade_ratio": self._volume_snapshots[-1].large_trade_ratio if self._volume_snapshots else None,
            } if self._volume_snapshots else None,
            "latest_delta": {
                "cumulative_delta": self._delta_snapshots[-1].cumulative_delta if self._delta_snapshots else None,
                "delta_momentum": self._delta_snapshots[-1].delta_momentum if self._delta_snapshots else None,
                "delta_divergence": self._delta_snapshots[-1].delta_divergence_type if self._delta_snapshots else None,
            } if self._delta_snapshots else None,
        }


genuine_volume_analyzer = GenuineVolumeAnalyzer()
