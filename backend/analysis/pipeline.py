from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Callable

logger = logging.getLogger(__name__)

from backend.analysis.alerts import check_signal_alert, check_regime_alert
from backend.analysis.btc_patterns import detect_btc_patterns
from backend.analysis.ensemble_model import ensemble as ensemble_model
from backend.analysis.self_optimizer import optimizer as self_optimizer
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
from backend.utils.system_health import get_system_health as _get_system_health
from backend.storage import repository as repo
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
    ScalpContext,
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
        self._alerted_signal_ids: set[str] = set()

        # Thread safety for async execution
        self._lock = asyncio.Lock()

        # Pattern discovery throttle — full re-clustering is expensive (650+ patterns)
        # and only needs to happen every ~60s, not on every snapshot cycle.
        self._last_pattern_discovery_ms: int = 0
        self._pattern_discovery_interval_ms: int = 60_000

        # One-shot seeding of pattern intelligence engine.
        self._pattern_seeded: bool = False

        # Unified scalping engine — PRIMARY signal source
        self.scalp_engine = UnifiedScalpEngine()
        self.scalp_risk = ScalpRiskManager()
        self.scalp_context = None
        self._last_scalp_context: ScalpContext | None = None
        self.futures_context: FuturesContext | dict | None = None
        self.ai_ict_review: Any = None

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
                timeframe=store.timeframe,
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
        # Inject pattern intelligence into btc_patterns context
        self._inject_pattern_intel()

        # Pre-seed pattern intelligence engine with historical data
        self._seed_pattern_intel(candles)

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
            latest_quote = self.quote_history[-1]
            self.ob_imbalances = self.orderbook_analyzer.update_imbalances(self.ob_imbalances, latest_quote)
        
        if self.quote_history:
            latest_quote = self.quote_history[-1]
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
                # Inject discovered patterns from PatternIntelligenceEngine into BtcPatternContext
                self._inject_pattern_intel()
        if self.quote_history:
            latest_candle = closed_candles[-1] if closed_candles else None
            latest_quote = self.quote_history[-1]
            if latest_candle and latest_quote:
                self.ob_accumulations = self.orderbook_analyzer.update_accumulation_status(
                    self.ob_accumulations, latest_candle, latest_quote
                )

        from backend.analysis.mtf_confluence import compute_mtf_confluence
        mtf = compute_mtf_confluence(store.timeframe, {store.timeframe: store}, {store.timeframe: self})

        # ── SINGLE SIGNAL SOURCE: Unified Scalping Engine ──
        # All data sources (candles, metrics, FVGs, OBs, swings, regime,
        # liquidity, futures context, orderbook) are computed ONCE in
        # _full_recalculate / _incremental_update and fed into the scalp
        # engine. There is NO secondary/legacy signal path — this is the
        # only signal generator in the system.
        if closed_candles and len(closed_candles) >= 20:
            fresh_ctx = self.scalp_engine.compute(
                candles=closed_candles,
                metrics=self.metrics,
                fvgs=self.fvgs,
                order_blocks=self.order_blocks,
                swings=self.swings,
                regime=self.regime,
                liquidity_events=self.liquidity_events,
                futures_context=self.futures_context,
                timeframe=store.timeframe,
            )
            # Cache the last valid scalp context (one with signals)
            # so signals survive page refreshes even when cooldown blocks
            # new signal generation on the snapshot request.
            if fresh_ctx.signals:
                self._last_scalp_context = fresh_ctx
            self.scalp_context = fresh_ctx
        elif self._last_scalp_context is not None:
            # No candle data to compute from — serve last cached context
            self.scalp_context = self._last_scalp_context

        # Fall back to last known scalp context when current computation
        # returns no signals (e.g. cooldown, blockers) but we have a
        # recent valid context — keeps the UI alive across page refreshes.
        display_ctx = self.scalp_context
        if display_ctx and not display_ctx.signals and self._last_scalp_context is not None:
            if self._last_scalp_context.signals:
                display_ctx = self._last_scalp_context

        # Run pattern discovery periodically — clustering is expensive
        # (650+ patterns), so throttle to every ~60s. Injection into
        # btc_patterns is cheap and uses the already-discovered cache, so
        # we do it every cycle to keep the UI live.
        try:
            from backend.analysis.self_aware_agent import get_agent
            pi = get_agent().pattern_intel
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_pattern_discovery_ms >= self._pattern_discovery_interval_ms:
                pi.discover_patterns()
                self._last_pattern_discovery_ms = now_ms
            # Cheap: re-emit the already-discovered patterns into the
            # btc_patterns context with decayed stats.
            self._inject_pattern_intel()
        except Exception:
            pass

        # ── Stale Signal Gate ───────────────────────────────────────────
        # A signal is stale if its SL or TP was already hit by the market,
        # or if its time limit has expired. When stale, we clear both the
        # display context and the cache so the old signal disappears.
        if display_ctx and display_ctx.signals and closed_candles:
            valid_signals: list[ScalpSignal] = []
            for sig in display_ctx.signals:
                now_ms = int(time.time() * 1000)
                expired = sig.time_limit_ms > 0 and now_ms > sig.time_limit_ms
                is_long = "LONG" in sig.signal_type
                sl_hit = False
                tp_hit = False
                if is_long:
                    sl_hit = any(c.low <= sig.sl_level for c in closed_candles[-20:])
                    tp_hit = any(c.high >= sig.target_1 for c in closed_candles[-10:])
                else:
                    sl_hit = any(c.high >= sig.sl_level for c in closed_candles[-20:])
                    tp_hit = any(c.low <= sig.target_1 for c in closed_candles[-10:])
                if not sl_hit and not tp_hit and not expired:
                    valid_signals.append(sig)
            if len(valid_signals) != len(display_ctx.signals):
                ai_brain = display_ctx.ai_intelligence or getattr(self.scalp_context, 'ai_intelligence', None)
                display_ctx = ScalpContext(timestamp=display_ctx.timestamp, ai_intelligence=ai_brain)
                self._last_scalp_context = None

        # Convert scalping signals to TradeSignal for system compatibility
        scalp_signals_as_trade: list[TradeSignal] = []
        if display_ctx and display_ctx.signals:
            for ss in display_ctx.signals:
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
                    status="open" if ss.status == "active" else ss.status,
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
                    max_hold_minutes=ss.max_hold_minutes,
                    enriched_features=ss.enriched_features,
                )
                scalp_signals_as_trade.append(t_sig)

        # SINGLE signal source: unified scalping engine only
        signals = scalp_signals_as_trade[:1] if scalp_signals_as_trade else []

        psych = self.psychology
        if psych is None:
            psych = PsychologySnapshot(
                timestamp=candle.timestamp if candle else int(time.time() * 1000),
                fear_greed_score=0.0, fear_greed_label="neutral",
                retail_participation=0.5, smart_money_activity=0.0,
                emotional_state="balanced", trap_risk=0.5,
                conviction_score=0.5, psychological_levels=[],
                summary="Insufficient data for psychology analysis",
            )
        read = self.readability
        if read is None:
            read = ReadabilitySnapshot(
                timestamp=candle.timestamp if candle else int(time.time() * 1000),
                overall_score=0.5, grade="C", candle_clarity=0.5,
                trend_quality=None, range_quality=None,
                noise_level=0.5, structure_reliability=0.5,
                tradeability="fair", dominant_pattern="unknown",
            )

        payload = {
            "update_type": update_type,
            "symbol": store.symbol,
            "timeframe": store.timeframe,
            "candle": to_wire(candle) if candle else None,
            "swings": to_wire(self.swings[-80:]),
            "signals": to_wire(signals),
            "metrics": self._metrics_payload(),
            "projection": to_wire(self.projection),
            "regime": to_wire(self.regime),
            "psychology": to_wire(psych),
            "readability": to_wire(read),
            "btc_patterns": to_wire(self.btc_patterns),
            "orderbook": {
                "imbalances": to_wire(self.ob_imbalances[-15:]),
                "spread_dynamics": to_wire(self.ob_spread_dynamics[-15:]),
                "depth_levels": to_wire(self.ob_depth_levels[-20:]),
                "accumulations": to_wire([a for a in self.ob_accumulations if a.status == "active"][-10:]),
            },
            "scalp": to_wire(display_ctx) if display_ctx else None,
            "scalp_risk": self.scalp_risk.get_risk_summary(),
            "stats": {
                "closed_candles": len(closed_candles),
                "signals": len(signals),
                "scalp_signals": len(display_ctx.signals) if display_ctx else 0,
                "scalp_blocked": len(display_ctx.trade_blocked_reasons) if display_ctx else 0,
                "ob_imbalances": len(self.ob_imbalances),
                "ob_spread_anomalies": len([d for d in self.ob_spread_dynamics if d.status != "normal"]),
                "ob_accumulations": len([a for a in self.ob_accumulations if a.status == "active"]),
                "btc_patterns": len(self.btc_patterns.patterns) if self.btc_patterns else 0,
                "btc_behaviors": len(self.btc_patterns.investor_behaviors) if self.btc_patterns else 0,
                "fear_greed": self.psychology.fear_greed_label if self.psychology else "unknown",
                "readability_grade": self.readability.grade if self.readability else "unknown",
                "tradeability": self.readability.tradeability if self.readability else "unknown",
                "ensemble": ensemble_model.get_stats(),
                "self_optimizer": self_optimizer.get_status(),
                "anomaly_detector": self.scalp_engine.anomaly_detector.get_status(),
                "trading_psychology": self._agent_psychology_status(),
                "pattern_intel": self._agent_pattern_intel(),
                "system_health": _get_system_health(),
            }
        }
        try:
            from backend.utils.panel_freshness import panel_freshness
            panel_freshness.mark_updated("ensemble")
            panel_freshness.mark_updated("anomaly_detector")
            panel_freshness.mark_updated("ai_lab")
            panel_freshness.mark_updated("optimizer")
        except Exception:
            pass
        if include_candles:
            payload["candles"] = to_wire(store.get_chart_candles())

        if self.ai_ict_review is not None:
            payload["ai_ict"] = to_wire(self.ai_ict_review)

        # Save signals before paper trading (foreign key reference)
        for sig in signals:
            repo.save_signal(to_wire(sig))

        # Paper trading & alerts
        if self._paper_trading and candle:
            events = self._paper_trading.evaluate_signals(
                signals, candle, symbol=store.symbol, timeframe=store.timeframe,
                mtf_confluence=mtf,
                regime=self.regime.phase if self.regime else "unknown",
            )
            for ev in events:
                if ev["type"] == "trade_opened":
                    self.scalp_risk.record_trade_open(ev.get("trade"))
                elif ev["type"] == "trade_closed":
                    self.scalp_risk.record_trade_close(ev.get("pnl", 0))
                    # Notify scalp engine when a trade is stopped out
                    reason = ev.get("reason", "")
                    trade = ev.get("trade", {})
                    side = trade.get("side", "")
                    if reason == "stop_loss" and side and hasattr(self, 'scalp_engine'):
                        self.scalp_engine.record_sl_hit(side)
                    # Feed closed trade to ensemble model and self-optimizer
                    trade_data = {
                        'direction': trade.get('side', 'unknown'),
                        'regime': trade.get('regime', self.regime.phase if self.regime else 'unknown'),
                        'confidence': trade.get('confidence', 0.5),
                        'pnl_pct': trade.get('pnl_pct', ev.get('pnl', 0)),
                        'won': ev.get('pnl', 0) > 0,
                        'hold_minutes': trade.get('hold_minutes', 0),
                        'entry_price': trade.get('entry_price', 0),
                        'exit_price': trade.get('exit_price', 0),
                    }
                    # Record in ensemble for weight learning
                    # Use trade_data directly instead of scalp_context so outcomes
                    # are recorded even when the scalp context has been cleared
                    # (cooldown, SL gate, stale signal gate, etc.).
                    if trade_data['direction'] != 'unknown':
                        from backend.analysis.ensemble_model import EnsembleScore
                        ens_score = EnsembleScore(
                            direction=trade_data['direction'],
                            confidence=trade_data['confidence'],
                            microstructure_score=0.5,
                            ict_score=0.5,
                            momentum_score=0.5,
                            regime=trade_data['regime'],
                            weights_used={},
                            reasons=[],
                        )
                        ensemble_model.record_outcome(ens_score, trade_data['won'], trade_data['pnl_pct'])
                    # Record in self-optimizer
                    self_optimizer.record_trade(trade_data)
                    # Active learning: optimize on every trade close to refine signals
                    if hasattr(self_optimizer, 'optimize_on_close'):
                        opt_result = self_optimizer.optimize_on_close(trade_data)
                        if opt_result.get('status') == 'applied':
                            logger.info("AI Lab applied optimization: %s", opt_result.get('changes', {}))
                    # Run scheduled self-optimization if due
                    elif self_optimizer.should_optimize():
                        opt_result = self_optimizer.run_optimization()
                        if opt_result.get('status') == 'applied':
                            logger.info("Self-optimization applied: %s", opt_result)
                # Only alert on blocked trades, not lifecycle events
                if ev["type"] == "trade_blocked":
                    self._on_alert(ev)

        if self._paper_trading:
            payload["paper_trading"] = repo.get_paper_trade_stats()

        for sig in signals:
            if sig.id not in self._alerted_signal_ids:
                alert = check_signal_alert(to_wire(sig))
                if alert:
                    self._on_alert(alert)
                self._alerted_signal_ids.add(sig.id)

        # Prune stale signal IDs to prevent memory growth (keep last 500)
        if len(self._alerted_signal_ids) > 1000:
            sorted_ids = sorted(self._alerted_signal_ids)
            self._alerted_signal_ids = set(sorted_ids[-500:])

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
        ai_decision = getattr(self, "_ai_decision", {}) or {}

        # Newer runtime flows keep the current AI review on ai_ict_review.
        # Expose that same decision shape to the history recorder so analytics
        # remains aligned with the live snapshot payload.
        if not ai_decision and self.ai_ict_review is not None:
            ai_decision = to_wire(self.ai_ict_review)

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
            "metrics": self._metrics_payload(),
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
            "ai_decision": ai_decision,
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

    def _seed_pattern_intel(self, candles: list[Candle]) -> None:
        """Pre-seed pattern intelligence engine with historical candle data.

        Only runs once (guarded by self._pattern_seeded) to prevent
        repeated flooding of the segment hash set across multiple
        full-recalculate cycles.
        """
        if self._pattern_seeded or len(candles) < 20:
            return
        self._pattern_seeded = True
        if not settings.enable_pattern_startup_seed:
            logger.info("Pattern intelligence startup seed skipped")
            return
        try:
            from backend.analysis.self_aware_agent import get_agent
            pi = get_agent().pattern_intel
            # Slide through historical candles in overlapping segments
            start = max(8, len(candles) - settings.pattern_seed_max_segments - 4)
            for i in range(start, len(candles) - 4):
                segment = candles[:i + 1]
                lookahead = candles[i + 1:i + 5]
                # Only record when segment has a closed lookahead
                if len(lookahead) >= 4:
                    pi.record_candles(segment, lookahead=lookahead)
            logger.info("Pattern intelligence seeded with %d segments", len(pi.segments))
            # Run initial discovery
            discovered = pi.discover_patterns()
            if discovered:
                logger.info("Pattern intelligence discovered %d patterns from historical data", len(discovered))
        except Exception:
            logger.exception("Failed to seed pattern intelligence")

    def _inject_pattern_intel(self) -> None:
        """Inject PatternIntelligenceEngine discovered patterns into btc_patterns context.

        Uses the cached `_discovered` set (populated by the throttled
        `discover_patterns()` call in snapshot) — does NOT re-run clustering
        on every cycle, which is too expensive to do per-snapshot.
        """
        if self.btc_patterns is None:
            return
        try:
            from backend.analysis.self_aware_agent import get_agent
            from backend.models.types import BtcPattern
            pi = get_agent().pattern_intel
            patterns = list(pi._discovered.values())
            now_ms = int(time.time() * 1000)
            # Clear previous injection — this runs every snapshot cycle
            # and must not accumulate duplicates between candle resets.
            self.btc_patterns.patterns.clear()
            self.btc_patterns.bullish_pattern_score = 0.0
            self.btc_patterns.bearish_pattern_score = 0.0
            for dp in patterns:
                # Use effective (decay-adjusted) stats for filtering and scoring
                eff_conf = pi._effective_confidence(dp) if hasattr(pi, '_effective_confidence') else dp.confidence
                eff_wr = pi._effective_win_rate(dp) if hasattr(pi, '_effective_win_rate') else dp.win_rate
                eff_ret = pi._effective_avg_return(dp) if hasattr(pi, '_effective_avg_return') else dp.avg_return
                decay = pi._decay_factor(dp.last_seen) if hasattr(pi, '_decay_factor') else 1.0

                if dp.occurrences < 3 or eff_conf < 0.3:
                    continue
                p = BtcPattern(
                    id=dp.pattern_id,
                    timestamp=int(dp.last_seen),
                    name=f"AI_{dp.direction.upper()}_{eff_wr:.0%}",
                    direction=dp.direction,
                    confidence=eff_conf,
                    score=eff_wr,
                    description=f"Discovered pattern: {dp.occurrences} occurrences, {eff_wr:.0%} effective win rate, avg return {eff_ret:.2%}, decay {decay:.0%}",
                    candle_count=8,
                    completed=True,
                )
                self.btc_patterns.patterns.append(p)
                if dp.direction == "bullish":
                    self.btc_patterns.bullish_pattern_score += eff_conf * eff_wr * 0.1
                elif dp.direction == "bearish":
                    self.btc_patterns.bearish_pattern_score += eff_conf * eff_wr * 0.1
            # Recompute pattern signal
            if self.btc_patterns.bullish_pattern_score > self.btc_patterns.bearish_pattern_score:
                self.btc_patterns.pattern_signal = "bullish"
            elif self.btc_patterns.bearish_pattern_score > self.btc_patterns.bullish_pattern_score:
                self.btc_patterns.pattern_signal = "bearish"
        except Exception:
            pass

    def _agent_psychology_status(self) -> dict:
        try:
            from backend.analysis.self_aware_agent import get_agent
            return get_agent().get_agent_status().get("psychology", {})
        except Exception:
            return {}

    def _agent_pattern_intel(self) -> dict:
        try:
            from backend.analysis.self_aware_agent import get_agent
            return get_agent().get_agent_status().get("pattern_intel", {})
        except Exception:
            return {}

    def _metrics_payload(self) -> dict | None:
        if not self.metrics:
            return None
        return {
            "timestamp": getattr(self.metrics, "timestamp", 0),
            "rsi14": self.metrics.rsi14,
            "atr14": self.metrics.atr14,
            "ema20": self.metrics.ema20,
            "ema50": self.metrics.ema50,
            "vwap": self.metrics.vwap,
            "vwap_distance_pct": self.metrics.vwap_distance_pct,
            "volume_zscore": self.metrics.volume_zscore,
            "realized_volatility": self.metrics.realized_volatility,
            "parkinson_volatility": getattr(self.metrics, "parkinson_volatility", 0.0),
            "garman_klass_volatility": getattr(self.metrics, "garman_klass_volatility", 0.0),
            "displacement_ratio": getattr(self.metrics, "displacement_ratio", 0.0),
            "premium_discount": getattr(self.metrics, "premium_discount", 0.0),
            "equilibrium": getattr(self.metrics, "equilibrium", 0.0),
            "range_high": getattr(self.metrics, "range_high", 0.0),
            "range_low": getattr(self.metrics, "range_low", 0.0),
            "trend_score": self.metrics.trend_score,
            "volatility_score": self.metrics.volatility_score,
            "institutional_bias": self.metrics.institutional_bias,
            "bias_score": self.metrics.bias_score,
            "expected_move": self.metrics.expected_move,
            "expected_move_pct": getattr(self.metrics, "expected_move_pct", 0.0),
            "hurst_exponent": getattr(self.metrics, "hurst_exponent", 0.0),
            "shannon_entropy": getattr(self.metrics, "shannon_entropy", 0.0),
            "garch_volatility": getattr(self.metrics, "garch_volatility", 0.0),
            "garch_persistence": getattr(self.metrics, "garch_persistence", 0.0),
            "kalman_trend": getattr(self.metrics, "kalman_trend", 0.0),
            "kalman_trend_strength": getattr(self.metrics, "kalman_trend_strength", 0.0),
            "markov_bull_prob": getattr(self.metrics, "markov_bull_prob", 0.0),
            "markov_bear_prob": getattr(self.metrics, "markov_bear_prob", 0.0),
            "markov_regime_certainty": getattr(self.metrics, "markov_regime_certainty", 0.0),
            "monte_carlo_var95": getattr(self.metrics, "monte_carlo_var95", 0.0),
            "monte_carlo_expected_return": getattr(self.metrics, "monte_carlo_expected_return", 0.0),
            "monte_carlo_max_drawdown": getattr(self.metrics, "monte_carlo_max_drawdown", 0.0),
            "fourier_dominant_period": getattr(self.metrics, "fourier_dominant_period", 0.0),
            "fourier_cycle_strength": getattr(self.metrics, "fourier_cycle_strength", 0.0),
            "volume_profile_poc": getattr(self.metrics, "volume_profile_poc", 0.0),
            "volume_profile_vah": getattr(self.metrics, "volume_profile_vah", 0.0),
            "volume_profile_val": getattr(self.metrics, "volume_profile_val", 0.0),
            "volume_profile_imbalance": getattr(self.metrics, "volume_profile_imbalance", 0.0),
            "return_skewness": getattr(self.metrics, "return_skewness", 0.0),
            "return_kurtosis": getattr(self.metrics, "return_kurtosis", 0.0),
            "fractal_dimension": getattr(self.metrics, "fractal_dimension", 0.0),
            "ljung_box_statistic": getattr(self.metrics, "ljung_box_statistic", 0.0),
            "autocorrelation_lag1": getattr(self.metrics, "autocorrelation_lag1", 0.0),
        }

    def set_store_reference(self, store: CandleStore) -> None:
        """Set reference to candle store for state extraction."""
        self._symbol = store.symbol
        self._timeframe = store.timeframe
        self._store = store

    def set_aggregated_price(self, price: float, spread_pct: float, exchange_count: int) -> None:
        """Set the multi-exchange aggregated price for cross-validation."""
        if hasattr(self, 'scalp_engine') and self.scalp_engine is not None:
            self.scalp_engine.ingest_aggregated_price(price, spread_pct, exchange_count)

    def _get_closed_candles_for_state(self) -> list[Candle]:
        """Get closed candles from the stored reference."""
        if hasattr(self, "_store"):
            return self._store.get_closed_candles()
        return []



