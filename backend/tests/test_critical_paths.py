from __future__ import annotations

from types import MethodType

from backend.analysis.backtest import BacktestEngine
from backend.analysis.regime_v2 import detect_market_regime
from backend.analysis.unified_scalp import UnifiedScalpEngine
from backend.ingestion.delta_ws import parse_quote_message
from backend.models.types import Candle, LiquidityEvent, MarketMetrics


def _candles(count: int, base: float = 100.0) -> list[Candle]:
    out: list[Candle] = []
    for i in range(count):
        price = base + i * 0.05
        out.append(
            Candle(
                timestamp=1_700_000_000_000 + i * 300_000,
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.2,
                volume=100 + i,
                is_closed=True,
            )
        )
    return out


def _metrics(ts: int) -> MarketMetrics:
    return MarketMetrics(
        timestamp=ts,
        atr14=0.1,
        ema20=100,
        ema50=100,
        rsi14=50,
        vwap=100,
        vwap_distance_pct=0,
        volume_zscore=0,
        realized_volatility=0,
        parkinson_volatility=0,
        garman_klass_volatility=0,
        displacement_ratio=0,
        premium_discount=0,
        equilibrium=100,
        range_high=101,
        range_low=99,
        trend_score=0,
        volatility_score=0,
        institutional_bias="neutral",
        bias_score=0,
        expected_move=0,
        expected_move_pct=0,
    )


def test_funding_oi_ingested():
    engine = UnifiedScalpEngine()
    engine.ingest_funding(0.0001, ts=1000)
    assert engine._cur_funding == 0.0001
    assert engine._fund_hist[-1] == (1000, 0.0001)

    engine.ingest_oi(500_000_000, ts=1000)
    assert engine._cur_oi == 500_000_000
    assert engine._oi_hist[-1] == (1000, 500_000_000)


def test_quote_parser_rejects_missing_symbol():
    assert parse_quote_message({"type": "ticker", "close": "100"}, "BTCUSD") is None


def test_candle_close_check_uses_latest():
    engine = UnifiedScalpEngine()
    candles = _candles(25)
    candles[-2] = Candle(candles[-2].timestamp, 102, 103, 99, 99.2, 200, True)
    candles[-1] = Candle(candles[-1].timestamp, 100, 104, 99, 103.5, 200, True)
    engine._cur_funding = 0.0001
    engine._oi_hist.append((candles[-2].timestamp, 1000))
    engine._oi_hist.append((candles[-1].timestamp, 1100))
    engine._cur_oi = 1100

    engine._filters = MethodType(lambda self, *args, **kwargs: [], engine)
    engine._signal_quality_blockers = MethodType(lambda self, *args, **kwargs: [], engine)
    engine._confluence_long = MethodType(lambda self, *args, **kwargs: (0.65, ["a", "b", "c"]), engine)
    engine._confluence_short = MethodType(lambda self, *args, **kwargs: (0.10, ["x"]), engine)

    ctx = engine.compute(candles)
    assert ctx.signals
    assert "Weak bullish candle close" not in ctx.trade_blocked_reasons


def test_signal_quality_edge_is_non_negative_with_mixed_score_scales():
    engine = UnifiedScalpEngine()
    blockers = engine._signal_quality_blockers(
        candles=_candles(80),
        side="long",
        winning_score=0.62,
        losing_score=0.90,
        adaptive_threshold=0.60,
        adaptive_edge=0.09,
        winning_reasons=["agent", "ensemble", "momentum"],
    )

    assert not any("Directional edge -" in blocker for blocker in blockers)
    assert not any(blocker.startswith("Directional edge") for blocker in blockers)


def test_regime_accumulation_distribution_mutually_exclusive():
    candles = [
        Candle(1_700_000_000_000 + i * 300_000, 100, 101, 99, 100, 100, True)
        for i in range(48)
    ]
    events = [
        LiquidityEvent("sell", candles[-2].timestamp, "sell_side", 99, 98.8, 100, 0.2, 0.5, True, 0.8, "sell sweep"),
        LiquidityEvent("buy", candles[-1].timestamp, "buy_side", 101, 101.2, 100, 0.2, 0.5, True, 0.8, "buy sweep"),
    ]

    regime = detect_market_regime(candles, _metrics(candles[-1].timestamp), events)

    assert regime is not None
    assert regime.phase == "accumulation"
    assert "Buy-side sweep rejected below mid" not in regime.reason


def test_walk_forward_compounds_balance():
    engine = BacktestEngine(initial_balance=10_000)
    candles = _candles(200)
    seen_start_balances: list[float] = []

    def fake_single(self, candles, symbol, timeframe):
        return {
            "start_date": candles[0].timestamp,
            "end_date": candles[-1].timestamp,
            "total_trades": 1,
            "winning_trades": 1,
            "win_rate": 1.0,
            "total_pnl": 1000,
            "sharpe_ratio": 1.0,
            "final_balance": 11_000,
            "trades": [],
            "equity_curve": [],
        }

    def fake_single_with_balance(self, candles, symbol, timeframe, start_balance):
        seen_start_balances.append(start_balance)
        return {
            "start_date": candles[0].timestamp,
            "end_date": candles[-1].timestamp,
            "total_trades": 1,
            "winning_trades": 1,
            "win_rate": 1.0,
            "total_pnl": 1000,
            "sharpe_ratio": 1.0,
            "final_balance": start_balance + 1000,
            "trades": [],
            "equity_curve": [],
        }

    engine._run_single = MethodType(fake_single, engine)
    engine._run_single_with_balance = MethodType(fake_single_with_balance, engine)

    result = engine._run_walk_forward(candles, "BTCUSDT", "5m", 0.7)

    assert seen_start_balances == [11_000]
    assert result["combined"]["final_balance"] == 12_000
