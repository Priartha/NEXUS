import unittest

from backend.analysis.ai_ict import _live_volume_pulse
from backend.analysis.signals import _current_trailing_stop
from backend.models.types import Candle, TradeSignal


class TrailingAndVolumeTest(unittest.TestCase):
    def test_live_volume_pulse_above_baseline(self) -> None:
        candles = [
            {"timestamp": 1000 + i * 60_000, "volume": 10.0}
            for i in range(10)
        ]
        live = {"timestamp": 1000 + 10 * 60_000, "volume": 30.0}
        pulse = _live_volume_pulse(live, candles + [live])
        self.assertGreaterEqual(pulse, 2.5)

    def test_trailing_stop_tightens_for_buy_signal(self) -> None:
        signal = TradeSignal(
            id="s1",
            timestamp=60_000,
            side="buy",
            entry=100.0,
            stop_loss=96.0,
            exit_price=112.0,
            risk_reward=3.0,
            confidence=0.7,
            reason="test",
        )
        candles = [
            Candle(timestamp=60_000, open=100.0, high=101.0, low=99.5, close=100.5, volume=1.0, is_closed=True),
            Candle(timestamp=120_000, open=100.5, high=106.0, low=100.0, close=105.0, volume=1.0, is_closed=True),
            Candle(timestamp=180_000, open=105.0, high=108.0, low=104.5, close=107.0, volume=1.0, is_closed=True),
        ]
        trailing = _current_trailing_stop(signal, candles, atr=2.0)
        self.assertGreater(trailing, signal.stop_loss)


if __name__ == "__main__":
    unittest.main()
