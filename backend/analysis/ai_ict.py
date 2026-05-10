from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from backend.models.types import AiIctDecision, SentimentSnapshot


class AiIctService:
    def __init__(
        self,
        provider: str = "auto",
        gemini_model: str = "gemini-2.5-flash",
        gemini_api_key: str = "",
        gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        self.provider = provider.lower().strip()
        self.gemini_model = gemini_model
        self.gemini_api_key = gemini_api_key
        self.gemini_base_url = gemini_base_url.rstrip("/")

    async def analyze(self, payload: dict[str, Any], sentiment: SentimentSnapshot) -> AiIctDecision:
        fallback = self.local_review(payload, sentiment)
        if self._active_provider_name() != "gemini":
            return fallback

        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": (
                                "You are an institutional ICT market-structure analyst inside a BTC trading terminal. "
                                "Return one final setup only: bullish, bearish, or neutral/NO_TRADE. Use only the supplied technical "
                                "snapshot. The local pricing engine enforces a fixed 1:3 risk/reward plan, so refine direction, grade, "
                                "confidence, confirmations, and blockers only. Do not claim certainty and do not use the word guarantee "
                                "except to say there is no guarantee. Return strict JSON. Grade only if the setup has sufficient evidence "
                                "from liquidity, structure, displacement, FVG/order-block context, volatility, sentiment, high options "
                                "momentum, and qualified option Greeks.\n\n"
                                f"{json.dumps(_compact_context(payload, sentiment, fallback), separators=(',', ':'))}"
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": _gemini_schema(),
            },
        }

        try:
            response_json = await self._post_gemini(body)

            parsed = json.loads(_extract_gemini_text(response_json))
            direction = _enum(str(parsed.get("direction", fallback.direction)), {"bullish", "bearish", "neutral"}, fallback.direction)
            grade = _enum(str(parsed.get("grade", fallback.grade)), {"A+", "A", "B", "C", "NO_TRADE"}, fallback.grade)
            readiness = _enum(
                str(parsed.get("readiness", fallback.readiness)),
                {"premium", "qualified", "watchlist", "avoid"},
                fallback.readiness,
            )
            confidence = _clamp(float(parsed.get("confidence", fallback.confidence)), 0.0, 0.95)
            setup_score = _clamp(float(parsed.get("setup_score", fallback.setup_score)), 0.0, 1.0)
            blockers = _string_list(parsed.get("blockers"))[:6] or fallback.blockers
            phase_block = _phase_block_reason(payload, direction)
            options_block = _options_block_reason(payload, direction)
            execution_block = phase_block or options_block
            signal = _best_signal_for_side(
                [_dict(item) for item in payload.get("signals", [])],
                "buy" if direction == "bullish" else "sell" if direction == "bearish" else "",
            )
            if direction in {"bullish", "bearish"} and signal is None:
                execution_block = execution_block or f"No active {direction.upper()} signal exists for final direction"
            if execution_block:
                direction = "neutral"
                grade = "NO_TRADE"
                readiness = "avoid"
                confidence = min(confidence, 0.49)
                setup_score = min(setup_score, 0.49)
                blockers = _prepend_unique(blockers, execution_block)[:6]
            if direction == "neutral" or grade == "NO_TRADE":
                direction = "neutral"
                grade = "NO_TRADE"
                readiness = "avoid"
                confidence = min(confidence, 0.49)
                setup_score = min(setup_score, 0.49)
            price_plan = _build_price_plan(
                payload=payload,
                direction=direction,
                signal=signal,
                candle=_dict(payload.get("candle")),
                candles=[_dict(item) for item in payload.get("candles", [])],
                metrics=_dict(payload.get("metrics")),
                fvgs=[_dict(item) for item in payload.get("fvgs", [])],
                order_blocks=[_dict(item) for item in payload.get("order_blocks", [])],
                liquidity=[_dict(item) for item in payload.get("liquidity", [])],
                projection=_dict(payload.get("projection")),
            )
            if direction == "neutral" or grade == "NO_TRADE":
                price_plan["entry"] = None
                price_plan["stop_loss"] = None
                price_plan["take_profit"] = None
                price_plan["risk_reward"] = None
                price_plan["primary_signal_id"] = None
            confirmations = _string_list(parsed.get("confirmations"))[:7] or fallback.confirmations
            summary = str(parsed.get("summary", fallback.summary))[:520]
            selected_option = _option_for_direction(payload, direction)
            if execution_block:
                confirmations = []
                selected_option = None
                summary = f"WAIT setup: NO_TRADE / avoid. {execution_block}; one final options setup is blocked until momentum and Greeks confirm."

            return AiIctDecision(
                timestamp=fallback.timestamp,
                timeframe=fallback.timeframe,
                provider="gemini",
                model="NEXUS",
                direction=direction,
                grade=grade,
                readiness=readiness,
                confidence=round(confidence, 3),
                setup_score=round(setup_score, 3),
                entry=price_plan["entry"],
                stop_loss=price_plan["stop_loss"],
                take_profit=price_plan["take_profit"],
                risk_reward=price_plan["risk_reward"],
                invalidation=price_plan["invalidation"],
                primary_signal_id=price_plan["primary_signal_id"],
                summary=summary,
                option_contract=selected_option,
                momentum_score=_directional_momentum(payload, direction),
                options_score=_as_float(selected_option.get("score"), None) if selected_option else None,
                confirmations=confirmations,
                blockers=blockers,
                calculations=[
                    item
                    for item in [*fallback.calculations[:5], *price_plan["calculations"]]
                    if item
                ][:10],
                updated_at=int(time.time() * 1000),
            )
        except Exception as exc:
            fallback.error = f"Gemini ICT review unavailable; deterministic confluence used: {exc}"
            return fallback

    async def _post_gemini(self, body: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=22, follow_redirects=True) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        f"{self.gemini_base_url}/models/{self.gemini_model}:generateContent",
                        headers={
                            "x-goog-api-key": self.gemini_api_key,
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    response.raise_for_status()
                    return response.json()
                except Exception as exc:
                    last_error = exc
                    if attempt == 0:
                        await _sleep_retry()
        raise last_error or RuntimeError("Gemini request failed")

    def local_review(self, payload: dict[str, Any], sentiment: SentimentSnapshot) -> AiIctDecision:
        metrics = _dict(payload.get("metrics"))
        projection = _dict(payload.get("projection"))
        regime = _dict(payload.get("regime"))
        options_context = _dict(payload.get("options_context"))
        signals = [_dict(item) for item in payload.get("signals", [])]
        liquidity_events = [_dict(item) for item in payload.get("liquidity_events", [])]
        fvgs = [_dict(item) for item in payload.get("fvgs", [])]
        order_blocks = [_dict(item) for item in payload.get("order_blocks", [])]
        liquidity = [_dict(item) for item in payload.get("liquidity", [])]
        structure = [_dict(item) for item in payload.get("structure", [])]
        candles = [_dict(item) for item in payload.get("candles", [])]
        candle = _dict(payload.get("candle"))
        timeframe = str(payload.get("timeframe") or "5m")
        timestamp = int(candle.get("timestamp") or projection.get("timestamp") or metrics.get("timestamp") or int(time.time() * 1000))

        scorecard = {"bullish": 0.18, "bearish": 0.18}
        evidence: dict[str, list[str]] = {"bullish": [], "bearish": []}
        sentiment_label = sentiment.label
        bias = str(metrics.get("institutional_bias") or "neutral")

        def add(direction_key: str, points: float, reason: str) -> None:
            if direction_key not in scorecard or points <= 0:
                return
            scorecard[direction_key] += points
            evidence[direction_key].append(reason)

        buy_signal = _best_signal_for_side(signals, "buy")
        sell_signal = _best_signal_for_side(signals, "sell")
        for side, signal in (("buy", buy_signal), ("sell", sell_signal)):
            if not signal:
                continue
            direction_key = "bullish" if side == "buy" else "bearish"
            signal_confidence = float(signal.get("confidence") or 0.0)
            rr = float(signal.get("risk_reward") or 0.0)
            add(
                direction_key,
                signal_confidence * 0.28 + min(rr / 3.0, 1.0) * 0.08,
                f"{side.upper()} signal {signal_confidence:.0%} confidence, {rr:.1f}R structure",
            )

        projection_direction = str(projection.get("direction") or "neutral")
        if projection_direction in {"bullish", "bearish"}:
            projection_confidence = float(projection.get("probability") or 0.5)
            add(projection_direction, projection_confidence * 0.14, f"Institutional projection {projection_confidence:.0%}")

        if bias in {"bullish", "bearish"}:
            add(bias, 0.1 + min(abs(float(metrics.get("bias_score") or 0.0)) * 0.1, 0.08), f"{bias} institutional bias")

        regime_phase = str(regime.get("phase") or "")
        regime_bias = str(regime.get("bias") or "")
        regime_confidence = float(regime.get("confidence") or 0.0)
        if regime_phase == "accumulation":
            add("bullish", 0.1 + regime_confidence * 0.06, f"Accumulation phase {regime_confidence:.0%}")
        elif regime_phase == "distribution":
            add("bearish", 0.1 + regime_confidence * 0.06, f"Distribution phase {regime_confidence:.0%}")
        elif regime_bias in {"bullish", "bearish"}:
            add(regime_bias, regime_confidence * 0.06, f"Regime bias {regime_bias} {regime_confidence:.0%}")
        elif regime_phase in {"consolidation", "range_bound"}:
            scorecard["bullish"] -= 0.04
            scorecard["bearish"] -= 0.04

        if sentiment_label in {"bullish", "bearish"}:
            add(sentiment_label, sentiment.confidence * 0.07, f"AI sentiment {sentiment_label} {sentiment.confidence:.0%}")

        bullish_event = _best_liquidity_event(liquidity_events, "sell_side")
        bearish_event = _best_liquidity_event(liquidity_events, "buy_side")
        if bullish_event:
            liquidity_score = float(bullish_event.get("engineered_score") or 0.0)
            add("bullish", min(liquidity_score * 0.13, 0.13), f"Sell-side sweep engineered {liquidity_score:.0%}")
        if bearish_event:
            liquidity_score = float(bearish_event.get("engineered_score") or 0.0)
            add("bearish", min(liquidity_score * 0.13, 0.13), f"Buy-side sweep engineered {liquidity_score:.0%}")

        for direction_key in ("bullish", "bearish"):
            if _has_direction(fvgs, direction_key):
                add(direction_key, 0.05, f"{direction_key} FVG confluence")
            if _has_direction(order_blocks, direction_key):
                add(direction_key, 0.05, f"{direction_key} order-block confluence")

        for label in structure[-8:]:
            direction_key = str(label.get("direction") or "")
            kind = str(label.get("kind") or "")
            if direction_key in {"bullish", "bearish"} and kind in {"BOS", "CHoCH"}:
                add(direction_key, 0.06 if kind == "CHoCH" else 0.05, f"{kind} close confirms {direction_key} structure")

        displacement = float(metrics.get("displacement_ratio") or 0.0)
        volume_z = float(metrics.get("volume_zscore") or 0.0)
        if displacement >= 1.15:
            body_direction = "bullish" if float(candle.get("close") or 0.0) >= float(candle.get("open") or 0.0) else "bearish"
            add(body_direction, 0.05, f"Displacement {displacement:.2f}x ATR")
        if volume_z >= 1.0:
            stronger_direction = "bullish" if scorecard["bullish"] >= scorecard["bearish"] else "bearish"
            add(stronger_direction, 0.03, f"Volume expansion z-score {volume_z:.2f}")
        volume_pulse = _live_volume_pulse(candle, candles)
        if volume_pulse >= 1.35:
            stronger_direction = "bullish" if scorecard["bullish"] >= scorecard["bearish"] else "bearish"
            add(stronger_direction, min(0.05, (volume_pulse - 1.0) * 0.08), f"Live volume pulse {volume_pulse:.2f}x")

        premium_discount = float(metrics.get("premium_discount") or 0.0)
        if premium_discount <= -0.25:
            add("bullish", 0.035, "Discount-side pricing")
        elif premium_discount >= 0.25:
            add("bearish", 0.035, "Premium-side pricing")

        call_candidate = _dict(options_context.get("call_candidate"))
        put_candidate = _dict(options_context.get("put_candidate"))
        bullish_momentum = _as_float(options_context.get("bullish_momentum_score"), 0.0)
        bearish_momentum = _as_float(options_context.get("bearish_momentum_score"), 0.0)
        minimum_momentum = _as_float(options_context.get("minimum_momentum_score"), 0.40)
        if call_candidate.get("qualified") and bullish_momentum >= minimum_momentum:
            add(
                "bullish",
                min(_as_float(call_candidate.get("score"), 0.0) * 0.11, 0.11),
                f"CALL Greeks qualified {call_candidate.get('symbol')} momentum {bullish_momentum:.0%}",
            )
        if put_candidate.get("qualified") and bearish_momentum >= minimum_momentum:
            add(
                "bearish",
                min(_as_float(put_candidate.get("score"), 0.0) * 0.11, 0.11),
                f"PUT Greeks qualified {put_candidate.get('symbol')} momentum {bearish_momentum:.0%}",
            )

        direction = "bullish" if scorecard["bullish"] >= scorecard["bearish"] else "bearish"
        opposite = "bearish" if direction == "bullish" else "bullish"
        separation = abs(scorecard[direction] - scorecard[opposite])
        score = _clamp(scorecard[direction] + separation * 0.42, 0.0, 0.95)
        confirmations = evidence[direction][:7]
        blockers: list[str] = []

        if scorecard[direction] < 0.52:
            blockers.append("Combined confluence is below execution threshold")
        if separation < 0.12:
            blockers.append("Bullish and bearish evidence are too close")
        aligned_liquidity_event = _best_liquidity_event(liquidity_events, "sell_side" if direction == "bullish" else "buy_side")
        if not aligned_liquidity_event:
            blockers.append("No fresh liquidity sweep aligned with final direction")
        phase_block = _phase_block_reason(payload, direction)
        if phase_block:
            blockers.append(phase_block)
        options_block = _options_block_reason(payload, direction)
        if options_block:
            blockers.append(options_block)
        if sentiment_label in {"bullish", "bearish"} and not _sentiment_aligns(direction, sentiment_label):
            blockers.append(f"AI sentiment conflict: {sentiment_label}")
        if bias in {"bullish", "bearish"} and bias != direction:
            blockers.append(f"Institutional bias conflict: {bias}")

        execution_block = phase_block or options_block
        if execution_block:
            direction = "neutral"
            score = min(score, 0.49)
            confirmations = []
            blockers = _prepend_unique(blockers, execution_block)
        elif scorecard[direction] < 0.48:
            direction = "neutral"
            score = min(score, 0.49)
            confirmations = []
            blockers = ["No execution-grade directional edge"]

        if direction in {"bullish", "bearish"}:
            active_signal = buy_signal if direction == "bullish" else sell_signal
            if active_signal is None:
                blockers.append(f"No active {direction.upper()} signal supports this direction")
                direction = "neutral"
                score = min(score, 0.49)
                confirmations = []

        price_plan = _build_price_plan(
            payload=payload,
            direction=direction,
            signal=buy_signal if direction == "bullish" else sell_signal if direction == "bearish" else None,
            candle=candle,
            candles=candles,
            metrics=metrics,
            fvgs=fvgs,
            order_blocks=order_blocks,
            liquidity=liquidity,
            projection=projection,
        )
        score = _clamp(score, 0.0, 0.95)
        grade, readiness = _grade(score)
        confidence = min(0.95, score * 0.96)
        selected_option = _option_for_direction(payload, direction)

        if grade == "NO_TRADE":
            readiness = "avoid"
            selected_option = None
            price_plan = {
                "entry": None,
                "stop_loss": None,
                "take_profit": None,
                "risk_reward": None,
                "invalidation": _optional_float(projection.get("invalidation")),
                "primary_signal_id": None,
                "calculations": price_plan["calculations"],
            }

        calculations = [
            f"ATR14 {float(metrics.get('atr14') or 0):.2f}",
            f"VWAP {float(metrics.get('vwap') or 0):.2f}",
            f"RSI14 {float(metrics.get('rsi14') or 0):.1f}",
            f"Premium/discount {float(metrics.get('premium_discount') or 0):.2f}",
            f"Expected move {float(metrics.get('expected_move') or 0):.2f}",
            f"Live volume pulse {_live_volume_pulse(candle, candles):.2f}x",
            f"Phase {regime_phase or 'unknown'}",
            f"Options momentum {_directional_momentum(payload, direction):.0%}",
            *(_option_calculations(selected_option) if selected_option else []),
            *price_plan["calculations"],
        ]

        action = "WAIT" if direction == "neutral" or grade == "NO_TRADE" else ("BUY" if direction == "bullish" else "SELL")
        if action == "WAIT":
            wait_reason = blockers[0] if blockers else "Execution-grade confirmation is not present"
            summary = f"WAIT setup: NO_TRADE / avoid. Phase {regime_phase or 'unknown'}; {wait_reason}."
        else:
            summary = f"{action} setup: {grade} / {readiness}. Phase {regime_phase or 'unknown'}; one 1:3 plan from liquidity, structure, volatility, sentiment, and institutional confluence."

        return AiIctDecision(
            timestamp=timestamp,
            timeframe=timeframe,
            provider="deterministic",
            model="NEXUS",
            direction=direction,
            grade=grade,
            readiness=readiness,
            confidence=round(confidence, 3),
            setup_score=round(score, 3),
            entry=price_plan["entry"],
            stop_loss=price_plan["stop_loss"],
            take_profit=price_plan["take_profit"],
            risk_reward=price_plan["risk_reward"],
            invalidation=price_plan["invalidation"],
            primary_signal_id=price_plan["primary_signal_id"],
            summary=summary,
            option_contract=selected_option,
            momentum_score=_directional_momentum(payload, direction),
            options_score=_as_float(selected_option.get("score"), None) if selected_option else None,
            confirmations=confirmations[:7],
            blockers=blockers[:6],
            calculations=calculations,
            updated_at=int(time.time() * 1000),
        )

    def _active_provider_name(self) -> str:
        if self.provider == "local":
            return "deterministic"
        if self.provider in {"gemini", "auto"} and self.gemini_api_key:
            return "gemini"
        return "deterministic"


def _compact_context(payload: dict[str, Any], sentiment: SentimentSnapshot, fallback: AiIctDecision) -> dict[str, Any]:
    return {
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "latest_candle": payload.get("candle"),
        "metrics": payload.get("metrics"),
        "projection": payload.get("projection"),
        "regime": payload.get("regime"),
        "options_context": payload.get("options_context"),
        "latest_signals": payload.get("signals", [])[-8:],
        "liquidity_events": payload.get("liquidity_events", [])[-8:],
        "active_fvgs": payload.get("fvgs", [])[-8:],
        "active_order_blocks": payload.get("order_blocks", [])[-6:],
        "sentiment": {
            "label": sentiment.label,
            "score": sentiment.score,
            "confidence": sentiment.confidence,
            "summary": sentiment.summary,
        },
        "deterministic_review": {
            "direction": fallback.direction,
            "grade": fallback.grade,
            "readiness": fallback.readiness,
            "setup_score": fallback.setup_score,
            "confidence": fallback.confidence,
            "entry": fallback.entry,
            "stop_loss": fallback.stop_loss,
            "take_profit": fallback.take_profit,
            "risk_reward": fallback.risk_reward,
            "confirmations": fallback.confirmations,
            "blockers": fallback.blockers,
        },
    }


def _gemini_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
            "grade": {"type": "string", "enum": ["A+", "A", "B", "C", "NO_TRADE"]},
            "readiness": {"type": "string", "enum": ["premium", "qualified", "watchlist", "avoid"]},
            "confidence": {"type": "number"},
            "setup_score": {"type": "number"},
            "summary": {"type": "string"},
            "confirmations": {"type": "array", "items": {"type": "string"}},
            "blockers": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "direction",
            "grade",
            "readiness",
            "confidence",
            "setup_score",
            "summary",
            "confirmations",
            "blockers",
        ],
    }


def _best_signal(signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    actionable = [signal for signal in signals if signal.get("status") in {"open", "pending"}]
    candidates = actionable or signals[-12:]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda signal: (
            float(signal.get("confidence") or 0.0) * 0.7
            + min(float(signal.get("risk_reward") or 0.0) / 4, 1.0) * 0.3,
            int(signal.get("timestamp") or 0),
        ),
    )


def _best_signal_for_side(signals: list[dict[str, Any]], side: str) -> dict[str, Any] | None:
    side_signals = [signal for signal in signals if signal.get("side") == side]
    return _best_signal(side_signals)


def _build_price_plan(
    payload: dict[str, Any],
    direction: str,
    signal: dict[str, Any] | None,
    candle: dict[str, Any],
    candles: list[dict[str, Any]],
    metrics: dict[str, Any],
    fvgs: list[dict[str, Any]],
    order_blocks: list[dict[str, Any]],
    liquidity: list[dict[str, Any]],
    projection: dict[str, Any],
) -> dict[str, Any]:
    del payload
    base = {
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_reward": None,
        "invalidation": _optional_float(projection.get("invalidation")),
        "primary_signal_id": None,
        "calculations": ["RR locked 1:3"],
    }
    if direction not in {"bullish", "bearish"}:
        return base

    side = "buy" if direction == "bullish" else "sell"
    close = _as_float(candle.get("close"), _as_float(candles[-1].get("close"), 0.0) if candles else 0.0)
    if close <= 0:
        return base

    atr = max(_as_float(metrics.get("atr14"), 0.0), close * 0.001)
    signal_entry = _optional_float(signal.get("entry") if signal else None)
    signal_stop = _optional_float(
        signal.get("trailing_stop") if signal and signal.get("trailing_stop") is not None else signal.get("stop_loss") if signal else None
    )

    if signal and signal_entry is not None and signal.get("side") == side:
        entry = signal_entry
        entry_reason = "AI selected primary ICT signal entry"
    else:
        entry, entry_reason = _derive_entry(direction, close, metrics, fvgs, order_blocks)

    if signal_stop is not None and _stop_is_valid(direction, entry, signal_stop):
        stop_loss = signal_stop
        stop_reason = "primary signal invalidation"
    else:
        stop_loss, stop_reason = _derive_stop(direction, entry, close, atr, metrics, candles, liquidity, projection)

    risk = abs(entry - stop_loss)
    min_risk = max(atr * 0.65, close * 0.0008)
    if risk < min_risk or not _stop_is_valid(direction, entry, stop_loss):
        stop_loss = entry - min_risk if direction == "bullish" else entry + min_risk
        risk = min_risk
        stop_reason = "ATR minimum invalidation"

    take_profit = entry + (risk * 3.0) if direction == "bullish" else entry - (risk * 3.0)
    invalidation = stop_loss

    return {
        "entry": _optional_float(entry),
        "stop_loss": _optional_float(stop_loss),
        "take_profit": _optional_float(take_profit),
        "risk_reward": 3.0,
        "invalidation": _optional_float(invalidation),
        "primary_signal_id": str(signal.get("id")) if signal else None,
        "calculations": [
            "RR locked 1:3",
            f"Entry: {entry_reason}",
            f"SL: {stop_reason}",
            f"Risk {risk:.2f}",
            "TP = entry +/- 3R",
        ],
    }


def _derive_entry(
    direction: str,
    close: float,
    metrics: dict[str, Any],
    fvgs: list[dict[str, Any]],
    order_blocks: list[dict[str, Any]],
) -> tuple[float, str]:
    candidates: list[tuple[float, float, str]] = []

    def add(price: float, reason: str, weight: float = 1.0) -> None:
        if price <= 0:
            return
        if direction == "bullish" and price <= close:
            candidates.append((price, abs(close - price) * weight, reason))
        if direction == "bearish" and price >= close:
            candidates.append((price, abs(close - price) * weight, reason))

    for fvg in fvgs[-12:]:
        if fvg.get("direction") != direction or fvg.get("is_filled"):
            continue
        midpoint = (_as_float(fvg.get("top"), close) + _as_float(fvg.get("bottom"), close)) / 2
        add(midpoint, "active FVG midpoint", 0.85)

    for block in order_blocks[-10:]:
        if block.get("direction") != direction or block.get("is_breaker"):
            continue
        midpoint = (_as_float(block.get("top"), close) + _as_float(block.get("bottom"), close)) / 2
        add(midpoint, "order-block mean threshold", 0.9)

    add(_as_float(metrics.get("vwap"), 0.0), "VWAP mean threshold", 1.0)
    add(_as_float(metrics.get("equilibrium"), 0.0), "dealing-range equilibrium", 1.05)

    if direction == "bullish":
        range_low = _as_float(metrics.get("range_low"), close)
        if range_low < close:
            add(close - ((close - range_low) * 0.665), "OTE 62%-70.5% retracement", 0.95)
    else:
        range_high = _as_float(metrics.get("range_high"), close)
        if range_high > close:
            add(close + ((range_high - close) * 0.665), "OTE 62%-70.5% retracement", 0.95)

    if not candidates:
        return close, "market close execution"
    price, _, reason = min(candidates, key=lambda item: item[1])
    return price, reason


def _derive_stop(
    direction: str,
    entry: float,
    close: float,
    atr: float,
    metrics: dict[str, Any],
    candles: list[dict[str, Any]],
    liquidity: list[dict[str, Any]],
    projection: dict[str, Any],
) -> tuple[float, str]:
    buffer = max(atr * 0.22, _as_float(metrics.get("expected_move"), atr) * 0.08, close * 0.00035)
    recent = candles[-14:]
    if direction == "bullish":
        anchors = [_as_float(item.get("low"), entry) for item in recent if _as_float(item.get("low"), entry) < entry]
        anchors.extend(
            _as_float(level.get("price"), entry)
            for level in liquidity[-20:]
            if level.get("kind") == "equal_low" and _as_float(level.get("price"), entry) < entry
        )
        projection_invalid = _as_float(projection.get("invalidation"), entry)
        if projection_invalid < entry:
            anchors.append(projection_invalid)
        if anchors:
            return min(anchors) - buffer, "below swept sell-side liquidity"
        return entry - max(atr, close * 0.0012), "ATR protective stop"

    anchors = [_as_float(item.get("high"), entry) for item in recent if _as_float(item.get("high"), entry) > entry]
    anchors.extend(
        _as_float(level.get("price"), entry)
        for level in liquidity[-20:]
        if level.get("kind") == "equal_high" and _as_float(level.get("price"), entry) > entry
    )
    projection_invalid = _as_float(projection.get("invalidation"), entry)
    if projection_invalid > entry:
        anchors.append(projection_invalid)
    if anchors:
        return max(anchors) + buffer, "above swept buy-side liquidity"
    return entry + max(atr, close * 0.0012), "ATR protective stop"


def _stop_is_valid(direction: str, entry: float, stop_loss: float) -> bool:
    return (direction == "bullish" and stop_loss < entry) or (direction == "bearish" and stop_loss > entry)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _live_volume_pulse(candle: dict[str, Any], candles: list[dict[str, Any]]) -> float:
    live_volume = _as_float(candle.get("volume"), 0.0)
    if live_volume <= 0:
        return 1.0
    baseline = [
        _as_float(item.get("volume"), 0.0)
        for item in candles[-25:]
        if _as_float(item.get("volume"), 0.0) > 0 and int(_as_float(item.get("timestamp"), 0.0)) != int(_as_float(candle.get("timestamp"), 0.0))
    ]
    if len(baseline) < 5:
        return 1.0
    baseline.sort()
    median = baseline[len(baseline) // 2]
    if median <= 0:
        return 1.0
    return _clamp(live_volume / median, 0.0, 5.0)


def _direction_from_signal(signal_side: Any, projection_direction: str) -> str:
    if signal_side == "buy":
        return "bullish"
    if signal_side == "sell":
        return "bearish"
    return projection_direction if projection_direction in {"bullish", "bearish"} else "neutral"


def _best_liquidity_event(events: list[dict[str, Any]], side: str) -> dict[str, Any] | None:
    if not side:
        return None
    matches = [event for event in events if event.get("side") == side]
    if not matches:
        return None
    return max(matches[-8:], key=lambda event: float(event.get("engineered_score") or 0.0))


def _phase_block_reason(payload: dict[str, Any], direction: str) -> str | None:
    if direction not in {"bullish", "bearish"}:
        return None

    regime = _dict(payload.get("regime"))
    phase = str(regime.get("phase") or "")
    confidence = _as_float(regime.get("confidence"), 0.0)
    liquidity_events = [_dict(item) for item in payload.get("liquidity_events", [])]
    aligned_side = "sell_side" if direction == "bullish" else "buy_side"
    aligned_event = _best_liquidity_event(liquidity_events, aligned_side)

    if phase == "accumulation" and direction == "bearish" and confidence >= 0.55:
        return "Accumulation phase blocks shorts until bearish breakdown confirms"
    if phase == "distribution" and direction == "bullish" and confidence >= 0.55:
        return "Distribution phase blocks longs until bullish reclaim confirms"
    if phase in {"consolidation", "range_bound"}:
        if aligned_event:
            return None
        if _option_for_direction(payload, direction):
            return None
        return f"Market phase is {phase}; wait for a liquidity sweep or range break"
    return None


def _options_block_reason(payload: dict[str, Any], direction: str) -> str | None:
    if direction not in {"bullish", "bearish"}:
        return None

    options_context = _dict(payload.get("options_context"))
    if not options_context:
        return None

    candidate = _option_for_direction(payload, direction)
    if not candidate:
        return "No Delta option contract available for final direction"

    return None


def _option_for_direction(payload: dict[str, Any], direction: str) -> dict[str, Any] | None:
    options_context = _dict(payload.get("options_context"))
    key = "call_candidate" if direction == "bullish" else "put_candidate" if direction == "bearish" else ""
    candidate = _dict(options_context.get(key))
    return candidate or None


def _directional_momentum(payload: dict[str, Any], direction: str) -> float:
    options_context = _dict(payload.get("options_context"))
    if direction == "bullish":
        return _as_float(options_context.get("bullish_momentum_score"), 0.0)
    if direction == "bearish":
        return _as_float(options_context.get("bearish_momentum_score"), 0.0)
    return _as_float(options_context.get("momentum_score"), 0.0)


def _option_calculations(option_contract: dict[str, Any]) -> list[str]:
    if not option_contract:
        return []
    delta = _as_float(option_contract.get("delta"), 0.0)
    gamma = _as_float(option_contract.get("gamma"), 0.0)
    spread_pct = _as_float(option_contract.get("spread_pct"), 0.0) * 100
    score = _as_float(option_contract.get("score"), 0.0)
    return [
        f"Option {option_contract.get('symbol')}",
        f"Delta {delta:.2f} Gamma {gamma:.6f}",
        f"Spread {spread_pct:.1f}%",
        f"Greeks score {score:.0%}",
    ]


def _prepend_unique(items: list[str], first: str) -> list[str]:
    result = [first]
    result.extend(item for item in items if item != first)
    return result


def _has_direction(items: list[dict[str, Any]], direction: str) -> bool:
    if direction not in {"bullish", "bearish"}:
        return False
    return any(item.get("direction") == direction for item in items[-10:])


def _sentiment_aligns(direction: str, sentiment_label: str) -> bool:
    return (direction == "bullish" and sentiment_label == "bullish") or (
        direction == "bearish" and sentiment_label == "bearish"
    )


def _grade(score: float) -> tuple[str, str]:
    if score >= 0.88:
        return "A+", "premium"
    if score >= 0.78:
        return "A", "premium"
    if score >= 0.68:
        return "B", "qualified"
    if score >= 0.58:
        return "C", "watchlist"
    return "NO_TRADE", "avoid"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _extract_gemini_text(response_json: dict[str, Any]) -> str:
    candidates = response_json.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini response did not include candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            return text
    raise ValueError("Gemini response did not include text")


async def _sleep_retry() -> None:
    await asyncio.sleep(2)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:180] for item in value if str(item).strip()]


def _enum(value: str, allowed: set[str], fallback: str) -> str:
    return value if value in allowed else fallback


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
