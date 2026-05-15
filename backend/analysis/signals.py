from __future__ import annotations

import math

from scipy.stats import norm

from backend.analysis.institutional import compute_market_metrics
from backend.analysis.ids import stable_id
from backend.models.types import (
    Candle,
    FVG,
    LiquidityEvent,
    LiquidityLevel,
    MarketMetrics,
    OrderBlock,
    StructureLabel,
    Swing,
    TradeSignal,
)


def detect_trade_signals(
    candles: list[Candle],
    swings: list[Swing],
    structure: list[StructureLabel],
    fvgs: list[FVG],
    order_blocks: list[OrderBlock],
    liquidity: list[LiquidityLevel],
    liquidity_events: list[LiquidityEvent] | None = None,
    metrics: MarketMetrics | None = None,
    reward_multiple: float = 3.0,
) -> list[TradeSignal]:
    signals: list[TradeSignal] = []
    liquidity_events = liquidity_events or []
    candle_by_ts = {candle.timestamp: candle for candle in candles}
    ordered_candles = sorted(candles, key=lambda candle: candle.timestamp)
    index_by_ts = {candle.timestamp: index for index, candle in enumerate(ordered_candles)}

    for label in structure:
        if label.kind.value not in {"BOS", "CHoCH"} or label.direction not in {"bullish", "bearish"}:
            continue

        candle = candle_by_ts.get(label.timestamp)
        if candle is None:
            continue

        index = index_by_ts[label.timestamp]
        atr = _atr(ordered_candles[: index + 1], period=14)
        if atr <= 0:
            continue

        side = "buy" if label.direction == "bullish" else "sell"
        prefix_candles = ordered_candles[: index + 1]
        prefix_swings = [swing for swing in swings if swing.timestamp <= label.timestamp]
        local_metrics = (
            metrics
            if metrics is not None and metrics.timestamp == label.timestamp
            else compute_market_metrics(prefix_candles, prefix_swings)
        )
        entry, entry_reason = _institutional_entry(
            side=side,
            timestamp=label.timestamp,
            close=candle.close,
            swings=swings,
            candles=prefix_candles,
            fvgs=fvgs,
            order_blocks=order_blocks,
            metrics=local_metrics,
        )
        stop_loss = _institutional_stop(
            side=side,
            timestamp=label.timestamp,
            entry=entry,
            atr=atr,
            swings=swings,
            candles=prefix_candles,
            liquidity=liquidity,
            metrics=local_metrics,
        )
        risk = abs(entry - stop_loss)
        min_risk = atr * 0.65
        if risk <= 0 or risk < min_risk:
            stop_loss = entry - min_risk if side == "buy" else entry + min_risk
            risk = min_risk

        if risk <= 0:
            continue

        exit_price, target_reason = _institutional_target(
            side=side,
            timestamp=label.timestamp,
            entry=entry,
            risk=risk,
            min_reward_multiple=reward_multiple,
            swings=swings,
            liquidity=liquidity,
            metrics=local_metrics,
        )
        confidence, reason, institutional_score, liquidity_score, bias_score = _confidence_and_reason(
            side=side,
            label=label,
            candle=candle,
            atr=atr,
            entry_reason=entry_reason,
            target_reason=target_reason,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity=liquidity,
            liquidity_events=liquidity_events,
            metrics=local_metrics,
        )
        risk_reward = abs(exit_price - entry) / risk
        risk_profile = _institutional_risk_profile(
            entry=entry,
            risk=risk,
            risk_reward=risk_reward,
            confidence=confidence,
            metrics=local_metrics,
        )
        if risk_profile["risk_of_ruin"] > 0.6 or risk_profile["cvar95_loss"] > (risk * 3.0):
            continue
        confidence = round(_clamp(confidence - risk_profile["penalty"], 0.2, 0.93), 2)
        reason = f"{reason}, kelly {risk_profile['kelly_fraction']:.3f}, cvar95 {risk_profile['cvar95_loss']:.2f}, ruin {risk_profile['risk_of_ruin']:.2f}"
        signal = TradeSignal(
            id=stable_id("signal", side, label.kind.value, label.timestamp, entry, stop_loss, exit_price),
            timestamp=label.timestamp,
            side=side,
            entry=round(entry, 2),
            stop_loss=round(stop_loss, 2),
            exit_price=round(exit_price, 2),
            risk_reward=round(risk_reward, 2),
            confidence=confidence,
            reason=reason,
            institutional_score=institutional_score,
            liquidity_score=liquidity_score,
            bias_score=bias_score,
            expected_move=round(local_metrics.expected_move, 2) if local_metrics else round(atr, 2),
            win_probability=round(risk_profile["win_probability"], 3),
            kelly_fraction=round(risk_profile["kelly_fraction"], 4),
            suggested_risk_fraction=round(risk_profile["suggested_risk_fraction"], 4),
            cvar95_loss=round(risk_profile["cvar95_loss"], 2),
            risk_of_ruin=round(risk_profile["risk_of_ruin"], 3),
        )
        signal.trailing_stop = round(
            _current_trailing_stop(signal, ordered_candles, atr),
            2,
        )
        _update_signal_status(signal, ordered_candles)
        signals.append(signal)

    deduped: dict[str, TradeSignal] = {}
    for signal in signals:
        deduped[signal.id] = signal
    return sorted(deduped.values(), key=lambda item: item.timestamp)


def _atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0

    ranges: list[float] = []
    recent = candles[-(period + 1) :]
    for previous, current in zip(recent, recent[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(ranges) / len(ranges) if ranges else 0.0


def _institutional_entry(
    side: str,
    timestamp: int,
    close: float,
    swings: list[Swing],
    candles: list[Candle],
    fvgs: list[FVG],
    order_blocks: list[OrderBlock],
    metrics: MarketMetrics | None,
) -> tuple[float, str]:
    direction = "bullish" if side == "buy" else "bearish"
    candidates: list[tuple[float, float, str]] = []

    for fvg in fvgs:
        if fvg.direction != direction or fvg.timestamp > timestamp:
            continue
        if fvg.fill_timestamp is not None and fvg.fill_timestamp <= timestamp:
            continue
        midpoint = (fvg.top + fvg.bottom) / 2
        candidates.append((midpoint, abs(close - midpoint), "50% FVG rebalance"))

    for block in order_blocks:
        if block.direction != direction or block.timestamp > timestamp:
            continue
        if block.breaker_timestamp is not None and block.breaker_timestamp <= timestamp:
            continue
        midpoint = (block.top + block.bottom) / 2
        candidates.append((midpoint, abs(close - midpoint), "order-block mean threshold"))

    if metrics:
        if side == "buy":
            if metrics.vwap <= close:
                candidates.append((metrics.vwap, abs(close - metrics.vwap) * 0.9, "session VWAP mean reversion"))
            if metrics.equilibrium <= close:
                candidates.append((metrics.equilibrium, abs(close - metrics.equilibrium), "dealing-range equilibrium"))
        else:
            if metrics.vwap >= close:
                candidates.append((metrics.vwap, abs(close - metrics.vwap) * 0.9, "session VWAP mean reversion"))
            if metrics.equilibrium >= close:
                candidates.append((metrics.equilibrium, abs(close - metrics.equilibrium), "dealing-range equilibrium"))

    valid = [
        candidate
        for candidate in candidates
        if (side == "buy" and candidate[0] <= close) or (side == "sell" and candidate[0] >= close)
    ]
    if valid:
        price, _, reason = min(valid, key=lambda item: item[1])
        return price, reason

    if side == "buy":
        lows = [swing for swing in swings if swing.kind == "low" and swing.timestamp < timestamp]
        impulse_low = lows[-1].price if lows else min(candle.low for candle in candles[-10:])
        ote_62 = close - ((close - impulse_low) * 0.62)
        ote_705 = close - ((close - impulse_low) * 0.705)
        return (ote_62 + ote_705) / 2, "OTE 62%-70.5% retracement cluster"

    highs = [swing for swing in swings if swing.kind == "high" and swing.timestamp < timestamp]
    impulse_high = highs[-1].price if highs else max(candle.high for candle in candles[-10:])
    ote_62 = close + ((impulse_high - close) * 0.62)
    ote_705 = close + ((impulse_high - close) * 0.705)
    return (ote_62 + ote_705) / 2, "OTE 62%-70.5% retracement cluster"


def _institutional_stop(
    side: str,
    timestamp: int,
    entry: float,
    atr: float,
    swings: list[Swing],
    candles: list[Candle],
    liquidity: list[LiquidityLevel],
    metrics: MarketMetrics | None,
) -> float:
    buffer = max(atr * 0.22, (metrics.expected_move * 0.08 if metrics else 0.0))
    if side == "buy":
        swing_lows = [swing.price for swing in swings if swing.kind == "low" and swing.timestamp < timestamp and swing.price < entry]
        swept_lows = [
            level.price
            for level in liquidity
            if level.kind == "equal_low" and level.price < entry and level.sweep_timestamp and level.sweep_timestamp <= timestamp
        ]
        recent_low = min(candle.low for candle in candles[-12:])
        anchor = min([recent_low, *(swing_lows[-3:] or [recent_low]), *(swept_lows[-2:] or [recent_low])])
        return anchor - buffer

    swing_highs = [swing.price for swing in swings if swing.kind == "high" and swing.timestamp < timestamp and swing.price > entry]
    swept_highs = [
        level.price
        for level in liquidity
        if level.kind == "equal_high" and level.price > entry and level.sweep_timestamp and level.sweep_timestamp <= timestamp
    ]
    recent_high = max(candle.high for candle in candles[-12:])
    anchor = max([recent_high, *(swing_highs[-3:] or [recent_high]), *(swept_highs[-2:] or [recent_high])])
    return anchor + buffer


def _institutional_target(
    side: str,
    timestamp: int,
    entry: float,
    risk: float,
    min_reward_multiple: float,
    swings: list[Swing],
    liquidity: list[LiquidityLevel],
    metrics: MarketMetrics | None,
) -> tuple[float, str]:
    minimum = entry + (risk * min_reward_multiple) if side == "buy" else entry - (risk * min_reward_multiple)
    return minimum, f"fixed {min_reward_multiple:.0f}R target with opposing liquidity validation"


def _confidence_and_reason(
    side: str,
    label: StructureLabel,
    candle: Candle,
    atr: float,
    entry_reason: str,
    target_reason: str,
    fvgs: list[FVG],
    order_blocks: list[OrderBlock],
    liquidity: list[LiquidityLevel],
    liquidity_events: list[LiquidityEvent],
    metrics: MarketMetrics | None,
) -> tuple[float, str, float, float, float]:
    direction = "bullish" if side == "buy" else "bearish"
    signal_liquidity = "equal_low" if side == "buy" else "equal_high"
    event_side = "sell_side" if side == "buy" else "buy_side"
    score = 0.46
    liquidity_score = 0.0
    bias_score = 0.0
    reasons = [
        f"{label.kind.value} {direction} close through {label.broken_swing_price:.1f}",
        entry_reason,
        f"ATR14 {atr:.1f}",
        target_reason,
    ]

    if any(fvg.direction == direction and fvg.timestamp <= candle.timestamp for fvg in fvgs[-20:]):
        score += 0.1
        reasons.append("active FVG confluence")

    if any(block.direction == direction and block.timestamp <= candle.timestamp for block in order_blocks[-12:]):
        score += 0.1
        reasons.append("order block confluence")

    if any(
        level.kind == signal_liquidity and level.swept and level.sweep_timestamp and level.sweep_timestamp <= candle.timestamp
        for level in liquidity[-20:]
    ):
        score += 0.08
        reasons.append("liquidity sweep")

    event = _best_liquidity_event(liquidity_events, event_side, candle.timestamp)
    if event:
        liquidity_score = event.engineered_score
        score += min(0.16, event.engineered_score * 0.16)
        reasons.append(f"engineered {event.side.replace('_', '-')} sweep {event.engineered_score:.2f}")

    if label.kind.value == "CHoCH":
        score += 0.05
        reasons.append("structure shift")

    if metrics:
        bias_score = metrics.bias_score if side == "buy" else -metrics.bias_score
        if bias_score > 0:
            score += min(0.14, bias_score * 0.18)
            reasons.append(f"{metrics.institutional_bias} institutional bias")
        else:
            score -= min(0.08, abs(bias_score) * 0.1)
            reasons.append("bias conflict")

        if metrics.displacement_ratio >= 1.15:
            score += 0.05
            reasons.append(f"displacement {metrics.displacement_ratio:.1f}x ATR")

        if metrics.volume_zscore >= 1.0:
            score += 0.04
            reasons.append(f"volume z-score {metrics.volume_zscore:.1f}")

    confidence = round(_clamp(score, 0.25, 0.93), 2)
    return confidence, ", ".join(reasons), confidence, round(liquidity_score, 2), round(bias_score, 3)


def _update_signal_status(signal: TradeSignal, candles: list[Candle]) -> None:
    later = [candle for candle in candles if candle.timestamp > signal.timestamp]
    filled = False
    atr = _atr(candles, period=14)
    trailing_stop = signal.stop_loss
    for candle in later:
        if signal.side == "buy":
            if not filled and candle.low <= signal.entry:
                filled = True
            if not filled:
                continue
            trailing_stop = max(trailing_stop, _current_trailing_stop(signal, candles, atr, up_to_ts=candle.timestamp))
            stopped = candle.low <= trailing_stop
            targeted = candle.high >= signal.exit_price
        else:
            if not filled and candle.high >= signal.entry:
                filled = True
            if not filled:
                continue
            trailing_stop = min(trailing_stop, _current_trailing_stop(signal, candles, atr, up_to_ts=candle.timestamp))
            stopped = candle.high >= trailing_stop
            targeted = candle.low <= signal.exit_price

        if stopped:
            signal.status = "stopped"
            signal.exit_timestamp = candle.timestamp
            return
        if targeted:
            signal.status = "target_hit"
            signal.exit_timestamp = candle.timestamp
            signal.trailing_stop = round(trailing_stop, 2)
            return

    if filled:
        signal.trailing_stop = round(trailing_stop, 2)
    signal.status = "open" if filled else "pending"


def _best_liquidity_event(
    liquidity_events: list[LiquidityEvent],
    side: str,
    timestamp: int,
) -> LiquidityEvent | None:
    candidates = [event for event in liquidity_events if event.side == side and event.timestamp <= timestamp]
    if not candidates:
        return None
    return max(candidates[-8:], key=lambda event: event.engineered_score)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _current_trailing_stop(
    signal: TradeSignal,
    candles: list[Candle],
    atr: float,
    up_to_ts: int | None = None,
) -> float:
    if atr <= 0:
        return signal.stop_loss
    scoped = [c for c in candles if c.timestamp >= signal.timestamp and (up_to_ts is None or c.timestamp <= up_to_ts)]
    if not scoped:
        return signal.stop_loss
    trail_gap = max(atr * 1.1, abs(signal.entry - signal.stop_loss) * 0.75)
    if signal.side == "buy":
        peak = max(candle.high for candle in scoped)
        return max(signal.stop_loss, peak - trail_gap)
    trough = min(candle.low for candle in scoped)
    return min(signal.stop_loss, trough + trail_gap)


def _institutional_risk_profile(
    entry: float,
    risk: float,
    risk_reward: float,
    confidence: float,
    metrics: MarketMetrics | None,
) -> dict[str, float]:
    win_probability = _clamp(0.45 + (confidence - 0.5) * 0.9, 0.38, 0.78)
    loss_probability = 1.0 - win_probability
    b = max(risk_reward, 1e-6)
    kelly_fraction = _clamp(win_probability - (loss_probability / b), 0.0, 0.3)
    # Fractional Kelly (1/4 Kelly) with hard institutional cap.
    suggested_risk_fraction = _clamp(kelly_fraction * 0.25, 0.0025, 0.02)

    trade_sigma = max(risk / max(entry, 1e-6), 1e-5)
    if metrics is not None:
        trade_sigma = max(trade_sigma, abs(metrics.expected_move_pct) / 100)
    cvar95_return = _gaussian_cvar(alpha=0.95, sigma=trade_sigma)
    cvar95_loss = entry * cvar95_return

    unit_risk = _clamp(suggested_risk_fraction, 1e-4, 0.05)
    bankroll_units = max(5.0, min(400.0, 1.0 / unit_risk))
    if win_probability <= loss_probability:
        risk_of_ruin = 1.0
    else:
        risk_of_ruin = _clamp((loss_probability / win_probability) ** bankroll_units, 0.0, 1.0)

    penalty = _clamp(max(0.0, cvar95_loss / max(risk, 1e-6) - 1.0) * 0.08 + risk_of_ruin * 0.12, 0.0, 0.22)
    return {
        "win_probability": win_probability,
        "kelly_fraction": kelly_fraction,
        "suggested_risk_fraction": suggested_risk_fraction,
        "cvar95_loss": cvar95_loss,
        "risk_of_ruin": risk_of_ruin,
        "penalty": penalty,
    }


def _gaussian_cvar(alpha: float, sigma: float) -> float:
    alpha = _clamp(alpha, 0.8, 0.995)
    z = norm.ppf(alpha)
    phi = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return sigma * (phi / max(1.0 - alpha, 1e-6))
