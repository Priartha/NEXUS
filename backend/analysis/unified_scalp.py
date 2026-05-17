"""
NEXUS Unified Scalping Engine v2.0

Single-signal scalping engine that combines ALL data sources into one
confluence-weighted scalping signal for BTC/USDT perpetual futures.

Data sources fused:
  1. Order Flow: Delta, CVD, absorption, footprint imbalance
  2. VWAP: Price deviation, compression state, band position
  3. Funding Rate: Current rate, contrarian bias, extreme detection
  4. Open Interest: Change %, trend, momentum confirmation
  5. Liquidation Levels: Cluster proximity, sweep targets
  6. Liquidity Sweeps: Reclaim status, entry triggers
  7. Volume Profile: POC, VAH, VAL positioning
  8. Options: IV regime, gamma exposure
  9. ICT Patterns: FVG proximity, order blocks, market structure
  10. Market Regime: Phase, bias, volatility state
  11. RSI(3): Exhaustion reads on 1m/3m/5m
  12. Killzone: Session timing for high-probability windows

Output: EXACTLY ONE scalping signal or NO_TRADE.
"""

from __future__ import annotations

import math
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from backend.config import settings
from backend.models.types import (
    Candle,
    FVG,
    LiquidityEvent,
    LiquidityLevel,
    MarketMetrics,
    MarketQuote,
    MarketRegime,
    OptionContract,
    OptionsContext,
    OrderBlock,
    ScalpContext,
    ScalpFunding,
    ScalpLiquidationLevel,
    ScalpOpenInterest,
    ScalpOptionsGreeks,
    ScalpOrderFlow,
    ScalpSignal,
    ScalpVWAP,
    ScalpVolumeProfile,
    ScalpLiquiditySweep,
    Swing,
)


# ─── Micro-helpers ────────────────────────────────────────────────────────

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


# ─── Unified Scalping Engine ──────────────────────────────────────────────

class UnifiedScalpEngine:
    """
    Computes all 12 data sources and fuses them into a single
    confluence-weighted scalping signal.
    """

    def __init__(self) -> None:
        self._quotes: deque[MarketQuote] = deque(maxlen=5000)
        self._oi_hist: deque[tuple[int, float]] = deque(maxlen=200)
        self._fund_hist: deque[tuple[int, float]] = deque(maxlen=100)
        self._cur_funding: float = 0.0
        self._cur_oi: float = 0.0
        self._spot_vol_avg: float = 0.0
        self._iv_hist: deque[float] = deque(maxlen=252)
        self._cur_iv: float = 0.0
        self._liq_cache: list[dict] = []

    # ── Data ingestion ────────────────────────────────────────────────

    def ingest_quote(self, q: MarketQuote) -> None:
        self._quotes.append(q)

    def ingest_funding(self, rate: float, ts: int | None = None) -> None:
        self._cur_funding = rate
        self._fund_hist.append((ts or int(time.time() * 1000), rate))

    def ingest_oi(self, oi: float, ts: int | None = None) -> None:
        self._cur_oi = oi
        self._oi_hist.append((ts or int(time.time() * 1000), oi))

    def ingest_iv(self, iv: float) -> None:
        self._cur_iv = iv
        self._iv_hist.append(iv)

    def ingest_spot_vol_avg(self, avg: float) -> None:
        self._spot_vol_avg = avg

    def ingest_liquidations(self, levels: list[dict]) -> None:
        self._liq_cache = levels

    # ── Public entry point ────────────────────────────────────────────

    def compute(
        self,
        candles: list[Candle],
        metrics: MarketMetrics | None = None,
        fvgs: list[FVG] | None = None,
        order_blocks: list[OrderBlock] | None = None,
        swings: list[Swing] | None = None,
        regime: MarketRegime | None = None,
        liquidity_events: list[LiquidityEvent] | None = None,
        options_context: OptionsContext | dict[str, Any] | None = None,
    ) -> ScalpContext:
        now_ms = int(time.time() * 1000)
        if len(candles) < 20:
            return ScalpContext(timestamp=now_ms)

        ordered = sorted(candles, key=lambda c: c.timestamp)
        closes = [c.close for c in ordered]
        price = closes[-1]

        # Compute all 12 data sources
        order_flow = self._order_flow(ordered)
        funding = self._funding(now_ms)
        oi = self._open_interest()
        liq_levels = self._liquidation_levels(price)
        vwap = self._vwap(ordered)
        vol_profile = self._volume_profile(ordered)
        options_greeks = self._options_greeks(now_ms, options_context)
        sweeps = self._liquidity_sweeps(ordered)
        rsi_3 = _rsi(closes[-20:], 3) if len(closes) >= 4 else 50.0
        kill_active, kill_session = _is_killzone(ordered[-1].timestamp)

        blockers = self._filters(ordered, funding, options_greeks, options_context)

        # If blocked, return context with blockers only
        if blockers:
            return ScalpContext(
                timestamp=now_ms,
                order_flow=order_flow,
                funding=funding,
                open_interest=oi,
                liquidation_levels=liq_levels,
                vwap=vwap,
                volume_profile=vol_profile,
                options_greeks=options_greeks,
                liquidity_sweeps=sweeps,
                rsi_3=round(rsi_3, 2),
                spot_volume_ok=all(b != "Spot volume below 30-day average" for b in blockers),
                options_spread_ok=all("spread" not in b.lower() for b in blockers),
                macro_event_block=any("macro" in b.lower() for b in blockers),
                trade_blocked_reasons=blockers,
            )

        # Fuse ALL sources into confluence scores for LONG and SHORT
        long_score, long_reasons = self._confluence_long(
            price, order_flow, vwap, oi, funding, sweeps,
            vol_profile, rsi_3, kill_active, kill_session,
            metrics, fvgs, order_blocks, regime, ordered, options_context,
        )
        short_score, short_reasons = self._confluence_short(
            price, order_flow, vwap, oi, funding, sweeps,
            vol_profile, rsi_3, kill_active, kill_session,
            metrics, fvgs, order_blocks, regime, ordered, options_context,
        )

        # Select the winning direction only after hard quality gates. The
        # optimizer showed that loose confidence thresholds overtrade badly.
        atr = _atr(ordered, 14)
        signals: list[ScalpSignal] = []
        threshold = settings.scalp_min_confluence_score
        winning_side = "long" if long_score >= short_score else "short"
        winning_score = long_score if winning_side == "long" else short_score
        losing_score = short_score if winning_side == "long" else long_score
        quality_blockers = self._signal_quality_blockers(
            ordered, winning_side, winning_score, losing_score, options_context
        )

        if quality_blockers:
            return ScalpContext(
                timestamp=now_ms,
                order_flow=order_flow,
                funding=funding,
                open_interest=oi,
                liquidation_levels=liq_levels,
                vwap=vwap,
                volume_profile=vol_profile,
                options_greeks=options_greeks,
                liquidity_sweeps=sweeps,
                signals=[],
                rsi_3=round(rsi_3, 2),
                spot_volume_ok=True,
                options_spread_ok=all("spread" not in b.lower() for b in quality_blockers),
                macro_event_block=False,
                trade_blocked_reasons=quality_blockers,
            )

        if long_score >= threshold and long_score >= short_score:
            option_contract = self._select_directional_option(options_context, "call")
            signals.append(self._build_signal(
                "LONG FUTURES + BUY CALL", price, atr, long_score, long_reasons, now_ms, option_contract,
            ))
        elif short_score >= threshold and short_score > long_score:
            option_contract = self._select_directional_option(options_context, "put")
            signals.append(self._build_signal(
                "SHORT FUTURES + BUY PUT", price, atr, short_score, short_reasons, now_ms, option_contract,
            ))

        return ScalpContext(
            timestamp=now_ms,
            order_flow=order_flow,
            funding=funding,
            open_interest=oi,
            liquidation_levels=liq_levels,
            vwap=vwap,
            volume_profile=vol_profile,
            options_greeks=options_greeks,
            liquidity_sweeps=sweeps,
            signals=signals,
            rsi_3=round(rsi_3, 2),
            spot_volume_ok=True,
            options_spread_ok=True,
            macro_event_block=False,
            trade_blocked_reasons=[],
        )

    # ── 12 Data source computations ───────────────────────────────────

    def _order_flow(self, candles: list[Candle]) -> ScalpOrderFlow:
        deltas: list[float] = []
        for i in range(1, len(candles)):
            mid = (candles[i - 1].close + candles[i].close) / 2.0
            if candles[i].close > mid:
                deltas.append(candles[i].volume)
            elif candles[i].close < mid:
                deltas.append(-candles[i].volume)
            else:
                deltas.append(0.0)

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
            delta=round(last_delta, 4),
            cvd=round(cvd, 4),
            cvd_slope=round(slope, 4),
            volume_delta_ratio=round(vol_delta_ratio, 4),
            absorption_ratio=round(absorption, 4),
            aggressive_buy_volume=round(buy_vol, 4),
            aggressive_sell_volume=round(sell_vol, 4),
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
            timestamp=now_ms,
            current_rate=round(rate, 6),
            projected_8h=round(proj, 6),
            next_reset_ms=self._next_funding_reset(now_ms),
            is_extreme=extreme,
            contrarian_bias=bias,
        )

    def _open_interest(self) -> ScalpOpenInterest:
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
            timestamp=int(time.time() * 1000),
            current_oi=round(cur, 2),
            oi_change_pct=round(change_pct, 4),
            oi_delta=round(cur - prev, 2),
            oi_trend=trend,
            momentum_confirmation=momentum,
        )

    def _liquidation_levels(self, price: float) -> list[ScalpLiquidationLevel]:
        if self._liq_cache:
            out: list[ScalpLiquidationLevel] = []
            for e in self._liq_cache:
                p = e.get("price", 0)
                s = e.get("size", 0)
                side = e.get("side", "long")
                d = abs(p - price) / price * 100
                out.append(ScalpLiquidationLevel(
                    price=p, size=s, side=side,
                    distance_pct=round(d, 3),
                    cluster_strength=_clamp(s / 1_000_000, 0, 1),
                ))
            return sorted(out, key=lambda x: x.distance_pct)[:10]

        out = []
        for pct in [0.5, 1.0, 1.5, 2.0, 3.0, 5.0]:
            out.append(ScalpLiquidationLevel(
                price=round(price * (1 - pct / 100), 2),
                size=round(500_000 / pct, 0),
                side="long", distance_pct=pct,
                cluster_strength=round(1.0 - pct / 10, 3),
            ))
            out.append(ScalpLiquidationLevel(
                price=round(price * (1 + pct / 100), 2),
                size=round(500_000 / pct, 0),
                side="short", distance_pct=pct,
                cluster_strength=round(1.0 - pct / 10, 3),
            ))
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
            timestamp=candles[-1].timestamp,
            vwap=round(vwap, 2),
            upper_band_1sd=round(vwap + std, 2),
            lower_band_1sd=round(vwap - std, 2),
            upper_band_2sd=round(vwap + 2 * std, 2),
            lower_band_2sd=round(vwap - 2 * std, 2),
            price_deviation_pct=round(dev, 4),
            is_compressed=abs(dev) < 0.15,
        )

    def _volume_profile(self, candles: list[Candle]) -> ScalpVolumeProfile:
        recent = candles[-80:]
        hi = max(c.high for c in recent)
        lo = min(c.low for c in recent)
        bins_n = 24
        bs = (hi - lo) / bins_n if hi > lo else 1.0
        bins = [0.0] * bins_n
        for c in recent:
            idx = _clamp(int((c.close - lo) / bs), 0, bins_n - 1)
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
            timestamp=candles[-1].timestamp,
            poc=round(poc, 2),
            vah=round(vah, 2),
            val=round(val, 2),
            value_area_width_pct=round(((vah - val) / poc * 100) if poc > 0 else 0, 4),
        )

    def _options_greeks(self, now_ms: int, options_context: OptionsContext | dict[str, Any] | None = None) -> ScalpOptionsGreeks:
        best_contract = self._best_options_contract(options_context)
        iv_values = [
            value for value in (
                self._contract_value(best_contract, "bid_iv"),
                self._contract_value(best_contract, "ask_iv"),
            )
            if value is not None and value > 0
        ]
        if iv_values:
            self.ingest_iv(sum(iv_values) / len(iv_values))

        iv = self._cur_iv
        ivr = self._iv_rank()
        ivp = self._iv_percentile()
        regime = "low" if ivr < 30 else ("high" if ivr > 70 else (
            "no_trade" if 30 <= ivr <= 50 else "neutral"
        ))
        return ScalpOptionsGreeks(
            timestamp=now_ms,
            delta=round(abs(self._contract_value(best_contract, "delta") or 0.0), 4),
            gamma=round(abs(self._contract_value(best_contract, "gamma") or 0.0), 6),
            theta=round(self._contract_value(best_contract, "theta") or 0.0, 6),
            vega=round(self._contract_value(best_contract, "vega") or 0.0, 6),
            iv_rank=round(ivr, 2),
            iv_percentile=round(ivp, 2),
            iv_regime=regime,
            theta_decay_per_hour=round(iv * 0.0001, 6),
        )

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
                sweeps.append(ScalpLiquiditySweep(
                    timestamp=cur.timestamp, level=lv, side="short",
                    sweep_type="resistance_sweep", reclaimed=True,
                    strength=_clamp(1.0 - d * 100, 0, 1),
                    entry_trigger=cur.close < lv * 0.999,
                ))
        for lv in lows:
            if cur.low <= lv and cur.close > lv:
                d = abs(cur.close - lv) / lv
                sweeps.append(ScalpLiquiditySweep(
                    timestamp=cur.timestamp, level=lv, side="long",
                    sweep_type="support_sweep", reclaimed=True,
                    strength=_clamp(1.0 - d * 100, 0, 1),
                    entry_trigger=cur.close > lv * 1.001,
                ))
        return sorted(sweeps, key=lambda s: s.strength, reverse=True)[:5]

    def _iv_rank(self) -> float:
        hist = list(self._iv_hist)
        if len(hist) < 2:
            return 0.0
        lo, hi = min(hist), max(hist)
        return (self._cur_iv - lo) / (hi - lo) * 100 if hi != lo else 50.0

    def _iv_percentile(self) -> float:
        hist = list(self._iv_hist)
        if len(hist) < 2:
            return 0.0
        return sum(1 for v in hist if v <= self._cur_iv) / len(hist) * 100

    def _next_funding_reset(self, now_ms: int) -> int:
        from datetime import timedelta
        now = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
        for h in [0, 8, 16]:
            r = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if r > now:
                return int(r.timestamp() * 1000)
        nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return int(nxt.timestamp() * 1000)

    # ── Trade filters ─────────────────────────────────────────────────

    def _filters(
        self,
        candles: list[Candle],
        funding: ScalpFunding,
        options: ScalpOptionsGreeks,
        options_context: OptionsContext | dict[str, Any] | None,
    ) -> list[str]:
        blockers: list[str] = []
        if funding.is_extreme:
            blockers.append(f"Funding extreme: {funding.current_rate * 100:.3f}%")
        if 30 <= options.iv_rank <= 50:
            blockers.append(f"IVR {options.iv_rank:.0f} in no-edge zone")
        source_count = self._context_value(options_context, "source_count", 0) or 0
        if source_count > 0:
            blockers.extend(self._options_blockers(options_context)[:3])
        if self._spot_vol_avg > 0:
            avg_vol = sum(c.volume for c in candles[-20:]) / 20
            if avg_vol < self._spot_vol_avg * settings.scalp_min_spot_volume_ratio:
                blockers.append("Spot volume below 30-day average")
        return blockers

    def _signal_quality_blockers(
        self,
        candles: list[Candle],
        side: str,
        winning_score: float,
        losing_score: float,
        options_context: OptionsContext | dict[str, Any] | None,
    ) -> list[str]:
        blockers: list[str] = []
        closes = [c.close for c in candles]
        price = closes[-1]
        threshold = settings.scalp_min_confluence_score
        edge = winning_score - losing_score
        if winning_score < threshold:
            blockers.append(f"Confluence {winning_score:.2f} below {threshold:.2f} hard threshold")
        if edge < settings.scalp_min_directional_edge:
            blockers.append(f"Directional edge {edge:.2f} below {settings.scalp_min_directional_edge:.2f}")

        ema9 = _ema(closes[-80:], 9)
        ema21 = _ema(closes[-100:], 21)
        ema50 = _ema(closes[-140:], 50)
        ema100 = _ema(closes[-180:], 100)
        trend_strength = abs(ema21 - ema100) / price if price > 0 else 0.0
        if trend_strength < settings.scalp_min_trend_strength:
            blockers.append(f"Trend strength {trend_strength:.4f} below minimum")
        if side == "long" and not (price > ema21 and ema9 > ema21 > ema50):
            blockers.append("Long trend stack not aligned")
        if side == "short" and not (price < ema21 and ema9 < ema21 < ema50):
            blockers.append("Short trend stack not aligned")

        recent_volume = sum(c.volume for c in candles[-5:]) / min(len(candles), 5)
        base_window = candles[-50:-5] if len(candles) >= 55 else candles[:-5]
        base_volume = sum(c.volume for c in base_window) / len(base_window) if base_window else recent_volume
        volume_ratio = recent_volume / base_volume if base_volume > 0 else 1.0
        if volume_ratio < settings.scalp_min_volume_impulse:
            blockers.append(f"Volume impulse {volume_ratio:.2f} below {settings.scalp_min_volume_impulse:.2f}")

        source_count = self._context_value(options_context, "source_count", 0) or 0
        if settings.scalp_require_options_alignment and source_count > 0:
            momentum_key = "bullish_momentum_score" if side == "long" else "bearish_momentum_score"
            option_side = "call" if side == "long" else "put"
            momentum = self._context_value(options_context, momentum_key, 0.0) or 0.0
            contract = self._select_directional_option(options_context, option_side)
            if momentum < settings.min_options_momentum_score:
                blockers.append(f"BTC options momentum {momentum:.0%} below {settings.min_options_momentum_score:.0%}")
            if not self._context_value(contract, "qualified", False):
                blockers.append(f"No qualified BTC {option_side} contract")
        return blockers[:6]

    # ── Confluence scoring ────────────────────────────────────────────

    def _confluence_long(
        self,
        price: float,
        of: ScalpOrderFlow,
        vwap: ScalpVWAP,
        oi: ScalpOpenInterest,
        funding: ScalpFunding,
        sweeps: list[ScalpLiquiditySweep],
        vp: ScalpVolumeProfile,
        rsi_3: float,
        kill_active: bool,
        kill_session: str,
        metrics: MarketMetrics | None,
        fvgs: list[FVG] | None,
        obs: list[OrderBlock] | None,
        regime: MarketRegime | None,
        candles: list[Candle],
        options_context: OptionsContext | dict[str, Any] | None,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        # 1. Order Flow (weight: 0.22)
        if of.delta > 0:
            score += 0.10
            reasons.append("Delta positive")
        if of.cvd_slope > 0:
            score += 0.07
            reasons.append("CVD rising")
        if of.absorption_ratio < 0.35:
            score += 0.05
            reasons.append("Low absorption")

        # 2. VWAP (weight: 0.15)
        if vwap.is_compressed:
            score += 0.08
            reasons.append("VWAP compressed")
        if price > vwap.vwap:
            score += 0.04
            reasons.append("Above VWAP")
        if price <= vwap.lower_band_1sd:
            score += 0.03
            reasons.append("Near lower VWAP band")

        # 3. Open Interest (weight: 0.10)
        if oi.momentum_confirmation:
            score += 0.06
            reasons.append(f"OI spike +{oi.oi_change_pct:.1f}%")
        if oi.oi_trend == "increasing":
            score += 0.04
            reasons.append("OI increasing")

        # 4. Funding (weight: 0.08)
        if funding.contrarian_bias == "bullish":
            score += 0.08
            reasons.append("Funding contrarian bullish")

        # 5. Liquidity Sweeps (weight: 0.15)
        for s in sweeps:
            if s.side == "long" and s.entry_trigger and s.reclaimed:
                score += 0.15
                reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break
            elif s.side == "long" and s.reclaimed:
                score += 0.08
                reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break

        # 6. Volume Profile (weight: 0.07)
        if vp.poc > 0:
            dist_to_poc = abs(price - vp.poc) / vp.poc
            if dist_to_poc < 0.002:
                score += 0.04
                reasons.append("At POC")
            if price <= vp.val:
                score += 0.03
                reasons.append("Below VAL — discount zone")

        # 7. RSI(3) exhaustion (weight: 0.07)
        if 25 <= rsi_3 <= 45:
            score += 0.05
            reasons.append(f"RSI(3) {rsi_3:.0f} recovery zone")
        elif rsi_3 < 20:
            score -= 0.05
            reasons.append(f"RSI(3) {rsi_3:.0f} extreme — wait")
        elif rsi_3 < 30:
            score += 0.03
            reasons.append(f"RSI(3) {rsi_3:.0f} oversold bounce")

        # 8. Killzone (weight: 0.05)
        if kill_active:
            score += 0.05
            reasons.append(f"Killzone: {kill_session}")

        # 9. ICT FVG proximity (weight: 0.05)
        if fvgs:
            active = [f for f in fvgs if not f.is_filled and f.direction == "bullish"]
            for f in active:
                if abs(price - f.bottom) / price < 0.003:
                    score += 0.05
                    reasons.append("Near bullish FVG")
                    break

        # 10. Order Block proximity (weight: 0.05)
        if obs:
            active = [o for o in obs if not o.is_breaker and o.direction == "bullish"]
            for o in active:
                if abs(price - o.top) / price < 0.003:
                    score += 0.05
                    reasons.append("Near bullish OB")
                    break

        # 11. Regime filter (weight: 0.05)
        if regime:
            if regime.phase == "trending" and regime.bias == "bullish":
                score += 0.05
                reasons.append("Trending bullish regime")
            elif regime.phase == "accumulation":
                score += 0.03
                reasons.append("Accumulation regime")

        # 12. Market metrics trend (weight: 0.03)
        if metrics and metrics.trend_score > 0.15:
            score += 0.03
            reasons.append("Trend score bullish")

        # 13. BTC options momentum and contract quality (weight: 0.16)
        options_momentum = self._context_value(options_context, "bullish_momentum_score", 0.0) or 0.0
        if options_momentum >= settings.min_options_momentum_score:
            score += _clamp(options_momentum, 0.0, 1.0) * 0.11
            reasons.append(f"BTC call momentum {options_momentum:.0%}")
        call_contract = self._select_directional_option(options_context, "call")
        if self._context_value(call_contract, "qualified", False):
            score += 0.05
            reasons.append("Qualified BTC call contract")

        return _clamp(score, 0, 1), reasons

    def _confluence_short(
        self,
        price: float,
        of: ScalpOrderFlow,
        vwap: ScalpVWAP,
        oi: ScalpOpenInterest,
        funding: ScalpFunding,
        sweeps: list[ScalpLiquiditySweep],
        vp: ScalpVolumeProfile,
        rsi_3: float,
        kill_active: bool,
        kill_session: str,
        metrics: MarketMetrics | None,
        fvgs: list[FVG] | None,
        obs: list[OrderBlock] | None,
        regime: MarketRegime | None,
        candles: list[Candle],
        options_context: OptionsContext | dict[str, Any] | None,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        # 1. Order Flow (weight: 0.22)
        if of.delta < 0:
            score += 0.10
            reasons.append("Delta negative")
        if of.cvd_slope < 0:
            score += 0.07
            reasons.append("CVD falling")
        if of.absorption_ratio < 0.35:
            score += 0.05
            reasons.append("Low absorption")

        # 2. VWAP (weight: 0.15)
        if vwap.is_compressed:
            score += 0.08
            reasons.append("VWAP compressed")
        if price < vwap.vwap:
            score += 0.04
            reasons.append("Below VWAP")
        if price >= vwap.upper_band_1sd:
            score += 0.03
            reasons.append("Near upper VWAP band")

        # 3. Open Interest (weight: 0.10)
        if oi.momentum_confirmation and oi.oi_trend == "increasing":
            score += 0.06
            reasons.append(f"OI spike confirms bearish +{oi.oi_change_pct:.1f}%")
        if oi.oi_trend == "decreasing":
            score += 0.04
            reasons.append("OI decreasing")

        # 4. Funding (weight: 0.08)
        if funding.contrarian_bias == "bearish":
            score += 0.08
            reasons.append("Funding contrarian bearish")

        # 5. Liquidity Sweeps (weight: 0.15)
        for s in sweeps:
            if s.side == "short" and s.entry_trigger and s.reclaimed:
                score += 0.15
                reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break
            elif s.side == "short" and s.reclaimed:
                score += 0.08
                reasons.append(f"Sweep reclaimed ${s.level:.0f}")
                break

        # 6. Volume Profile (weight: 0.07)
        if vp.poc > 0:
            if price >= vp.vah:
                score += 0.04
                reasons.append("Above VAH — premium zone")
            dist_to_poc = abs(price - vp.poc) / vp.poc
            if dist_to_poc < 0.002:
                score += 0.03
                reasons.append("At POC rejection")

        # 7. RSI(3) exhaustion (weight: 0.07)
        if 55 <= rsi_3 <= 75:
            score += 0.05
            reasons.append(f"RSI(3) {rsi_3:.0f} rejection zone")
        elif rsi_3 > 80:
            score -= 0.05
            reasons.append(f"RSI(3) {rsi_3:.0f} extreme — wait")

        # 8. Killzone (weight: 0.05)
        if kill_active:
            score += 0.05
            reasons.append(f"Killzone: {kill_session}")

        # 9. ICT FVG proximity (weight: 0.05)
        if fvgs:
            active = [f for f in fvgs if not f.is_filled and f.direction == "bearish"]
            for f in active:
                if abs(price - f.top) / price < 0.003:
                    score += 0.05
                    reasons.append("Near bearish FVG")
                    break

        # 10. Order Block proximity (weight: 0.05)
        if obs:
            active = [o for o in obs if not o.is_breaker and o.direction == "bearish"]
            for o in active:
                if abs(price - o.bottom) / price < 0.003:
                    score += 0.05
                    reasons.append("Near bearish OB")
                    break

        # 11. Regime filter (weight: 0.05)
        if regime:
            if regime.phase == "trending" and regime.bias == "bearish":
                score += 0.05
                reasons.append("Trending bearish regime")
            elif regime.phase == "distribution":
                score += 0.03
                reasons.append("Distribution regime")

        # 12. Market metrics trend (weight: 0.03)
        if metrics and metrics.trend_score < -0.15:
            score += 0.03
            reasons.append("Trend score bearish")

        # 13. BTC options momentum and contract quality (weight: 0.16)
        options_momentum = self._context_value(options_context, "bearish_momentum_score", 0.0) or 0.0
        if options_momentum >= settings.min_options_momentum_score:
            score += _clamp(options_momentum, 0.0, 1.0) * 0.11
            reasons.append(f"BTC put momentum {options_momentum:.0%}")
        put_contract = self._select_directional_option(options_context, "put")
        if self._context_value(put_contract, "qualified", False):
            score += 0.05
            reasons.append("Qualified BTC put contract")

        return _clamp(score, 0, 1), reasons

    # ── Signal builder ────────────────────────────────────────────────

    def _build_signal(
        self,
        signal_type: str,
        price: float,
        atr: float,
        score: float,
        reasons: list[str],
        now_ms: int,
        option_contract: OptionContract | dict[str, Any] | None = None,
    ) -> ScalpSignal:
        is_long = "LONG" in signal_type or "CALL" in signal_type

        entry = price
        sl = price - atr * 1.2 if is_long else price + atr * 1.2
        t1 = price + atr * 1.8 if is_long else price - atr * 1.8
        t2 = price + atr * 3.0 if is_long else price - atr * 3.0
        rr = abs(t1 - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0

        leverage = min(settings.scalp_max_leverage, max(3, int(10 * score)))
        confidence = "HIGH" if score >= 0.70 else "MEDIUM"
        time_limit = now_ms + settings.scalp_max_hold_minutes * 60 * 1000
        strike = self._contract_value(option_contract, "strike_price") or 0.0
        expiry = str(self._contract_value(option_contract, "expiry") or "")
        option_symbol = self._contract_value(option_contract, "symbol")
        if option_symbol:
            reasons = [*reasons, f"Option contract {option_symbol}"]

        from backend.analysis.ids import stable_id
        return ScalpSignal(
            id=stable_id("scalp", "long" if is_long else "short", now_ms, int(price * 10), int(sl * 10)),
            timestamp=now_ms,
            signal_type=signal_type,
            entry_zone_low=round(entry - atr * 0.1, 2),
            entry_zone_high=round(entry + atr * 0.1, 2),
            sl_level=round(sl, 2),
            target_1=round(t1, 2),
            target_2=round(t2, 2),
            leverage=leverage,
            strike=round(strike, 2),
            expiry=expiry,
            reason=" | ".join(reasons),
            risk_reward=round(rr, 2),
            confidence=confidence,
            time_limit_ms=time_limit,
            max_hold_minutes=settings.scalp_max_hold_minutes,
            partial_exit_pct=settings.scalp_partial_exit_pct,
        )

    def _best_options_contract(self, options_context: OptionsContext | dict[str, Any] | None) -> OptionContract | dict[str, Any] | None:
        candidates = [
            contract
            for contract in (
                self._select_directional_option(options_context, "call"),
                self._select_directional_option(options_context, "put"),
            )
            if contract is not None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda contract: self._contract_value(contract, "score") or 0.0)

    def _select_directional_option(
        self,
        options_context: OptionsContext | dict[str, Any] | None,
        side: str,
    ) -> OptionContract | dict[str, Any] | None:
        key = "call_candidate" if side == "call" else "put_candidate"
        contract = self._context_value(options_context, key)
        return contract if contract else None

    def _options_blockers(self, options_context: OptionsContext | dict[str, Any] | None) -> list[str]:
        blockers = self._context_value(options_context, "blockers", []) or []
        return [
            str(item)
            for item in blockers
            if item and not str(item).startswith("No liquid BTC ")
        ]

    def _contract_value(self, contract: OptionContract | dict[str, Any] | None, key: str) -> Any:
        return self._context_value(contract, key)

    def _context_value(self, source: Any, key: str, default: Any = None) -> Any:
        if source is None:
            return default
        if isinstance(source, dict):
            return source.get(key, default)
        return getattr(source, key, default)
