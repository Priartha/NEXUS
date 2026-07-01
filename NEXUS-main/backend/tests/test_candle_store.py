import unittest

from backend.engine.candle_store import CandleStore


class CandleStoreTest(unittest.TestCase):
    def test_ignores_late_tick_for_previous_bucket(self) -> None:
        store = CandleStore("BTCUSD", "1m", max_candles=10)
        store.update_tick(price=100.0, qty=1.0, timestamp=120_000)
        store.update_tick(price=101.0, qty=2.0, timestamp=180_000)

        # Late tick for prior minute should not mutate current candle.
        mutated = store.update_tick(price=99.0, qty=5.0, timestamp=121_000)

        self.assertFalse(mutated)
        self.assertIsNotNone(store.live_candle)
        self.assertEqual(store.live_candle.timestamp, 180_000)
        self.assertEqual(store.live_candle.open, 101.0)
        self.assertEqual(store.live_candle.high, 101.0)
        self.assertEqual(store.live_candle.low, 101.0)
        self.assertEqual(store.live_candle.close, 101.0)
        self.assertEqual(store.live_candle.volume, 2.0)


if __name__ == "__main__":
    unittest.main()
