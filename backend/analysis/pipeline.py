from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Callable

from backend.analysis.alerts import check_signal_alert, check_regime_alert
from backend.analysis.btc_patterns import detect_btc_patterns
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import build_price_projection, compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_psychology import detect_market_psychology, PsychologySnapshot
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.orderbook import OrderbookAnalyzer
from backend.analysis.paper_trading import PaperTradingEngine
from backend.analysis.price_action_readability import assess_price_action_readability, ReadabilitySnapshot
from backend.analysis.regime_v2 import detect_market_regime
from backend.analysis.unified_scalp import UnifiedScalpEngine
from backend.analysis.scalp_risk import ScalpRiskManager
from backend.config import settings
from backend.storage import repository as repo
from backend.analysis.signals import detect_trade_signals
from backend.analysis.swing_detector import detect_swings
from backend.engine.candle_store import CandleStore
from backend.models.types import (
    BtcPatternContext,
    Candle,
    FVG,
    FuturesContext,
    LiquidityEvent,
    LiquidityLevel,
    MarketMetrics,
    MarketQuote,
    MarketRegime,
    OrderBlock,
    OrderbookAccumulation,
    OrderbookDepthLevel,
    OrderbookImbalance,
    PriceProjection,
    SpreadDynamics,
    Swing,
    TradeSignal,
    to_wire,
)


class AnalysisPipeline:
    def __init__(self, swing_window: int = 2, lookback: int = 80,
                 paper_trading: PaperTradingEngine | None = None,
                 on_alert: Callable[[dict], None] | None = None) -> None:
        self.swing_window = swing_window
        self.lookback = lookback
        self.swings: list[Swing] = []
        self.metrics: MarketMetrics | None = None
        self.projection: PriceProjection | None = None
        self.regime: MarketRegime | None = None
        
        # Orderbook analysis
        self.orderbook_analyzer = OrderbookAnalyzer(history_size=500)
        self.ob_imbalances: list[OrderbookImbalance] = []
        self.ob_spread_dynamics: list[SpreadDynamics] = []
        self.ob_depth_levels: list[OrderbookDepthLevel] = []
        self.ob_accumulations: list[OrderbookAccumulation] = []
        self.quote_history: deque[MarketQuote] = deque(maxlen=1000)
        
        # ICT pattern state
        self.fvgs: list[FVG] = []
        self.order_blocks: list[OrderBlock] = []
        self.liquidity: list[LiquidityLevel] = []
        self.liquidity_events: list[LiquidityEvent] = []
        
        # BTC movement & investor behavior patterns
        self.btc_patterns: BtcPatternContext | None = None
        self._btc_patterns_ts = 0

        # Market psychology & price action readability
        self.psychology: PsychologySnapshot | None = None
        self.readability: ReadabilitySnapshot | None = None

        # Paper trading & alerts
        self._paper_trading = paper_trading
        self._on_alert = on_alert or (lambda _: None)
        self._last_regime_phase: str | None = None

        self._last_candle_count = 0

        # Thread safety for async execution
        self._lock = asyncio.Lock()

        # Unified scalping engine — PRIMARY signal source
        self.scalp_engine = UnifiedScalpEngine()
        self.scalp_risk = ScalpRiskManager()
        self.scalp_context = None
        self.futures_context: FuturesContext | dict | None = None

    def add_quote(self, quote: MarketQuote) -> None:
        """Add a market quote for orderbook analysis."""
        self.quote_history.append(quote)
        self.orderbook_analyzer.add_quote(quote)
        self.scalp_engine.ingest_quote(quote)

    def set_futures_context(self, futures_context: FuturesContext | dict | None) -> None:
        self.futures_context = futures_context

    def refresh_scalp_context(self, store: CandleStore) -> dict:
        closed_candles = store.get_closed_candles()
        if closed_candles and len(closed_candles) >= 20:
            self.scalp_context = self.scalp_engine.compute(
                candles=closed_candles,
                metrics=self.metrics,
                fvgs=self.fvgs,
                order_blocks=self.order_blocks,
                swings=self.swings,
                regime=self.regime,
                liquidity_events=self.liquidity_events,
                futures_context=self.futures_context,
            )
        return {
            "scalp": to_wire(self.scalp_context) if self.scalp_context else None,
            "scalp_risk": self.scalp_risk.get_risk_summary(),
        }

    def run(self, store: CandleStore, force_full: bool = False) -> dict:
        candles = store.get_closed_candles()
        latest = store.latest_closed()
        if latest is None:
            return self.snapshot(store, update_type="close")

        if force_full or len(candles) - self._last_candle_count > 10 or not self.swings:
            self._full_recalculate(candles)
        else:
            self._incremental_update(candles, latest)

        self._last_candle_count = len(candles)
        return self._serialize(store, update_type="close", candle=latest, include_candles=False)

    def snapshot(self, store: CandleStore, update_type: str = "snapshot") -> dict:
        candles = store.get_closed_candles()
        if candles and len(candles) != self._last_candle_count:
            self._full_recalculate(candles)
            self._last_candle_count = len(candles)
        current = store.live_candle or store.latest_closed()
        return self._serialize(store, update_type=update_type, candle=current, include_candles=True)

    async def run_async(self, store: CandleStore, force_full: bool = False) -> dict:
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.run, store, force_full)

    async def snapshot_async(self, store: CandleStore, update_type: str = "snapshot") -> dict:
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self.snapshot, store, update_type)

    def _full_recalculate(self, candles: list[Candle]) -> None:
        if not candles:
            return

        window = candles[-self.lookback :]
        self.swings = detect_swings(candles, n=self.swing_window)[-250:]
        self.metrics = compute_market_metrics(candles, self.swings)

        # ICT pattern detection
        self.fvgs = detect_fvgs(window)
        self.order_blocks = detect_order_blocks(window, self.swings)
        self.liquidity = detect_equal_levels(self.swings)

        # Update FVG fills and OB breakers
        for c in window:
            self.fvgs = update_fvg_fills(self.fvgs, c)
            self.order_blocks = update_order_block_breakers(self.order_blocks, c)
            self.liquidity = check_liquidity_sweeps(self.liquidity, c)

        atr = self.metrics.atr14 if self.metrics else 0.0
        self.liquidity_events = detect_liquidity_events(window, self.liquidity, atr)[-80:]

        self.regime = detect_market_regime(candles, self.metrics, self.liquidity_events)
        self.projection = build_price_projection(candles, self.metrics, self.liquidity_events)

        # Market psychology detection
        self.psychology = detect_market_psychology(
            candles=candles,
            liquidity_events=self.liquidity_events,
            regime=self.regime,
        )

        # Price action readability assessment
        self.readability = assess_price_action_readability(
            candles=candles,
            swings=self.swings,
            liquidity=self.liquidity,
            regime=self.regime,
        )

        # BTC movement & investor behavior pattern analysis
        self.btc_patterns = detect_btc_patterns(
            candles=window,
            swings=self.swings,
            fvgs=self.fvgs,
            order_blocks=self.order_blocks,
            liquidity=self.liquidity,
            liquidity_events=self.liquidity_events,
            metrics=self.metrics,
            regime=self.regime,
        )
        self._btc_patterns_ts = candles[-1].timestamp

        # Orderbook analysis - always run
        self.ob_imbalances = self.orderbook_analyzer.detect_imbalances()
        self.ob_spread_dynamics = self.orderbook_analyzer.detect_spread_dynamics()
        self.ob_depth_levels = self.orderbook_analyzer.detect_depth_saturation()
        self.ob_accumulations = self.orderbook_analyzer.detect_accumulation_distribution(candles)

    def _incremental_update(self, candles: list[Candle], latest: Candle) -> None:
        recent = candles[-self.lookback :]
        recent_swings = detect_swings(recent, n=self.swing_window)
        existing_swings = {(swing.timestamp, swing.kind) for swing in self.swings}
        new_swings = [
            swing for swing in recent_swings if (swing.timestamp, swing.kind) not in existing_swings
        ]
        if new_swings:
            self.swings = sorted([*self.swings, *new_swings], key=lambda swing: swing.timestamp)[-250:]

        self.metrics = compute_market_metrics(candles, self.swings)

        # Incremental ICT pattern updates
        new_fvgs = detect_fvgs(recent)
        for c in recent:
            new_fvgs = update_fvg_fills(new_fvgs, c)
        self.fvgs = self._merge_fvgs(new_fvgs)

        new_obs = detect_order_blocks(recent, self.swings)
        for c in recent:
            new_obs = update_order_block_breakers(new_obs, c)
        self.order_blocks = self._merge_obs(new_obs)

        self.liquidity = detect_equal_levels(self.swings)
        self.liquidity = check_liquidity_sweeps(self.liquidity, latest)

        atr = self.metrics.atr14 if self.metrics else 0.0
        new_events = detect_liquidity_events(recent, self.liquidity, atr)
        self.liquidity_events = self._merge_liquidity_events(new_events)

        self.regime = detect_market_regime(candles, self.metrics, self.liquidity_events)
        self.projection = build_price_projection(candles, self.metrics, self.liquidity_events)

        # Incremental market psychology & readability
        self.psychology = detect_market_psychology(
            candles=candles,
            liquidity_events=self.liquidity_events,
            regime=self.regime,
        )
        self.readability = assess_price_action_readability(
            candles=candles,
            swings=self.swings,
            liquidity=self.liquidity,
            regime=self.regime,
        )

        # Incremental BTC pattern analysis
        self.btc_patterns = detect_btc_patterns(
            candles=recent,
            swings=self.swings,
            fvgs=self.fvgs,
            order_blocks=self.order_blocks,
            liquidity=self.liquidity,
            liquidity_events=self.liquidity_events,
            metrics=self.metrics,
            regime=self.regime,
        )
        self._btc_patterns_ts = latest.timestamp

        # Incremental orderbook analysis - always run
        self.ob_imbalances = self.orderbook_analyzer.detect_imbalances()
        self.ob_spread_dynamics = self.orderbook_analyzer.detect_spread_dynamics()
        self.ob_depth_levels = self.orderbook_analyzer.detect_depth_saturation()
        if self.quote_history:
            latest_quote = list(self.quote_history)[-1]
            self.ob_imbalances = self.orderbook_analyzer.update_imbalances(self.ob_imbalances, latest_quote)
        
        # Update accumulation status if we have quotes
        if self.quote_history:
            latest_quote = list(self.quote_history)[-1] if self.quote_history else None
            self.ob_accumulations = self.orderbook_analyzer.update_accumulation_status(
                self.ob_accumulations, latest, latest_quote
            )
        
        # Detect new accumulations
        new_accums = self.orderbook_analyzer.detect_accumulation_distribution(candles[-5:])
        self._merge_ob_accumulations(new_accums)

    def _merge_ob_accumulations(self, new_accums: list[OrderbookAccumulation]) -> None:
        current = {accum.id: accum for accum in self.ob_accumulations}
        for accum in new_accums:
            current.setdefault(accum.id, accum)
        self.ob_accumulations = sorted(current.values(), key=lambda item: item.timestamp)[-30:]

    def _merge_fvgs(self, new_fvgs: list[FVG]) -> list[FVG]:
        existing_ids = {f.id for f in self.fvgs}
        merged = list(self.fvgs)
        for fvg in new_fvgs:
            if fvg.id not in existing_ids:
                merged.append(fvg)
        return [f for f in merged if not f.is_filled][-50:]

    def _merge_obs(self, new_obs: list[OrderBlock]) -> list[OrderBlock]:
        existing_ids = {ob.id for ob in self.order_blocks}
        merged = list(self.order_blocks)
        for ob in new_obs:
            if ob.id not in existing_ids:
                merged.append(ob)
        return [ob for ob in merged if not ob.is_breaker][-30:]

    def _merge_liquidity_events(self, new_events: list[LiquidityEvent]) -> list[LiquidityEvent]:
        existing_ids = {e.id for e in self.liquidity_events}
        merged = list(self.liquidity_events)
        for event in new_events:
            if event.id not in existing_ids:
                merged.append(event)
        return sorted(merged, key=lambda e: e.timestamp)[-80:]

    def _serialize(
        self,
        store: CandleStore,
        update_type: str,
        candle: Candle | None,
        include_candles: bool,
    ) -> dict:
        closed_candles = store.get_closed_candles()
        if closed_candles and (self.metrics is None or self.metrics.timestamp != closed_candles[-1].timestamp):
            self.metrics = compute_market_metrics(closed_candles, self.swings)
            self.regime = detect_market_regime(closed_candles, self.metrics, self.liquidity_events)
            self.projection = build_price_projection(closed_candles, self.metrics, self.liquidity_events)
            if self._btc_patterns_ts != closed_candles[-1].timestamp:
                self.btc_patterns = detect_btc_patterns(
                    candles=closed_candles[-self.lookback:],
                    swings=self.swings,
                    fvgs=self.fvgs,
                    order_blocks=self.order_blocks,
                    liquidity=self.liquidity,
                    liquidity_events=self.liquidity_events,
                    metrics=self.metrics,
                    regime=self.regime,
                )
                self._btc_patterns_ts = closed_candles[-1].timestamp
        # Refresh accumulations status with latest candle data
        if self.quote_history:
            latest_candle = closed_candles[-1] if closed_candles else None
            latest_quote = list(self.quote_history)[-1] if self.quote_history else None
            if latest_candle and latest_quote:
                self.ob_accumulations = self.orderbook_analyzer.update_accumulation_status(
                    self.ob_accumulations, latest_candle, latest_quote
                )

        from backend.analysis.mtf_confluence import compute_mtf_confluence
        mtf = compute_mtf_confluence(store.timeframe, {store.timeframe: store}, {store.timeframe: self})

        ob_imb_data = to_wire(self.ob_imbalances[-15:])
        ob_acc_data = to_wire([a for a in self.ob_accumulations if a.status == "active"][-10:])

        # ── UNIFIED SCALPING ENGINE — PRIMARY signal source ──
        # Fuses ALL data: order flow + VWAP + funding + OI + liquidation
        # + volume profile + options + ICT patterns + regime + RSI + killzone
        if closed_candles and len(closed_candles) >= 20:
            self.scalp_context = self.scalp_engine.compute(
                candles=closed_candles,
                metrics=self.metrics,
                fvgs=self.fvgs,
                order_blocks=self.order_blocks,
                swings=self.swings,
                regime=self.regime,
                liquidity_events=self.liquidity_events,
                futures_context=self.futures_context,
            )

        # Convert scalping signals to TradeSignal for system compatibility
        scalp_signals_as_trade: list[TradeSignal] = []
        if self.scalp_context and self.scalp_context.signals:
            for ss in self.scalp_context.signals:
                conf_map = {"HIGH": 0.80, "MEDIUM": 0.65, "LOW": 0.40}
                side = "buy" if "LONG" in ss.signal_type else "sell"
                t_sig = TradeSignal(
                    id=ss.id,
                    timestamp=ss.timestamp,
                    side=side,
                    entry=round((ss.entry_zone_low + ss.entry_zone_high) / 2, 2),
                    stop_loss=ss.sl_level,
                    exit_price=ss.target_1,
                    risk_reward=ss.risk_reward,
                    confidence=conf_map.get(ss.confidence, 0.65),
                    reason=ss.reason,
                    status=ss.status,
                    institutional_score=round(ss.risk_reward / 5.0, 3),
                    liquidity_score=0.5,
                    bias_score=0.5,
                    expected_move=abs(ss.target_2 - ss.entry_zone_low),
                    win_probability=round(min(ss.risk_reward / (ss.risk_reward + 1), 0.85), 3),
                    kelly_fraction=round(max(0, (conf_map.get(ss.confidence, 0.65) * ss.risk_reward - (1 - conf_map.get(ss.confidence, 0.65))) / ss.risk_reward) * 0.5, 4),
                    suggested_risk_fraction=settings.scalp_max_risk_pct if hasattr(settings, 'scalp_max_risk_pct') else 0.01,
                    cvar95_loss=round(abs(ss.entry_zone_low - ss.sl_level) * 1.5, 2),
                    risk_of_ruin=0.02,
                    trailing_stop=None,
                    trailing_mode="atr_chandelier",
                    model="unified-scalp-v2",
                )
                scalp_signals_as_trade.append(t_sig)

        # Legacy signals as secondary (deprioritized)
        legacy_signals: list[TradeSignal] = detect_trade_signals(
            candles=closed_candles,
            metrics=self.metrics,
            fvgs=self.fvgs,
            order_blocks=self.order_blocks,
            liquidity_events=self.liquidity_events,
            swings=self.swings,
            regime=self.regime,
            mtf_confluence=mtf,
            ob_imbalances=ob_imb_data,
            ob_accumulations=ob_acc_data,
            psychology=self.psychology,
            readability=self.readability,
        ) if closed_candles else []

        # PRIMARY signal = scalping signal (always takes priority)
        if scalp_signals_as_trade:
            signals = scalp_signals_as_trade[:1]
        elif legacy_signals:
            signals = _select_primary_signal(legacy_signals)
        else:
            signals = []

        payload = {
            "update_type": update_type,
            "symbol": store.symbol,
            "timeframe": store.timeframe,
            "candle": to_wire(candle) if candle else None,
            "swings": to_wire(self.swings[-80:]),
            "signals": to_wire(signals),
            "metrics": to_wire(self.metrics),
            "projection": to_wire(self.projection),
            "regime": to_wire(self.regime),
            "psychology": to_wire(self.psychology),
            "readability": to_wire(self.readability),
            "btc_patterns": to_wire(self.btc_patterns),
            "orderbook": {
                "imbalances": to_wire(self.ob_imbalances[-15:]),
                "spread_dynamics": to_wire(self.ob_spread_dynamics[-15:]),
                "depth_levels": to_wire(self.ob_depth_levels[-20:]),
                "accumulations": to_wire([a for a in self.ob_accumulations if a.status == "active"][-10:]),
            },
            "scalp": to_wire(self.scalp_context) if self.scalp_context else None,
            "scalp_risk": self.scalp_risk.get_risk_summary(),
            "stats": {
                "closed_candles": len(closed_candles),
                "signals": len(signals),
                "scalp_signals": len(self.scalp_context.signals) if self.scalp_context else 0,
                "scalp_blocked": len(self.scalp_context.trade_blocked_reasons) if self.scalp_context else 0,
                "ob_imbalances": len(self.ob_imbalances),
                "ob_spread_anomalies": len([d for d in self.ob_spread_dynamics if d.status != "normal"]),
                "ob_accumulations": len([a for a in self.ob_accumulations if a.status == "active"]),
                "btc_patterns": len(self.btc_patterns.patterns) if self.btc_patterns else 0,
                "btc_behaviors": len(self.btc_patterns.investor_behaviors) if self.btc_patterns else 0,
                "fear_greed": self.psychology.fear_greed_label if self.psychology else "unknown",
                "readability_grade": self.readability.grade if self.readability else "unknown",
                "tradeability": self.readability.tradeability if self.readability else "unknown",
            },
        }
        if include_candles:
            payload["candles"] = to_wire(store.get_chart_candles())

        # Paper trading stats
        if self._paper_trading:
            pt_stats = repo.get_paper_trade_stats()
            payload["paper_trading"] = pt_stats

        # Save signals before paper trading (foreign key reference)
        for sig in signals:
            repo.save_signal(to_wire(sig))

        # Paper trading & alerts
        if self._paper_trading and signals and candle:
            events = self._paper_trading.evaluate_signals(
                signals, candle, symbol=store.symbol, timeframe=store.timeframe,
                mtf_confluence=mtf,
            )
            for ev in events:
                self._on_alert(ev)

        for sig in signals:
            alert = check_signal_alert(to_wire(sig))
            if alert:
                self._on_alert(alert)

        if self.regime and self.regime.phase != self._last_regime_phase:
            alert = check_regime_alert(self._last_regime_phase, self.regime.phase)
            if alert:
                self._on_alert(alert)
            self._last_regime_phase = self.regime.phase

        return payload

    def get_state(self) -> dict | None:
        """Get current pipeline state for history recording."""
        if not self.metrics or not self.regime:
            return None

        closed = self._get_closed_candles_for_state()
        latest = closed[-1] if closed else None
        price = latest.close if latest else 0

        patterns = []
        if self.btc_patterns:
            for p in self.btc_patterns.patterns:
                patterns.append({
                    "id": p.id,
                    "name": p.name,
                    "direction": p.direction,
                    "confidence": p.confidence,
                    "score": p.score,
                    "description": p.description,
                    "candle_count": p.candle_count,
                    "completed": p.completed,
                })

        fvgs_active = [f for f in self.fvgs if not f.is_filled]
        obs_active = [ob for ob in self.order_blocks if not ob.is_breaker]

        return {
            "symbol": getattr(self, "_symbol", "BTCUSDT"),
            "timeframe": getattr(self, "_timeframe", "5m"),
            "price": price,
            "change_pct": ((price - closed[-2].close) / closed[-2].close * 100) if len(closed) >= 2 else 0,
            "regime": {
                "phase": self.regime.phase,
                "bias": self.regime.bias,
                "confidence": self.regime.confidence,
                "range_high": self.regime.range_high,
                "range_low": self.regime.range_low,
                "range_mid": self.regime.range_mid,
                "width_pct": self.regime.width_pct,
                "atr_compression": self.regime.atr_compression,
                "efficiency_ratio": self.regime.efficiency_ratio,
                "volume_state": self.regime.volume_state,
                "reason": self.regime.reason,
            },
            "metrics": {
                "rsi14": self.metrics.rsi14,
                "atr14": self.metrics.atr14,
                "ema20": self.metrics.ema20,
                "ema50": self.metrics.ema50,
                "vwap": self.metrics.vwap,
                "vwap_distance_pct": self.metrics.vwap_distance_pct,
                "volume_zscore": self.metrics.volume_zscore,
                "realized_volatility": self.metrics.realized_volatility,
                "trend_score": self.metrics.trend_score,
                "volatility_score": self.metrics.volatility_score,
                "institutional_bias": self.metrics.institutional_bias,
                "bias_score": self.metrics.bias_score,
                "expected_move": self.metrics.expected_move,
                "expected_move_pct": getattr(self.metrics, "expected_move_pct", 0.0),
                "hurst_exponent": getattr(self.metrics, "hurst_exponent", 0.0),
                "shannon_entropy": getattr(self.metrics, "shannon_entropy", 0.0),
                "garch_volatility": getattr(self.metrics, "garch_volatility", 0.0),
                "kalman_trend_strength": getattr(self.metrics, "kalman_trend_strength", 0.0),
                "markov_bull_prob": getattr(self.metrics, "markov_bull_prob", 0.0),
                "markov_bear_prob": getattr(self.metrics, "markov_bear_prob", 0.0),
                "monte_carlo_var95": getattr(self.metrics, "monte_carlo_var95", 0.0),
                "fourier_dominant_period": getattr(self.metrics, "fourier_dominant_period", 0.0),
                "volume_profile_poc": getattr(self.metrics, "volume_profile_poc", 0.0),
                "volume_profile_imbalance": getattr(self.metrics, "volume_profile_imbalance", 0.0),
                "return_skewness": getattr(self.metrics, "return_skewness", 0.0),
                "return_kurtosis": getattr(self.metrics, "return_kurtosis", 0.0),
                "fractal_dimension": getattr(self.metrics, "fractal_dimension", 0.0),
            },
            "patterns": patterns,
            "fvgs": [{"id": f.id, "direction": f.direction, "top": f.top, "bottom": f.bottom} for f in fvgs_active],
            "order_blocks": [{"id": ob.id, "direction": ob.direction, "top": ob.top, "bottom": ob.bottom} for ob in obs_active],
            "liquidity": [{"id": l.id, "kind": l.kind, "price": l.price} for l in self.liquidity],
            "liquidity_events": [
                {
                    "id": e.id,
                    "side": e.side,
                    "swept_level": e.swept_level,
                    "sweep_price": e.sweep_price,
                    "close_price": e.close_price,
                    "sweep_depth": e.sweep_depth,
                    "displacement": e.displacement,
                    "reclaimed": e.reclaimed,
                    "engineered_score": e.engineered_score,
                    "reason": e.reason,
                    "level_kind": getattr(e, "level_kind", ""),
                    "level_price": getattr(e, "level_price", 0.0),
                    "touch_count": getattr(e, "touch_count", 0),
                }
                for e in self.liquidity_events
            ],
            "sentiment": getattr(self, "_sentiment", {}),
            "ai_decision": getattr(self, "_ai_decision", {}),
            "orderbook": {
                "bid": self.orderbook_analyzer.current_bid if hasattr(self.orderbook_analyzer, "current_bid") else None,
                "ask": self.orderbook_analyzer.current_ask if hasattr(self.orderbook_analyzer, "current_ask") else None,
                "spread": self.orderbook_analyzer.current_spread if hasattr(self.orderbook_analyzer, "current_spread") else None,
                "spread_pct": self.orderbook_analyzer.current_spread_pct if hasattr(self.orderbook_analyzer, "current_spread_pct") else None,
                "mid": self.orderbook_analyzer.current_mid if hasattr(self.orderbook_analyzer, "current_mid") else None,
                "imbalance_count": len(self.ob_imbalances),
                "accumulation_count": len([a for a in self.ob_accumulations if a.status == "active"]),
                "spread_anomaly_count": len([d for d in self.ob_spread_dynamics if d.status != "normal"]),
                "raw_imbalances": to_wire(self.ob_imbalances[-10:]),
                "raw_accumulations": to_wire(self.ob_accumulations[-10:]),
            },
            "candle_count": len(closed),
            "session": self.metrics.session if hasattr(self.metrics, "session") else None,
            "halving_phase": self.metrics.halving_phase if hasattr(self.metrics, "halving_phase") else None,
            "volatility_regime": self.metrics.volatility_regime if hasattr(self.metrics, "volatility_regime") else None,
        }

    def get_closed_candles(self) -> list[dict]:
        """Get closed candles for archiving."""
        closed = self._get_closed_candles_for_state()
        return [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "is_closed": True,
            }
            for c in closed
        ]

    def set_store_reference(self, store: CandleStore) -> None:
        """Set reference to candle store for state extraction."""
        self._symbol = store.symbol
        self._timeframe = store.timeframe
        self._store = store

    def _get_closed_candles_for_state(self) -> list[Candle]:
        """Get closed candles from the stored reference."""
        if hasattr(self, "_store"):
            return self._store.get_closed_candles()
        return []


def _select_primary_signal(signals: list[TradeSignal]) -> list[TradeSignal]:
    active = [signal for signal in signals if signal.status in {"open", "pending"}]
    candidates = active or signals[-12:]
    if not candidates:
        return []
    primary = max(
        candidates,
        key=lambda signal: (
            signal.confidence * 0.6
            + min(signal.risk_reward / 3, 1.0) * 0.3
            + signal.win_probability * 0.1,
            signal.timestamp,
        ),
    )
    return [primary]
