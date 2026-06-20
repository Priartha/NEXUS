"""
NEXUS Unified Scalping Engine v4.0 — Self-Optimising AI Trading Brain

Single-signal scalping engine for BTCUSD perpetual futures.
PRIMARY SIGNAL: Self-Aware Trading Agent — no external dependencies, pure price action.

V4 NEW DATA SOURCES (added on top of V3):
  13. Market Structure: Break of Structure (BoS), market structure shift (MSS)
  14. RSI/Price Divergence: Regular + hidden divergence on RSI(14)
  15. Multi-Timeframe Alignment: Systematic scoring across 1m/5m/15m/1h
  16. Candle Patterns: Pin bar, engulfing, inside bar, momentum candle
  17. Kelly Position Sizing: Optimal size from win rate + confidence + RR
  18. Regime-Adaptive SL/TP: Wider stops in trending, tighter in range
  19. Correlation Check: ETH/BTC cross-asset confirmation

V3 data sources carried forward:
   1-12. Order Flow, VWAP, Funding, OI, Liquidations, Sweeps,
         Volume Profile, ICT Patterns, Regime, RSI(3), Killzone, Wick Rejection

Output: EXACTLY ONE futures scalping signal or NO_TRADE.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.analysis.wick_rejection import analyze_wick_rejection
from backend.analysis.self_aware_agent import SelfAwareTradingAgent, get_agent
from backend.analysis.ensemble_model import ensemble as ensemble_model
from backend.analysis.self_optimizer import optimizer as self_optimizer
from backend.analysis.anomaly_detection import MarketAnomalyDetector, adaptive_stop
from backend.analysis.cvd_divergence import cvd_divergence_detector
from backend.analysis.funding_strategy import funding_strategy
from backend.analysis.adaptive_sltp import adaptive_sltp as adaptive_sltp_engine
from backend.analysis.trader_profile import get_trader_profile
from backend.config import settings

logger = logging.getLogger(__name__)
from backend.models.types import (
    Candle,
    FVG,
    LiquidityEvent,
    LiquidityLevel,
    MarketMetrics,
    MarketQuote,
    MarketRegime,
    OrderBlock,
    ScalpContext,
    ScalpFunding,
    ScalpFundingRate,
    ScalpLiquidationLevel,
    ScalpOpenInterest,
    ScalpWickRejection,
    ScalpOrderFlow,
    ScalpSignal,
    ScalpVWAP,
    ScalpVolumeProfile,
    ScalpLiquiditySweep,
    Swing,
    FuturesContext,
)


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2.0 / (period + 1)
    r = values[0]
    for v in values[1:]:
        r = (v - r) * k + r
    return r


def _atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    rng: list[float] = []
    for a, b in zip(candles[-(period + 1):], candles[-period:]):
        rng.append(max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)))
    return sum(rng) / len(rng)


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    g: list[float] = []
    l: list[float] = []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        g.append(max(d, 0.0))
        l.append(max(-d, 0.0))
    ag = sum(g[:period]) / period
    al = sum(l[:period]) / period
    for i in range(period, len(closes) - 1):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    rs = ag / al if al > 0 else 100.0
    return 100.0 - 100.0 / (1.0 + rs)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _is_killzone(ts_ms: int) -> tuple[bool, str]:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    t = dt.hour + dt.minute / 60.0
    if 2.0 <= t < 5.0:
        return True, "london"
    if 8.5 <= t < 11.0:
        return True, "ny_am"
    if 13.5 <= t < 16.0:
        return True, "ny_pm"
    return False, "off_hours"


class UnifiedScalpEngine:
    """
    Computes all 11 data sources and fuses them into a single
    confluence-weighted futures scalping signal.
    """

    def __init__(self) -> None:
        self._quotes: deque[MarketQuote] = deque(maxlen=5000)
        self._oi_hist: deque[tuple[int, float]] = deque(maxlen=200)
        self._fund_hist: deque[tuple[int, float]] = deque(maxlen=100)
        self._cur_funding: float = 0.0
        self._cur_oi: float = 0.0
        self._spot_vol_avg: float = 0.0
        self._liq_cache: list[dict] = []
        self._last_signal_ts: int = 0
        self._signal_cooldown_ms: int = 1 * 60 * 1000
        self._use_candle_timestamp_for_cooldown: bool = True
        # Multi-exchange aggregated price for cross-validation
        self._last_aggregated_price: float | None = None
        self._last_aggregated_spread_pct: float = 0.0
        self._last_exchange_count: int = 0
        self.anomaly_detector = MarketAnomalyDetector()
        # SL breach tracking — prevents showing new signals after previous SL was hit
        self._last_sl_level: float = 0.0
        self._last_sl_side: str = ""
        self._last_sl_signal_ts: int = 0
        self._sl_breached: bool = False
        self._sl_breached_at_ms: int = 0
        self._sl_cooldown_ms: int = 15 * 60 * 1000  # 15m cooldown after SL hit

    def ingest_quote(self, q: MarketQuote) -> None:
        self._quotes.append(q)

    def ingest_funding(self, rate: float, ts: int | None = None) -> None:
        self._cur_funding = rate
        self._fund_hist.append((ts or int(time.time() * 1000), rate))

    def ingest_oi(self, oi: float, ts: int | None = None) -> None:
        self._cur_oi = oi
        self._oi_hist.append((ts or int(time.time() * 1000), oi))

    def ingest_spot_vol_avg(self, avg: float) -> None:
        self._spot_vol_avg = avg

    def ingest_liquidations(self, levels: list[dict]) -> None:
        self._liq_cache = levels

    def ingest_aggregated_price(self, price: float, spread_pct: float, exchange_count: int) -> None:
        """Ingest multi-exchange aggregated price for cross-validation."""
        self._last_aggregated_price = price
        self._last_aggregated_spread_pct = spread_pct
        self._last_exchange_count = exchange_count

    def _data_coherence_check(self, candles: list[Candle], now_ms: int, timeframe: str) -> list[str]:
        """Verify ALL data sources are coherent and fresh before signal generation."""
        issues: list[str] = []
        if not candles:
            issues.append("No candle data available")
            return issues

        # Check candle ordering and gaps
        for i in range(1, len(candles)):
            if candles[i].timestamp <= candles[i-1].timestamp:
                issues.append(f"Non-monotonic candle timestamps at index {i}")
                break

        # Check for price anomalies (zero, negative, extreme outliers)
        closes = [c.close for c in candles[-50:]]
        if not closes:
            issues.append("No close prices available")
            return issues

        mean_price = sum(closes) / len(closes)
        if mean_price <= 0:
            issues.append("Mean price near zero — data corruption likely")
            return issues

        for i, c in enumerate(candles[-20:]):
            idx = len(candles) - 20 + i
            if any(v <= 0 for v in [c.open, c.high, c.low, c.close]):
                issues.append(f"Non-positive price in candle {idx}")
                break
            if c.high < c.low or c.high < c.open or c.high < c.close:
                issues.append(f"Invalid candle range at index {idx}")
                break
            # Check for extreme outliers (>50% move in one candle)
            change = abs(c.close - candles[max(0, idx-1)].close) / candles[max(0, idx-1)].close
            if change > 0.50:
                issues.append(f"Extreme {change*100:.0f}% price move in candle {idx}")
                break

        # Cross-check aggregated price vs candle close
        if self._last_aggregated_price and self._last_aggregated_price > 0 and closes:
            deviation = abs(closes[-1] - self._last_aggregated_price) / self._last_aggregated_price
            if deviation > 0.01:
                issues.append(
                    f"Price mismatch: candle close ${closes[-1]:.2f} vs "
                    f"{self._last_exchange_count}-exchange agg ${self._last_aggregated_price:.2f} "
                    f"({deviation*100:.2f}%)"
                )

        # Ensure futures context has recent data if available
        interval_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
        expected_interval_ms = interval_seconds.get(timeframe, 300) * 1000
        latest_ts_ms = candles[-1].timestamp
        stale_ms = now_ms - latest_ts_ms
        if stale_ms > expected_interval_ms * 4:
            issues.append(f"Stale candles: last candle {stale_ms//60000}m ago")

        return issues

    def record_sl_hit(self, side: str) -> None:
        self._sl_breached = True
        self._sl_breached_at_ms = int(time.time() * 1000)
        logger.info("Scalp SL breach recorded for side=%s — blocking same-direction signals for %d minutes",
                     side, self._sl_cooldown_ms // 60000)

    def _previous_sl_breached(self, candles: list[Candle], now_ms: int) -> str:
        if not self._last_sl_level or not self._last_sl_side or not self._last_sl_signal_ts:
            return ""
        if not candles:
            return ""
        latest = max(c.timestamp for c in candles)
        age_ms = latest - self._last_sl_signal_ts
        if age_ms > self._sl_cooldown_ms:
            return ""
        recent = [c for c in candles if c.timestamp >= self._last_sl_signal_ts - 300000]
        if self._last_sl_side == "long":
            if any(c.low <= self._last_sl_level for c in recent):
                self._sl_breached = True
                self._sl_breached_at_ms = now_ms
                return "long"
        elif self._last_sl_side == "short":
            if any(c.high >= self._last_sl_level for c in recent):
                self._sl_breached = True
                self._sl_breached_at_ms = now_ms
                return "short"
        return ""

    def _sl_cooldown_active(self, now_ms: int, side: str, check_ts: int) -> bool:
        effective_cooldown = max(self._sl_cooldown_ms, self._signal_cooldown_ms * 2)
        elapsed = now_ms - self._sl_breached_at_ms
        return elapsed < effective_cooldown

    def compute(
        self,
        candles: list[Candle],
        metrics: MarketMetrics | None = None,
        fvgs: list[FVG] | None = None,
        order_blocks: list[OrderBlock] | None = None,
        swings: list[Swing] | None = None,
        regime: MarketRegime | None = None,
        liquidity_events: list[LiquidityEvent] | None = None,
        futures_context: FuturesContext | dict[str, Any] | None = None,
        timeframe: str = "5m",
    ) -> ScalpContext:
        if self._use_candle_timestamp_for_cooldown and candles:
            now_ms = int(candles[-1].timestamp)
        else:
            now_ms = int(time.time() * 1000)
        if len(candles) < 20:
            ctx = ScalpContext(timestamp=now_ms)
            ctx.ai_brain_active = True
            ctx.ai_intelligence = get_agent().get_agent_status()
            return ctx

        # ── Data coherence gate ─────────────────────────────────────────
        # Verify ALL data sources are coherent before computing signals.
        # If data is corrupted, stale, or inconsistent across sources, we
        # return a blocked context rather than a false signal.
        coherence_issues = self._data_coherence_check(candles, now_ms, timeframe)
        if coherence_issues:
            ctx = ScalpContext(timestamp=now_ms)
            ctx.trade_blocked_reasons = coherence_issues
            ctx.ai_brain_active = True
            ctx.ai_intelligence = get_agent().get_agent_status()
            logger.warning(f"Data coherence check failed: {'; '.join(coherence_issues)}")
            return ctx

        # ── Anomaly / OOD detection gate ────────────────────────────────
        # Detect black swan events, regime shifts, and out-of-distribution
        # market states. Block trading during anomalies.
        last_candle_for_anomaly = candles[-1] if candles else None
        anomaly = self.anomaly_detector.detect(last_candle_for_anomaly)
        if anomaly.should_block_trade:
            logger.warning("Anomaly detected: %s (score=%.2f) — blocking trades",
                           anomaly.anomaly_type, anomaly.anomaly_score)
            ctx = ScalpContext(timestamp=now_ms)
            ctx.trade_blocked_reasons = [f"Anomaly: {anomaly.description}"]
            ctx.ai_brain_active = True
            ctx.ai_intelligence = get_agent().get_agent_status()
            return ctx
        # Update anomaly detector with new data
        self.anomaly_detector.update(last_candle_for_anomaly)

        ordered = sorted(candles, key=lambda c: c.timestamp)
        self._last_candles = ordered
        self._last_liq_levels = getattr(futures_context, 'liquidation_clusters', []) if futures_context else []
        closes = [c.close for c in ordered]
        price = closes[-1]

        order_flow = self._order_flow(ordered)

        # Feed order flow to CVD divergence detector
        if order_flow:
            cvd_divergence_detector.ingest(ordered[-1].timestamp, price, order_flow.cvd)

        # Detect CVD divergences
        cvd_divs = cvd_divergence_detector.detect()

        # Compute funding rate strategy signal
        funding_strat_signal = funding_strategy.compute(
            self._cur_funding, price,
            regime.phase if regime else None,
        )

        funding = self._funding(now_ms)
        funding_rate = self._funding_rate(now_ms, futures_context)
        oi = self._open_interest(futures_context)
        liq_levels = self._liquidation_levels(price, futures_context)
        vwap = self._vwap(ordered)
        vol_profile = self._volume_profile(ordered)
        sweeps = self._liquidity_sweeps(ordered)
        wick = self._wick_rejection(ordered)
        rsi_3 = _rsi(closes[-20:], 3) if len(closes) >= 4 else 50.0
        kill_active, kill_session = _is_killzone(ordered[-1].timestamp)

        # ── V4 New Analyses ─────────────────────────────────────────────
        ms = self._market_structure(ordered, swings)
        div = self._divergence(ordered)
        mtf = self._mtf_alignment(price, regime, timeframe)
        candle_pat = self._candle_patterns(ordered)
        correlation = self._correlation_check()

        # ── Common Sense Checks ─────────────────────────────────────────
        # Sanity checks every human trader would follow before considering a trade
        atr_for_common_sense = _atr(ordered, 14)
        common_sense_blockers = self._common_sense_blockers(
            ordered, price, atr_for_common_sense, now_ms, timeframe,
        )
        has_macro_event_block = any("macro" in b.lower() or "FOMC" in b or "CPI" in b or "NFP" in b for b in common_sense_blockers)

        # Common sense blocks are soft warnings — only hard-block the most severe
        severe_cs = [b for b in common_sense_blockers if any(k in b.lower() for k in
            ["atr spike", "stale data", "price deviation", "cross-exchange spread"])]
        cs_advisory = [b for b in common_sense_blockers if b not in severe_cs]
        self._cs_advisory = cs_advisory
        for b in severe_cs:
            logger.warning("Common sense block: %s", b)

        # ── SL Breach Gate ─────────────────────────────────────────────
        # If the previous scalp signal's SL was hit by price, block new
        # signals in the same direction to avoid re-entry into a losing setup.
        breached_side = self._previous_sl_breached(ordered, now_ms)
        self._sl_breached = bool(breached_side)

        # ── Hard signal blockers ──
        blockers = self._filters(ordered, funding, funding_rate, futures_context)
        blockers.extend(severe_cs)

        if blockers:
            ctx = ScalpContext(
                timestamp=now_ms,
                order_flow=order_flow,
                funding=funding,
                funding_rate=funding_rate,
                open_interest=oi,
                liquidation_levels=liq_levels,
                vwap=vwap,
                volume_profile=vol_profile,
                liquidity_sweeps=sweeps,
                wick_rejection=wick,
                rsi_3=round(rsi_3, 2),
                spot_volume_ok=all(b != "Spot volume below 30-day average" for b in blockers),
                macro_event_block=has_macro_event_block,
                trade_blocked_reasons=blockers,
                common_sense_warnings=common_sense_blockers,
            )
            ctx.futures_leverage = settings.futures_leverage
            ctx.estimated_funding_cost_8h = round(funding_rate.current_rate * 3 * 100, 4) if funding_rate else 0.0
            ctx.ai_brain_active = True
            ctx.ai_intelligence = get_agent().get_agent_status()
            return ctx

        long_score, long_reasons = self._confluence_long(
            price, order_flow, vwap, oi, funding, sweeps,
            vol_profile, rsi_3, kill_active, kill_session,
            metrics, fvgs, order_blocks, regime, ordered, futures_context, wick,
        )
        short_score, short_reasons = self._confluence_short(
            price, order_flow, vwap, oi, funding, sweeps,
            vol_profile, rsi_3, kill_active, kill_session,
            metrics, fvgs, order_blocks, regime, ordered, futures_context, wick,
        )

        # ── V4 Score Boosts (gracefully degrade on missing data) ────────
        try:
            # Market Structure Break — strong directional confirmation
            if ms.get("bos") == "bullish":
                long_score += 0.08; long_reasons.append(f"BoS bullish ({ms['strength']:.1f}%)")
            elif ms.get("bos") == "bearish":
                short_score += 0.08; short_reasons.append(f"BoS bearish ({ms['strength']:.1f}%)")
            if ms.get("mss") == "bullish_shift":
                long_score += 0.12; long_reasons.append("MSS bullish shift")
            elif ms.get("mss") == "bearish_shift":
                short_score += 0.12; short_reasons.append("MSS bearish shift")
            # Divergence — powerful reversal signal
            if div.get("type") == "bullish_regular":
                long_score += 0.10; long_reasons.append(f"Bullish divergence ({div['strength']:.2f})")
            elif div.get("type") == "bearish_regular":
                short_score += 0.10; short_reasons.append(f"Bearish divergence ({div['strength']:.2f})")
            elif div.get("type") == "bullish_hidden":
                long_score += 0.06; long_reasons.append("Hidden bullish divergence")
            elif div.get("type") == "bearish_hidden":
                short_score += 0.06; short_reasons.append("Hidden bearish divergence")
            # CVD Divergence — strongest orderflow reversal signal
            for cvd_div in cvd_divs:
                if cvd_div.divergence_type == "bullish_regular":
                    long_score += 0.15 * cvd_div.strength; long_reasons.append(f"CVD bullish divergence ({cvd_div.strength:.0%})")
                elif cvd_div.divergence_type == "bearish_regular":
                    short_score += 0.15 * cvd_div.strength; short_reasons.append(f"CVD bearish divergence ({cvd_div.strength:.0%})")
                elif cvd_div.divergence_type == "bullish_hidden":
                    long_score += 0.10 * cvd_div.strength; long_reasons.append(f"CVD hidden bullish divergence ({cvd_div.strength:.0%})")
                elif cvd_div.divergence_type == "bearish_hidden":
                    short_score += 0.10 * cvd_div.strength; short_reasons.append(f"CVD hidden bearish divergence ({cvd_div.strength:.0%})")
            # Funding strategy boost
            if funding_strat_signal and funding_strat_signal.direction != "neutral":
                if funding_strat_signal.direction == "long":
                    long_score += 0.12 * funding_strat_signal.strength; long_reasons.append(f"Funding strategy long (z={funding_strat_signal.zscore:.1f})")
                elif funding_strat_signal.direction == "short":
                    short_score += 0.12 * funding_strat_signal.strength; short_reasons.append(f"Funding strategy short (z={funding_strat_signal.zscore:.1f})")
            # Candle patterns — micro-structure confirmation
            if candle_pat.get("pin_bar") == "bullish":
                long_score += 0.06; long_reasons.append(f"Bullish pin bar ({candle_pat.get('pin_bar_strength', 1):.1f}x)")
            elif candle_pat.get("pin_bar") == "bearish":
                short_score += 0.06; short_reasons.append(f"Bearish pin bar ({candle_pat.get('pin_bar_strength', 1):.1f}x)")
            if candle_pat.get("engulfing") == "bullish":
                long_score += 0.07; long_reasons.append("Bullish engulfing")
            elif candle_pat.get("engulfing") == "bearish":
                short_score += 0.07; short_reasons.append("Bearish engulfing")
            if candle_pat.get("momentum_candle") == "bullish":
                long_score += 0.04; long_reasons.append(f"Momentum candle ({candle_pat.get('momentum_strength', 1):.1f}x)")
            elif candle_pat.get("momentum_candle") == "bearish":
                short_score += 0.04; short_reasons.append(f"Momentum candle ({candle_pat.get('momentum_strength', 1):.1f}x)")
            if candle_pat.get("nr7"):
                long_reasons.append("NR7 compression — breakout imminent")
                short_reasons.append("NR7 compression — breakout imminent")
            # MTF alignment — macro context reinforces direction
            if mtf.get("alignment") == "bullish":
                long_score += 0.05 * mtf.get("confidence", 0.5); long_reasons.append(f"MTF bullish (conf {mtf.get('confidence', 0):.0%})")
            elif mtf.get("alignment") == "bearish":
                short_score += 0.05 * mtf.get("confidence", 0.5); short_reasons.append(f"MTF bearish (conf {mtf.get('confidence', 0):.0%})")
            # Correlation check — cross-asset confirmation
            if not correlation.get("aligned", True):
                long_score -= 0.03; short_score -= 0.03
        except Exception:
            pass

        atr = _atr(ordered, 14)
        signals: list[ScalpSignal] = []

        # ── Get adaptive parameters from self-optimizer ──
        regime_phase = regime.phase if regime else "unknown"
        adaptive_params = self_optimizer.get_adaptive_params(regime_phase)

        # Use adaptive threshold from self-optimizer
        threshold = adaptive_params.get('min_confidence', settings.scalp_min_confluence_score)
        trader_profile = get_trader_profile()
        threshold = trader_profile.confidence_threshold(threshold, ordered[-1])

        has_oi = oi.current_oi > 0 and len(self._oi_hist) >= 2
        has_funding = self._cur_funding != 0.0
        missing_sources = sum([not has_oi, not has_funding])
        if missing_sources > 0:
            max_possible = 1.0 - (missing_sources * 0.11)
            normalized_threshold = threshold * (max_possible / 1.0)
            threshold = max(normalized_threshold, 0.35)

        # Record candle data for pattern intelligence engine
        try:
            get_agent().pattern_intel.record_candles(ordered, volatility_regime=regime.phase if regime else "normal")
        except Exception:
            pass

        # ── Self-Aware AI Agent is the CENTRAL BRAIN ────────────────────────
        # It receives ALL 15 data sources + price action + memory and makes the final decision
        agent_result = get_agent().analyze_enriched(
            candles=ordered, order_flow=order_flow, vwap=vwap, oi=oi,
            funding=funding_rate, sweeps=sweeps, vol_profile=vol_profile,
            rsi_3=rsi_3, kill_active=kill_active, kill_session=kill_session,
            metrics=metrics, fvgs=fvgs, order_blocks=order_blocks,
            regime_obj=regime, wick=wick, futures_context=futures_context,
            long_confluence=long_score, short_confluence=short_score,
            timeframe=timeframe,
        )

        # ── Ensemble Model: 4-model blend (microstructure + ICT + momentum + XGBoost) ──
        micro_score, micro_reasons = ensemble_model.score_microstructure(
            order_flow, vwap, oi, funding_rate, price, regime_phase,
        )
        ict_score, ict_reasons = ensemble_model.score_ict(
            fvgs, order_blocks, sweeps, regime, price, regime_phase, ordered,
        )
        momentum_score, momentum_reasons = ensemble_model.score_momentum(
            rsi_3, ordered, kill_active, kill_session, metrics, wick,
        )
        # XGBoost scoring — ML-based directional prediction
        xgb_score_val = 0.5
        xgb_reasons: list[str] = []
        try:
            from backend.analysis.xgboost_model import xgboost_model
            from backend.storage.feature_store import feature_store
            fv = feature_store.get_feature_vector(ordered[-1].timestamp, settings.symbol, timeframe)
            if fv:
                xgb_pred = xgboost_model.predict(ordered[-1].timestamp, fv)
                if xgb_pred.direction == "long":
                    xgb_score_val = 0.5 + xgb_pred.probability * 0.5
                    xgb_reasons.append(f"ML bullish ({xgb_pred.probability:.1%})")
                elif xgb_pred.direction == "short":
                    xgb_score_val = 0.5 - xgb_pred.probability * 0.5
                    xgb_reasons.append(f"ML bearish ({xgb_pred.probability:.1%})")
                else:
                    xgb_reasons.append(f"ML neutral ({xgb_pred.probability:.1%})")
        except Exception:
            pass
        ensemble_result = ensemble_model.combine(
            micro_score, ict_score, momentum_score, regime_phase,
            micro_reasons, ict_reasons, momentum_reasons,
            xgboost_score=xgb_score_val, xgboost_reasons=xgb_reasons,
        )

        # ── Blend Agent + Ensemble (60% agent, 40% ensemble) ──
        agent_has_signal = agent_result.get('signal') in ('LONG', 'SHORT')
        ensemble_direction = ensemble_result.direction
        ensemble_confidence = ensemble_result.confidence

        if agent_has_signal:
            agent_long = 1.0 if agent_result['signal'] == 'LONG' else 0.0
            agent_conf = agent_result['confidence']
        else:
            agent_long = 1.0 if long_score >= short_score else 0.0
            agent_conf = max(long_score, short_score)

        # Ensemble score: map direction + confidence to [0, 1]
        ensemble_long_score = 0.5 + (ensemble_confidence * 0.5 if ensemble_direction == 'long' else -ensemble_confidence * 0.5)

        # Final blend
        blended_long = agent_long * 0.6 + ensemble_long_score * 0.4
        blended_confidence = agent_conf * 0.6 + ensemble_confidence * 0.4

        # Apply signal quality multiplier from self-optimizer's historical learning
        if hasattr(self_optimizer, 'score_signal'):
            quality_mult = self_optimizer.score_signal(
                'long' if blended_long >= 0.5 else 'short',
                regime_phase,
                blended_confidence,
            )
            blended_confidence *= quality_mult
            if quality_mult < 0.9 or quality_mult > 1.1:
                logger.info("Signal quality mult=%.2f for regime=%s", quality_mult, regime_phase)

        if agent_has_signal:
            winning_side = agent_result['signal'].lower()
            winning_score = blended_confidence
            winning_reasons = [r for r in agent_result.get('reason', '').split(' | ') if r]
            winning_reasons.extend(ensemble_result.reasons[:3])
            edge = abs(agent_result.get('long_score', 0) - agent_result.get('short_score', 0))
        else:
            winning_side = "long" if blended_long >= 0.5 else "short"
            winning_score = blended_confidence
            losing_score = 1.0 - blended_confidence
            winning_reasons = long_reasons if winning_side == "long" else short_reasons
            winning_reasons.extend(ensemble_result.reasons[:3])
            edge = abs(blended_long - 0.5) * 2

        # ── SL Breach Cooldown ──────────────────────────────────────────
        # After a previous signal's SL was hit, block new same-direction
        # signals for the cooldown period to avoid re-entering a losing setup.
        sl_blocker = ""
        if self._last_sl_side == winning_side and self._sl_cooldown_active(now_ms, winning_side, self._sl_breached_at_ms):
            remaining = (self._sl_cooldown_ms - (now_ms - self._sl_breached_at_ms)) // 60000
            sl_blocker = f"SL breach cooldown: {remaining}m remaining for {winning_side}"

        quality_blockers = self._signal_quality_blockers(
            ordered, winning_side, winning_score, 1.0 - winning_score if agent_has_signal else (short_score if winning_side == "long" else long_score),
            regime, threshold, winning_reasons,
            adaptive_edge=trader_profile.edge_threshold(
                adaptive_params.get('min_edge', settings.scalp_min_directional_edge),
                ordered[-1].timestamp,
            ),
        )
        quality_blockers.extend(trader_profile.signal_blockers(None, ordered[-1]))
        if sl_blocker:
            quality_blockers.append(sl_blocker)

        if quality_blockers:
            paper_signals: list[ScalpSignal] = []
            if (
                settings.paper_exploration_enabled
                and winning_score >= settings.paper_exploration_min_score
                and not sl_blocker
            ):
                agent_memory = get_agent().memory if hasattr(get_agent(), 'memory') else None
                win_rate = (
                    agent_memory.winning_trades / agent_memory.total_trades
                    if agent_memory and agent_memory.total_trades > 0 else 0.5
                )
                adaptive_sltp = self._regime_adaptive_sltp(price, atr, winning_score, regime)
                kelly = self._kelly_position_size(win_rate, winning_score, 2.0)
                last_candle = ordered[-1]
                paper_reason = [
                    "PAPER_EXPLORATION_ONLY",
                    *winning_reasons[:6],
                    "Live blockers: " + "; ".join(quality_blockers[:4]),
                ]
                paper_sig = self._build_signal(
                    f"{winning_side.upper()} BTCUSD",
                    price,
                    atr,
                    winning_score,
                    paper_reason,
                    now_ms,
                    funding_rate,
                    enriched_features=agent_result.get('enriched_features') if agent_has_signal else None,
                    candle=last_candle,
                    regime=regime,
                    adaptive_sltp=adaptive_sltp,
                    kelly=kelly,
                )
                if paper_sig:
                    paper_sig.status = "paper"
                    paper_sig.model = "unified-scalp-paper-exploration"
                    paper_signals.append(paper_sig)
            ctx = ScalpContext(
                timestamp=now_ms,
                order_flow=order_flow,
                funding=funding,
                funding_rate=funding_rate,
                open_interest=oi,
                liquidation_levels=liq_levels,
                vwap=vwap,
                volume_profile=vol_profile,
                liquidity_sweeps=sweeps,
                wick_rejection=wick,
                signals=paper_signals,
                rsi_3=round(rsi_3, 2),
                spot_volume_ok=True,
                macro_event_block=False,
                trade_blocked_reasons=quality_blockers,
                common_sense_warnings=cs_advisory,
            )
            ctx.futures_leverage = settings.futures_leverage
            ctx.estimated_funding_cost_8h = round(funding_rate.current_rate * 3 * 100, 4) if funding_rate else 0.0
            ctx.ai_brain_active = True
            ctx.ai_intelligence = get_agent().get_agent_status()
            return ctx

        # Block signals in consolidation regime - no clear directional edge
        if regime and regime.phase == "consolidation":
            return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Blocked: consolidation regime - no directional edge"])

        # Block signals in range_bound — agent can override if confident
        range_override = False
        if regime and regime.phase == "range_bound":
            if agent_has_signal and agent_result.get('confidence', 0) > 0.65:
                range_override = True  # Agent overrides range block with high confidence
            else:
                range_high = regime.range_high or max(c.high for c in ordered[-20:])
                range_low = regime.range_low or min(c.low for c in ordered[-20:])
                range_mid = (range_high + range_low) / 2
                if winning_side == "long" and price > range_mid:
                    return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Blocked: long in range_bound above mid"])
                if winning_side == "short" and price < range_mid:
                    return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Blocked: short in range_bound below mid"])

        if settings.scalp_require_candle_confirmation and regime and regime.phase == "range_bound" and not range_override:
            last_candle = ordered[-1]
            candle_range = last_candle.high - last_candle.low
            is_range_candle = regime is not None and regime.phase == "range_bound"
            if candle_range > 0:
                close_position = (last_candle.close - last_candle.low) / candle_range
                if is_range_candle:
                    if winning_side == "long" and close_position >= 0.40:
                        return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Range: long needs discount close (<40%)"])
                    if winning_side == "short" and close_position <= 0.60:
                        return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Range: short needs premium close (>60%)"])
                else:
                    if winning_side == "long" and close_position < 0.60:
                        return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Weak bullish candle close"])
                    if winning_side == "short" and close_position > 0.40:
                        return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Weak bearish candle close"])

        if settings.scalp_require_mtf_alignment and regime and regime.phase == "trending":
            if regime.bias == "bullish" and winning_side == "short":
                return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Blocked: short signal in bullish trend"])
            if regime.bias == "bearish" and winning_side == "long":
                return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, ["Blocked: long signal in bearish trend"])

        cooldown_ts = ordered[-1].timestamp if self._use_candle_timestamp_for_cooldown else now_ms
        if cooldown_ts - self._last_signal_ts < self._signal_cooldown_ms:
            remaining = (self._signal_cooldown_ms - (cooldown_ts - self._last_signal_ts)) / 60000
            return self._blocked_ctx(now_ms, order_flow, funding, funding_rate, oi, liq_levels, vwap, vol_profile, sweeps, rsi_3, [f"Cooldown: {remaining:.1f}m until next signal"])

        # ── V4 Regime-Adaptive SL/TP & Kelly Position Sizing ────────────
        adaptive_sltp = self._regime_adaptive_sltp(price, atr, winning_score, regime)
        agent_memory = get_agent().memory if hasattr(get_agent(), 'memory') else None
        win_rate = (agent_memory.winning_trades / agent_memory.total_trades
                    if agent_memory and agent_memory.total_trades > 0 else 0.5)
        rr = 2.0  # placeholder RR — actual is computed in _build_signal after SL
        kelly = self._kelly_position_size(win_rate, winning_score, rr)

        # Build signal from either the agent's decision or fallback confluence
        last_candle = ordered[-1]
        if agent_has_signal:
            sig = self._build_signal(
                agent_result['signal'] + " BTCUSD", price, atr,
                agent_result['confidence'], winning_reasons, now_ms, funding_rate,
                enriched_features=agent_result.get('enriched_features'),
                candle=last_candle, regime=regime,
                adaptive_sltp=adaptive_sltp, kelly=kelly,
            )
            if sig:
                signals.append(sig)
                self._last_signal_ts = cooldown_ts
        else:
            if long_score >= threshold and long_score >= short_score:
                sig = self._build_signal("LONG BTCUSD", price, atr, long_score, long_reasons, now_ms, funding_rate, candle=last_candle, regime=regime, adaptive_sltp=adaptive_sltp, kelly=kelly)
                if sig:
                    signals.append(sig)
                    self._last_signal_ts = cooldown_ts
            elif short_score >= threshold and short_score > long_score:
                sig = self._build_signal("SHORT BTCUSD", price, atr, short_score, short_reasons, now_ms, funding_rate, candle=last_candle, regime=regime, adaptive_sltp=adaptive_sltp, kelly=kelly)
                if sig:
                    signals.append(sig)
                    self._last_signal_ts = cooldown_ts

        # Track last signal SL for breach detection on next cycle
        if signals and len(signals) > 0:
            sig = signals[-1]
            self._last_sl_level = sig.sl_level
            self._last_sl_side = "long" if "LONG" in sig.signal_type else "short"
            self._last_sl_signal_ts = cooldown_ts
            self._sl_breached = False
            self._sl_breached_at_ms = 0
            # Record prediction using the actual signal ID so paper trading
            # outcomes can be matched back to this prediction.
            from backend.analysis.model_tracker import model_tracker
            model_tracker.record_prediction(
                signal_id=sig.id,
                timeframe=timeframe,
                predicted_direction=self._last_sl_side,
                predicted_grade=sig.confidence,
                predicted_confidence=sig.score,
            )
            # Track decision in trading psychology for fatigue/calibration
            try:
                get_agent().trading_psychology.record_decision()
            except Exception:
                pass

        ctx = ScalpContext(
            timestamp=now_ms,
            order_flow=order_flow,
            funding=funding,
            funding_rate=funding_rate,
            open_interest=oi,
            liquidation_levels=liq_levels,
            vwap=vwap,
            volume_profile=vol_profile,
            liquidity_sweeps=sweeps,
            wick_rejection=wick,
            signals=signals,
            rsi_3=round(rsi_3, 2),
            spot_volume_ok=True,
            macro_event_block=False,
            trade_blocked_reasons=[],
            common_sense_warnings=cs_advisory,
        )
        ctx.futures_leverage = settings.futures_leverage
        ctx.estimated_funding_cost_8h = round(funding_rate.current_rate * 3 * 100, 4) if funding_rate else 0.0
        
        # Store AI brain status in context
        ctx.ai_brain_active = True
        ctx.ai_intelligence = get_agent().get_agent_status()
        
        return ctx

    def _blocked_ctx(self, now_ms, of, fund, fr, oi, liq, vwap, vp, sweeps, rsi_3, reasons, wick=None):
        cs_warn = getattr(self, '_cs_advisory', [])
        ctx = ScalpContext(
            timestamp=now_ms, order_flow=of, funding=fund, funding_rate=fr,
            open_interest=oi, liquidation_levels=liq, vwap=vwap, volume_profile=vp,
            liquidity_sweeps=sweeps, wick_rejection=wick, signals=[], rsi_3=round(rsi_3, 2),
            spot_volume_ok=True, macro_event_block=False, trade_blocked_reasons=reasons,
            common_sense_warnings=cs_warn,
        )
        ctx.futures_leverage = settings.futures_leverage
        ctx.estimated_funding_cost_8h = round(fr.current_rate * 3 * 100, 4) if fr else 0.0
        ctx.ai_brain_active = True
        ctx.ai_intelligence = get_agent().get_agent_status()
        return ctx

    # ── Data source computations ──

    def _order_flow(self, candles: list[Candle]) -> ScalpOrderFlow:
        deltas: list[float] = []
        for i in range(1, len(candles)):
            if candles[i].close >= candles[i].open:
                deltas.append(candles[i].volume)
            else:
                deltas.append(-candles[i].volume)
        cvd = sum(deltas)
        recent = deltas[-10:] if len(deltas) >= 10 else deltas
        slope = (sum(recent[-3:]) - sum(recent[:3])) / max(len(recent), 1)
        total = sum(abs(d) for d in deltas)
        vol_delta_ratio = abs(cvd) / total if total > 0 else 0.0
        buy_vol = sum(d for d in deltas if d > 0)
        sell_vol = abs(sum(d for d in deltas if d < 0))
        agg_total = buy_vol + sell_vol
        absorption = min(buy_vol, sell_vol) / agg_total if agg_total > 0 else 0.5
        last_delta = deltas[-1] if deltas else 0.0
        last_c = candles[-1]
        footprint = abs(last_delta) / last_c.volume if last_c.volume > 0 else 0.0
        return ScalpOrderFlow(
            timestamp=candles[-1].timestamp,
            delta=round(last_delta, 4), cvd=round(cvd, 4), cvd_slope=round(slope, 4),
            volume_delta_ratio=round(vol_delta_ratio, 4), absorption_ratio=round(absorption, 4),
            aggressive_buy_volume=round(buy_vol, 4), aggressive_sell_volume=round(sell_vol, 4),
            footprint_imbalance=round(footprint, 4),
        )

    def _funding(self, now_ms: int) -> ScalpFunding:
        rate = self._cur_funding
        proj = rate * 3.0
        extreme = abs(rate) > settings.scalp_funding_rate_extreme
        bias = "bearish" if rate > settings.scalp_funding_rate_extreme else (
            "bullish" if rate < -settings.scalp_funding_rate_extreme else "neutral"
        )
        return ScalpFunding(
            timestamp=now_ms, current_rate=round(rate, 6), projected_8h=round(proj, 6),
            annualized_rate=round(rate * 365 * 3, 4),
            next_reset_ms=self._next_funding_reset(now_ms),
            is_extreme=extreme, contrarian_bias=bias,
        )

    def _funding_rate(self, now_ms: int, fc: FuturesContext | dict | None = None) -> ScalpFundingRate:
        rate = self._context_value(fc, "funding_rate", self._cur_funding)
        annualized = rate * 365 * 3
        apr = annualized * 100
        predicted = rate * 3
        reset = self._next_funding_reset(now_ms)
        extreme = abs(rate) > 0.001
        bias = "bullish" if rate < -0.0005 else ("bearish" if rate > 0.0005 else "neutral")
        return ScalpFundingRate(
            timestamp=now_ms, current_rate=round(rate, 6), annualized=round(annualized, 6),
            funding_apr=round(apr, 4), predicted_8h=round(predicted, 6),
            time_to_next=max(0, reset - now_ms), is_extreme=extreme, bias=bias,
        )

    def _open_interest(self, fc: FuturesContext | dict | None = None) -> ScalpOpenInterest:
        oi_from_context = self._context_value(fc, "oi_value", 0.0)
        if oi_from_context > 0:
            self._cur_oi = oi_from_context
        if len(self._oi_hist) < 2:
            return ScalpOpenInterest(timestamp=int(time.time() * 1000))
        cur = self._cur_oi
        prev = self._oi_hist[-2][1]
        change_pct = ((cur - prev) / prev * 100) if prev > 0 else 0.0
        hist = list(self._oi_hist)
        if len(hist) >= 10:
            older = sum(r[1] for r in hist[-10:-5]) / 5
            newer = sum(r[1] for r in hist[-5:]) / 5
            trend = "increasing" if newer > older * 1.02 else ("decreasing" if newer < older * 0.98 else "neutral")
        else:
            trend = "neutral"
        momentum = change_pct > 1.0 and trend == "increasing"
        return ScalpOpenInterest(
            timestamp=int(time.time() * 1000), current_oi=round(cur, 2),
            oi_change_pct=round(change_pct, 4), oi_delta=round(cur - prev, 2),
            oi_trend=trend, momentum_confirmation=momentum,
        )

    def _liquidation_levels(self, price: float, fc: FuturesContext | dict | None = None) -> list[ScalpLiquidationLevel]:
        clusters = self._context_value(fc, "liquidation_clusters", [])
        if clusters:
            out: list[ScalpLiquidationLevel] = []
            for e in clusters:
                p = e.get("price", 0)
                s = e.get("size", 0)
                side = e.get("side", "long")
                d = abs(p - price) / price * 100
                cs = e.get("strength", _clamp(s / 1_000_000, 0, 1))
                out.append(ScalpLiquidationLevel(price=p, size=s, side=side, distance_pct=round(d, 3), cluster_strength=cs))
            return sorted(out, key=lambda x: x.distance_pct)[:10]
        out = []
        for pct in [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]:
            out.append(ScalpLiquidationLevel(price=round(price * (1 - pct / 100), 2), size=round(500_000 / pct, 0), side="long", distance_pct=pct, cluster_strength=round(1.0 - pct / 10, 3)))
            out.append(ScalpLiquidationLevel(price=round(price * (1 + pct / 100), 2), size=round(500_000 / pct, 0), side="short", distance_pct=pct, cluster_strength=round(1.0 - pct / 10, 3)))
        return sorted(out, key=lambda x: x.distance_pct)[:10]

    def _vwap(self, candles: list[Candle]) -> ScalpVWAP:
        cv = 0.0
        cvp = 0.0
        cvpd = 0.0
        for c in candles:
            tp = (c.high + c.low + c.close) / 3.0
            cv += c.volume
            cvp += tp * c.volume
            if cv > 0:
                cvpd += (tp - cvp / cv) ** 2 * c.volume
        vwap = cvp / cv if cv > 0 else candles[-1].close
        std = math.sqrt(cvpd / cv) if cv > 0 else 0
        price = candles[-1].close
        dev = ((price - vwap) / vwap * 100) if vwap > 0 else 0
        return ScalpVWAP(
            timestamp=candles[-1].timestamp, vwap=round(vwap, 2),
            upper_band_1sd=round(vwap + std, 2), lower_band_1sd=round(vwap - std, 2),
            upper_band_2sd=round(vwap + 2 * std, 2), lower_band_2sd=round(vwap - 2 * std, 2),
            price_deviation_pct=round(dev, 4), is_compressed=abs(dev) < 2.0,
        )

    def _volume_profile(self, candles: list[Candle]) -> ScalpVolumeProfile:
        recent = candles[-80:]
        hi = max(c.high for c in recent)
        lo = min(c.low for c in recent)
        bins_n = 24
        bs = (hi - lo) / bins_n if hi > lo else 1.0
        bins = [0.0] * bins_n
        for c in recent:
            tp = (c.high + c.low + c.close) / 3.0
            idx = _clamp(int((tp - lo) / bs), 0, bins_n - 1)
            bins[idx] += c.volume
        tv = sum(bins)
        poc_i = bins.index(max(bins))
        poc = lo + (poc_i + 0.5) * bs
        cum = 0.0
        vah = poc
        for i in range(poc_i, bins_n):
            cum += bins[i]
            if cum >= tv * 0.35:
                vah = lo + (i + 0.5) * bs
                break
        cum = 0.0
        val = poc
        for i in range(poc_i, -1, -1):
            cum += bins[i]
            if cum >= tv * 0.35:
                val = lo + (i + 0.5) * bs
                break
        return ScalpVolumeProfile(
            timestamp=candles[-1].timestamp, poc=round(poc, 2),
            vah=round(vah, 2), val=round(val, 2),
            value_area_width_pct=round(((vah - val) / poc * 100) if poc > 0 else 0, 4),
        )

    def _wick_rejection(self, candles: list[Candle]) -> ScalpWickRejection:
        return analyze_wick_rejection(candles)

    def _liquidity_sweeps(self, candles: list[Candle]) -> list[ScalpLiquiditySweep]:
        if len(candles) < 20:
            return []
        recent = candles[-50:]
        highs = sorted([c.high for c in recent], reverse=True)[:3]
        lows = sorted([c.low for c in recent])[:3]
        cur = candles[-1]
        sweeps: list[ScalpLiquiditySweep] = []
        for lv in highs:
            if cur.high >= lv and cur.close < lv:
                d = abs(cur.close - lv) / lv
                sweeps.append(ScalpLiquiditySweep(timestamp=cur.timestamp, level=lv, side="short", sweep_type="resistance_sweep", reclaimed=True, strength=_clamp(1.0 - d * 100, 0, 1), entry_trigger=cur.close < lv * 0.999))
        for lv in lows:
            if cur.low <= lv and cur.close > lv:
                d = abs(cur.close - lv) / lv
                sweeps.append(ScalpLiquiditySweep(timestamp=cur.timestamp, level=lv, side="long", sweep_type="support_sweep", reclaimed=True, strength=_clamp(1.0 - d * 100, 0, 1), entry_trigger=cur.close > lv * 1.001))
        return sorted(sweeps, key=lambda s: s.strength, reverse=True)[:5]

    def _next_funding_reset(self, now_ms: int) -> int:
        from datetime import timedelta
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        for h in [0, 8, 16]:
            r = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if r > now:
                return int(r.timestamp() * 1000)
        nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return int(nxt.timestamp() * 1000)

    # ── Trade filters ──

    def _filters(self, candles: list[Candle], funding: ScalpFunding, fr: ScalpFundingRate, fc: FuturesContext | dict | None = None) -> list[str]:
        blockers: list[str] = []
        if funding.is_extreme and abs(funding.current_rate) > 0.002:
            blockers.append(f"Funding extreme: {funding.current_rate * 100:.3f}%")
        if self._spot_vol_avg > 0:
            avg_vol = sum(c.volume for c in candles[-20:]) / 20
            if avg_vol < self._spot_vol_avg * settings.scalp_min_spot_volume_ratio * 0.8:
                blockers.append("Spot volume below 30-day average")
        return blockers

    def _common_sense_blockers(
        self, candles: list[Candle], price: float, atr: float, now_ms: int, timeframe: str,
    ) -> list[str]:
        """Common-sense market sanity checks every human trader would follow."""
        blockers: list[str] = []

        # 0. Multi-Exchange Price Deviation Check
        # If the primary data source price deviates significantly from the
        # volume-weighted median of multiple exchanges, the data may be stale
        # or anomalous — block trading until they converge.
        if self._last_aggregated_price is not None and self._last_aggregated_price > 0:
            deviation = abs(price - self._last_aggregated_price) / self._last_aggregated_price
            if deviation > 0.005:
                blockers.append(
                    f"Price deviation: {deviation*100:.3f}% from {self._last_exchange_count}-exchange "
                    f"aggregate (${self._last_aggregated_price:.2f}) — possible data anomaly"
                )
            if self._last_aggregated_spread_pct > 0.01:
                blockers.append(
                    f"Cross-exchange spread {self._last_aggregated_spread_pct*100:.3f}% "
                    f"— exchanges disagree on price"
                )

        # 1. ATR Spike Guard — volatility explosion / flash crash protection
        if len(candles) >= 60:
            atr_values = []
            for i in range(14, len(candles)):
                c = candles[i]
                p = candles[i - 1]
                tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
                atr_values.append(tr)
            median_atr = sorted(atr_values)[len(atr_values) // 2] if atr_values else atr
            if median_atr > 0 and atr > median_atr * 3.0:
                blockers.append(f"ATR spike: {atr:.2f} vs median {median_atr:.2f} ({atr/median_atr:.1f}x) — abnormal volatility")

        # 2. Stale Data Guard — feed failure detection
        interval_seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
        expected_interval = interval_seconds.get(timeframe, 300) * 1000
        latest_ts = candles[-1].timestamp if candles else now_ms
        if now_ms - latest_ts > expected_interval * 3:
            mins_stale = (now_ms - latest_ts) / 60000
            blockers.append(f"Stale data: last candle {mins_stale:.0f}m ago ({timeframe})")

        # 3. Price Spike Guard — flash crash / data error protection
        if len(candles) >= 3:
            prev_close = candles[-2].close
            change_pct = abs(price - prev_close) / prev_close * 100 if prev_close > 0 else 0
            if change_pct > 3.0:
                blockers.append(f"Price spike: {change_pct:.1f}% move in last candle — possible data anomaly")
            elif change_pct > 1.5:
                blockers.append(f"Large move: {change_pct:.1f}% in last candle — waiting for stabilization")

        # 4. Low Volume Hours — thin market protection
        dt = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        hour = dt.hour
        weekday = dt.weekday()
        is_weekend = weekday >= 5
        if is_weekend:
            blockers.append("Weekend — reduced liquidity")
        elif hour < 2 or hour >= 23:
            blockers.append(f"Low-volume hours ({hour:02d}:00 UTC) — waiting for liquidity")
        elif hour < 7:
            recent_vol = sum(c.volume for c in candles[-5:]) / max(len(candles[-5:]), 1)
            base_vol = sum(c.volume for c in candles[-50:-5]) / max(len(candles[-50:-5]), 1)
            if base_vol > 0 and recent_vol < base_vol * 0.4:
                blockers.append(f"Asian session low volume: {recent_vol/base_vol:.0%} of normal")

        # 5. Consecutive Candle Direction — trend exhaustion detection
        if len(candles) >= 8:
            same_dir = 0
            for i in range(1, min(9, len(candles))):
                c = candles[-i]
                if c.close > c.open:
                    same_dir = same_dir + 1 if same_dir >= 0 else 1
                else:
                    same_dir = same_dir - 1 if same_dir <= 0 else -1
            if same_dir >= 6:
                blockers.append(f"{same_dir} consecutive bullish candles — extended move, waiting for pullback")
            elif same_dir <= -6:
                blockers.append(f"{abs(same_dir)} consecutive bearish candles — extended move, waiting for bounce")

        # 6. Volume Collapse Guard
        if len(candles) >= 20:
            recent_v = sum(c.volume for c in candles[-3:]) / 3
            normal_v = sum(c.volume for c in candles[-20:-3]) / 17 if len(candles) >= 20 else recent_v
            if normal_v > 0 and recent_v < normal_v * 0.2:
                blockers.append(f"Volume collapse: {recent_v/normal_v:.0%} of normal — no conviction")

        # 7. Trading Psychology — behavioral bias warnings
        try:
            psych = get_agent().trading_psychology.get_state()
            for w in psych.warnings[:3]:
                blockers.append(w)
        except Exception:
            pass

        return blockers

    def _signal_quality_blockers(self, candles: list[Candle], side: str, winning_score: float, losing_score: float, regime: MarketRegime | None = None, adaptive_threshold: float | None = None, winning_reasons: list[str] | None = None, adaptive_edge: float | None = None) -> list[str]:
        blockers: list[str] = []
        closes = [c.close for c in candles]
        price = closes[-1]
        threshold = adaptive_threshold if adaptive_threshold is not None else settings.scalp_min_confluence_score
        edge = abs(winning_score - losing_score)
        # Use adaptive edge threshold if provided
        edge_threshold = adaptive_edge if adaptive_edge is not None else settings.scalp_min_directional_edge

        if winning_reasons is not None and len(winning_reasons) < 3:
            blockers.append(f"Only {len(winning_reasons)} data sources contributing (need 3+)")
            return blockers[:6]
        is_trending = regime is not None and regime.phase == "trending"
        is_consolidation = regime is not None and regime.phase == "consolidation"
        is_range_bound = regime is not None and regime.phase == "range_bound"
        if is_consolidation:
            min_edge = max(0.05, edge_threshold)
        elif is_range_bound:
            min_edge = max(0.04, edge_threshold)
        else:
            min_edge = max(0.03, edge_threshold)
        if edge < min_edge:
            blockers.append(f"Directional edge {edge:.2f} below {min_edge:.2f}")

        ema21 = _ema(closes[-100:], 21)
        ema50 = _ema(closes[-140:], 50)
        trend_strength = abs(ema21 - ema50) / price if price > 0 else 0.0

        if is_trending:
            if trend_strength < 0.0005:
                blockers.append(f"Trend strength {trend_strength:.4f} too weak for trending")
        else:
            if trend_strength < 0.0003:
                blockers.append(f"Trend strength {trend_strength:.4f} too flat")

        recent_volume = sum(c.volume for c in candles[-5:]) / min(len(candles), 5)
        base_window = candles[-50:-5] if len(candles) >= 55 else candles[:-5]
        base_volume = sum(c.volume for c in base_window) / len(base_window) if base_window else recent_volume
        volume_ratio = recent_volume / base_volume if base_volume > 0 else 1.0
        if is_trending:
            vol_threshold = 0.50
        elif is_consolidation:
            vol_threshold = 0.40
        else:
            vol_threshold = 0.45
        if volume_ratio < vol_threshold:
            blockers.append(f"Volume impulse {volume_ratio:.2f} below {vol_threshold:.2f}")

        rsi_current = _rsi(closes[-10:], 10) if len(closes) >= 11 else 50.0
        if is_range_bound:
            if side == "long" and rsi_current > 70:
                blockers.append(f"Range long: RSI {rsi_current:.0f} overbought")
            if side == "short" and rsi_current < 30:
                blockers.append(f"Range short: RSI {rsi_current:.0f} oversold")
        else:
            if side == "long" and rsi_current > 75:
                blockers.append(f"Long: RSI {rsi_current:.0f} overbought, wait for pullback")
            if side == "short" and rsi_current < 25:
                blockers.append(f"Short: RSI {rsi_current:.0f} oversold, wait for rally")

        return blockers[:6]

    # ── Confluence scoring ──

    def _confluence_long(self, price: float, of: ScalpOrderFlow, vwap: ScalpVWAP, oi: ScalpOpenInterest, funding: ScalpFunding, sweeps: list[ScalpLiquiditySweep], vp: ScalpVolumeProfile, rsi_3: float, kill_active: bool, kill_session: str, metrics: MarketMetrics | None, fvgs: list[FVG] | None, obs: list[OrderBlock] | None, regime: MarketRegime | None, candles: list[Candle], fc: FuturesContext | dict | None = None, wick: ScalpWickRejection | None = None) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        # 1. Order Flow (weight: 0.25)
        if of.delta > 0:
            score += 0.12; reasons.append("Delta positive")
        if of.cvd_slope > 0:
            score += 0.08; reasons.append("CVD rising")
        if of.footprint_imbalance > 0.6:
            score += 0.05; reasons.append("Footprint bullish")

        # 2. VWAP (weight: 0.12)
        if price > vwap.vwap:
            score += 0.07; reasons.append("Above VWAP")
        if price <= vwap.lower_band_1sd:
            score += 0.05; reasons.append("Near lower VWAP band")

        # 3. Open Interest (weight: 0.12) — INCREASED FROM 0.10
        if oi.momentum_confirmation:
            score += 0.07; reasons.append(f"OI spike +{oi.oi_change_pct:.1f}%")
        if oi.oi_trend == "increasing":
            score += 0.05; reasons.append("OI increasing")

        # 4. Funding Rate (weight: 0.10) — INCREASED FROM 0.08
        if funding.contrarian_bias == "bullish":
            score += 0.10; reasons.append("Funding contrarian bullish")

        # 5. Liquidity Sweeps (weight: 0.15)
        for s in sweeps:
            if s.side == "long" and s.entry_trigger and s.reclaimed:
                score += 0.15; reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break
            elif s.side == "long" and s.reclaimed:
                score += 0.08; reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break

        # 6. Volume Profile (weight: 0.07)
        if vp.poc > 0:
            dist_to_poc = abs(price - vp.poc) / vp.poc
            if dist_to_poc < 0.002:
                score += 0.04; reasons.append("At POC")
            if price <= vp.val:
                score += 0.03; reasons.append("Below VAL — discount zone")

        # 7. RSI(3) exhaustion (weight: 0.07)
        if 25 <= rsi_3 <= 45:
            score += 0.05; reasons.append(f"RSI(3) {rsi_3:.0f} recovery zone")
        elif rsi_3 < 20:
            score -= 0.05; reasons.append(f"RSI(3) {rsi_3:.0f} extreme — wait")
        elif rsi_3 < 30:
            score += 0.03; reasons.append(f"RSI(3) {rsi_3:.0f} oversold bounce")

        # 8. Killzone (weight: 0.05)
        if kill_active:
            score += 0.05; reasons.append(f"Killzone: {kill_session}")

        # 9. ICT FVG proximity (weight: 0.05)
        if fvgs and regime:
            if regime.phase == "trending":
                if regime.bias == "bullish":
                    active = [f for f in fvgs if not f.is_filled and f.direction == "bullish"]
                    for f in active:
                        if abs(price - f.bottom) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bullish FVG")
                            break
                elif regime.bias == "bearish":
                    active = [f for f in fvgs if not f.is_filled and f.direction == "bearish"]
                    for f in active:
                        if abs(price - f.top) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bearish FVG")
                            break
            else:
                active = [f for f in fvgs if not f.is_filled and f.direction == "bullish"]
                for f in active:
                    if abs(price - f.bottom) / price < 0.003:
                        score += 0.03; reasons.append("Near bullish FVG (range)")
                        break

        # 10. Order Block proximity (weight: 0.05)
        if obs and regime:
            if regime.phase == "trending":
                if regime.bias == "bullish":
                    active = [o for o in obs if not o.is_breaker and o.direction == "bullish"]
                    for o in active:
                        if abs(price - o.top) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bullish OB")
                            break
                elif regime.bias == "bearish":
                    active = [o for o in obs if not o.is_breaker and o.direction == "bearish"]
                    for o in active:
                        if abs(price - o.bottom) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bearish OB")
                            break
            else:
                active = [o for o in obs if not o.is_breaker and o.direction == "bullish"]
                for o in active:
                    if abs(price - o.top) / price < 0.003:
                        score += 0.03; reasons.append("Near bullish OB (range)")
                        break

        # 11. Regime (weight: 0.05)
        if regime:
            if regime.phase == "trending" and regime.bias == "bullish":
                score += 0.05; reasons.append("Trending bullish regime")
            elif regime.phase == "accumulation":
                score += 0.04; reasons.append("Accumulation regime")
            elif regime.phase == "range_bound" and price <= vp.val:
                score += 0.03; reasons.append("Range bound — buying value low")

        # 12. Market metrics trend (weight: 0.03)
        if metrics and metrics.trend_score > 0.15:
            score += 0.03; reasons.append("Trend score bullish")

        # 13. Futures funding bias (weight: 0.06) — REPLACED options momentum
        fc_bias = self._context_value(fc, "funding_contrarian_bias", "neutral")
        if fc_bias == "bullish" and self._cur_funding == 0.0:
            score += 0.06; reasons.append("Futures funding bullish contrarian")

        # 14. Futures OI momentum (weight: 0.04) — REPLACED options contract
        fc_oi_mom = self._context_value(fc, "oi_momentum_confirmation", False)
        if fc_oi_mom:
            score += 0.04; reasons.append("OI confirms bullish momentum")

        # 15. Wick Rejection (weight: 0.08)
        # Long lower wick = price rejected at low → bullish move expected
        if wick and wick.bullish_rejection_active:
            wick_score = abs(wick.rejection_strength) * 0.08
            score += wick_score
            reasons.append(f"Long lower wick: {wick.description}")

        return _clamp(score, 0, 1), reasons

    def _confluence_short(self, price: float, of: ScalpOrderFlow, vwap: ScalpVWAP, oi: ScalpOpenInterest, funding: ScalpFunding, sweeps: list[ScalpLiquiditySweep], vp: ScalpVolumeProfile, rsi_3: float, kill_active: bool, kill_session: str, metrics: MarketMetrics | None, fvgs: list[FVG] | None, obs: list[OrderBlock] | None, regime: MarketRegime | None, candles: list[Candle], fc: FuturesContext | dict | None = None, wick: ScalpWickRejection | None = None) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        # 1. Order Flow (weight: 0.25)
        if of.delta < 0:
            score += 0.12; reasons.append("Delta negative")
        if of.cvd_slope < 0:
            score += 0.08; reasons.append("CVD falling")
        if of.footprint_imbalance > 0.6:
            score += 0.05; reasons.append("Footprint bearish")

        # 2. VWAP (weight: 0.12)
        if price < vwap.vwap:
            score += 0.07; reasons.append("Below VWAP")
        if price >= vwap.upper_band_1sd:
            score += 0.05; reasons.append("Near upper VWAP band")

        # 3. Open Interest (weight: 0.12)
        if oi.momentum_confirmation and oi.oi_trend == "increasing":
            score += 0.07; reasons.append(f"OI spike confirms bearish +{oi.oi_change_pct:.1f}%")
        if oi.oi_trend == "decreasing":
            score += 0.05; reasons.append("OI decreasing")

        # 4. Funding Rate (weight: 0.10)
        if funding.contrarian_bias == "bearish":
            score += 0.10; reasons.append("Funding contrarian bearish")

        # 5. Liquidity Sweeps (weight: 0.15)
        for s in sweeps:
            if s.side == "short" and s.entry_trigger and s.reclaimed:
                score += 0.15; reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break
            elif s.side == "short" and s.reclaimed:
                score += 0.08; reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break

        # 6. Volume Profile (weight: 0.07)
        if vp.poc > 0:
            if price >= vp.vah:
                score += 0.04; reasons.append("Above VAH — premium zone")
            dist_to_poc = abs(price - vp.poc) / vp.poc
            if dist_to_poc < 0.002:
                score += 0.03; reasons.append("At POC rejection")

        # 7. RSI(3) exhaustion (weight: 0.07)
        if 55 <= rsi_3 <= 75:
            score += 0.05; reasons.append(f"RSI(3) {rsi_3:.0f} rejection zone")
        elif rsi_3 > 80:
            score -= 0.05; reasons.append(f"RSI(3) {rsi_3:.0f} extreme — wait")

        # 8. Killzone (weight: 0.05)
        if kill_active:
            score += 0.05; reasons.append(f"Killzone: {kill_session}")

        # 9. ICT FVG proximity (weight: 0.05)
        if fvgs and regime:
            if regime.phase == "trending":
                if regime.bias == "bearish":
                    active = [f for f in fvgs if not f.is_filled and f.direction == "bearish"]
                    for f in active:
                        if abs(price - f.top) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bearish FVG")
                            break
                elif regime.bias == "bullish":
                    active = [f for f in fvgs if not f.is_filled and f.direction == "bullish"]
                    for f in active:
                        if abs(price - f.bottom) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bullish FVG")
                            break
            else:
                active = [f for f in fvgs if not f.is_filled and f.direction == "bearish"]
                for f in active:
                    if abs(price - f.top) / price < 0.003:
                        score += 0.03; reasons.append("Near bearish FVG (range)")
                        break

        # 10. Order Block proximity (weight: 0.05)
        if obs and regime:
            if regime.phase == "trending":
                if regime.bias == "bearish":
                    active = [o for o in obs if not o.is_breaker and o.direction == "bearish"]
                    for o in active:
                        if abs(price - o.bottom) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bearish OB")
                            break
                elif regime.bias == "bullish":
                    active = [o for o in obs if not o.is_breaker and o.direction == "bullish"]
                    for o in active:
                        if abs(price - o.top) / price < 0.003:
                            score += 0.05; reasons.append("Pullback into bullish OB")
                            break
            else:
                active = [o for o in obs if not o.is_breaker and o.direction == "bearish"]
                for o in active:
                    if abs(price - o.bottom) / price < 0.003:
                        score += 0.03; reasons.append("Near bearish OB (range)")
                        break

        # 11. Regime (weight: 0.05)
        if regime:
            if regime.phase == "trending" and regime.bias == "bearish":
                score += 0.05; reasons.append("Trending bearish regime")
            elif regime.phase == "distribution":
                score += 0.04; reasons.append("Distribution regime")
            elif regime.phase == "range_bound" and price >= vp.vah:
                score += 0.03; reasons.append("Range bound — selling at value high")

        # 12. Market metrics trend (weight: 0.03)
        if metrics and metrics.trend_score < -0.15:
            score += 0.03; reasons.append("Trend score bearish")

        # 13. Futures funding bias (weight: 0.06)
        fc_bias = self._context_value(fc, "funding_contrarian_bias", "neutral")
        if fc_bias == "bearish" and self._cur_funding == 0.0:
            score += 0.06; reasons.append("Futures funding bearish contrarian")

        # 14. Futures OI momentum (weight: 0.04)
        fc_oi_mom = self._context_value(fc, "oi_momentum_confirmation", False)
        if fc_oi_mom:
            score += 0.04; reasons.append("OI confirms bearish momentum")

        # 15. Wick Rejection (weight: 0.08)
        # Long upper wick = price rejected at high → bearish move expected
        if wick and wick.bearish_rejection_active:
            wick_score = abs(wick.rejection_strength) * 0.08
            score += wick_score
            reasons.append(f"Long upper wick: {wick.description}")

        return _clamp(score, 0, 1), reasons

    # ── Filter: Only trade with regime direction ──
    def _regime_direction_filter(self, candles: list[Candle], side: str, regime: MarketRegime | None) -> str | None:
        """Only allow trades that align with regime bias."""
        if regime is None:
            return "No regime detected"
        
        if regime.phase != "trending":
            return f"Non-trending regime: {regime.phase}"
        
        if regime.bias == "bullish" and side == "sell":
            return "Bearish trade in bullish regime"
        if regime.bias == "bearish" and side == "buy":
            return "Bullish trade in bearish regime"
        
        return None  # Passes filter

    def _build_signal(self, signal_type: str, price: float, atr: float, score: float, reasons: list[str], now_ms: int, fr: ScalpFundingRate | None = None, enriched_features: dict | None = None, candle: Candle | None = None, regime: MarketRegime | None = None, adaptive_sltp: dict | None = None, kelly: dict | None = None) -> ScalpSignal | None:
        is_long = "LONG" in signal_type
        if score <= 0:
            return None

        # Use V5 adaptive SL/TP from AdaptiveSLTPEngine (volatility quantile)
        try:
            from backend.analysis.adaptive_sltp import adaptive_sltp as asltp
            candles_for_adaptive = getattr(self, '_last_adaptive_candles', None)
            if not candles_for_adaptive:
                candles_for_adaptive = getattr(self, '_last_candles', [])
            if candles_for_adaptive:
                liq_levels = [lvl.price for lvl in getattr(self, '_last_liq_levels', [])] if hasattr(self, '_last_liq_levels') else None
                asltp_result = asltp.compute(
                    candles=candles_for_adaptive,
                    side="long" if is_long else "short",
                    entry_price=price,
                    confidence=score,
                    regime=regime,
                    liquidity_levels=liq_levels,
                )
                sl_mult = asltp_result.sl_atr_multiple
                tp1_mult = asltp_result.tp_atr_multiple
                tp2_mult = asltp_result.tp_atr_multiple * 1.5
                reasons.append(asltp_result.description)
            else:
                sl_mult = max(2.0, 4.0 - score * 2)
                tp1_mult = 3.0 + score * 3
                tp2_mult = 5.0 + score * 6
        except Exception:
            # Fallback to V4 adaptive SL/TP
            if adaptive_sltp:
                sl_mult = adaptive_sltp.get("sl_mult", 2.0)
                tp1_mult = adaptive_sltp.get("tp1_mult", 3.0)
                tp2_mult = adaptive_sltp.get("tp2_mult", 5.0)
                if adaptive_sltp.get("reason") and adaptive_sltp["reason"] != "default":
                    reasons.append(f"Adaptive SL/TP: {adaptive_sltp['reason']}")
            else:
                sl_mult = max(2.0, 4.0 - score * 2)
                tp1_mult = 3.0 + score * 3
                tp2_mult = 5.0 + score * 6

        # V4 Kelly position sizing
        if kelly:
            kelly_boost = kelly.get("leverage_boost", 1.0)
            reasons.append(f"Kelly: {kelly.get('conservative_pct', 0)}% at risk")
        else:
            kelly_boost = 1.0

        # ── FIX: Entry at retracement level, NOT at candle close ──────────────
        # Root cause: signal fires after candle closes, but entering at close
        # means buying at the top of a completed move (or selling at the bottom).
        # The market then reverses because the move is already exhausted.
        #
        # Fix: Position entry zone so price must retrace INTO the candle body.
        # For longs: entry below close (into lower body or wick).
        # For shorts: entry above close (into upper body or wick).
        if candle:
            candle_range = candle.high - candle.low
            if is_long:
                # LONG: enter on pullback into the candle body (below close)
                # Use the candle's lower half as entry zone
                zone_mid = min(price, candle.open + candle_range * 0.3)
                zone_buffer = atr * 0.05
                entry = zone_mid
                entry_zone_low = round(candle.low, 2)
                entry_zone_high = round(max(zone_mid + zone_buffer, candle.open), 2)
                # Prevent zone from being above close (never buy at candle top)
                entry_zone_high = min(entry_zone_high, round(price * 0.9995, 2))
            else:
                # SHORT: enter on bounce into the candle body (above close)
                # Use the candle's upper half as entry zone
                zone_mid = max(price, candle.close - candle_range * 0.3)
                zone_buffer = atr * 0.05
                entry = zone_mid
                entry_zone_low = round(min(zone_mid - zone_buffer, candle.close), 2)
                entry_zone_high = round(candle.high, 2)
                # Prevent zone from being below close (never sell at candle bottom)
                entry_zone_low = max(entry_zone_low, round(price * 1.0005, 2))
        else:
            # Fallback if no candle provided
            entry = price
            entry_dist = atr * 0.1
            entry_zone_low = round(entry - entry_dist, 2)
            entry_zone_high = round(entry + entry_dist, 2)

        sl_dist = atr * sl_mult
        t2_dist = atr * tp2_mult
        t1_dist = atr * tp1_mult
        
        sl = entry - sl_dist if is_long else entry + sl_dist
        t1 = entry + t1_dist if is_long else entry - t1_dist
        t2 = entry + t2_dist if is_long else entry - t2_dist
        
        rr = round(abs(t2 - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0.0
        
        base_leverage = max(3, int(10 * score * kelly_boost))
        leverage = min(settings.scalp_max_leverage, base_leverage + 5)
        
        confidence = "HIGH" if score >= 0.65 else ("MEDIUM" if score >= 0.50 else "LOW")
        time_limit = now_ms + settings.scalp_max_hold_minutes * 60 * 1000
        funding_impact = (fr.current_rate * 3 * 100) if fr else 0.0
        if funding_impact != 0:
            reasons.append(f"Funding: {funding_impact:.3f}% per 8h")

        from backend.analysis.ids import stable_id
        signal = ScalpSignal(
            id=stable_id("scalp", "long" if is_long else "short", now_ms, int(entry * 10), int(sl * 10)),
            timestamp=now_ms, signal_type=signal_type,
            entry_zone_low=entry_zone_low, entry_zone_high=entry_zone_high,
            sl_level=round(sl, 2), target_1=round(t1, 2), target_2=round(t2, 2),
            leverage=leverage, reason=" | ".join(reasons), score=round(score, 4), risk_reward=round(rr, 2),
            confidence=confidence, time_limit_ms=time_limit,
            max_hold_minutes=settings.scalp_max_hold_minutes,
            partial_exit_pct=settings.scalp_partial_exit_pct,
            funding_impact_pct=round(funding_impact, 4),
        )
        if enriched_features:
            signal.enriched_features = enriched_features
        return signal

    def _context_value(self, source: Any, key: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)

    # ═══════════════════════════════════════════════════════════
    # V4 NEW ANALYSIS METHODS
    # ═══════════════════════════════════════════════════════════

    def _market_structure(self, candles: list[Candle], swings: list[Swing] | None) -> dict:
        """Detect Break of Structure (BoS) and Market Structure Shift (MSS)."""
        result: dict = {"bos": None, "mss": None, "structure": "neutral", "strength": 0.0}
        if len(candles) < 20:
            return result
        highs = [c.high for c in candles[-40:]]
        lows = [c.low for c in candles[-40:]]
        if len(highs) < 5:
            return result
        recent_high = max(highs[-5:])
        recent_low = min(lows[-5:])
        prev_high = max(highs[-10:-5]) if len(highs) >= 10 else recent_high
        prev_low = min(lows[-10:-5]) if len(lows) >= 10 else recent_low
        last_c = candles[-1]
        # Bullish BoS: price breaks above prior swing high
        if last_c.close > prev_high > recent_low:
            result["bos"] = "bullish"
            result["strength"] = (last_c.close - prev_high) / prev_high * 100
            result["structure"] = "uptrend"
        # Bearish BoS: price breaks below prior swing low
        elif last_c.close < prev_low < recent_high:
            result["bos"] = "bearish"
            result["strength"] = (prev_low - last_c.close) / prev_low * 100
            result["structure"] = "downtrend"
        # MSS: failed breakout that reverses — higher low then breaks structure
        if len(highs) >= 15:
            mid_high = max(highs[-15:-5]) if len(highs) >= 15 else recent_high
            mid_low = min(lows[-15:-5]) if len(lows) >= 15 else recent_low
            if prev_low < mid_low and last_c.close > mid_high and result["bos"] != "bearish":
                result["mss"] = "bullish_shift"
                result["strength"] = max(result["strength"], (last_c.close - mid_high) / mid_high * 100)
                result["structure"] = "uptrend"
            elif prev_high > mid_high and last_c.close < mid_low and result["bos"] != "bullish":
                result["mss"] = "bearish_shift"
                result["strength"] = max(result["strength"], (mid_low - last_c.close) / mid_low * 100)
                result["structure"] = "downtrend"
        if swings and len(swings) >= 2:
            last_swing = swings[-1]
            prev_swing = swings[-2]
            if last_swing.kind == "high" and last_swing.price > prev_swing.price:
                result["bos"] = "bullish"
                result["structure"] = "uptrend"
            elif last_swing.kind == "low" and last_swing.price < prev_swing.price:
                result["bos"] = "bearish"
                result["structure"] = "downtrend"
        return result

    def _divergence(self, candles: list[Candle]) -> dict:
        """Detect regular and hidden RSI/Price divergence."""
        result: dict = {"type": None, "strength": 0.0, "description": ""}
        if len(candles) < 30:
            return result
        closes = [c.close for c in candles]
        rsi14 = _rsi(closes[-30:], 14)
        high_idx = max(1, len(closes) - 20)
        prices = closes[-20:]
        rsis = [_rsi(closes[:high_idx + i], 14) for i in range(20)] if len(closes) >= 34 else []
        if len(rsis) < 10:
            return result
        price_swing_highs = []
        price_swing_lows = []
        rsi_swing_highs = []
        rsi_swing_lows = []
        for i in range(2, len(prices) - 2):
            if prices[i] > prices[i-1] and prices[i] > prices[i-2] and prices[i] > prices[i+1] and prices[i] > prices[i+2]:
                price_swing_highs.append((i, prices[i]))
            if prices[i] < prices[i-1] and prices[i] < prices[i-2] and prices[i] < prices[i+1] and prices[i] < prices[i+2]:
                price_swing_lows.append((i, prices[i]))
            if i < len(rsis) and rsis[i] > rsis[i-1] and rsis[i] > rsis[i-2] and rsis[i] > rsis[i+1] and rsis[i] > rsis[i+2]:
                rsi_swing_highs.append((i, rsis[i]))
            if i < len(rsis) and rsis[i] < rsis[i-1] and rsis[i] < rsis[i-2] and rsis[i] < rsis[i+1] and rsis[i] < rsis[i+2]:
                rsi_swing_lows.append((i, rsis[i]))
        # Regular bearish divergence: price makes higher high, RSI makes lower high
        if len(price_swing_highs) >= 2 and len(rsi_swing_highs) >= 2:
            ph1, ph_val1 = price_swing_highs[-2]
            ph2, ph_val2 = price_swing_highs[-1]
            if len(rsi_swing_highs) >= 2:
                rh1, rsi1 = rsi_swing_highs[-2]
                rh2, rsi2 = rsi_swing_highs[-1]
                if ph_val2 > ph_val1 and rsi2 < rsi1:
                    result["type"] = "bearish_regular"
                    result["strength"] = (ph_val2 - ph_val1) / ph_val1 + (rsi1 - rsi2) / 100
                    result["description"] = f"Bearish divergence: price HH {ph_val2:.0f} > {ph_val1:.0f}, RSI LH {rsi2:.0f} < {rsi1:.0f}"
        # Regular bullish divergence: price makes lower low, RSI makes higher low
        if len(price_swing_lows) >= 2 and len(rsi_swing_lows) >= 2:
            pl1, pl_val1 = price_swing_lows[-2]
            pl2, pl_val2 = price_swing_lows[-1]
            if len(rsi_swing_lows) >= 2:
                rl1, rsi_l1 = rsi_swing_lows[-2]
                rl2, rsi_l2 = rsi_swing_lows[-1]
                if pl_val2 < pl_val1 and rsi_l2 > rsi_l1:
                    result["type"] = "bullish_regular"
                    result["strength"] = (pl_val1 - pl_val2) / pl_val1 + (rsi_l2 - rsi_l1) / 100
                    result["description"] = f"Bullish divergence: price LL {pl_val2:.0f} < {pl_val1:.0f}, RSI HL {rsi_l2:.0f} > {rsi_l1:.0f}"
        # Hidden bearish divergence: price makes lower high, RSI makes higher high
        if len(price_swing_highs) >= 2 and len(rsi_swing_highs) >= 2 and not result["type"]:
            ph1, ph_val1 = price_swing_highs[-2]
            ph2, ph_val2 = price_swing_highs[-1]
            rh1, rsi1 = rsi_swing_highs[-2]
            rh2, rsi2 = rsi_swing_highs[-1]
            if ph_val2 < ph_val1 and rsi2 > rsi1:
                result["type"] = "bearish_hidden"
                result["strength"] = (ph_val1 - ph_val2) / ph_val1 + (rsi2 - rsi1) / 100
                result["description"] = f"Hidden bearish divergence: price LH, RSI HH"
        # Hidden bullish divergence: price makes higher low, RSI makes lower low
        if len(price_swing_lows) >= 2 and len(rsi_swing_lows) >= 2 and not result["type"]:
            pl1, pl_val1 = price_swing_lows[-2]
            pl2, pl_val2 = price_swing_lows[-1]
            rl1, rsi_l1 = rsi_swing_lows[-2]
            rl2, rsi_l2 = rsi_swing_lows[-1]
            if pl_val2 > pl_val1 and rsi_l2 < rsi_l1:
                result["type"] = "bullish_hidden"
                result["strength"] = (pl_val2 - pl_val1) / pl_val1 + (rsi_l1 - rsi_l2) / 100
                result["description"] = f"Hidden bullish divergence: price HL, RSI LL"
        return result

    def _mtf_alignment(self, price: float, regime: MarketRegime | None, timeframe: str) -> dict:
        """Compute multi-timeframe alignment score from higher-timeframe regime data.

        Uses the current regime (which already fuses multiple TFs) to determine
        how well the current TF aligns with the macro direction.
        """
        result: dict = {"alignment": "neutral", "score": 0.0, "confidence": 0.5}
        if not regime:
            return result
        tf_num = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(timeframe, 5)
        # Regime phase carries MTF information — trending regimes on HTF filter to LTF
        if regime.phase == "trending":
            base_conf = 0.35 if tf_num <= 5 else (0.50 if tf_num <= 15 else 0.65)
            if regime.bias == "bullish":
                result["alignment"] = "bullish"
                result["score"] = base_conf
                result["confidence"] = 0.5 + base_conf * 0.5
            elif regime.bias == "bearish":
                result["alignment"] = "bearish"
                result["score"] = base_conf
                result["confidence"] = 0.5 + base_conf * 0.5
        elif regime.phase == "accumulation":
            result["alignment"] = "bullish_biased"
            result["score"] = 0.25
            result["confidence"] = 0.4
        elif regime.phase == "distribution":
            result["alignment"] = "bearish_biased"
            result["score"] = 0.25
            result["confidence"] = 0.4
        # Boost alignment score when price is confirmed by regime direction
        if regime.phase in ("trending", "accumulation", "distribution") and regime.bias:
            if regime.bias == "bullish" and price < (regime.range_low or 0) * 0.995:
                result["score"] += 0.1
                result["confidence"] = min(result["confidence"] + 0.1, 0.9)
            elif regime.bias == "bearish" and price > (regime.range_high or 0) * 1.005:
                result["score"] += 0.1
                result["confidence"] = min(result["confidence"] + 0.1, 0.9)
        result["score"] = min(result["score"], 0.8)
        return result

    def _candle_patterns(self, candles: list[Candle]) -> dict:
        """Detect candle-based confirmation patterns (pin bar, engulfing, inside bar, momentum)."""
        result: dict = {
            "pin_bar": None, "engulfing": None, "inside_bar": None,
            "momentum_candle": None, "nr7": False,
        }
        if len(candles) < 3:
            return result
        prev, curr = candles[-2], candles[-1]
        prange = prev.high - prev.low
        crange = curr.high - curr.low
        if prange <= 0 or crange <= 0:
            return result
        # Pin bar: long wick opposite to close direction
        upper_wick = curr.high - max(curr.open, curr.close)
        lower_wick = min(curr.open, curr.close) - curr.low
        body = abs(curr.close - curr.open)
        total_range = upper_wick + lower_wick + body
        if total_range > 0:
            if curr.close > curr.open and lower_wick > body * 2 and lower_wick > upper_wick * 2:
                result["pin_bar"] = "bullish"
                result["pin_bar_strength"] = min(lower_wick / body, 3.0)
            elif curr.close < curr.open and upper_wick > body * 2 and upper_wick > lower_wick * 2:
                result["pin_bar"] = "bearish"
                result["pin_bar_strength"] = min(upper_wick / body, 3.0)
        # Engulfing: current body fully covers previous body
        prev_body_top = max(prev.open, prev.close)
        prev_body_bot = min(prev.open, prev.close)
        curr_body_top = max(curr.open, curr.close)
        curr_body_bot = min(curr.open, curr.close)
        if prev_body_bot < curr_body_bot and prev_body_top < curr_body_top:
            if curr.close > curr.open and prev.close < prev.open:
                result["engulfing"] = "bullish"
            elif curr.close < curr.open and prev.close > prev.open:
                result["engulfing"] = "bearish"
        # Inside bar: current within prior range
        if curr.high < prev.high and curr.low > prev.low:
            result["inside_bar"] = True
        # Momentum candle: large body with direction
        avg_body = sum(abs(c.close - c.open) for c in candles[-10:]) / 10 if len(candles) >= 10 else body
        if avg_body > 0 and body > avg_body * 1.8:
            result["momentum_candle"] = "bullish" if curr.close > curr.open else "bearish"
            result["momentum_strength"] = body / avg_body
        # NR7: narrowest range of last 7 candles
        if len(candles) >= 7:
            ranges = [c.high - c.low for c in candles[-7:]]
            if crange <= min(ranges):
                result["nr7"] = True
        return result

    def _correlation_check(self) -> dict:
        """Quick ETH/BTC correlation check using available context.

        Returns a dict with directional alignment and strength.
        Since we don't always have ETH data in this context, we
        return a neutral signal and let the confluence score use it.
        """
        result: dict = {"aligned": True, "strength": 0.5, "bias": "neutral"}
        try:
            from backend.analysis.self_aware_agent import get_agent
            agent = get_agent()
            if hasattr(agent, '_last_correlation') and agent._last_correlation:
                result["bias"] = agent._last_correlation.get("bias", "neutral")
                result["strength"] = agent._last_correlation.get("correlation", 0.5)
                result["aligned"] = result["strength"] > 0.3
        except Exception:
            pass
        return result

    def _kelly_position_size(self, win_rate: float, confidence: float, rr: float) -> dict:
        """Compute optimal position size using Kelly Criterion.

        f* = (p * b - q) / b
        where p = win probability, q = loss probability (1-p), b = odds (RR)

        Returns dict with kelly fraction, conservative fraction (half-kelly),
        and recommended leverage adjustment.
        """
        result: dict = {"kelly_pct": 0.0, "conservative_pct": 0.0, "leverage_boost": 1.0}
        p = max(0.01, min(0.99, win_rate * 0.7 + confidence * 0.3))
        q = 1.0 - p
        b = max(0.1, rr)
        kelly = (p * b - q) / b if b > 0 else 0.0
        kelly = max(0.0, min(0.5, kelly))
        result["kelly_pct"] = round(kelly * 100, 1)
        result["conservative_pct"] = round(kelly * 50, 1)
        # Leverage adjustment: higher Kelly fraction = can take more leverage
        if kelly > 0.15:
            result["leverage_boost"] = 1.3
        elif kelly > 0.08:
            result["leverage_boost"] = 1.15
        else:
            result["leverage_boost"] = 0.9
        return result

    def _regime_adaptive_sltp(self, price: float, atr: float, score: float, regime: MarketRegime | None) -> dict:
        """Compute regime-aware SL/TP multipliers.

        Trending: wider SL (ride trend), wider TP (let profits run)
        Range: tighter SL (quick stops), tighter TP (mean reversion)
        Volatile: wider everything
        Quiet: tighter everything
        """
        result: dict = {"sl_mult": 2.0, "tp1_mult": 3.0, "tp2_mult": 5.0, "reason": "default"}
        if not regime:
            return result
        base_sl = max(1.5, 4.0 - score * 2)
        base_tp1 = 2.0 + score * 3
        base_tp2 = 4.0 + score * 6
        if regime.phase == "trending":
            result["sl_mult"] = base_sl * 1.3
            result["tp1_mult"] = base_tp1 * 1.5
            result["tp2_mult"] = base_tp2 * 1.5
            result["reason"] = f"trending: wider stops (×1.3) / wider targets (×1.5)"
        elif regime.phase in ("range_bound", "consolidation"):
            result["sl_mult"] = base_sl * 0.8
            result["tp1_mult"] = base_tp1 * 0.7
            result["tp2_mult"] = base_tp2 * 0.7
            result["reason"] = f"{regime.phase}: tighter stops (×0.8) / tighter targets (×0.7)"
        elif regime.phase in ("accumulation", "distribution"):
            result["sl_mult"] = base_sl * 1.1
            result["tp1_mult"] = base_tp1 * 1.1
            result["tp2_mult"] = base_tp2 * 1.1
            result["reason"] = f"{regime.phase}: moderately wider (×1.1)"
        elif regime.volatility_state in ("high", "extreme"):
            result["sl_mult"] = base_sl * 1.4
            result["tp1_mult"] = base_tp1 * 1.2
            result["tp2_mult"] = base_tp2 * 1.2
            result["reason"] = f"high vol: wider stops (×1.4)"
        return result
