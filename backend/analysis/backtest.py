"""
Backtest Engine for NEXUS - v3.0

NEW FEATURES:
- Walk-forward validation (train/test split)
- Statistical significance testing (t-test, Monte Carlo, DSR, PBO)
- Overfitting detection
- Regime-specific performance attribution
- Benchmark comparison (buy-and-hold, SMA crossover)
- Funding rate and swap cost tracking
"""

from __future__ import annotations

import logging
import math
import random
import time
import uuid
from collections import deque
from typing import Any

from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_structure import detect_structure
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.regime_v2 import detect_market_regime
from backend.analysis.unified_scalp import UnifiedScalpEngine
from backend.analysis.statistical_tests import compute_full_statistics, compute_sharpe_ratio
from backend.analysis.swing_detector import detect_swings
from backend.engine.candle_aggregator import timeframe_to_ms
from backend.models.types import Candle

logger = logging.getLogger("backend")


class BacktestEngine:
    """Walk-forward backtesting engine with statistical validation."""

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        position_size_pct: float = 0.02,
        max_concurrent: int = 1,
        slippage_pct: float = 0.0001,
        commission_pct: float = 0.0002,
        max_hold_bars: int = 6,
        breakeven_threshold: float = 1.0,
        trailing_stop: bool = True,
        trailing_atr_multiplier: float = 1.5,
        funding_rate_per_8h: float = 0.0001,
        signal_side_mode: str = "normal",
        avoid_reason_tokens: list[str] | None = None,
        tp_atr_multiplier: float = 0.0,  # 0 = use signal default
        sl_atr_multiplier: float = 0.0,  # 0 = use signal default
        require_regime_alignment: bool = False,
        max_candles: int = 0,  # 0 = unlimited
    ):
        self.initial_balance = float(initial_balance)
        self.position_size_pct = float(position_size_pct)
        self.max_concurrent = max_concurrent
        self.slippage_pct = float(slippage_pct)
        self.commission_pct = float(commission_pct)
        self.max_hold_bars = max_hold_bars
        self.breakeven_threshold = breakeven_threshold
        self.trailing_stop = trailing_stop
        self.trailing_atr_multiplier = trailing_atr_multiplier
        self.funding_rate_per_8h = funding_rate_per_8h
        self.signal_side_mode = signal_side_mode
        self.avoid_reason_tokens = avoid_reason_tokens or []
        self.tp_atr_multiplier = tp_atr_multiplier
        self.sl_atr_multiplier = sl_atr_multiplier
        self.require_regime_alignment = require_regime_alignment
        self.max_candles = max_candles
        self._tp_atr_multiplier = None  # Set via set_tp_multiplier()

    def set_tp_multiplier(self, mult: float | None):
        """Override TP to be `mult` Ã— SL distance instead of signal's target_2.
        e.g., mult=3 means 3:1 R:R (6 ATR TP with 2 ATR SL). None = use signal default."""
        self._tp_atr_multiplier = mult

    def run(
        self,
        candles: list[Candle],
        symbol: str = "BTC/USDT",
        timeframe: str = "5m",
        walk_forward: bool = False,
        train_pct: float = 0.7,
    ) -> dict:
        candles = sorted(candles, key=lambda c: c.timestamp)
        if self.max_candles > 0 and len(candles) > self.max_candles:
            candles = candles[-self.max_candles:]

        if walk_forward and len(candles) >= 200:
            return self._run_walk_forward(candles, symbol, timeframe, train_pct)

        return self._run_single(candles, symbol, timeframe)

    def _run_single(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
    ) -> dict:
        return self._run_single_with_balance(candles, symbol, timeframe, self.initial_balance)

    def _run_single_with_balance(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
        start_balance: float,
    ) -> dict:
        if len(candles) < 80:
            return self._insufficient_data_result(candles, symbol, timeframe, start_balance)

        try:
            results, equity, balance, peak, open_trades, returns_series, regime_map = self._execute_trades(
                candles, timeframe, start_balance=start_balance
            )
        except Exception as e:
            logger.exception("_execute_trades failed")
            raise RuntimeError(f"Backtest trade execution failed for {symbol} {timeframe}") from e

        try:
            benchmark_returns = self._compute_benchmark_returns(candles)
            sma_returns = self._compute_sma_benchmark_returns(candles)
        except Exception as e:
            logger.warning(f"Benchmark return computation failed: {e}")
            benchmark_returns = []
            sma_returns = []

        stats = self._compute_stats(results, equity, balance, candles, symbol, timeframe, start_balance=start_balance)
        try:
            stats.update(self._compute_benchmark_stats(candles, benchmark_returns, sma_returns))
        except Exception as e:
            logger.warning(f"Benchmark stats failed: {e}")
            stats["benchmark_buy_hold"] = None
            stats["benchmark_sma_crossover"] = None

        try:
            stat_result = compute_full_statistics(
                returns=benchmark_returns if benchmark_returns else [0.0],
                strategy_returns=returns_series if returns_series else None,
                returns_matrix=[returns_series, benchmark_returns, sma_returns] if (returns_series and benchmark_returns) else None,
                n_trials=3,
            )
            stats["statistical"] = {
                "deflated_sharpe": stat_result.deflated_sharpe,
                "p_value": stat_result.p_value,
                "is_significant": stat_result.is_significant,
                "monte_carlo_p_value": stat_result.monte_carlo_p_value,
                "probability_of_overfitting": stat_result.probability_of_overfitting,
                "confidence_interval_95": list(stat_result.confidence_interval_95),
                "min_track_record_length": stat_result.min_track_record_length,
            }
        except Exception as e:
            logger.warning(f"Statistical tests failed: {e}")
            stats["statistical"] = None
            stats["statistical_error"] = str(e)

        try:
            regime_perf = self._compute_regime_performance(candles, results, regime_map)
            stats["regime_performance"] = regime_perf
        except Exception as e:
            logger.warning(f"Regime performance computation failed: {e}")
            stats["regime_performance"] = {}

        stats["trades"] = results
        stats["equity_curve"] = equity
        return stats

    def _insufficient_data_result(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
        start_balance: float,
    ) -> dict:
        initial_balance = float(start_balance)
        return {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "timeframe": timeframe,
            "start_date": candles[0].timestamp if candles else 0,
            "end_date": candles[-1].timestamp if candles else 0,
            "candle_count": len(candles),
            "calculation_status": "insufficient_data",
            "initial_balance": initial_balance,
            "final_balance": initial_balance,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_consecutive_losses": 0,
            "slippage_pct": self.slippage_pct,
            "commission_pct": self.commission_pct,
            "total_funding_cost": 0.0,
            "funding_rate_per_8h": self.funding_rate_per_8h,
            "statistical": None,
            "regime_performance": {},
            "benchmark_buy_hold": None,
            "benchmark_sma_crossover": None,
            "trades": [],
            "equity_curve": [],
        }

    def _run_walk_forward(
        self,
        candles: list[Candle],
        symbol: str,
        timeframe: str,
        train_pct: float,
    ) -> dict:
        n = len(candles)
        train_size = int(n * train_pct)
        train_candles = candles[:train_size]
        test_candles = candles[train_size:]

        train_result = self._run_single(train_candles, symbol, timeframe)
        test_result = self._run_single_with_balance(
            test_candles, symbol, timeframe, start_balance=train_result["final_balance"]
        )

        combined_balance = test_result["final_balance"]
        combined_pnl = combined_balance - self.initial_balance
        combined_trades = train_result.get("trades", []) + test_result.get("trades", [])
        wins = [t for t in combined_trades if t.get("pnl", 0) > 0]
        losses = [t for t in combined_trades if t.get("pnl", 0) <= 0]
        gross_profit = sum(t.get("pnl", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.99 if wins else 0.0)
        combined_equity = train_result.get("equity_curve", []) + test_result.get("equity_curve", [])
        max_drawdown_pct = max((e.get("drawdown_pct", 0) for e in combined_equity), default=0)
        regime_performance = self._merge_regime_performance(
            train_result.get("regime_performance", {}),
            test_result.get("regime_performance", {}),
        )
        try:
            benchmark_buy_hold = self._compute_benchmark_stats(
                candles,
                self._compute_benchmark_returns(candles),
                self._compute_sma_benchmark_returns(candles),
            ).get("benchmark_buy_hold", {})
        except Exception as e:
            logger.warning(f"Walk-forward benchmark stats failed: {e}")
            benchmark_buy_hold = {}

        return {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "timeframe": timeframe,
            "walk_forward": True,
            "train_period": {
                "start_date": train_result["start_date"],
                "end_date": train_result["end_date"],
                "candle_count": len(train_candles),
                "total_trades": train_result["total_trades"],
                "win_rate": train_result["win_rate"],
                "total_pnl": train_result["total_pnl"],
                "sharpe_ratio": train_result["sharpe_ratio"],
            },
            "test_period": {
                "start_date": test_result["start_date"],
                "end_date": test_result["end_date"],
                "candle_count": len(test_candles),
                "total_trades": test_result["total_trades"],
                "win_rate": test_result["win_rate"],
                "total_pnl": test_result["total_pnl"],
                "sharpe_ratio": test_result["sharpe_ratio"],
            },
            "combined": {
                "initial_balance": self.initial_balance,
                "final_balance": round(combined_balance, 2),
                "total_pnl": round(combined_pnl, 2),
                "total_pnl_pct": round((combined_pnl / self.initial_balance) * 100, 4),
                "total_trades": train_result["total_trades"] + test_result["total_trades"],
                "winning_trades": len(wins),
                "losing_trades": len(losses),
                "win_rate": round(
                    (train_result["winning_trades"] + test_result["winning_trades"]) /
                    max(train_result["total_trades"] + test_result["total_trades"], 1), 4
                ),
                "profit_factor": round(profit_factor, 4),
                "max_drawdown_pct": round(max_drawdown_pct, 4),
                "degradation": round(
                    test_result["sharpe_ratio"] - train_result["sharpe_ratio"], 4
                ) if test_result["total_trades"] > 0 else 0,
            },
            "is_robust": test_result["total_trades"] > 5 and test_result["sharpe_ratio"] > 0,
            "benchmark_buy_hold": benchmark_buy_hold,
            "regime_performance": regime_performance,
            "trades": combined_trades,
            "equity_curve": combined_equity,
        }

    def _merge_regime_performance(self, first: dict, second: dict) -> dict:
        phases = set(first) | set(second)
        merged = {}
        for phase in phases:
            a = first.get(phase, {})
            b = second.get(phase, {})
            trade_count = a.get("trade_count", 0) + b.get("trade_count", 0)
            total_pnl = a.get("total_pnl", 0) + b.get("total_pnl", 0)
            wins = round(a.get("win_rate", 0) * a.get("trade_count", 0)) + round(b.get("win_rate", 0) * b.get("trade_count", 0))
            merged[phase] = {
                "trade_count": trade_count,
                "total_pnl": round(total_pnl, 2),
                "avg_pnl": round(total_pnl / trade_count, 2) if trade_count else 0,
                "win_rate": round(wins / trade_count, 4) if trade_count else 0,
            }
        return merged

    def _execute_trades(self, candles: list[Candle], timeframe: str = "5m", start_balance: float | None = None):
        results: list[dict] = []
        equity: list[dict] = []
        initial_balance = self.initial_balance if start_balance is None else float(start_balance)
        balance = initial_balance
        peak = balance
        open_trades: list[dict] = []
        returns_series: list[float] = []
        regime_map: dict[int, str] = {}

        # Normalize funding rate to per-bar (was incorrectly using full 8h rate per bar)
        bar_ms = timeframe_to_ms(timeframe)
        bars_per_8h = 8 * 3600 * 1000 / bar_ms
        funding_per_bar = self.funding_rate_per_8h / bars_per_8h

        swing_engine: list[Any] = []
        fvg_engine: list[Any] = []
        ob_engine: list[Any] = []
        liq_engine: list[Any] = []
        liq_evt_engine: list[Any] = []
        metrics_engine = None

        from backend.config import settings
        scalp = UnifiedScalpEngine()
        scalp._use_candle_timestamp_for_cooldown = True  # Use candle time for backtest
        lookback = 80
        min_candles = max(lookback, 50)
        last_signal_ts = 0

        # Seed OI and funding with realistic defaults for backtest
        # Use settings default funding (negative means we get paid to hold)
        scalp._cur_funding = settings.futures_default_funding  # Typical: -0.0001 (we earn funding)
        base_oi = 500_000_000.0  # $500M base OI
        for i in range(min_candles):
            ts = candles[i].timestamp
            oi_variation = base_oi * (1 + (i % 20 - 10) * 0.001)  # Small oscillation
            scalp._oi_hist.append((ts, oi_variation))
            scalp._cur_oi = base_oi

        # Use settings leverage (20x default for better profit)
        leverage = settings.futures_leverage

        for i in range(min_candles, len(candles)):
            window = candles[max(0, i + 1 - 500):i + 1]
            recent = window[-lookback:]
            current = candles[i]

            swing_engine = detect_swings(window)[-250:]
            fvg_engine = detect_fvgs(recent)
            ob_engine = detect_order_blocks(recent, swing_engine)
            liq_engine = detect_equal_levels(swing_engine)

            for c in recent:
                fvg_engine = update_fvg_fills(fvg_engine, c)
                ob_engine = update_order_block_breakers(ob_engine, c)
                liq_engine = check_liquidity_sweeps(liq_engine, c)

            metrics_engine = compute_market_metrics(window, swing_engine)
            atr = metrics_engine.atr14 if metrics_engine else 0.0
            liq_evt_engine = detect_liquidity_events(recent, liq_engine, atr)[-80:]
            structure = detect_structure(swing_engine, window)
            regime = detect_market_regime(window, metrics_engine, liq_evt_engine)
            if regime:
                regime_map[current.timestamp] = regime.phase

            # Update OI with slight trend to enable momentum detection
            prev_oi = scalp._cur_oi
            oi_change = prev_oi * (0.001 if i % 3 == 0 else -0.0005)
            scalp._cur_oi = prev_oi + oi_change
            scalp._oi_hist.append((current.timestamp, scalp._cur_oi))

            # UNIFIED SCALPING ENGINE â€” primary signal source
            scalp_ctx = scalp.compute(
                candles=window,
                metrics=metrics_engine,
                fvgs=fvg_engine,
                order_blocks=ob_engine,
                swings=swing_engine,
                regime=regime,
                liquidity_events=liq_evt_engine,
                timeframe=timeframe,
            )

            signals = scalp_ctx.signals

            # Convert ScalpSignal to backtest-compatible format
            compatible_signals = []
            for ss in signals:
                # Map confidence based on score relative to threshold
                # Scores range from ~0.20 to ~0.70 in backtest mode
                raw_score = ss.risk_reward  # Not ideal, but use signal strength
                conf_map = {"HIGH": 0.75, "MEDIUM": 0.60, "LOW": 0.45}
                entry = (ss.entry_zone_low + ss.entry_zone_high) / 2
                side = "buy" if "LONG" in ss.signal_type else "sell"
                stop_loss = ss.sl_level
                exit_price = ss.target_2
                if self.signal_side_mode == "invert":
                    side = "sell" if side == "buy" else "buy"
                    stop_distance = abs(entry - ss.sl_level)
                    target_distance = abs(ss.target_2 - entry)
                    if side == "buy":
                        stop_loss = entry - stop_distance
                        exit_price = entry + target_distance
                    else:
                        stop_loss = entry + stop_distance
                        exit_price = entry - target_distance
                compatible_signals.append(type("CompatSignal", (), {
                    "id": ss.id,
                    "timestamp": ss.timestamp,
                    "side": side,
                    "entry": entry,
                    "stop_loss": stop_loss,
                    "exit_price": exit_price,
                    "confidence": conf_map.get(ss.confidence, 0.50),
                    "reason": ss.reason,
                    "risk_reward": ss.risk_reward,
                })())
            signals = compatible_signals

            new_signals = [s for s in signals if s.timestamp > last_signal_ts]
            last_signal_ts = max((s.timestamp for s in signals), default=last_signal_ts)

            for sig in new_signals:
                if self.avoid_reason_tokens and any(token in sig.reason for token in self.avoid_reason_tokens):
                    continue
                if self.require_regime_alignment:
                    blocker = scalp._regime_direction_filter(window, sig.side, regime)
                    if blocker:
                        continue
                if len([t for t in open_trades if t["status"] == "open"]) >= self.max_concurrent:
                    continue
                if sig.confidence < 0.42:
                    continue

                risk_per_trade = balance * self.position_size_pct
                risk_per_unit = abs(sig.entry - sig.stop_loss)
                quantity = risk_per_trade / risk_per_unit if risk_per_unit > 0 else 0

                slippage = sig.entry * self.slippage_pct
                entry_with_slippage = sig.entry + slippage if sig.side == "buy" else sig.entry - slippage

                notional = entry_with_slippage * quantity
                commission = notional * self.commission_pct

                tp = sig.exit_price
                sl = sig.stop_loss
                if self.tp_atr_multiplier > 0:
                    # Override TP: entry +/- tp_atr_multiplier * (risk_per_unit / 2.0)
                    atr_frac = risk_per_unit / 2.0
                    tp = sig.entry + self.tp_atr_multiplier * atr_frac if sig.side == "buy" else sig.entry - self.tp_atr_multiplier * atr_frac
                if self.sl_atr_multiplier > 0:
                    # Override SL: entry -/+ sl_atr_multiplier * (risk_per_unit / 2.0)
                    atr_frac = risk_per_unit / 2.0
                    sl = sig.entry - self.sl_atr_multiplier * atr_frac if sig.side == "buy" else sig.entry + self.sl_atr_multiplier * atr_frac
                trade = {
                    "id": str(uuid.uuid4()),
                    "signal_id": sig.id,
                    "timestamp": sig.timestamp,
                    "side": sig.side,
                    "entry_price": round(entry_with_slippage, 2),
                    "raw_entry": sig.entry,
                    "stop_loss": sl,
                    "initial_sl": sl,
                    "take_profit": tp,
                    "quantity": quantity,
                    "status": "open",
                    "confidence": sig.confidence,
                    "reason": sig.reason,
                    "risk_reward": sig.risk_reward,
                    "slippage": round(slippage, 2),
                    "commission": round(commission, 2),
                    "bars_held": 0,
                }
                open_trades.append(trade)

            for trade in list(open_trades):
                if trade["status"] != "open":
                    continue
                side = trade["side"]
                entry = trade["entry_price"]
                sl = trade["stop_loss"]
                tp = trade["take_profit"]
                qty = trade["quantity"]
                bars_held = trade.get("bars_held", 0) + 1
                trade["bars_held"] = bars_held

                if bars_held == 1 and current.timestamp == trade["timestamp"]:
                    continue

                if self.trailing_stop:
                    risk = abs(entry - trade.get("initial_sl", sl))
                    if risk > 0:
                        if side == "buy":
                            profit_r = (current.high - entry) / risk
                            if profit_r >= self.breakeven_threshold:
                                trade["stop_loss"] = max(trade["stop_loss"], entry)
                                sl = trade["stop_loss"]
                        else:
                            profit_r = (entry - current.low) / risk
                            if profit_r >= self.breakeven_threshold:
                                trade["stop_loss"] = min(trade["stop_loss"], entry)
                                sl = trade["stop_loss"]

                funding_cost = funding_per_bar * entry * qty
                if bars_held >= self.max_hold_bars + 1:
                    exit_price = current.close
                    pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                    pnl -= trade["commission"] + funding_cost
                    pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["pnl"] = round(pnl, 2)
                    trade["pnl_pct"] = round(pnl_pct, 4)
                    trade["close_reason"] = "time_exit"
                    trade["funding_cost"] = round(funding_cost, 2)
                    balance += pnl
                    returns_series.append(pnl / balance if balance > 0 else 0)
                    results.append(dict(trade))
                    continue

                if side == "buy":
                    hit_stop = current.low <= sl
                    hit_target = current.high >= tp
                else:
                    hit_stop = current.high >= sl
                    hit_target = current.low <= tp

                if hit_stop:
                    exit_price = sl
                    pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                    pnl -= trade["commission"] + funding_cost
                    pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["pnl"] = round(pnl, 2)
                    trade["pnl_pct"] = round(pnl_pct, 4)
                    trade["close_reason"] = "stop_loss"
                    trade["funding_cost"] = round(funding_cost, 2)
                    balance += pnl
                    returns_series.append(pnl / balance if balance > 0 else 0)
                    results.append(dict(trade))
                elif hit_target:
                    exit_price = tp
                    pnl = (exit_price - entry) * qty if side == "buy" else (entry - exit_price) * qty
                    pnl -= trade["commission"] + funding_cost
                    pnl_pct = pnl / (entry * qty) * 100 if entry * qty > 0 else 0
                    trade["status"] = "closed"
                    trade["exit_price"] = exit_price
                    trade["exit_timestamp"] = current.timestamp
                    trade["pnl"] = round(pnl, 2)
                    trade["pnl_pct"] = round(pnl_pct, 4)
                    trade["close_reason"] = "target_hit"
                    trade["funding_cost"] = round(funding_cost, 2)
                    balance += pnl
                    returns_series.append(pnl / balance if balance > 0 else 0)
                    results.append(dict(trade))

            if balance > peak:
                peak = balance
                peak_ts = current.timestamp
            dd = peak - balance
            dd_pct = dd / peak * 100 if peak > 0 else 0

            if i % 5 == 0 or i == len(candles) - 1:
                equity.append({
                    "timestamp": current.timestamp,
                    "account_balance": round(balance, 2),
                    "drawdown": round(dd, 2),
                    "drawdown_pct": round(dd_pct, 4),
                })

        return results, equity, balance, peak, open_trades, returns_series, regime_map

    def _compute_stats(self, results, equity, balance, candles, symbol="", timeframe="", start_balance: float | None = None):
        initial_balance = self.initial_balance if start_balance is None else float(start_balance)
        total_pnl = balance - initial_balance
        total_pnl_pct = (total_pnl / initial_balance) * 100 if initial_balance > 0 else 0.0
        closed = [r for r in results if r.get("exit_price") is not None]
        wins = [r for r in closed if r.get("pnl", 0) > 0]
        losses = [r for r in closed if r.get("pnl", 0) <= 0]

        max_dd = max((e["drawdown_pct"] for e in equity), default=0)
        max_dd_val = max((e["drawdown"] for e in equity), default=0)
        avg_win = sum(r["pnl"] for r in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(r["pnl"] for r in losses) / len(losses)) if losses else 0
        profit_factor = 0.0
        if wins and losses:
            gross_profit = sum(r["pnl"] for r in wins)
            gross_loss = abs(sum(r["pnl"] for r in losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        elif wins:
            profit_factor = float("inf")

        returns = [e["account_balance"] / initial_balance - 1 for e in equity]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_returns = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0
        n_periods = len(returns)
        periods_per_year = 365 * 24 * 60 * 60 / ((candles[-1].timestamp - candles[0].timestamp) / 1000) if len(candles) >= 2 and (candles[-1].timestamp - candles[0].timestamp) > 0 else 365
        sharpe = (avg_return / std_returns * math.sqrt(periods_per_year)) if std_returns > 0 else 0

        max_consecutive_losses = 0
        current_consecutive = 0
        for r in closed:
            if r.get("pnl", 0) <= 0:
                current_consecutive += 1
                max_consecutive_losses = max(max_consecutive_losses, current_consecutive)
            else:
                current_consecutive = 0

        total_funding = sum(r.get("funding_cost", 0) for r in closed)

        return {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "timeframe": timeframe,
            "start_date": candles[0].timestamp if candles else 0,
            "end_date": candles[-1].timestamp if candles else 0,
            "candle_count": len(candles),
            "initial_balance": initial_balance,
            "final_balance": round(balance, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 4),
            "total_trades": len(closed),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / len(closed), 4) if closed else 0,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.99,
            "max_drawdown": round(max_dd_val, 2),
            "max_drawdown_pct": round(max_dd, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_consecutive_losses": max_consecutive_losses,
            "slippage_pct": self.slippage_pct,
            "commission_pct": self.commission_pct,
            "total_funding_cost": round(total_funding, 2),
            "funding_rate_per_8h": self.funding_rate_per_8h,
        }

    def _compute_benchmark_returns(self, candles: list[Candle]) -> list[float]:
        """Buy-and-hold benchmark returns."""
        if len(candles) < 10:
            return []
        returns = []
        for i in range(1, len(candles)):
            prev = candles[i-1].close
            if prev > 0:
                ret = (candles[i].close - prev) / prev
                returns.append(ret)
        return returns

    def _compute_sma_benchmark_returns(self, candles: list[Candle]) -> list[float]:
        """SMA crossover (20/50) benchmark returns."""
        if len(candles) < 60:
            return []
        closes = [c.close for c in candles]
        sma20 = []
        sma50 = []
        for i in range(len(closes)):
            if i >= 19:
                sma20.append(sum(closes[i-19:i+1]) / 20)
            if i >= 49:
                sma50.append(sum(closes[i-49:i+1]) / 50)

        returns = []
        in_position = False
        for i in range(50, len(closes)):
            s20 = sma20[i - 19] if (i - 19) < len(sma20) else None
            s50 = sma50[i - 49] if (i - 49) < len(sma50) else None
            if s20 and s50:
                if s20 > s50 and not in_position:
                    in_position = True
                elif s20 < s50 and in_position:
                    in_position = False
                if in_position:
                    ret = (closes[i] - closes[i-1]) / closes[i-1]
                    returns.append(ret)
                else:
                    returns.append(0.0)
        return returns

    def _compute_benchmark_stats(self, candles, bh_returns, sma_returns):
        bh_sharpe = compute_sharpe_ratio(bh_returns) if bh_returns else 0.0
        sma_sharpe = compute_sharpe_ratio(sma_returns) if sma_returns else 0.0

        bh_total = (candles[-1].close - candles[0].close) / candles[0].close * 100 if len(candles) > 1 else 0.0

        return {
            "benchmark_buy_hold": {
                "total_return_pct": round(bh_total, 4),
                "sharpe_ratio": round(bh_sharpe, 4),
            },
            "benchmark_sma_crossover": {
                "sharpe_ratio": round(sma_sharpe, 4),
            },
        }

    def _compute_regime_performance(self, candles, trades, regime_map: dict[int, str] | None = None):
        """Regime-specific performance attribution."""
        if not candles or not trades:
            return {}

        if regime_map is None:
            regime_map = {}
            window_size = 80
            for i in range(window_size, len(candles)):
                window = candles[i-window_size:i+1]
                metrics = compute_market_metrics(window, [])
                swings = detect_swings(window)[-50:]
                liq_events = detect_liquidity_events(window[-20:], [], metrics.atr14 if metrics else 0)[-20:]
                regime = detect_market_regime(window, metrics, liq_events)
                if regime:
                    regime_map[candles[i].timestamp] = regime.phase
        if not regime_map:
            return {}

        regime_pnl: dict[str, list[float]] = {}
        for trade in trades:
            ts = trade.get("timestamp", 0)
            closest = min(regime_map, key=lambda k: abs(k - ts))
            regime_pnl.setdefault(regime_map[closest], []).append(trade.get("pnl", 0))

        result = {}
        for phase, pnls in regime_pnl.items():
            result[phase] = {
                "trade_count": len(pnls),
                "total_pnl": round(sum(pnls), 2),
                "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
                "win_rate": round(len([p for p in pnls if p > 0]) / len(pnls), 4) if pnls else 0,
            }
        return result
