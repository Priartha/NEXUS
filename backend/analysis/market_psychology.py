"""
Market Psychology Detection Module for NEXUS

Detects psychological market states from price action:
- Fear/Greed extremes from candle patterns
- Retail trap detection (false breakouts, stop hunts)
- Smart money accumulation/distribution signatures
- Emotional exhaustion (panic capitulation, FOMO tops)
- Psychological support/resistance levels
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from backend.models.types import Candle, LiquidityEvent, MarketRegime


@dataclass
class PsychologySignal:
    """Single psychology detection event."""
    id: str
    timestamp: int
    type: str  # fear_extreme, greed_extreme, retail_trap, smart_money_entry, smart_money_exit, panic_capitulation, fomo_exhaustion, psychological_level
    side: str  # bullish, bearish, neutral
    intensity: float  # 0.0-1.0
    confidence: float  # 0.0-1.0
    description: str
    price_level: float
    reason: str


@dataclass
class PsychologySnapshot:
    """Complete market psychology state."""
    timestamp: int
    fear_greed_score: float  # -1.0 (extreme fear) to +1.0 (extreme greed)
    fear_greed_label: str  # extreme_fear, fear, neutral, greed, extreme_greed
    retail_participation: float  # 0.0-1.0, high = retail-dominated
    smart_money_activity: float  # 0.0-1.0, high = institutional activity
    emotional_state: str  # panic, cautious, balanced, euphoric, exhausted
    trap_risk: float  # 0.0-1.0, probability of false breakout
    conviction_score: float  # 0.0-1.0, how reliable current move is
    psychological_levels: list[float]  # key psychological S/R levels
    active_signals: list[PsychologySignal] = field(default_factory=list)
    summary: str = ""


def _compute_fear_greed(candles: list[Candle], regime: MarketRegime | None) -> tuple[float, str]:
    """Compute fear/greed score from multiple price action factors."""
    if len(candles) < 20:
        return 0.0, "neutral"

    closes = [c.close for c in candles]
    recent = candles[-10:]

    # 1. RSI-based sentiment (from price momentum)
    gains = []
    losses = []
    for i in range(1, min(15, len(closes))):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains) / len(gains) if gains else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    rsi_raw = 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss if avg_loss > 0 else 100.0)))
    rsi_sentiment = (rsi_raw - 50.0) / 50.0  # -1 to +1

    # 2. Candle body analysis - long bodies show conviction
    bodies = [abs(c.close - c.open) for c in recent]
    wicks_upper = [c.high - max(c.open, c.close) for c in recent]
    wicks_lower = [min(c.open, c.close) - c.low for c in recent]

    avg_body = sum(bodies) / len(bodies) if bodies else 0
    avg_wick = (sum(wicks_upper) + sum(wicks_lower)) / (2 * len(wicks_upper)) if wicks_upper else 0

    # Long upper wicks = rejection/selling pressure (fear)
    # Long lower wicks = buying support (greed)
    wick_ratio = (sum(wicks_upper) - sum(wicks_lower)) / (sum(wicks_upper) + sum(wicks_lower) + 1e-9)

    # 3. Price position relative to recent range
    range_high = max(c.high for c in candles[-20:])
    range_low = min(c.low for c in candles[-20:])
    range_width = range_high - range_low
    price_position = (closes[-1] - range_low) / range_width if range_width > 0 else 0.5

    # Near highs = greed, near lows = fear
    position_sentiment = (price_position - 0.5) * 2.0

    # 4. Consecutive direction
    consecutive_up = 0
    consecutive_down = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            consecutive_up += 1
            consecutive_down = 0
        elif closes[i] < closes[i - 1]:
            consecutive_down += 1
            consecutive_up = 0
        else:
            break

    streak_sentiment = 0.0
    if consecutive_up >= 5:
        streak_sentiment = min(consecutive_up / 10.0, 1.0)  # greed from FOMO
    elif consecutive_down >= 5:
        streak_sentiment = -min(consecutive_down / 10.0, 1.0)  # fear from panic

    # 5. Volume confirmation
    volumes = [c.volume for c in recent]
    avg_vol = sum(volumes) / len(volumes) if volumes else 1
    current_vol = volumes[-1] if volumes else 0
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

    # High volume on down moves = panic selling (fear)
    # High volume on up moves = FOMO buying (greed)
    last_candle = candles[-1]
    if last_candle.close < last_candle.open:
        vol_sentiment = -min((vol_ratio - 1.0) / 2.0, 1.0)
    else:
        vol_sentiment = min((vol_ratio - 1.0) / 2.0, 1.0)

    # Weighted combination
    score = (
        rsi_sentiment * 0.30 +
        (-wick_ratio) * 0.20 +
        position_sentiment * 0.20 +
        streak_sentiment * 0.15 +
        vol_sentiment * 0.15
    )

    # Regime adjustment
    if regime:
        if regime.phase == "accumulation":
            score = score * 0.7 + 0.15  # slight greed bias
        elif regime.phase == "distribution":
            score = score * 0.7 - 0.15  # slight fear bias
        elif regime.phase == "range_bound":
            score *= 0.6  # compress toward neutral

    score = max(-1.0, min(1.0, score))

    if score <= -0.6:
        label = "extreme_fear"
    elif score <= -0.2:
        label = "fear"
    elif score <= 0.2:
        label = "neutral"
    elif score <= 0.6:
        label = "greed"
    else:
        label = "extreme_greed"

    return score, label


def _detect_retail_traps(candles: list[Candle], liquidity_events: list[LiquidityEvent]) -> list[PsychologySignal]:
    """Detect where retail traders are likely getting trapped."""
    signals = []
    if len(candles) < 30:
        return signals

    recent = candles[-30:]
    closes = [c.close for c in recent]

    # 1. False breakout detection
    range_high = max(c.high for c in recent[:20])
    range_low = min(c.low for c in recent[:20])

    for i in range(20, len(recent)):
        c = recent[i]
        # Breakout above resistance that fails
        if c.high > range_high * 1.001 and c.close < range_high:
            trap_distance = (c.high - c.close) / c.close
            if trap_distance > 0.002:  # At least 0.2% rejection
                signals.append(PsychologySignal(
                    id=f"trap_false_breakout_high_{c.timestamp}",
                    timestamp=c.timestamp,
                    type="retail_trap",
                    side="bearish",
                    intensity=min(trap_distance * 100, 1.0),
                    confidence=0.75,
                    description=f"False breakout above {range_high:.2f}, rejected to {c.close:.2f}",
                    price_level=c.high,
                    reason="Retail FOMO into breakout, smart money selling into strength"
                ))

        # Breakdown below support that fails
        if c.low < range_low * 0.999 and c.close > range_low:
            trap_distance = (c.close - c.low) / c.close
            if trap_distance > 0.002:
                signals.append(PsychologySignal(
                    id=f"trap_false_breakdown_low_{c.timestamp}",
                    timestamp=c.timestamp,
                    type="retail_trap",
                    side="bullish",
                    intensity=min(trap_distance * 100, 1.0),
                    confidence=0.75,
                    description=f"False breakdown below {range_low:.2f}, reclaimed to {c.close:.2f}",
                    price_level=c.low,
                    reason="Retail panic selling, smart money buying weakness"
                ))

    # 2. Recent liquidity sweeps as trap indicators
    for event in liquidity_events[-5:]:
        if event.reclaimed:
            side = "bullish" if event.side == "sell_side" else "bearish"
            signals.append(PsychologySignal(
                id=f"trap_liquidity_sweep_{event.id}",
                timestamp=event.timestamp,
                type="retail_trap",
                side=side,
                intensity=event.engineered_score,
                confidence=0.80,
                description=f"Liquidity sweep at {event.sweep_price:.2f}, reclaimed",
                price_level=event.swept_level,
                reason=event.reason
            ))

    return signals


def _detect_smart_money_activity(candles: list[Candle]) -> tuple[float, list[PsychologySignal]]:
    """Detect smart money accumulation/distribution patterns."""
    signals = []
    if len(candles) < 50:
        return 0.0, signals

    recent = candles[-50:]
    activity_score = 0.0

    # 1. Volume analysis - smart money leaves volume fingerprints
    volumes = [c.volume for c in recent]
    avg_vol = sum(volumes) / len(volumes)

    # Look for high volume on small candles (absorption)
    absorption_count = 0
    for c in recent[-20:]:
        body_size = abs(c.close - c.open)
        range_size = c.high - c.low
        if range_size > 0 and c.volume > avg_vol * 1.3 and body_size < range_size * 0.3:
            absorption_count += 1

    if absorption_count >= 3:
        activity_score += 0.3
        signals.append(PsychologySignal(
            id=f"sm_absorption_{recent[-1].timestamp}",
            timestamp=recent[-1].timestamp,
            type="smart_money_entry" if recent[-1].close > recent[-1].open else "smart_money_exit",
            side="bullish" if recent[-1].close > recent[-1].open else "bearish",
            intensity=min(absorption_count / 10.0, 1.0),
            confidence=0.70,
            description=f"Volume absorption detected ({absorption_count} instances)",
            price_level=recent[-1].close,
            reason="High volume with small bodies indicates institutional absorption"
        ))

    # 2. Stealth accumulation - gradual price rise on declining volume
    last_10 = recent[-10:]
    price_changes = [last_10[i].close - last_10[i].open for i in range(len(last_10))]
    vol_changes = [last_10[i].volume for i in range(len(last_10))]

    up_candles = sum(1 for pc in price_changes if pc > 0)
    down_candles = sum(1 for pc in price_changes if pc < 0)

    # More up candles but declining volume = stealth accumulation
    if up_candles >= 7 and vol_changes[-1] < vol_changes[0] * 0.8:
        activity_score += 0.25
        total_gain = sum(price_changes)
        signals.append(PsychologySignal(
            id=f"sm_stealth_accum_{recent[-1].timestamp}",
            timestamp=recent[-1].timestamp,
            type="smart_money_entry",
            side="bullish",
            intensity=0.65,
            confidence=0.65,
            description=f"Stealth accumulation: {up_candles}/10 up candles, declining volume",
            price_level=recent[-1].close,
            reason="Smart money accumulating without moving price significantly"
        ))

    # 3. Distribution pattern - price stalling at highs with increasing volume
    range_high = max(c.high for c in recent)
    high_touches = sum(1 for c in recent[-15:] if abs(c.high - range_high) / range_high < 0.001)

    if high_touches >= 3:
        high_volumes = [c.volume for c in recent[-15:] if abs(c.high - range_high) / range_high < 0.001]
        if high_volumes and sum(high_volumes) / len(high_volumes) > avg_vol * 1.1:
            activity_score += 0.3
            signals.append(PsychologySignal(
                id=f"sm_distribution_{recent[-1].timestamp}",
                timestamp=recent[-1].timestamp,
                type="smart_money_exit",
                side="bearish",
                intensity=min(high_touches / 5.0, 1.0),
                confidence=0.70,
                description=f"Distribution at highs: {high_touches} touches with elevated volume",
                price_level=range_high,
                reason="Smart money distributing into strength at resistance"
            ))

    return min(activity_score, 1.0), signals


def _detect_emotional_extremes(candles: list[Candle]) -> tuple[str, list[PsychologySignal]]:
    """Detect panic capitulation and FOMO exhaustion."""
    signals = []
    if len(candles) < 30:
        return "balanced", signals

    recent = candles[-30:]
    closes = [c.close for c in recent]

    # 1. Panic capitulation - long red candles with high volume
    consecutive_down = 0
    max_down_run = 0
    down_volume_sum = 0
    down_volume_count = 0

    for i in range(len(recent)):
        c = recent[i]
        if c.close < c.open:
            consecutive_down += 1
            body = c.open - c.close
            range_size = c.high - c.low
            if range_size > 0 and body / range_size > 0.7:  # Strong bearish candle
                down_volume_sum += c.volume
                down_volume_count += 1
        else:
            if consecutive_down >= 4:
                max_down_run = max(max_down_run, consecutive_down)
            consecutive_down = 0

    max_down_run = max(max_down_run, consecutive_down)

    if max_down_run >= 5 and down_volume_count >= 3:
        avg_down_vol = down_volume_sum / down_volume_count
        recent_avg_vol = sum(c.volume for c in recent[-10:]) / 10
        if avg_down_vol > recent_avg_vol * 1.5:
            signals.append(PsychologySignal(
                id=f"panic_capitulation_{recent[-1].timestamp}",
                timestamp=recent[-1].timestamp,
                type="panic_capitulation",
                side="bullish",  # Contrarian - capitulation often marks bottoms
                intensity=min(max_down_run / 10.0, 1.0),
                confidence=0.80,
                description=f"Panic capitulation: {max_down_run} consecutive down candles with high volume",
                price_level=closes[-1],
                reason="Extreme fear often marks exhaustion of selling pressure"
            ))

    # 2. FOMO exhaustion - parabolic move with weakening momentum
    consecutive_up = 0
    max_up_run = 0

    for i in range(len(recent)):
        c = recent[i]
        if c.close > c.open:
            consecutive_up += 1
        else:
            max_up_run = max(max_up_run, consecutive_up)
            consecutive_up = 0
    max_up_run = max(max_up_run, consecutive_up)

    # Check for parabolic acceleration
    if max_up_run >= 5:
        first_half_gain = sum(closes[i] - closes[i-1] for i in range(1, len(closes)//2) if closes[i] > closes[i-1])
        second_half_gain = sum(closes[i] - closes[i-1] for i in range(len(closes)//2, len(closes)) if closes[i] > closes[i-1])

        # If second half gains are smaller despite more up candles = exhaustion
        if second_half_gain < first_half_gain * 0.5 and max_up_run >= 6:
            signals.append(PsychologySignal(
                id=f"fomo_exhaustion_{recent[-1].timestamp}",
                timestamp=recent[-1].timestamp,
                type="fomo_exhaustion",
                side="bearish",  # Contrarian - FOMO marks tops
                intensity=min(max_up_run / 10.0, 1.0),
                confidence=0.75,
                description=f"FOMO exhaustion: {max_up_run} up candles but weakening momentum",
                price_level=closes[-1],
                reason="Late buyers entering as momentum fades - reversal risk high"
            ))

    # Determine overall emotional state
    if any(s.type == "panic_capitulation" for s in signals):
        emotional_state = "panic"
    elif any(s.type == "fomo_exhaustion" for s in signals):
        emotional_state = "euphoric"
    elif any(s.type == "retail_trap" for s in signals):
        emotional_state = "cautious"
    else:
        emotional_state = "balanced"

    return emotional_state, signals


def _find_psychological_levels(candles: list[Candle]) -> list[float]:
    """Find key psychological support/resistance levels."""
    if len(candles) < 20:
        return []

    recent = candles[-50:]
    levels = []

    # 1. Round numbers (major psychological levels)
    current_price = candles[-1].close
    magnitude = 10 ** int(math.log10(current_price))

    # Major round numbers near current price
    for multiplier in [0.5, 1, 2, 5, 10]:
        round_level = round(current_price / (magnitude * multiplier)) * (magnitude * multiplier)
        if abs(round_level - current_price) / current_price < 0.05:  # Within 5%
            if round_level not in levels:
                levels.append(round_level)

    # 2. Recent significant highs/lows
    range_high = max(c.high for c in recent)
    range_low = min(c.low for c in recent)
    range_mid = (range_high + range_low) / 2

    levels.extend([range_high, range_low, range_mid])

    # 3. Fibonacci levels of recent range
    fib_levels = [0.236, 0.382, 0.5, 0.618, 0.786]
    for fib in fib_levels:
        level = range_low + (range_high - range_low) * fib
        levels.append(level)

    # Sort and deduplicate (within 0.1% tolerance)
    levels = sorted(set(levels))
    deduped = [levels[0]]
    for level in levels[1:]:
        if abs(level - deduped[-1]) / deduped[-1] > 0.001:
            deduped.append(level)

    return deduped[:10]  # Top 10 levels


def _compute_trap_risk(candles: list[Candle], psychology_signals: list[PsychologySignal]) -> float:
    """Compute probability that current breakout is a trap."""
    if len(candles) < 20:
        return 0.5

    recent = candles[-20:]
    risk = 0.5

    # 1. Recent false breakouts increase trap risk
    recent_traps = [s for s in psychology_signals if s.type == "retail_trap" and (candles[-1].timestamp - s.timestamp) < 3600000 * 4]
    risk += len(recent_traps) * 0.1

    # 2. Low volume breakouts are more likely traps
    volumes = [c.volume for c in recent]
    avg_vol = sum(volumes) / len(volumes)
    current_vol = volumes[-1]

    if current_vol < avg_vol * 0.7:
        risk += 0.15  # Low volume = suspicious

    # 3. Extended moves are more prone to traps
    range_high = max(c.high for c in recent)
    range_low = min(c.low for c in recent)
    current_price = candles[-1].close

    if current_price > range_high * 0.98 or current_price < range_low * 1.02:
        risk += 0.1  # At edge of range

    # 4. Wick analysis - long wicks indicate rejection
    last_candle = candles[-1]
    body = abs(last_candle.close - last_candle.open)
    range_size = last_candle.high - last_candle.low
    if range_size > 0 and body / range_size < 0.3:
        risk += 0.1  # Small body = indecision

    return min(max(risk, 0.0), 1.0)


def _compute_conviction(candles: list[Candle]) -> float:
    """Compute how reliable/convincing the current price action is."""
    if len(candles) < 20:
        return 0.5

    recent = candles[-20:]
    conviction = 0.5

    # 1. Trend consistency
    closes = [c.close for c in recent]
    up_days = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
    down_days = 20 - up_days

    dominant = max(up_days, down_days)
    conviction += (dominant - 10) / 20.0  # More one-sided = higher conviction

    # 2. Volume confirmation
    volumes = [c.volume for c in recent]
    avg_vol = sum(volumes) / len(volumes)

    # Check if volume supports the move
    if closes[-1] > closes[0]:  # Uptrend
        up_volumes = [volumes[i] for i in range(1, len(volumes)) if closes[i] > closes[i-1]]
        down_volumes = [volumes[i] for i in range(1, len(volumes)) if closes[i] < closes[i-1]]
    else:  # Downtrend
        down_volumes = [volumes[i] for i in range(1, len(volumes)) if closes[i] < closes[i-1]]
        up_volumes = [volumes[i] for i in range(1, len(volumes)) if closes[i] > closes[i-1]]

    if up_volumes and down_volumes:
        avg_up_vol = sum(up_volumes) / len(up_volumes)
        avg_down_vol = sum(down_volumes) / len(down_volumes)

        if closes[-1] > closes[0] and avg_up_vol > avg_down_vol:
            conviction += 0.15  # Volume confirms uptrend
        elif closes[-1] < closes[0] and avg_down_vol > avg_up_vol:
            conviction += 0.15  # Volume confirms downtrend
        else:
            conviction -= 0.1  # Volume contradicts

    # 3. Candle quality - clean candles vs messy
    clean_candles = 0
    for c in recent[-10:]:
        body = abs(c.close - c.open)
        range_size = c.high - c.low
        if range_size > 0 and body / range_size > 0.5:
            clean_candles += 1

    conviction += (clean_candles - 5) / 20.0

    return min(max(conviction, 0.0), 1.0)


def _compute_retail_participation(candles: list[Candle]) -> float:
    """Estimate how much retail traders are participating."""
    if len(candles) < 20:
        return 0.5

    recent = candles[-20:]
    participation = 0.5

    # 1. High volume on small moves = retail churn
    volumes = [c.volume for c in recent]
    avg_vol = sum(volumes) / len(volumes)

    small_move_count = 0
    for c in recent:
        move_pct = abs(c.close - c.open) / c.open
        if move_pct < 0.002 and c.volume > avg_vol * 1.2:
            small_move_count += 1

    participation += small_move_count * 0.03

    # 2. Erratic price action = retail dominance
    direction_changes = 0
    for i in range(2, len(recent)):
        prev_dir = 1 if recent[i-1].close > recent[i-1].open else -1
        curr_dir = 1 if recent[i].close > recent[i].open else -1
        if prev_dir != curr_dir:
            direction_changes += 1

    participation += (direction_changes - 10) / 30.0

    # 3. Long wicks on many candles = retail stop hunting
    wick_candles = 0
    for c in recent:
        body = abs(c.close - c.open)
        wicks = (c.high - max(c.open, c.close)) + (min(c.open, c.close) - c.low)
        if body > 0 and wicks / body > 1.5:
            wick_candles += 1

    participation += wick_candles * 0.02

    return min(max(participation, 0.0), 1.0)


def detect_market_psychology(
    candles: list[Candle],
    liquidity_events: list[LiquidityEvent] | None = None,
    regime: MarketRegime | None = None,
) -> PsychologySnapshot:
    """
    Main entry point - detect complete market psychology state.

    Returns a PsychologySnapshot with:
    - Fear/greed score and label
    - Retail participation estimate
    - Smart money activity level
    - Emotional state detection
    - Trap risk assessment
    - Conviction score
    - Psychological support/resistance levels
    - Active psychology signals
    """
    if len(candles) < 20:
        return PsychologySnapshot(
            timestamp=candles[-1].timestamp if candles else 0,
            fear_greed_score=0.0,
            fear_greed_label="neutral",
            retail_participation=0.5,
            smart_money_activity=0.0,
            emotional_state="balanced",
            trap_risk=0.5,
            conviction_score=0.5,
            psychological_levels=[],
            summary="Insufficient data for psychology analysis"
        )

    liquidity_events = liquidity_events or []
    timestamp = candles[-1].timestamp

    # Core metrics
    fear_greed_score, fear_greed_label = _compute_fear_greed(candles, regime)
    retail_participation = _compute_retail_participation(candles)
    smart_money_activity, sm_signals = _detect_smart_money_activity(candles)
    emotional_state, emotion_signals = _detect_emotional_extremes(candles)
    trap_signals = _detect_retail_traps(candles, liquidity_events)
    psychological_levels = _find_psychological_levels(candles)
    trap_risk = _compute_trap_risk(candles, trap_signals)
    conviction = _compute_conviction(candles)

    # Combine all signals
    all_signals = sm_signals + emotion_signals + trap_signals

    # Generate summary
    summary_parts = []
    if fear_greed_label in ("extreme_fear", "extreme_greed"):
        summary_parts.append(f"Market showing {fear_greed_label.replace('_', ' ')}")
    if retail_participation > 0.7:
        summary_parts.append("High retail participation - increased noise")
    elif retail_participation < 0.3:
        summary_parts.append("Low retail participation - cleaner moves")
    if smart_money_activity > 0.5:
        summary_parts.append("Active smart money participation detected")
    if emotional_state in ("panic", "euphoric"):
        summary_parts.append(f"Emotional state: {emotional_state} - reversal risk elevated")
    if trap_risk > 0.7:
        summary_parts.append("High trap risk - false breakouts likely")

    summary = ". ".join(summary_parts) if summary_parts else "Market psychology appears balanced"

    return PsychologySnapshot(
        timestamp=timestamp,
        fear_greed_score=round(fear_greed_score, 3),
        fear_greed_label=fear_greed_label,
        retail_participation=round(retail_participation, 3),
        smart_money_activity=round(smart_money_activity, 3),
        emotional_state=emotional_state,
        trap_risk=round(trap_risk, 3),
        conviction_score=round(conviction, 3),
        psychological_levels=[round(l, 2) for l in psychological_levels],
        active_signals=all_signals,
        summary=summary
    )
