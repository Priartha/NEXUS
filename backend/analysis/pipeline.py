from __future__ import annotations

from collections import deque
from typing import Any, Callable

from backend.analysis.alerts import check_signal_alert, check_regime_alert
from backend.analysis.btc_patterns import detect_btc_patterns
from backend.analysis.fvg_detector import detect_fvgs, update_fvg_fills
from backend.analysis.institutional import build_price_projection, compute_market_metrics
from backend.analysis.liquidity import check_liquidity_sweeps, detect_equal_levels
from backend.analysis.liquidity_engineering import detect_liquidity_events
from backend.analysis.market_structure import detect_structure
from backend.analysis.order_block import detect_order_blocks, update_order_block_breakers
from backend.analysis.orderbook import OrderbookAnalyzer
from backend.analysis.paper_trading import PaperTradingEngine
from backend.analysis.regime import detect_market_regime
from backend.analysis.signals import detect_trade_signals
from backend.analysis.swing_detector import detect_swings
from backend.engine.candle_store import CandleStore
from backend.models.types import (
    BtcPatternContext,
    Candle,
    FVG,
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
    StructureLabel,
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
        self.fvgs: list[FVG] = []
        self.order_blocks: list[OrderBlock] = []
        self.liquidity: list[LiquidityLevel] = []
        self.liquidity_events: list[LiquidityEvent] = []
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
        
        # BTC movement & investor behavior patterns
        self.btc_patterns: BtcPatternContext | None = None

        # Paper trading & alerts
        self._paper_trading = paper_trading
        self._on_alert = on_alert or (lambda _: None)
        self._last_regime_phase: str | None = None

        self._last_candle_count = 0

    def add_quote(self, quote: MarketQuote) -> None:
        """Add a market quote for orderbook analysis."""
        self.quote_history.append(quote)
        self.orderbook_analyzer.add_quote(quote)

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

    def _full_recalculate(self, candles: list[Candle]) -> None:
        if not candles:
            return

        window = candles[-self.lookback :]
        self.swings = detect_swings(candles, n=self.swing_window)[-250:]
        self.fvgs = detect_fvgs(window)
        self.order_blocks = detect_order_blocks(window, self.swings)
        self.liquidity = detect_equal_levels(self.swings)

        for candle in window:
            self.fvgs = update_fvg_fills(self.fvgs, candle)
            self.order_blocks = update_order_block_breakers(self.order_blocks, candle)
            self.liquidity = check_liquidity_sweeps(self.liquidity, candle)
        self.metrics = compute_market_metrics(candles, self.swings)
        self.liquidity_events = detect_liquidity_events(window, self.liquidity, self.metrics.atr14 if self.metrics else 0.0)[-80:]
        self.regime = detect_market_regime(candles, self.metrics, self.liquidity_events)
        self.projection = build_price_projection(candles, self.metrics, self.liquidity_events)

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
            self._merge_liquidity(detect_equal_levels(self.swings))

        self.fvgs = update_fvg_fills(self.fvgs, latest)
        if len(candles) >= 3:
            self._merge_fvgs(detect_fvgs(candles[-3:]))

        self.order_blocks = update_order_block_breakers(self.order_blocks, latest)
        self._merge_order_blocks(detect_order_blocks(candles[-25:], self.swings))
        self.liquidity = check_liquidity_sweeps(self.liquidity, latest)
        self.metrics = compute_market_metrics(candles, self.swings)
        self._merge_liquidity_events(
            detect_liquidity_events(candles[-8:], self.liquidity, self.metrics.atr14 if self.metrics else 0.0)
        )
        self.regime = detect_market_regime(candles, self.metrics, self.liquidity_events)
        self.projection = build_price_projection(candles, self.metrics, self.liquidity_events)

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

    def _merge_fvgs(self, new_fvgs: list[FVG]) -> None:
        current = {fvg.id: fvg for fvg in self.fvgs}
        for fvg in new_fvgs:
            current.setdefault(fvg.id, fvg)
        self.fvgs = sorted(current.values(), key=lambda item: item.timestamp)[-150:]

    def _merge_order_blocks(self, new_blocks: list[OrderBlock]) -> None:
        current = {block.id: block for block in self.order_blocks}
        for block in new_blocks:
            current.setdefault(block.id, block)
        self.order_blocks = sorted(current.values(), key=lambda item: item.timestamp)[-80:]

    def _merge_liquidity(self, new_levels: list[LiquidityLevel]) -> None:
        current = {level.id: level for level in self.liquidity}
        for level in new_levels:
            current.setdefault(level.id, level)
        self.liquidity = sorted(current.values(), key=lambda item: item.price)[-120:]

    def _merge_liquidity_events(self, new_events: list[LiquidityEvent]) -> None:
        current = {event.id: event for event in self.liquidity_events}
        for event in new_events:
            current.setdefault(event.id, event)
        self.liquidity_events = sorted(current.values(), key=lambda item: item.timestamp)[-80:]

    def _merge_ob_accumulations(self, new_accums: list[OrderbookAccumulation]) -> None:
        current = {accum.id: accum for accum in self.ob_accumulations}
        for accum in new_accums:
            current.setdefault(accum.id, accum)
        self.ob_accumulations = sorted(current.values(), key=lambda item: item.timestamp)[-30:]

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
        # Refresh accumulations status with latest candle data
        if self.quote_history:
            latest_candle = closed_candles[-1] if closed_candles else None
            latest_quote = list(self.quote_history)[-1] if self.quote_history else None
            if latest_candle and latest_quote:
                self.ob_accumulations = self.orderbook_analyzer.update_accumulation_status(
                    self.ob_accumulations, latest_candle, latest_quote
                )

        structure: list[StructureLabel] = detect_structure(self.swings, closed_candles)
        active_fvgs = [fvg for fvg in self.fvgs if not fvg.is_filled][-30:]
        active_obs = [block for block in self.order_blocks if not block.is_breaker][-20:]
        active_liquidity = [level for level in self.liquidity if not level.swept][-20:]
        active_liquidity_events = self.liquidity_events[-20:]
        detected_signals: list[TradeSignal] = detect_trade_signals(
            candles=closed_candles,
            swings=self.swings,
            structure=structure,
            fvgs=self.fvgs,
            order_blocks=self.order_blocks,
            liquidity=self.liquidity,
            liquidity_events=self.liquidity_events,
            metrics=self.metrics,
        )
        signals = _select_primary_signal(detected_signals)

        payload = {
            "update_type": update_type,
            "symbol": store.symbol,
            "timeframe": store.timeframe,
            "candle": to_wire(candle) if candle else None,
            "swings": to_wire(self.swings[-80:]),
            "structure": to_wire(structure[-60:]),
            "fvgs": to_wire(active_fvgs),
            "order_blocks": to_wire(active_obs),
            "liquidity": to_wire(active_liquidity),
            "liquidity_events": to_wire(active_liquidity_events),
            "signals": to_wire(signals),
            "metrics": to_wire(self.metrics),
            "projection": to_wire(self.projection),
            "regime": to_wire(self.regime),
            "btc_patterns": to_wire(self.btc_patterns),
            "orderbook": {
                "imbalances": to_wire(self.ob_imbalances[-15:]),
                "spread_dynamics": to_wire(self.ob_spread_dynamics[-15:]),
                "depth_levels": to_wire(self.ob_depth_levels[-20:]),
                "accumulations": to_wire([a for a in self.ob_accumulations if a.status == "active"][-10:]),
            },
            "stats": {
                "closed_candles": len(closed_candles),
                "active_fvgs": len(active_fvgs),
                "active_order_blocks": len(active_obs),
                "active_liquidity": len(active_liquidity),
                "liquidity_events": len(active_liquidity_events),
                "signals": len(signals),
                "ob_imbalances": len(self.ob_imbalances),
                "ob_spread_anomalies": len([d for d in self.ob_spread_dynamics if d.status != "normal"]),
                "ob_accumulations": len([a for a in self.ob_accumulations if a.status == "active"]),
                "btc_patterns": len(self.btc_patterns.patterns) if self.btc_patterns else 0,
                "btc_behaviors": len(self.btc_patterns.investor_behaviors) if self.btc_patterns else 0,
            },
        }
        if include_candles:
            payload["candles"] = to_wire(store.get_chart_candles())

        # Paper trading stats
        if self._paper_trading:
            from backend.storage import repository as repo
            pt_stats = repo.get_paper_trade_stats()
            payload["paper_trading"] = pt_stats

        # Paper trading & alerts
        if self._paper_trading and signals and candle:
            events = self._paper_trading.evaluate_signals(
                detected_signals, candle, symbol=store.symbol, timeframe=store.timeframe,
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


def _select_primary_signal(signals: list[TradeSignal]) -> list[TradeSignal]:
    active = [signal for signal in signals if signal.status in {"open", "pending"}]
    candidates = active or signals[-12:]
    if not candidates:
        return []
    primary = max(
        candidates,
        key=lambda signal: (
            signal.confidence * 0.58
            + min(signal.risk_reward / 3, 1.0) * 0.18
            + signal.liquidity_score * 0.14
            + max(signal.bias_score, 0.0) * 0.1,
            signal.timestamp,
        ),
    )
    return [primary]
