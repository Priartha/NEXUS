"""Integration tests for storage, backtesting, and paper trading."""

import os
import tempfile
import unittest
from pathlib import Path

from backend.analysis.backtest import BacktestEngine
from backend.models.types import Candle


class TestBacktestEngine(unittest.TestCase):
    def setUp(self):
        self.engine = BacktestEngine(initial_balance=10_000, position_size_pct=0.02)

    def _dummy_candles(self, n: int = 100) -> list[Candle]:
        base = 80_000.0
        candles = []
        for i in range(n):
            t = 1_700_000_000_000 + i * 300_000
            drift = (i % 10 - 5) * 100
            candles.append(Candle(
                timestamp=t,
                open=base + drift,
                high=base + drift + 200,
                low=base + drift - 200,
                close=base + drift + (i % 3 - 1) * 50,
                volume=100 + (i % 20) * 10,
                is_closed=True,
            ))
        return candles

    def test_run_returns_result(self):
        candles = self._dummy_candles(200)
        result = self.engine.run(candles)
        self.assertIn("id", result)
        self.assertIn("total_trades", result)
        self.assertIn("equity_curve", result)
        self.assertIn("trades", result)
        self.assertGreater(result["candle_count"], 0)
        self.assertIsInstance(result["total_pnl"], float)

    def test_run_with_few_candles(self):
        result = self.engine.run([])
        self.assertEqual(result["total_trades"], 0)

    def test_ignores_paper_only_signals(self):
        from backend.models.types import ScalpContext, ScalpSignal

        candles = self._dummy_candles(100)

        class FakeScalp:
            _use_candle_timestamp_for_cooldown = True
            _cur_funding = 0.0
            _cur_oi = 500_000_000.0

            def __init__(self):
                self._oi_hist = []

            def compute(self, **kwargs):
                c = kwargs["candles"][-1]
                return ScalpContext(
                    timestamp=c.timestamp,
                    signals=[
                        ScalpSignal(
                            id="paper-only",
                            timestamp=c.timestamp,
                            signal_type="LONG BTCUSD",
                            entry_zone_low=c.close - 1,
                            entry_zone_high=c.close + 1,
                            sl_level=c.close - 10,
                            target_1=c.close + 10,
                            target_2=c.close + 20,
                            status="paper",
                            confidence="MEDIUM",
                            risk_reward=2.0,
                        )
                    ],
                )

        import backend.analysis.backtest as backtest_mod

        original = backtest_mod.UnifiedScalpEngine
        try:
            backtest_mod.UnifiedScalpEngine = FakeScalp
            result = self.engine.run(candles, symbol="BTCUSD", timeframe="15m")
        finally:
            backtest_mod.UnifiedScalpEngine = original

        self.assertEqual(result["total_trades"], 0)


class TestStorageLayer(unittest.TestCase):
    def setUp(self):
        self.db_dir = tempfile.mkdtemp()
        self.orig_path = Path("data") / "nexus.db"
        self.test_path = Path(self.db_dir) / "nexus.db"
        # Patch DB path — we just test the schema creates clean
        import backend.storage.schema as schema
        schema.DB_PATH = self.test_path
        schema.init_db()

    def test_schema_creates_tables(self):
        import sqlite3
        conn = sqlite3.connect(str(self.test_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [t[0] for t in tables]
        for expected in ("signals", "paper_trades", "backtest_runs", "alerts", "equity_curve"):
            self.assertIn(expected, names)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.db_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
