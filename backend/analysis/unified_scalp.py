"""
NEXUS Unified Scalping Engine v3.0 - Industry Grade AI Trading Brain

Single-signal scalping engine for BTCUSD perpetual futures on Delta Exchange.
PRIMARY SIGNAL: Self-Aware Trading Agent - no external dependencies, pure price action.

Data sources fused:
  1. Order Flow: Delta, CVD, absorption, footprint imbalance
  2. VWAP: Price deviation, compression state, band position
  3. Funding Rate: Current rate, annualized, contrarian bias, extreme detection
  4. Open Interest: Change %, trend, momentum confirmation
  5. Liquidation Levels: Cluster proximity, sweep targets
  6. Liquidity Sweeps: Reclaim status, entry triggers
  7. Volume Profile: POC, VAH, VAL positioning
  8. ICT Patterns: FVG proximity, order blocks, market structure
  9. Market Regime: Phase, bias, volatility state
  10. RSI(3): Exhaustion reads on 1m/3m/5m
  11. Killzone: Session timing for high-probability windows
  12. Wick Rejection: Long-wick reversal detection (price rejects long wick side)

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
from backend.analysis.self_aware_agent import SelfAwareTradingAgent, agent as ai_agent
from backend.analysis.ensemble_model import ensemble as ensemble_model
from backend.analysis.self_optimizer import optimizer as self_optimizer
from backend.analysis.anomaly_detection import anomaly_detector, adaptive_stop
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
        self._signal_cooldown_ms: int = 5 * 60 * 1000
        self._use_candle_timestamp_for_cooldown: bool = True
        # Multi-exchange aggregated price for cross-validation
        self._last_aggregated_price: float | None = None
        self._last_aggregated_spread_pct: float = 0.0
        self._last_exchange_count: int = 0

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
            ctx.ai_intelligence = ai_agent.get_agent_status()
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
            ctx.ai_intelligence = ai_agent.get_agent_status()
            logger.warning(f"Data coherence check failed: {'; '.join(coherence_issues)}")
            return ctx

        # ── Anomaly / OOD detection gate ────────────────────────────────
        # Detect black swan events, regime shifts, and out-of-distribution
        # market states. Block trading during anomalies.
        last_candle_for_anomaly = candles[-1] if candles else None
        anomaly = anomaly_detector.detect(last_candle_for_anomaly)
        if anomaly.should_block_trade:
            logger.warning("Anomaly detected: %s (score=%.2f) — blocking trades",
                           anomaly.anomaly_type, anomaly.anomaly_score)
            ctx = ScalpContext(timestamp=now_ms)
            ctx.trade_blocked_reasons = [f"Anomaly: {anomaly.description}"]
            ctx.ai_brain_active = True
            ctx.ai_intelligence = ai_agent.get_agent_status()
            return ctx
        # Update anomaly detector with new data
        anomaly_detector.update(last_candle_for_anomaly)

        ordered = sorted(candles, key=lambda c: c.timestamp)
        closes = [c.close for c in ordered]
        price = closes[-1]

        order_flow = self._order_flow(ordered)
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

        # ── Common Sense Checks ─────────────────────────────────────────
        # Sanity checks every human trader would follow before considering a trade
        atr_for_common_sense = _atr(ordered, 14)
        common_sense_blockers = self._common_sense_blockers(
            ordered, price, atr_for_common_sense, now_ms, timeframe,
        )
        has_macro_event_block = any("macro" in b.lower() or "FOMC" in b or "CPI" in b or "NFP" in b for b in common_sense_blockers)

        # Common sense blocks are soft warnings — only hard-block the most severe
        severe_cs = [b for b in common_sense_blockers if any(k in b.lower() for k in
            ["atr spike", "stale data", "price spike", "weekend"])]
        cs_advisory = [b for b in common_sense_blockers if b not in severe_cs]
        self._cs_advisory = cs_advisory
        for b in severe_cs:
            logger.warning("Common sense block: %s", b)

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
            ctx.ai_intelligence = ai_agent.get_agent_status()
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

        atr = _atr(ordered, 14)
        signals: list[ScalpSignal] = []

        # ── Get adaptive parameters from self-optimizer ──
        regime_phase = regime.phase if regime else "unknown"
        adaptive_params = self_optimizer.get_adaptive_params(regime_phase)

        # Use adaptive threshold from self-optimizer
        threshold = adaptive_params.get('min_confidence', settings.scalp_min_confluence_score)

        has_oi = oi.current_oi > 0 and len(self._oi_hist) >= 2
        has_funding = self._cur_funding != 0.0
        missing_sources = sum([not has_oi, not has_funding])
        if missing_sources > 0:
            max_possible = 1.0 - (missing_sources * 0.11)
            normalized_threshold = threshold * (max_possible / 1.0)
            threshold = max(normalized_threshold, 0.35)

        # ── Self-Aware AI Agent is the CENTRAL BRAIN ────────────────────────
        # It receives ALL 15 data sources + price action + memory and makes the final decision
        agent_result = ai_agent.analyze_enriched(
            candles=ordered, order_flow=order_flow, vwap=vwap, oi=oi,
            funding=funding_rate, sweeps=sweeps, vol_profile=vol_profile,
            rsi_3=rsi_3, kill_active=kill_active, kill_session=kill_session,
            metrics=metrics, fvgs=fvgs, order_blocks=order_blocks,
            regime_obj=regime, wick=wick, futures_context=futures_context,
            long_confluence=long_score, short_confluence=short_score,
            timeframe=timeframe,
        )

        # ── Ensemble Model: 3-model blend (microstructure + ICT + momentum) ──
        micro_score, micro_reasons = ensemble_model.score_microstructure(
            order_flow, vwap, oi, funding_rate, price, regime_phase,
        )
        ict_score, ict_reasons = ensemble_model.score_ict(
            fvgs, order_blocks, sweeps, regime, price, regime_phase, ordered,
        )
        momentum_score, momentum_reasons = ensemble_model.score_momentum(
            rsi_3, ordered, kill_active, kill_session, metrics, wick,
        )
        ensemble_result = ensemble_model.combine(
            micro_score, ict_score, momentum_score, regime_phase,
            micro_reasons, ict_reasons, momentum_reasons,
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

        quality_blockers = self._signal_quality_blockers(
            ordered, winning_side, winning_score, 1.0 - winning_score if agent_has_signal else (short_score if winning_side == "long" else long_score),
            regime, threshold, winning_reasons,
            adaptive_edge=adaptive_params.get('min_edge', settings.scalp_min_directional_edge),
        )

        if quality_blockers:
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
                signals=[],
                rsi_3=round(rsi_3, 2),
                spot_volume_ok=True,
                macro_event_block=False,
                trade_blocked_reasons=quality_blockers,
                common_sense_warnings=cs_advisory,
            )
            ctx.futures_leverage = settings.futures_leverage
            ctx.estimated_funding_cost_8h = round(funding_rate.current_rate * 3 * 100, 4) if funding_rate else 0.0
            ctx.ai_brain_active = True
            ctx.ai_intelligence = ai_agent.get_agent_status()
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

        # Build signal from either the agent's decision or fallback confluence
        last_candle = ordered[-1]
        if agent_has_signal:
            signals.append(self._build_signal(
                agent_result['signal'] + " BTCUSD", price, atr,
                agent_result['confidence'], winning_reasons, now_ms, funding_rate,
                enriched_features=agent_result.get('enriched_features'),
                candle=last_candle,
            ))
            self._last_signal_ts = cooldown_ts
        else:
            if long_score >= threshold and long_score >= short_score:
                signals.append(self._build_signal("LONG BTCUSD", price, atr, long_score, long_reasons, now_ms, funding_rate, candle=last_candle))
                self._last_signal_ts = cooldown_ts
            elif short_score >= threshold and short_score > long_score:
                signals.append(self._build_signal("SHORT BTCUSD", price, atr, short_score, short_reasons, now_ms, funding_rate, candle=last_candle))
                self._last_signal_ts = cooldown_ts

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
        ctx.ai_intelligence = ai_agent.get_agent_status()
        
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
        ctx.ai_intelligence = ai_agent.get_agent_status()
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

        return blockers

    def _signal_quality_blockers(self, candles: list[Candle], side: str, winning_score: float, losing_score: float, regime: MarketRegime | None = None, adaptive_threshold: float | None = None, winning_reasons: list[str] | None = None, adaptive_edge: float | None = None) -> list[str]:
        blockers: list[str] = []
        closes = [c.close for c in candles]
        price = closes[-1]
        threshold = adaptive_threshold if adaptive_threshold is not None else settings.scalp_min_confluence_score
        edge = winning_score - losing_score
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

    def _build_signal(self, signal_type: str, price: float, atr: float, score: float, reasons: list[str], now_ms: int, fr: ScalpFundingRate | None = None, enriched_features: dict | None = None, candle: Candle | None = None) -> ScalpSignal:
        is_long = "LONG" in signal_type
        
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

        sl_multiplier = max(2.0, 4.0 - score * 2)
        tp1_multiplier = 3.0 + score * 3
        tp2_multiplier = 5.0 + score * 6
        
        sl_dist = atr * sl_multiplier
        t2_dist = atr * tp2_multiplier
        t1_dist = atr * tp1_multiplier
        
        sl = entry - sl_dist if is_long else entry + sl_dist
        t1 = entry + t1_dist if is_long else entry - t1_dist
        t2 = entry + t2_dist if is_long else entry - t2_dist
        
        rr = round(abs(t2 - entry) / abs(entry - sl), 2) if abs(entry - sl) > 0 else 0.0
        
        base_leverage = max(3, int(10 * score))
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
