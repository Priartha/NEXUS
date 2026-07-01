import unittest

from backend.analysis.ai_ict import _live_volume_pulse
from backend.analysis.signals import detect_trade_signals, _atr, _rsi
from backend.models.types import Candle, TradeSignal, MarketMetrics


class TrailingAndVolumeTest(unittest.TestCase):
    def test_live_volume_pulse_above_baseline(self) -> None:
        candles = [
            {"timestamp": 1000 + i * 60_000, "volume": 10.0}
            for i in range(10)
        ]
        live = {"timestamp": 1000 + 10 * 60_000, "volume": 30.0}
        pulse = _live_volume_pulse(live, candles + [live])
        self.assertGreaterEqual(pulse, 2.5)

    def test_signal_generation_requires_minimum_candles(self) -> None:
        """Signal engine requires at least 100 candles."""
        candles = [
            Candle(
                timestamp=i * 60_000,
                open=100.0 + i * 0.1,
                high=101.0 + i * 0.1,
                low=99.0 + i * 0.1,
                close=100.5 + i * 0.1,
                volume=1.0,
                is_closed=True,
            )
            for i in range(50)
        ]
        signals = detect_trade_signals(candles)
        self.assertEqual(len(signals), 0)

    def test_atr_calculation(self) -> None:
        """ATR should return reasonable value for volatile candles."""
        candles = [
            Candle(
                timestamp=i * 60_000,
                open=100.0,
                high=105.0,
                low=95.0,
                close=100.0 + (i % 2) * 5,
                volume=1.0,
                is_closed=True,
            )
            for i in range(20)
        ]
        atr = _atr(candles, 14)
        self.assertGreater(atr, 0)

    def test_rsi_calculation(self) -> None:
        """RSI should return value between 0 and 100."""
        closes = [100.0 + i for i in range(20)]
        rsi = _rsi(closes, 14)
        self.assertGreaterEqual(rsi, 0)
        self.assertLessEqual(rsi, 100)


if __name__ == "__main__":
    unittest.main()
