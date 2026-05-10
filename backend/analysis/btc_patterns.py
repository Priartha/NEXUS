from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any

from backend.analysis.ids import stable_id
from backend.models.types import (
    BtcInvestorBehavior,
    BtcPattern,
    BtcPatternContext,
    Candle,
    LiquidityEvent,
    LiquidityLevel,
    MarketMetrics,
    MarketQuote,
    MarketRegime,
    OrderBlock,
    FVG,
    Swing,
)

# ─── BTC-specific session killzone windows (UTC) ──────────────────────────
KILLZONE_WINDOWS: dict[str, tuple[int, int]] = {
    "asian_open":  (0, 2),    # 00:00-02:00 UTC
    "asian_close": (7, 9),    # 07:00-09:00 UTC
    "london_open": (7, 9),    # 07:00-09:00 UTC
    "london_close": (15, 17), # 15:00-17:00 UTC
    "ny_open":     (13, 15),  # 13:00-15:00 UTC
    "ny_close":    (20, 22),  # 20:00-22:00 UTC
    "ny_london_overlap": (13, 17),  # 13:00-17:00 UTC
    "btc_funding_hour": (0, 1),     # 00:00 UTC funding rate settlement
}

HALVING_DATES_MS: list[int] = [
    1588636800000,  # 2020-05-11
    1640995200000,  # 2022-01-01 (estimate for next ~4y cycle)
    1704067200000,  # 2024-01-01
]


# ═══════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════════

def detect_btc_patterns(
    candles: list[Candle],
    swings: list[Swing],
    fvgs: list[FVG],
    order_blocks: list[OrderBlock],
    liquidity: list[LiquidityLevel],
    liquidity_events: list[LiquidityEvent],
    metrics: MarketMetrics | None,
    regime: MarketRegime | None,
) -> BtcPatternContext:
    now_ms = candles[-1].timestamp if candles else 0
    dt = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    hour = dt.hour
    weekday = dt.weekday()  # 0=Mon, 6=Sun
    is_weekend = weekday >= 5

    killzone = _detect_killzone(hour)
    session = _detect_session(hour)
    halving_phase = _detect_halving_phase(now_ms)
    vol_regime = _volatility_regime(metrics)
    clusters = _fractal_clusters(candles, metrics)

    patterns: list[BtcPattern] = []
    behaviors: list[BtcInvestorBehavior] = []
    lookback_80 = candles[-80:] if len(candles) >= 80 else candles
    lookback_40 = candles[-40:] if len(candles) >= 40 else candles

    # ── Movement behavior patterns ──
    p = _killzone_reversal_pattern(lookback_40, swings, killzone, metrics)
    if p: patterns.append(p)

    p = _volatility_squeeze_breakout(lookback_40, metrics)
    if p: patterns.append(p)

    p = _weekend_drift_pattern(lookback_40, is_weekend, weekday, metrics)
    if p: patterns.append(p)

    p = _halving_cycle_behavior(lookback_40, halving_phase, metrics)
    if p: patterns.append(p)

    p = _session_open_gap_fill(lookback_40, session, metrics)
    if p: patterns.append(p)

    p = _liquidation_cascade_pattern(lookback_40, liquidity_events, metrics)
    if p: patterns.append(p)

    p = _fractal_support_resistance(lookback_40, swings, metrics)
    if p: patterns.append(p)

    p = _time_price_reversal(lookback_40, swings, hour, metrics)
    if p: patterns.append(p)

    p = _volume_climax_pattern(lookback_40, metrics)
    if p: patterns.append(p)

    p = _double_distribution_pattern(lookback_40, swings, metrics)
    if p: patterns.append(p)

    # ── Investor behavior patterns ──
    b = _smart_money_distribution(lookback_40, swings, metrics)
    if b: behaviors.append(b)

    b = _smart_money_accumulation(lookback_40, swings, metrics)
    if b: behaviors.append(b)

    b = _retail_fomo_breakout(lookback_40, metrics, regime)
    if b: behaviors.append(b)

    b = _panic_capitulation(lookback_40, metrics, liquidity_events)
    if b: behaviors.append(b)

    b = _stop_hunt_reversal(lookback_40, liquidity_events, swings, metrics)
    if b: behaviors.append(b)

    b = _order_block_wyckoff(lookback_40, order_blocks, swings, metrics)
    if b: behaviors.append(b)

    b = _short_squeeze_pattern(lookback_40, liquidity_events, metrics)
    if b: behaviors.append(b)

    # Score directional bias from patterns
    bullish_score = sum(p.score for p in patterns if p.direction == "bullish")
    bearish_score = sum(p.score for p in patterns if p.direction == "bearish")
    bullish_score += sum(b.intensity * 0.12 for b in behaviors if b.side == "bullish")
    bearish_score += sum(b.intensity * 0.12 for b in behaviors if b.side == "bearish")

    pattern_signal = "bullish" if bullish_score > bearish_score + 0.08 else "bearish" if bearish_score > bullish_score + 0.08 else "neutral"

    return BtcPatternContext(
        timestamp=now_ms,
        killzone=killzone,
        session=session,
        weekday=weekday,
        hour=hour,
        is_weekend=is_weekend,
        halving_phase=halving_phase,
        volatility_regime=vol_regime,
        fractal_clusters=clusters,
        patterns=patterns,
        investor_behaviors=behaviors,
        bullish_pattern_score=round(bullish_score, 3),
        bearish_pattern_score=round(bearish_score, 3),
        pattern_signal=pattern_signal,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _detect_killzone(hour: int) -> str | None:
    for name, (start, end) in KILLZONE_WINDOWS.items():
        if start <= hour < end:
            return name
    return None


def _detect_session(hour: int) -> str:
    if 0 <= hour < 7:
        return "asian"
    if 7 <= hour < 13:
        return "london"
    if 13 <= hour < 20:
        return "ny"
    return "ny_close"


def _detect_halving_phase(now_ms: int) -> str:
    for i, halving in enumerate(HALVING_DATES_MS):
        next_halving = HALVING_DATES_MS[i + 1] if i + 1 < len(HALVING_DATES_MS) else halving + 126144000000
        progress = (now_ms - halving) / (next_halving - halving)
        if progress < 0:
            return "pre_halving"
        if progress < 0.15:
            return "post_halving_reaccumulation"
        if progress < 0.55:
            return "mid_cycle_bull"
        if progress < 0.8:
            return "late_cycle_manipulation"
        return "pre_halving_run"
    return "mid_cycle"


def _volatility_regime(metrics: MarketMetrics | None) -> str:
    if not metrics:
        return "unknown"
    vs = metrics.volatility_score
    atr_pct = (metrics.atr14 / (metrics.ema20 or 1)) * 100
    if atr_pct < 0.05:
        return "extreme_low"
    if atr_pct < 0.08:
        return "low"
    if atr_pct < 0.15:
        return "normal"
    if atr_pct < 0.25:
        return "elevated"
    return "high"


def _fractal_clusters(candles: list[Candle], metrics: MarketMetrics | None) -> list[str]:
    if not metrics or len(candles) < 20:
        return []
    clusters: list[str] = []
    close = candles[-1].close
    atr = metrics.atr14
    pivots: list[float] = []
    for i in range(5, len(candles) - 5, 5):
        pivots.append(candles[i].close)
    for p in pivots:
        dist = abs(p - close) / (atr or 1)
        if dist < 1.5:
            clusters.append(f"near_pivot_{p:.0f}")
    return list(set(clusters))[:5]


# ═══════════════════════════════════════════════════════════════════════════
#  BTC MOVEMENT BEHAVIOR PATTERNS
# ═══════════════════════════════════════════════════════════════════════════

def _killzone_reversal_pattern(
    candles: list[Candle],
    swings: list[Swing],
    killzone: str | None,
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    if not killzone or not metrics or len(candles) < 12:
        return None
    recent = candles[-12:]
    close = recent[-1].close
    atr = metrics.atr14
    high = max(c.high for c in recent)
    low = min(c.low for c in recent)
    range_pct = (high - low) / (close or 1)

    # Killzone reversal: price expanded then reversed in killzone window
    body_sizes = [abs(c.close - c.open) / (c.high - c.low + 0.01) for c in recent[-4:]]
    avg_body_ratio = statistics.mean(body_sizes)

    if range_pct > atr * 1.2 / (close or 1) and avg_body_ratio > 0.55:
        direction = "bullish" if recent[-1].close > recent[-4].close else "bearish"
        score = _clamp(min(range_pct * 80, 0.3) + (atr / (close or 1)) * 15, 0.0, 0.4)
        return BtcPattern(
            id=stable_id("btc_pat", "killzone_rev", killzone, recent[-1].timestamp),
            timestamp=recent[-1].timestamp,
            name=f"killzone_reversal_{killzone}",
            direction=direction,
            confidence=round(_clamp(score + 0.4, 0, 0.9), 2),
            score=round(score, 3),
            description=f"Killzone {killzone}: directional expansion + body confirmation suggests {direction} reversal pressure",
            candle_count=12,
        )
    return None


def _volatility_squeeze_breakout(
    candles: list[Candle],
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    if not metrics or len(candles) < 30:
        return None
    recent = candles[-30:]
    atr14 = metrics.atr14

    atr_values: list[float] = []
    for i in range(14, len(recent)):
        tr = max(
            recent[i].high - recent[i].low,
            abs(recent[i].high - recent[i - 1].close),
            abs(recent[i].low - recent[i - 1].close),
        )
        atr_values.append(tr)
    if len(atr_values) < 15:
        return None
    atr_series = []
    for i in range(14, len(atr_values)):
        atr_series.append(sum(atr_values[i - 14 : i]) / 14)
    if len(atr_series) < 10:
        return None

    current_atr = atr_series[-1]
    atr_min = min(atr_series[-15:])
    atr_max = max(atr_series[-15:])
    squeeze_ratio = (current_atr - atr_min) / (atr_max - atr_min + 0.01)
    latest = recent[-1]
    prev = recent[-2]
    close = latest.close

    body_direction = 1 if close >= latest.open else -1
    body_size = abs(close - latest.open) / (atr14 or 1)

    if squeeze_ratio < 0.25 and body_size > 1.0:
        direction = "bullish" if body_direction > 0 else "bearish"
        score = _clamp((1 - squeeze_ratio) * 0.25 + body_size * 0.08, 0.0, 0.4)
        return BtcPattern(
            id=stable_id("btc_pat", "vol_squeeze", direction, latest.timestamp),
            timestamp=latest.timestamp,
            name="volatility_squeeze_breakout",
            direction=direction,
            confidence=round(_clamp(score + 0.35, 0, 0.9), 2),
            score=round(score, 3),
            description=f"Volatility squeeze breakout: ATR compressed to {squeeze_ratio:.0%} of range then expanded {body_size:.1f}x with {direction} body",
            candle_count=30,
        )
    return None


def _weekend_drift_pattern(
    candles: list[Candle],
    is_weekend: bool,
    weekday: int,
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    if not metrics or len(candles) < 12:
        return None
    recent = candles[-12:]
    close = recent[-1].close
    open_12 = recent[0].open
    drift_pct = (close - open_12) / (open_12 or 1)

    if is_weekend:
        # BTC tends to drift with lower liquidity on weekends
        low_liquidity_vol = (max(c.high for c in recent) - min(c.low for c in recent)) / (close or 1)
        if low_liquidity_vol > metrics.atr14 * 0.5 / (close or 1):
            direction = "bullish" if drift_pct > 0 else "bearish"
            score = _clamp(abs(drift_pct) * 2.5, 0.0, 0.25)
            day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][weekday]
            return BtcPattern(
                id=stable_id("btc_pat", "weekend_drift", direction, recent[-1].timestamp),
                timestamp=recent[-1].timestamp,
                name="weekend_liquidity_drift",
                direction=direction,
                confidence=round(_clamp(score + 0.3, 0, 0.85), 2),
                score=round(score, 3),
                description=f"Weekend ({day_name}) low-liquidity drift: BTC moved {drift_pct*100:.1f}% with thin liquidity, likely to reverse on session open",
                candle_count=12,
            )

    # Monday open / Friday close patterns
    if weekday == 0 and len(candles) > 3:
        direction = "bullish" if drift_pct > 0 else "bearish"
        score = _clamp(abs(drift_pct) * 2, 0.0, 0.2)
        return BtcPattern(
            id=stable_id("btc_pat", "monday_open", direction, recent[-1].timestamp),
            timestamp=recent[-1].timestamp,
            name="monday_session_open",
            direction=direction,
            confidence=round(_clamp(score + 0.25, 0, 0.8), 2),
            score=round(score, 3),
            description=f"Monday open: BTC {direction} drift of {drift_pct*100:.1f}% sets weekly tone",
            candle_count=6,
        )
    if weekday == 4:
        direction = "bullish" if drift_pct > 0 else "bearish"
        score = _clamp(abs(drift_pct) * 1.5, 0.0, 0.15)
        return BtcPattern(
            id=stable_id("btc_pat", "friday_close", direction, recent[-1].timestamp),
            timestamp=recent[-1].timestamp,
            name="friday_position_squaring",
            direction=direction,
            confidence=round(_clamp(score + 0.2, 0, 0.75), 2),
            score=round(score, 3),
            description=f"Friday close: position squaring, BTC {drift_pct*100:.1f}%",
            candle_count=6,
        )
    return None


def _halving_cycle_behavior(
    candles: list[Candle],
    halving_phase: str,
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    if not metrics or len(candles) < 20:
        return None
    recent = candles[-20:]
    close = recent[-1].close
    displacing = metrics.displacement_ratio

    phase_patterns = {
        "pre_halving": ("bullish", 0.18, "Pre-halving: BTC historically rallies 3-6 months before halving"),
        "post_halving_reaccumulation": ("neutral", 0.12, "Post-halving: BTC reaccumulates for 3-6 months before next leg"),
        "mid_cycle_bull": ("bullish", 0.22, "Mid-cycle: BTC in strongest bullish phase, buying dips works historically"),
        "late_cycle_manipulation": ("bearish", 0.16, "Late-cycle: BTC manipulation zone, sharp moves both ways before pre-halving run"),
        "pre_halving_run": ("bullish", 0.2, "Pre-halving run-up: BTC typically sees parabolic move 6-12 months before halving"),
    }
    if halving_phase not in phase_patterns:
        return None

    direction, base_score, desc = phase_patterns[halving_phase]
    score = _clamp(base_score + displacing * 0.04, 0.0, 0.35)

    return BtcPattern(
        id=stable_id("btc_pat", "halving", halving_phase, recent[-1].timestamp),
        timestamp=recent[-1].timestamp,
        name=f"halving_cycle_{halving_phase}",
        direction=direction,
        confidence=round(_clamp(score + 0.35, 0, 0.85), 2),
        score=round(score, 3),
        description=desc,
        candle_count=20,
    )


def _session_open_gap_fill(
    candles: list[Candle],
    session: str,
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    if not metrics or len(candles) < 6 or session == "asian":
        return None
    recent = candles[-6:]
    close = recent[-1].close
    open_6 = recent[0].open
    gap = (close - open_6) / (open_6 or 1)
    atr_pct = metrics.atr14 / (close or 1)

    # Session open gap: BTC often fills gaps between sessions
    if abs(gap) > atr_pct * 1.2:
        direction = "bearish" if gap > 0 else "bullish"
        score = _clamp(abs(gap) * 3, 0.0, 0.3)
        return BtcPattern(
            id=stable_id("btc_pat", "session_gap", session, recent[-1].timestamp),
            timestamp=recent[-1].timestamp,
            name=f"session_open_gap_{session}",
            direction=direction,
            confidence=round(_clamp(score + 0.3, 0, 0.85), 2),
            score=round(score, 3),
            description=f"{session.capitalize()} session open gap: BTC gapped {gap*100:.1f}%, historical bias to fill",
            candle_count=6,
        )
    return None


def _liquidation_cascade_pattern(
    candles: list[Candle],
    liquidity_events: list[LiquidityEvent],
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    if not metrics or len(liquidity_events) < 2 or len(candles) < 10:
        return None
    recent = candles[-10:]
    close = recent[-1].close
    recent_events = [e for e in liquidity_events if e.timestamp >= recent[0].timestamp]

    if len(recent_events) < 2:
        return None

    # Cluster of liquidity sweeps in same direction = cascade
    sell_sweeps = [e for e in recent_events if e.side == "sell_side"]
    buy_sweeps = [e for e in recent_events if e.side == "buy_side"]

    side, events, cascade_dir = ("sell_side", sell_sweeps, "bullish") if len(sell_sweeps) >= len(buy_sweeps) else ("buy_side", buy_sweeps, "bearish")
    if len(events) < 2:
        return None

    avg_score = statistics.mean(e.engineered_score for e in events)
    total_displacement = sum(e.displacement for e in events)
    score = _clamp(avg_score * 0.15 + min(total_displacement * 0.04, 0.1), 0.0, 0.35)

    return BtcPattern(
        id=stable_id("btc_pat", "liq_cascade", cascade_dir, recent[-1].timestamp),
        timestamp=recent[-1].timestamp,
        name="liquidation_cascade",
        direction=cascade_dir,
        confidence=round(_clamp(score + 0.35, 0, 0.9), 2),
        score=round(score, 3),
        description=f"Liquidation cascade: {len(events)} consecutive {side.replace('_', '-')} sweeps ({avg_score:.0%} avg engineered score), suggests exhaustion",
        candle_count=len(candles[-10:]),
    )


def _fractal_support_resistance(
    candles: list[Candle],
    swings: list[Swing],
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    if not metrics or len(swings) < 10:
        return None
    close = candles[-1].close
    atr = metrics.atr14

    highs = sorted(set(s.price for s in swings if s.kind == "high"), reverse=True)
    lows = sorted(set(s.price for s in swings if s.kind == "low"))

    proximity_score_bullish = 0.0
    proximity_score_bearish = 0.0
    for h in highs[:5]:
        dist = abs(h - close) / (atr or 1)
        if dist < 0.8 and close < h:
            proximity_score_bearish += (1 - dist / 0.8) * 0.08
    for l in lows[:5]:
        dist = abs(l - close) / (atr or 1)
        if dist < 0.8 and close > l:
            proximity_score_bullish += (1 - dist / 0.8) * 0.08

    if proximity_score_bullish > 0.12:
        return BtcPattern(
            id=stable_id("btc_pat", "fractal_support", close, candles[-1].timestamp),
            timestamp=candles[-1].timestamp,
            name="fractal_support_bounce",
            direction="bullish",
            confidence=round(_clamp(proximity_score_bullish + 0.5, 0, 0.9), 2),
            score=round(proximity_score_bullish, 3),
            description=f"Fractal support: price near {len(lows)} historical swing lows within {atr:.0f}, BTC tends to bounce from fractal levels",
            candle_count=len(candles[-40:]),
        )
    if proximity_score_bearish > 0.12:
        return BtcPattern(
            id=stable_id("btc_pat", "fractal_resistance", close, candles[-1].timestamp),
            timestamp=candles[-1].timestamp,
            name="fractal_resistance_rejection",
            direction="bearish",
            confidence=round(_clamp(proximity_score_bearish + 0.5, 0, 0.9), 2),
            score=round(proximity_score_bearish, 3),
            description=f"Fractal resistance: price near {len(highs)} historical swing highs within {atr:.0f}, BTC tends to reject from fractal levels",
            candle_count=len(candles[-40:]),
        )
    return None


def _time_price_reversal(
    candles: list[Candle],
    swings: list[Swing],
    hour: int,
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    """BTC has specific times when reversals are statistically more likely."""
    if not metrics or len(candles) < 6:
        return None
    if hour not in {1, 8, 14, 16, 21}:  # Known BTC reversal windows
        return None
    recent = candles[-6:]
    close = recent[-1].close
    atr = metrics.atr14
    range_6 = max(c.high for c in recent) - min(c.low for c in recent)

    if range_6 > atr * 0.6:
        direction = "bullish" if recent[-1].close > recent[-3].close else "bearish"
        return BtcPattern(
            id=stable_id("btc_pat", "time_reversal", hour, recent[-1].timestamp),
            timestamp=recent[-1].timestamp,
            name=f"time_price_reversal_{hour}h",
            direction=direction,
            confidence=0.55,
            score=0.12,
            description=f"Hourly reversal window ({hour}:00 UTC): BTC has statistically higher reversal probability at this time",
            candle_count=6,
        )
    return None


def _volume_climax_pattern(
    candles: list[Candle],
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    """BTC volume climax (high vol + wide range) often signals exhaustion."""
    if not metrics or len(candles) < 5:
        return None
    recent = candles[-5:]
    latest = recent[-1]
    atr = metrics.atr14
    vz = metrics.volume_zscore

    body = abs(latest.close - latest.open)
    range_c = latest.high - latest.low

    if vz > 1.5 and range_c > atr * 0.8 and body > range_c * 0.6:
        direction = "bearish" if latest.close < latest.open else "bullish"
        score = _clamp(min(vz * 0.06, 0.15) + (body / (atr or 1)) * 0.06, 0.0, 0.3)
        return BtcPattern(
            id=stable_id("btc_pat", "volume_climax", direction, latest.timestamp),
            timestamp=latest.timestamp,
            name="volume_climax_exhaustion",
            direction=direction,
            confidence=round(_clamp(score + 0.4, 0, 0.85), 2),
            score=round(score, 3),
            description=f"Volume climax: z-score {vz:.1f} with {direction} body, BTC often reverses after climax volume",
            candle_count=5,
        )
    return None


def _double_distribution_pattern(
    candles: list[Candle],
    swings: list[Swing],
    metrics: MarketMetrics | None,
) -> BtcPattern | None:
    """Wyckoff-style double distribution: two equal highs with divergence."""
    if not metrics or len(swings) < 6:
        return None
    highs = [s for s in swings if s.kind == "high"]
    if len(highs) < 4:
        return None
    last_two = highs[-4:]
    clustered = []
    for h in last_two:
        for h2 in last_two:
            if h is h2:
                continue
            if abs(h.price - h2.price) / (h.price or 1) < 0.003:
                clustered.append((h, h2))
    if clustered and len(clustered) >= 2:
        avg_high = statistics.mean(c[0].price for c in clustered)
        if candles[-1].close < avg_high:
            return BtcPattern(
                id=stable_id("btc_pat", "double_dist", avg_high, candles[-1].timestamp),
                timestamp=candles[-1].timestamp,
                name="double_distribution_top",
                direction="bearish",
                confidence=0.6,
                score=0.15,
                description=f"Double distribution: equal highs near {avg_high:.0f}, BTC often breaks down after retesting resistance twice",
                candle_count=len(candles[-40:]),
            )
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  INVESTOR BEHAVIOR PATTERNS
# ═══════════════════════════════════════════════════════════════════════════

def _smart_money_distribution(
    candles: list[Candle],
    swings: list[Swing],
    metrics: MarketMetrics | None,
) -> BtcInvestorBehavior | None:
    """Smart money distributes to retail: long upper wicks on green candles + high volume."""
    if not metrics or len(candles) < 10:
        return None
    recent = candles[-10:]
    distribution_candles = 0
    total_vol = 0.0
    for c in recent:
        if c.close > c.open:
            upper_wick = c.high - c.close
            body = c.close - c.open
            if upper_wick > body * 0.6 and c.volume > 0:
                distribution_candles += 1
                total_vol += c.volume
    ratio = distribution_candles / len(recent)
    if ratio > 0.3:
        intensity = _clamp(ratio * 0.6 + min(total_vol / 1e6, 0.3), 0.0, 0.7)
        return BtcInvestorBehavior(
            id=stable_id("btc_inv", "distribution", candles[-1].timestamp),
            timestamp=candles[-1].timestamp,
            behavior_type="smart_money_distribution",
            side="bearish",
            confidence=round(_clamp(intensity + 0.2, 0, 0.9), 2),
            intensity=round(intensity, 3),
            description=f"Smart money distribution: {distribution_candles}/{len(recent)} green candles have long upper wicks ({ratio:.0%}), institutions selling into retail buying",
            price_level=candles[-1].close,
            volume_ratio=round(total_vol / (statistics.mean([c.volume for c in recent[:5]]) or 1), 2),
        )
    return None


def _smart_money_accumulation(
    candles: list[Candle],
    swings: list[Swing],
    metrics: MarketMetrics | None,
) -> BtcInvestorBehavior | None:
    """Smart money accumulates from retail: long lower wicks on red candles + high volume."""
    if not metrics or len(candles) < 10:
        return None
    recent = candles[-10:]
    accumulation_candles = 0
    total_vol = 0.0
    for c in recent:
        if c.close < c.open:
            lower_wick = c.close - c.low
            body = c.open - c.close
            if lower_wick > body * 0.6 and c.volume > 0:
                accumulation_candles += 1
                total_vol += c.volume
    ratio = accumulation_candles / len(recent)
    if ratio > 0.3:
        intensity = _clamp(ratio * 0.6 + min(total_vol / 1e6, 0.3), 0.0, 0.7)
        return BtcInvestorBehavior(
            id=stable_id("btc_inv", "accumulation", candles[-1].timestamp),
            timestamp=candles[-1].timestamp,
            behavior_type="smart_money_accumulation",
            side="bullish",
            confidence=round(_clamp(intensity + 0.2, 0, 0.9), 2),
            intensity=round(intensity, 3),
            description=f"Smart money accumulation: {accumulation_candles}/{len(recent)} red candles have long lower wicks ({ratio:.0%}), institutions accumulating from retail sellers",
            price_level=candles[-1].close,
            volume_ratio=round(total_vol / (statistics.mean([c.volume for c in recent[:5]]) or 1), 2),
        )
    return None


def _retail_fomo_breakout(
    candles: list[Candle],
    metrics: MarketMetrics | None,
    regime: MarketRegime | None,
) -> BtcInvestorBehavior | None:
    """Retail FOMO: breakout above recent range with surge volume but tight close = fakeout."""
    if not metrics or len(candles) < 15:
        return None
    recent = candles[-15:]
    latest = recent[-1]

    range_high = max(c.high for c in recent[:-1])
    range_low = min(c.low for c in recent[:-1])
    range_width = (range_high - range_low) / (range_low or 1)

    broke_resistance = latest.close > range_high and latest.high > range_high
    high_vol = metrics.volume_zscore > 0.8
    tight_close = (latest.high - latest.close) / (latest.high - latest.low + 0.01) < 0.3

    if broke_resistance and high_vol and tight_close:
        intensity = _clamp(metrics.volume_zscore * 0.1 + range_width * 0.5, 0.0, 0.6)
        return BtcInvestorBehavior(
            id=stable_id("btc_inv", "fomo_breakout", latest.timestamp),
            timestamp=latest.timestamp,
            behavior_type="retail_fomo_breakout",
            side="bearish",
            confidence=round(_clamp(intensity + 0.25, 0, 0.8), 2),
            intensity=round(intensity, 3),
            description=f"Retail FOMO breakout above {range_high:.0f}: volume z-score {metrics.volume_zscore:.1f}, retail chasing breakouts, smart money may distribute into strength",
            price_level=latest.close,
            volume_ratio=round(metrics.volume_zscore, 2),
        )

    # Breakdown FOMO (retail panic selling)
    broke_support = latest.close < range_low and latest.low < range_low
    if broke_support and high_vol and tight_close:
        intensity = _clamp(metrics.volume_zscore * 0.1 + range_width * 0.5, 0.0, 0.6)
        return BtcInvestorBehavior(
            id=stable_id("btc_inv", "fomo_breakdown", latest.timestamp),
            timestamp=latest.timestamp,
            behavior_type="retail_panic_breakdown",
            side="bullish",
            confidence=round(_clamp(intensity + 0.25, 0, 0.8), 2),
            intensity=round(intensity, 3),
            description=f"Retail panic breakdown below {range_low:.0f}: volume z-score {metrics.volume_zscore:.1f}, weak hands selling, smart money may accumulate",
            price_level=latest.close,
            volume_ratio=round(metrics.volume_zscore, 2),
        )
    return None


def _panic_capitulation(
    candles: list[Candle],
    metrics: MarketMetrics | None,
    liquidity_events: list[LiquidityEvent],
) -> BtcInvestorBehavior | None:
    """Panic capitulation: wide-range red candle, volume spike, long lower wick = seller exhaustion."""
    if not metrics or len(candles) < 5:
        return None
    latest = candles[-1]
    atr = metrics.atr14
    vz = metrics.volume_zscore

    is_red = latest.close < latest.open
    wide_range = (latest.high - latest.low) > atr * 0.8
    high_vol = vz > 1.2
    long_lower_wick = (latest.close - latest.low) / (latest.high - latest.low + 0.01) > 0.5

    if is_red and wide_range and high_vol and long_lower_wick:
        intensity = _clamp(min(vz * 0.1, 0.2) + 0.2 + (latest.close - latest.low) / (atr or 1) * 0.1, 0.0, 0.7)
        return BtcInvestorBehavior(
            id=stable_id("btc_inv", "capitulation", latest.timestamp),
            timestamp=latest.timestamp,
            behavior_type="panic_capitulation",
            side="bullish",
            confidence=round(_clamp(intensity + 0.3, 0, 0.9), 2),
            intensity=round(intensity, 3),
            description=f"Panic capitulation: z-score {vz:.1f}, wide range, long lower wick. Weak hands dumping to smart money who absorbs at lows",
            price_level=latest.low,
            volume_ratio=round(vz, 2),
        )
    return None


def _stop_hunt_reversal(
    candles: list[Candle],
    liquidity_events: list[LiquidityEvent],
    swings: list[Swing],
    metrics: MarketMetrics | None,
) -> BtcInvestorBehavior | None:
    """Stop hunt: liquidity sweep that immediately reverses = institutions hunting stops."""
    if not metrics or len(liquidity_events) < 1 or len(candles) < 5:
        return None
    latest = candles[-1]
    recent_events = [e for e in liquidity_events if e.timestamp >= candles[-5].timestamp]

    if not recent_events:
        return None

    best = max(recent_events, key=lambda e: e.engineered_score)
    displacement = best.displacement
    reclaimed = best.reclaimed
    depth_ratio = best.sweep_depth / (metrics.atr14 or 1)

    if reclaimed and displacement < 1.5 and depth_ratio < 0.4:
        direction = "bullish" if best.side == "sell_side" else "bearish"
        intensity = _clamp(best.engineered_score * 0.4 + (1 - displacement / 2) * 0.2, 0.0, 0.65)
        return BtcInvestorBehavior(
            id=stable_id("btc_inv", "stop_hunt", best.id[-8:], latest.timestamp),
            timestamp=latest.timestamp,
            behavior_type="stop_hunt_reversal",
            side=direction,
            confidence=round(_clamp(intensity + 0.3, 0, 0.9), 2),
            intensity=round(intensity, 3),
            description=f"Stop hunt + reversal: {best.side.replace('_', '-')} swept {best.sweep_depth:.1f} then reclaimed (engineered {best.engineered_score:.0%}), classic smart money stop hunt",
            price_level=best.swept_level,
            volume_ratio=round(best.displacement, 2),
        )
    return None


def _order_block_wyckoff(
    candles: list[Candle],
    order_blocks: list[OrderBlock],
    swings: list[Swing],
    metrics: MarketMetrics | None,
) -> BtcInvestorBehavior | None:
    """Wyckoff spring/UTAD using order blocks: BTC testing known OB with rejection = institutional defense."""
    if not metrics or len(order_blocks) < 2 or len(candles) < 10:
        return None
    latest = candles[-1]
    close = latest.close
    atr = metrics.atr14

    for ob in order_blocks[-6:]:
        if ob.is_breaker:
            continue
        mid = (ob.top + ob.bottom) / 2
        dist = abs(close - mid) / (atr or 1)
        if dist < 0.5:
            body_dir = close >= latest.open
            ob_dir = ob.direction == "bullish"
            if body_dir and ob_dir:
                intensity = _clamp((1 - dist / 0.5) * 0.35, 0.0, 0.55)
                return BtcInvestorBehavior(
                    id=stable_id("btc_inv", "ob_wyckoff", ob.id[-8:], latest.timestamp),
                    timestamp=latest.timestamp,
                    behavior_type="order_block_institutional_defense",
                    side="bullish",
                    confidence=round(_clamp(intensity + 0.4, 0, 0.9), 2),
                    intensity=round(intensity, 3),
                    description=f"Institutional OB defense: BTC bounced from {ob.direction} order block ({ob.bottom:.0f}-{ob.top:.0f}), Wyckoff spring pattern, smart money defends key levels",
                    price_level=mid,
                    volume_ratio=0.0,
                )
            if not body_dir and not ob_dir:
                intensity = _clamp((1 - dist / 0.5) * 0.35, 0.0, 0.55)
                return BtcInvestorBehavior(
                    id=stable_id("btc_inv", "ob_wyckoff_reject", ob.id[-8:], latest.timestamp),
                    timestamp=latest.timestamp,
                    behavior_type="order_block_institutional_rejection",
                    side="bearish",
                    confidence=round(_clamp(intensity + 0.4, 0, 0.9), 2),
                    intensity=round(intensity, 3),
                    description=f"Institutional OB rejection: BTC rejected from {ob.direction} order block ({ob.bottom:.0f}-{ob.top:.0f}), UTAD pattern, smart money distributes",
                    price_level=mid,
                    volume_ratio=0.0,
                )
    return None


def _short_squeeze_pattern(
    candles: list[Candle],
    liquidity_events: list[LiquidityEvent],
    metrics: MarketMetrics | None,
) -> BtcInvestorBehavior | None:
    """Short squeeze: rapid up moves after sweeping sell-side liquidity = shorts trapped."""
    if not metrics or len(liquidity_events) < 1 or len(candles) < 8:
        return None
    latest = candles[-1]
    recent = candles[-8:]
    recent_sell_events = [e for e in liquidity_events if e.side == "sell_side" and e.timestamp >= recent[0].timestamp]

    if not recent_sell_events:
        return None

    move_up = (latest.close - recent[0].open) / (recent[0].open or 1)
    avg_event_score = statistics.mean(e.engineered_score for e in recent_sell_events)
    candles_up = sum(1 for c in recent[-4:] if c.close > c.open)

    if move_up > 0.005 and avg_event_score > 0.5 and candles_up >= 3:
        intensity = _clamp(move_up * 30 + avg_event_score * 0.2, 0.0, 0.6)
        return BtcInvestorBehavior(
            id=stable_id("btc_inv", "short_squeeze", latest.timestamp),
            timestamp=latest.timestamp,
            behavior_type="short_squeeze",
            side="bullish",
            confidence=round(_clamp(intensity + 0.3, 0, 0.85), 2),
            intensity=round(intensity, 3),
            description=f"Short squeeze: BTC swept sell-side liquidity ({len(recent_sell_events)} events, {avg_event_score:.0%} score) then rallied {move_up*100:.2f}%, shorts trapped",
            price_level=latest.high,
            volume_ratio=round(move_up * 100, 2),
        )
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  UTILITY
# ═══════════════════════════════════════════════════════════════════════════

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
