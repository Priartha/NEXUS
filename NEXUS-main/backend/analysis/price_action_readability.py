"""
Price Action Readability Module for NEXUS

Scores how clear and tradeable the current price action is:
- Candle pattern clarity (clean vs messy candles)
- Trend definition quality (smooth vs choppy)
- Range boundary clarity (well-defined vs fuzzy)
- Noise vs signal detection
- Structure reliability scoring
- Overall readability grade
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from backend.models.types import Candle, LiquidityLevel, MarketRegime, Swing


@dataclass
class CandleQuality:
    """Quality metrics for individual candles."""
    timestamp: int
    body_ratio: float  # body size / total range (0-1)
    wick_balance: float  # -1 (lower wick only) to +1 (upper wick only)
    clarity: float  # 0-1, how decisive the candle is
    is_doji: bool
    is_marubozu: bool
    is_hammer: bool
    is_shooting_star: bool


@dataclass
class TrendQuality:
    """Quality metrics for current trend."""
    timestamp: int
    smoothness: float  # 0-1, how smooth the trend is
    consistency: float  # 0-1, how consistent directional moves are
    pullback_quality: float  # 0-1, are pullbacks shallow and orderly?
    acceleration: float  # -1 (decelerating) to +1 (accelerating)
    is_choppy: bool
    reliability: float  # 0-1, how reliable the trend is


@dataclass
class RangeQuality:
    """Quality metrics for current range."""
    timestamp: int
    boundary_clarity: float  # 0-1, how well-defined are S/R levels
    bounce_consistency: float  # 0-1, do price respect boundaries?
    internal_structure: float  # 0-1, is there clear internal structure?
    is_breaking_out: bool
    breakout_quality: float  # 0-1, if breaking out, how valid?
    reliability: float  # 0-1, how reliable the range is


@dataclass
class ReadabilitySnapshot:
    """Complete price action readability assessment."""
    timestamp: int
    overall_score: float  # 0-1, how readable/tradeable price action is
    grade: str  # A+, A, B+, B, C+, C, D, F
    candle_clarity: float  # 0-1
    trend_quality: Optional[TrendQuality]
    range_quality: Optional[RangeQuality]
    noise_level: float  # 0-1, how much noise vs signal
    structure_reliability: float  # 0-1
    tradeability: str  # excellent, good, fair, poor, avoid
    dominant_pattern: str  # trending, ranging, chopping, breaking_out
    key_observations: list[str] = field(default_factory=list)
    candle_qualities: list[CandleQuality] = field(default_factory=list)


def _analyze_candle_quality(candle: Candle) -> CandleQuality:
    """Analyze quality of a single candle."""
    body = abs(candle.close - candle.open)
    range_size = candle.high - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low

    body_ratio = body / range_size if range_size > 0 else 0.0

    # Wick balance: -1 = all lower wick, +1 = all upper wick
    total_wick = upper_wick + lower_wick
    wick_balance = (upper_wick - lower_wick) / total_wick if total_wick > 0 else 0.0

    # Clarity: high body ratio = clear direction
    clarity = body_ratio

    # Pattern detection
    is_doji = body_ratio < 0.1
    is_marubozu = body_ratio > 0.9 and wick_balance > -0.2 and wick_balance < 0.2

    # Hammer: small body at top, long lower wick
    is_hammer = (
        body_ratio < 0.3 and
        lower_wick > body * 2 and
        upper_wick < body * 0.5
    )

    # Shooting star: small body at bottom, long upper wick
    is_shooting_star = (
        body_ratio < 0.3 and
        upper_wick > body * 2 and
        lower_wick < body * 0.5
    )

    return CandleQuality(
        timestamp=candle.timestamp,
        body_ratio=round(body_ratio, 3),
        wick_balance=round(wick_balance, 3),
        clarity=round(clarity, 3),
        is_doji=is_doji,
        is_marubozu=is_marubozu,
        is_hammer=is_hammer,
        is_shooting_star=is_shooting_star
    )


def _compute_candle_clarity(candles: list[Candle]) -> tuple[float, list[CandleQuality]]:
    """Compute overall candle clarity score."""
    if len(candles) < 10:
        return 0.5, []

    recent = candles[-20:]
    qualities = [_analyze_candle_quality(c) for c in recent]

    # Average clarity
    avg_clarity = sum(q.clarity for q in qualities) / len(qualities)

    # Penalize doji clusters
    doji_count = sum(1 for q in qualities if q.is_doji)
    doji_penalty = doji_count * 0.05

    # Reward marubozu (strong conviction candles)
    marubozu_count = sum(1 for q in qualities if q.is_marubozu)
    marubozu_bonus = marubozu_count * 0.03

    # Penalize erratic wick patterns
    wick_volatility = sum(abs(q.wick_balance) for q in qualities) / len(qualities)
    # Moderate wick variation is normal, extreme is noisy
    wick_penalty = max(0, (1.0 - wick_volatility) * 0.1)

    score = avg_clarity - doji_penalty + marubozu_bonus + wick_penalty
    score = max(0.0, min(1.0, score))

    return score, qualities


def _assess_trend_quality(candles: list[Candle], swings: list[Swing] | None) -> TrendQuality:
    """Assess how clean and tradeable the current trend is."""
    if len(candles) < 30:
        return TrendQuality(
            timestamp=candles[-1].timestamp if candles else 0,
            smoothness=0.5,
            consistency=0.5,
            pullback_quality=0.5,
            acceleration=0.0,
            is_choppy=True,
            reliability=0.5
        )

    recent = candles[-30:]
    closes = [c.close for c in recent]
    timestamp = candles[-1].timestamp

    # 1. Smoothness - how consistently price moves in one direction
    # Use linear regression R-squared as smoothness proxy
    n = len(closes)
    x_mean = (n - 1) / 2
    y_mean = sum(closes) / n

    ss_tot = sum((y - y_mean) ** 2 for y in closes)
    if ss_tot == 0:
        smoothness = 0.0
    else:
        # Simple linear regression
        slope = sum((i - x_mean) * (closes[i] - y_mean) for i in range(n)) / ss_tot
        intercept = y_mean - slope * x_mean
        ss_res = sum((closes[i] - (slope * i + intercept)) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot)
        smoothness = max(0.0, r_squared)

    # 2. Consistency - how many candles move in trend direction
    trend_dir = 1 if closes[-1] > closes[0] else -1
    aligned_candles = sum(1 for i in range(1, len(closes)) if (closes[i] - closes[i-1]) * trend_dir > 0)
    consistency = aligned_candles / (len(closes) - 1)

    # 3. Pullback quality - are pullbacks shallow and brief?
    pullbacks = []
    current_pullback = 0
    for i in range(1, len(closes)):
        move = (closes[i] - closes[i-1]) * trend_dir
        if move < 0:  # Against trend = pullback
            current_pullback += abs(move)
        else:
            if current_pullback > 0:
                pullbacks.append(current_pullback)
            current_pullback = 0

    if pullbacks and trend_dir * (closes[-1] - closes[0]) > 0:
        total_move = abs(closes[-1] - closes[0])
        avg_pullback = sum(pullbacks) / len(pullbacks)
        # Good pullbacks are < 38.2% of total move
        pullback_quality = max(0.0, 1.0 - (avg_pullback / (total_move + 1e-9)))
    else:
        pullback_quality = 0.5

    # 4. Acceleration - is trend speeding up or slowing down?
    first_half_moves = [closes[i] - closes[i-1] for i in range(1, n//2)]
    second_half_moves = [closes[i] - closes[i-1] for i in range(n//2, n)]

    first_half_trend = sum(m * trend_dir for m in first_half_moves if m * trend_dir > 0)
    second_half_trend = sum(m * trend_dir for m in second_half_moves if m * trend_dir > 0)

    if first_half_trend > 0:
        acceleration = (second_half_trend - first_half_trend) / first_half_trend
        acceleration = max(-1.0, min(1.0, acceleration))
    else:
        acceleration = 0.0

    # 5. Choppy detection
    direction_changes = sum(1 for i in range(1, len(closes)) if (closes[i] - closes[i-1]) * (closes[i-1] - closes[max(0,i-2)]) < 0)
    is_choppy = direction_changes > n * 0.6

    # 6. Overall reliability
    reliability = (
        smoothness * 0.30 +
        consistency * 0.25 +
        pullback_quality * 0.20 +
        (1.0 if not is_choppy else 0.0) * 0.15 +
        max(0, acceleration) * 0.10
    )

    return TrendQuality(
        timestamp=timestamp,
        smoothness=round(smoothness, 3),
        consistency=round(consistency, 3),
        pullback_quality=round(pullback_quality, 3),
        acceleration=round(acceleration, 3),
        is_choppy=is_choppy,
        reliability=round(reliability, 3)
    )


def _assess_range_quality(candles: list[Candle], liquidity: list[LiquidityLevel] | None) -> RangeQuality:
    """Assess how well-defined and tradeable the current range is."""
    if len(candles) < 30:
        return RangeQuality(
            timestamp=candles[-1].timestamp if candles else 0,
            boundary_clarity=0.5,
            bounce_consistency=0.5,
            internal_structure=0.5,
            is_breaking_out=False,
            breakout_quality=0.0,
            reliability=0.5
        )

    recent = candles[-30:]
    timestamp = candles[-1].timestamp

    # 1. Find range boundaries
    highs = [c.high for c in recent]
    lows = [c.low for c in recent]

    # Use percentile-based boundaries for robustness
    sorted_highs = sorted(highs, reverse=True)
    sorted_lows = sorted(lows)

    range_high = sorted_highs[0]  # Top 1
    range_low = sorted_lows[0]    # Bottom 1
    range_width = range_high - range_low

    if range_width == 0:
        return RangeQuality(
            timestamp=timestamp,
            boundary_clarity=0.0,
            bounce_consistency=0.0,
            internal_structure=0.0,
            is_breaking_out=False,
            breakout_quality=0.0,
            reliability=0.0
        )

    # 2. Boundary clarity - how often does price touch boundaries?
    upper_touches = sum(1 for c in recent if abs(c.high - range_high) / range_width < 0.05)
    lower_touches = sum(1 for c in recent if abs(c.low - range_low) / range_width < 0.05)

    boundary_clarity = min((upper_touches + lower_touches) / 10.0, 1.0)

    # 3. Bounce consistency - do reversals happen at boundaries?
    reversals_at_boundary = 0
    total_boundary_touches = upper_touches + lower_touches

    for i in range(1, len(recent)):
        c = recent[i]
        prev = recent[i-1]

        # Reversal at top
        if abs(prev.high - range_high) / range_width < 0.05 and c.close < prev.close:
            reversals_at_boundary += 1
        # Reversal at bottom
        elif abs(prev.low - range_low) / range_width < 0.05 and c.close > prev.close:
            reversals_at_boundary += 1

    bounce_consistency = reversals_at_boundary / max(total_boundary_touches, 1)

    # 4. Internal structure - is there clear movement within range?
    closes = [c.close for c in recent]
    mid_point = (range_high + range_low) / 2
    crosses_mid = sum(1 for i in range(1, len(closes)) if (closes[i] - mid_point) * (closes[i-1] - mid_point) < 0)

    # Good ranges have 2-6 mid-point crosses in 30 candles
    internal_structure = 1.0 - abs(crosses_mid - 4) / 8.0
    internal_structure = max(0.0, min(1.0, internal_structure))

    # 5. Breakout detection
    current_price = closes[-1]
    is_breaking_out = current_price > range_high * 1.005 or current_price < range_low * 0.995

    # 6. Breakout quality (if breaking out)
    breakout_quality = 0.0
    if is_breaking_out:
        # Check volume
        volumes = [c.volume for c in recent]
        avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 1
        current_vol = volumes[-1]

        vol_confirmation = min(current_vol / avg_vol, 2.0) / 2.0

        # Check if breakout candle is strong
        last_candle = recent[-1]
        body = abs(last_candle.close - last_candle.open)
        range_size = last_candle.high - last_candle.low
        candle_strength = body / range_size if range_size > 0 else 0.0

        breakout_quality = (vol_confirmation * 0.6 + candle_strength * 0.4)

    # 7. Overall reliability
    reliability = (
        boundary_clarity * 0.30 +
        bounce_consistency * 0.30 +
        internal_structure * 0.20 +
        (1.0 - breakout_quality) * 0.20  # Breakouts reduce range reliability
    )

    return RangeQuality(
        timestamp=timestamp,
        boundary_clarity=round(boundary_clarity, 3),
        bounce_consistency=round(bounce_consistency, 3),
        internal_structure=round(internal_structure, 3),
        is_breaking_out=is_breaking_out,
        breakout_quality=round(breakout_quality, 3),
        reliability=round(reliability, 3)
    )


def _compute_noise_level(candles: list[Candle]) -> float:
    """Compute how much noise vs signal in price action."""
    if len(candles) < 20:
        return 0.5

    recent = candles[-20:]
    noise_factors = []

    # 1. Candle-to-candle direction changes
    closes = [c.close for c in recent]
    direction_changes = 0
    for i in range(2, len(closes)):
        prev_dir = closes[i-1] - closes[i-2]
        curr_dir = closes[i] - closes[i-1]
        if prev_dir * curr_dir < 0:
            direction_changes += 1

    change_ratio = direction_changes / (len(closes) - 2)
    noise_factors.append(change_ratio)

    # 2. Wick-to-body ratio (high = noisy)
    total_body = sum(abs(c.close - c.open) for c in recent)
    total_wick = sum((c.high - max(c.open, c.close)) + (min(c.open, c.close) - c.low) for c in recent)

    if total_body > 0:
        wick_body_ratio = total_wick / total_body
        noise_factors.append(min(wick_body_ratio / 2.0, 1.0))
    else:
        noise_factors.append(1.0)

    # 3. Gap analysis (gaps = noise in crypto, but still relevant)
    gaps = sum(1 for i in range(1, len(closes)) if abs(closes[i] - closes[i-1]) / closes[i-1] > 0.01)
    noise_factors.append(min(gaps / 5.0, 1.0))

    # 4. Volume inconsistency
    volumes = [c.volume for c in recent]
    if volumes:
        avg_vol = sum(volumes) / len(volumes)
        vol_std = math.sqrt(sum((v - avg_vol) ** 2 for v in volumes) / len(volumes))
        vol_cv = vol_std / avg_vol if avg_vol > 0 else 0
        noise_factors.append(min(vol_cv / 2.0, 1.0))

    # Average noise
    noise = sum(noise_factors) / len(noise_factors)
    return max(0.0, min(1.0, noise))


def _assess_structure_reliability(
    candles: list[Candle],
    swings: list[Swing] | None,
    liquidity: list[LiquidityLevel] | None,
    regime: MarketRegime | None
) -> float:
    """Assess how reliable the current market structure is."""
    if not swings or len(swings) < 4:
        return 0.3

    reliability = 0.5

    # 1. Swing consistency - do swings form clear HH/HL or LH/LL pattern?
    recent_swings = swings[-10:]
    highs = [s.price for s in recent_swings if s.kind == "high"]
    lows = [s.price for s in recent_swings if s.kind == "low"]

    if len(highs) >= 3:
        # Check for consistent higher highs or lower highs
        hh_count = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        lh_count = len(highs) - 1 - hh_count
        consistency = max(hh_count, lh_count) / (len(highs) - 1)
        reliability += (consistency - 0.5) * 0.3

    if len(lows) >= 3:
        hl_count = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1])
        ll_count = len(lows) - 1 - hl_count
        consistency = max(hl_count, ll_count) / (len(lows) - 1)
        reliability += (consistency - 0.5) * 0.3

    # 2. Liquidity level respect
    if liquidity:
        respected = sum(1 for level in liquidity if level.touch_count >= 2)
        total = len(liquidity)
        if total > 0:
            respect_ratio = respected / total
            reliability += (respect_ratio - 0.5) * 0.2

    # 3. Regime stability
    if regime:
        if regime.confidence > 0.7:
            reliability += 0.1
        elif regime.confidence < 0.4:
            reliability -= 0.1

    # 4. Price action cleanliness (from candles)
    closes = [c.close for c in candles[-20:]]
    if len(closes) >= 10:
        # Count how many candles are "clean" (body > 50% of range)
        clean = sum(1 for c in candles[-20:] if abs(c.close - c.open) / (c.high - c.low + 1e-9) > 0.5)
        clean_ratio = clean / 20
        reliability += (clean_ratio - 0.5) * 0.2

    return max(0.0, min(1.0, reliability))


def _determine_grade(score: float) -> str:
    """Convert readability score to letter grade."""
    if score >= 0.90:
        return "A+"
    elif score >= 0.80:
        return "A"
    elif score >= 0.70:
        return "B+"
    elif score >= 0.60:
        return "B"
    elif score >= 0.50:
        return "C+"
    elif score >= 0.40:
        return "C"
    elif score >= 0.30:
        return "D"
    else:
        return "F"


def _determine_tradeability(score: float) -> str:
    """Convert readability score to tradeability assessment."""
    if score >= 0.80:
        return "excellent"
    elif score >= 0.65:
        return "good"
    elif score >= 0.50:
        return "fair"
    elif score >= 0.35:
        return "poor"
    else:
        return "avoid"


def _determine_dominant_pattern(
    trend_quality: TrendQuality | None,
    range_quality: RangeQuality | None,
    noise_level: float
) -> str:
    """Determine the dominant price action pattern."""
    if noise_level > 0.7:
        return "chopping"

    if trend_quality and trend_quality.reliability > 0.6:
        return "trending"

    if range_quality and range_quality.reliability > 0.6:
        if range_quality.is_breaking_out:
            return "breaking_out"
        return "ranging"

    return "chopping"


def _generate_observations(
    candle_clarity: float,
    trend_quality: TrendQuality | None,
    range_quality: RangeQuality | None,
    noise_level: float,
    structure_reliability: float,
    dominant_pattern: str
) -> list[str]:
    """Generate human-readable observations about price action."""
    observations = []

    # Candle clarity observations
    if candle_clarity > 0.7:
        observations.append("Clean candle formations with clear directional bias")
    elif candle_clarity < 0.4:
        observations.append("Messy candles with long wicks - indecision prevalent")

    # Trend observations
    if trend_quality:
        if trend_quality.smoothness > 0.7:
            observations.append("Smooth, well-defined trend with minimal whipsaws")
        elif trend_quality.is_choppy:
            observations.append("Choppy trend with frequent reversals - trade carefully")

        if trend_quality.acceleration > 0.3:
            observations.append("Trend accelerating - momentum building")
        elif trend_quality.acceleration < -0.3:
            observations.append("Trend decelerating - potential exhaustion")

        if trend_quality.pullback_quality > 0.7:
            observations.append("Healthy pullbacks - good entry opportunities")

    # Range observations
    if range_quality:
        if range_quality.boundary_clarity > 0.7:
            observations.append("Well-defined range boundaries - clear S/R levels")

        if range_quality.bounce_consistency > 0.7:
            observations.append("Consistent bounces at range edges - reliable fade setup")

        if range_quality.is_breaking_out:
            if range_quality.breakout_quality > 0.6:
                observations.append("High-quality breakout in progress")
            else:
                observations.append("Weak breakout - high false breakout risk")

    # Noise observations
    if noise_level > 0.7:
        observations.append("High noise environment - reduce position size")
    elif noise_level < 0.3:
        observations.append("Low noise - clean signals likely")

    # Structure observations
    if structure_reliability > 0.7:
        observations.append("Market structure is reliable and well-defined")
    elif structure_reliability < 0.4:
        observations.append("Structure is ambiguous - wait for clarity")

    return observations


def assess_price_action_readability(
    candles: list[Candle],
    swings: list[Swing] | None = None,
    liquidity: list[LiquidityLevel] | None = None,
    regime: MarketRegime | None = None,
) -> ReadabilitySnapshot:
    """
    Main entry point - assess complete price action readability.

    Returns a ReadabilitySnapshot with:
    - Overall readability score and grade
    - Candle clarity analysis
    - Trend quality assessment (if trending)
    - Range quality assessment (if ranging)
    - Noise level measurement
    - Structure reliability score
    - Tradeability recommendation
    - Dominant pattern identification
    - Key observations
    """
    if len(candles) < 10:
        return ReadabilitySnapshot(
            timestamp=candles[-1].timestamp if candles else 0,
            overall_score=0.0,
            grade="F",
            candle_clarity=0.0,
            trend_quality=None,
            range_quality=None,
            noise_level=1.0,
            structure_reliability=0.0,
            tradeability="avoid",
            dominant_pattern="unknown",
            key_observations=["Insufficient data for readability analysis"]
        )

    timestamp = candles[-1].timestamp

    # Analyze components
    candle_clarity, candle_qualities = _compute_candle_clarity(candles)
    trend_quality = _assess_trend_quality(candles, swings)
    range_quality = _assess_range_quality(candles, liquidity)
    noise_level = _compute_noise_level(candles)
    structure_reliability = _assess_structure_reliability(candles, swings, liquidity, regime)

    # Determine dominant pattern
    dominant_pattern = _determine_dominant_pattern(trend_quality, range_quality, noise_level)

    # Compute overall score
    if dominant_pattern == "trending":
        overall_score = (
            candle_clarity * 0.20 +
            trend_quality.reliability * 0.35 +
            (1.0 - noise_level) * 0.20 +
            structure_reliability * 0.25
        )
    elif dominant_pattern == "ranging":
        overall_score = (
            candle_clarity * 0.20 +
            range_quality.reliability * 0.35 +
            (1.0 - noise_level) * 0.20 +
            structure_reliability * 0.25
        )
    elif dominant_pattern == "breaking_out":
        overall_score = (
            candle_clarity * 0.25 +
            range_quality.breakout_quality * 0.40 +
            (1.0 - noise_level) * 0.15 +
            structure_reliability * 0.20
        )
    else:  # chopping
        overall_score = (
            candle_clarity * 0.30 +
            (1.0 - noise_level) * 0.40 +
            structure_reliability * 0.30
        ) * 0.7  # Choppy markets inherently less tradeable

    overall_score = max(0.0, min(1.0, overall_score))

    # Derive assessments
    grade = _determine_grade(overall_score)
    tradeability = _determine_tradeability(overall_score)
    observations = _generate_observations(
        candle_clarity, trend_quality, range_quality, noise_level, structure_reliability, dominant_pattern
    )

    return ReadabilitySnapshot(
        timestamp=timestamp,
        overall_score=round(overall_score, 3),
        grade=grade,
        candle_clarity=round(candle_clarity, 3),
        trend_quality=trend_quality,
        range_quality=range_quality,
        noise_level=round(noise_level, 3),
        structure_reliability=round(structure_reliability, 3),
        tradeability=tradeability,
        dominant_pattern=dominant_pattern,
        key_observations=observations,
        candle_qualities=candle_qualities[-10:]  # Last 10 candles
    )
