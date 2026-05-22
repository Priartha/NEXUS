from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any

import httpx

from backend.models.types import AiIctDecision, SentimentSnapshot


def _hurst_exponent(prices: list[float]) -> float:
    n = len(prices)
    if n < 20:
        return 0.5
    lags = range(10, min(n // 4, n - 1), max(1, (n // 4 - 10) // 10))
    if not lags:
        return 0.5
    tau, log_rs = [], []
    for lag in lags:
        chunks = n // lag
        if chunks < 2:
            continue
        rs = []
        for c in range(chunks):
            segment = prices[c * lag : (c + 1) * lag]
            mean = sum(segment) / lag
            dev = [x - mean for x in segment]
            z = [0.0]
            for d in dev:
                z.append(z[-1] + d)
            R = max(z[1:]) - min(z[1:])
            S = (sum((x - mean) ** 2 for x in segment) / (lag - 1)) ** 0.5
            if S > 0 and R > 0:
                rs.append(R / S)
        if rs:
            avg_rs = sum(rs) / len(rs)
            tau.append(lag)
            log_rs.append(avg_rs)
    if len(tau) < 2:
        return 0.5
    from math import log

    n_vals = len(log_rs)
    sx = sum(log(t) for t in tau)
    sy = sum(log(rs) for rs in log_rs)
    sxx = sum(log(t) ** 2 for t in tau)
    sxy = sum(log(t) * log(rs) for t, rs in zip(tau, log_rs))
    h = (n_vals * sxy - sx * sy) / (n_vals * sxx - sx * sx) if (n_vals * sxx - sx * sx) != 0 else 0.5
    return max(0.01, min(0.99, h))


def _shannon_entropy(prices: list[float], bins: int = 10) -> float:
    from math import log

    if len(prices) < bins:
        return 1.0
    mn, mx = min(prices), max(prices)
    if mx == mn:
        return 0.0
    bin_w = (mx - mn) / bins
    counts = [0] * bins
    for p in prices:
        idx = min(int((p - mn) / bin_w), bins - 1)
        counts[idx] += 1
    total = len(prices)
    ent = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            ent -= p * log(p, 2)
    max_ent = log(bins, 2)
    return ent / max_ent if max_ent > 0 else 1.0


def _garch11_forecast(returns: list[float], horizon: int = 5) -> tuple[float, float]:
    """GARCH(1,1) volatility forecasting."""
    n = len(returns)
    if n < 30:
        return 0.0, 0.0
    mean_ret = sum(returns) / n
    residuals = [r - mean_ret for r in returns]
    var_init = sum(r * r for r in residuals) / n
    omega = var_init * 0.1
    alpha = 0.1
    beta = 0.85
    sigma_sq = var_init
    for _ in range(10):
        new_sigma_sq = omega + alpha * (residuals[-1] ** 2 if residuals else 0) + beta * sigma_sq
        sigma_sq = new_sigma_sq
    for _ in range(horizon):
        sigma_sq = omega + alpha * sigma_sq + beta * sigma_sq
    forecast_vol = math.sqrt(sigma_sq)
    persistence = alpha + beta
    return forecast_vol, persistence


def _kalman_filter_trend(prices: list[float]) -> dict[str, float]:
    """Kalman filter for dynamic trend tracking."""
    n = len(prices)
    if n < 10:
        return {"level": prices[-1] if prices else 0.0, "trend": 0.0, "trend_strength": 0.0, "prediction_error": 0.0, "filter_gain": 0.0}
    x = prices[0]
    v = 1.0
    R = 0.01
    Q = 0.001
    P = 1.0
    trend = 0.0
    errors: list[float] = []
    K = 0.0
    for i in range(1, n):
        x_pred = x + trend
        P_pred = P + Q
        K = P_pred / (P_pred + R)
        z = prices[i]
        innovation = z - x_pred
        errors.append(abs(innovation))
        x = x_pred + K * innovation
        trend += K * innovation * 0.1
        P = (1 - K) * P_pred
    avg_error = sum(errors[-10:]) / min(10, len(errors)) if errors else 0.0
    trend_strength = max(0.0, min(1.0, abs(trend) / max(avg_error, 0.001)))
    return {"level": x, "trend": trend, "trend_strength": trend_strength, "prediction_error": avg_error, "filter_gain": K}


def _markov_regime_switching(returns: list[float]) -> dict[str, float]:
    """Simplified Markov regime switching model."""
    n = len(returns)
    if n < 30:
        return {"bull_prob": 0.5, "bear_prob": 0.5, "transition_prob": 0.5, "regime_certainty": 0.0}
    pos_returns = [r for r in returns if r > 0]
    neg_returns = [r for r in returns if r < 0]
    bull_mean = sum(pos_returns) / len(pos_returns) if pos_returns else 0.0
    bear_mean = sum(neg_returns) / len(neg_returns) if neg_returns else 0.0
    bull_vol = math.sqrt(sum((r - bull_mean) ** 2 for r in pos_returns) / len(pos_returns)) if len(pos_returns) > 1 else 0.001
    bear_vol = math.sqrt(sum((r - bear_mean) ** 2 for r in neg_returns) / len(neg_returns)) if len(neg_returns) > 1 else 0.001
    bull_count = len(pos_returns)
    bear_count = len(neg_returns)
    bull_prior = bull_count / n
    bear_prior = bear_count / n
    last_ret = returns[-1]
    def normal_pdf(x, mu, sigma):
        return math.exp(-0.5 * ((x - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
    bull_likelihood = normal_pdf(last_ret, bull_mean, max(bull_vol, 0.001))
    bear_likelihood = normal_pdf(last_ret, bear_mean, max(bear_vol, 0.001))
    bull_post = bull_prior * bull_likelihood / max(bull_prior * bull_likelihood + bear_prior * bear_likelihood, 1e-10)
    bear_post = 1.0 - bull_post
    transition_prob = min(bull_count, bear_count) / max(n / 2, 1)
    regime_certainty = abs(bull_post - bear_post)
    return {
        "bull_prob": max(0.0, min(1.0, bull_post)),
        "bear_prob": max(0.0, min(1.0, bear_post)),
        "transition_prob": max(0.0, min(1.0, transition_prob)),
        "regime_certainty": max(0.0, min(1.0, regime_certainty)),
    }


def _monte_carlo_paths(
    initial_price: float,
    drift: float,
    volatility: float,
    steps: int = 30,
    simulations: int = 500,
) -> dict[str, float]:
    """Monte Carlo simulation for path-dependent risk analysis."""
    import random
    random.seed(int(time.time() * 1000) % (2**31))
    final_prices: list[float] = []
    max_drawdowns: list[float] = []
    dt = 1.0 / 252.0
    sqrt_dt = math.sqrt(dt)
    for _ in range(simulations):
        price = initial_price
        peak = price
        max_dd = 0.0
        for _ in range(steps):
            z = random.gauss(0, 1)
            price *= math.exp((drift - 0.5 * volatility ** 2) * dt + volatility * sqrt_dt * z)
            peak = max(peak, price)
            dd = (peak - price) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        final_prices.append(price)
        max_drawdowns.append(max_dd)
    final_prices.sort()
    p5 = final_prices[int(0.05 * simulations)]
    p50 = final_prices[int(0.50 * simulations)]
    expected_return = (p50 - initial_price) / initial_price if initial_price > 0 else 0.0
    var95 = (initial_price - p5) / initial_price if initial_price > 0 else 0.0
    avg_max_dd = sum(max_drawdowns) / len(max_drawdowns)
    return {
        "p5": p5, "p50": p50,
        "expected_return": expected_return,
        "max_drawdown_prob": avg_max_dd,
        "var95": var95,
    }


def _fourier_dominant_cycle(prices: list[float]) -> tuple[float, float]:
    """Fourier transform to detect dominant cycle period and strength."""
    n = len(prices)
    if n < 30:
        return 0.0, 0.0
    mean = sum(prices) / n
    centered = [p - mean for p in prices]
    max_power = 0.0
    dominant_period = 0
    min_period = 5
    max_period = n // 2
    for period in range(min_period, max_period + 1):
        freq = 2 * math.pi / period
        real = sum(centered[i] * math.cos(freq * i) for i in range(n))
        imag = sum(centered[i] * math.sin(freq * i) for i in range(n))
        power = (real ** 2 + imag ** 2) / n
        if power > max_power:
            max_power = power
            dominant_period = period
    total_power = sum(
        (sum(centered[i] * math.cos(2 * math.pi / p * i) for i in range(n)) ** 2 +
         sum(centered[i] * math.sin(2 * math.pi / p * i) for i in range(n)) ** 2) / n
        for p in range(min_period, max_period + 1)
    )
    cycle_strength = max_power / total_power if total_power > 0 else 0.0
    return float(dominant_period), max(0.0, min(1.0, cycle_strength))


def _volume_profile_analysis(candles: list[dict[str, Any]], num_bins: int = 20) -> dict[str, float]:
    """Volume profile analysis: POC, VAH, VAL, volume imbalance."""
    if not candles:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "volume_imbalance": 0.0}
    prices = [float(c.get("close") or 0.0) for c in candles]
    volumes = [float(c.get("volume") or 0.0) for c in candles]
    min_p = min(prices)
    max_p = max(prices)
    if max_p == min_p:
        return {"poc": min_p, "vah": min_p, "val": min_p, "volume_imbalance": 0.0}
    bin_width = (max_p - min_p) / num_bins
    bin_volumes = [0.0] * num_bins
    for price, volume in zip(prices, volumes):
        idx = min(int((price - min_p) / bin_width), num_bins - 1)
        bin_volumes[idx] += volume
    total_volume = sum(bin_volumes)
    if total_volume == 0:
        return {"poc": min_p, "vah": max_p, "val": min_p, "volume_imbalance": 0.0}
    poc_idx = bin_volumes.index(max(bin_volumes))
    poc = min_p + (poc_idx + 0.5) * bin_width
    upper_vol = sum(bin_volumes[i] for i in range(poc_idx + 1, num_bins))
    lower_vol = sum(bin_volumes[i] for i in range(0, poc_idx))
    imbalance = (upper_vol - lower_vol) / max(total_volume, 1e-10)
    return {"poc": poc, "vah": max_p, "val": min_p, "volume_imbalance": max(-1.0, min(1.0, imbalance))}


def _skewness_kurtosis(returns: list[float]) -> tuple[float, float]:
    """Compute skewness and kurtosis of returns distribution."""
    n = len(returns)
    if n < 10:
        return 0.0, 3.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(var) if var > 0 else 1e-10
    skew = sum((r - mean) ** 3 for r in returns) / (n * std ** 3)
    kurt = sum((r - mean) ** 4 for r in returns) / (n * std ** 4)
    return skew, kurt


def _fractal_dimension(prices: list[float]) -> float:
    """Fractal dimension via box-counting method."""
    n = len(prices)
    if n < 20:
        return 1.5
    min_p = min(prices)
    max_p = max(prices)
    range_p = max_p - min_p
    if range_p == 0:
        return 1.0
    num_boxes = 0
    box_size_x = n / 10.0
    box_size_y = range_p / 10.0
    for i in range(10):
        x_start = i * box_size_x
        x_end = (i + 1) * box_size_x
        segment = prices[int(x_start):int(x_end)]
        if not segment:
            continue
        seg_min = min(segment)
        seg_max = max(segment)
        num_boxes += math.ceil((seg_max - seg_min) / max(box_size_y, 1e-10))
    d = math.log(max(num_boxes, 1)) / math.log(10)
    return max(1.0, min(2.0, d))


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
                                "You are a quantitative statistical analyst inside a BTC trading terminal. "
                                "Return one final setup only: bullish, bearish, or neutral/NO_TRADE. Use only the supplied technical "
                                "snapshot. The local pricing engine enforces a fixed 1:3 risk/reward plan, so refine direction, grade, "
                                "confidence, confirmations, and blockers only. Do not claim certainty and do not use the word guarantee "
                                "except to say there is no guarantee. Return strict JSON. Grade only if the setup has sufficient evidence "
                                "from VWAP deviations, Bollinger Bands, RSI extremes, volatility regimes, volume confirmation, trend "
                                "slope, and sentiment.\n\n"
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
            execution_block = _phase_block_reason(payload, direction)
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
            if execution_block:
                confirmations = []
                summary = f"WAIT setup: NO_TRADE / avoid. {execution_block}."

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
        signals = [_dict(item) for item in payload.get("signals", [])]
        candles = [_dict(item) for item in payload.get("candles", [])]
        candle = _dict(payload.get("candle"))
        timeframe = str(payload.get("timeframe") or "5m")
        timestamp = int(candle.get("timestamp") or projection.get("timestamp") or metrics.get("timestamp") or int(time.time() * 1000))

        scorecard = {"bullish": 0.0, "bearish": 0.0}
        evidence: dict[str, list[str]] = {"bullish": [], "bearish": []}
        sentiment_label = sentiment.label

        def add(direction_key: str, points: float, reason: str) -> None:
            if direction_key not in scorecard or points <= 0:
                return
            scorecard[direction_key] += points
            evidence[direction_key].append(reason)

        def subtract(direction_key: str, points: float, reason: str) -> None:
            if direction_key not in scorecard or points <= 0:
                return
            scorecard[direction_key] = max(0.0, scorecard[direction_key] - points)
            evidence[direction_key].append(f"[-{reason}]")

        buy_signal = _best_signal_for_side(signals, "buy")
        sell_signal = _best_signal_for_side(signals, "sell")
        for side, signal in (("buy", buy_signal), ("sell", sell_signal)):
            if not signal:
                continue
            direction_key = "bullish" if side == "buy" else "bearish"
            signal_confidence = float(signal.get("confidence") or 0.0)
            rr = float(signal.get("risk_reward") or 0.0)
            if signal_confidence >= 0.50 and rr >= 2.0:
                add(
                    direction_key,
                    signal_confidence * 0.22 + min(rr / 4.0, 1.0) * 0.06,
                    f"{side.upper()} signal {signal_confidence:.0%} conf, {rr:.1f}R",
                )

        # ── Psychology & Readability: validation layer only ──
        # Signals already have psychology/readability baked into confidence.
        # AI uses these as conflict detectors, not additive scoring.
        psychology = _dict(payload.get("psychology"))
        readability = _dict(payload.get("readability"))

        if psychology and readability:
            fg_label = str(psychology.get("fear_greed_label") or "neutral")
            emotional = str(psychology.get("emotional_state") or "balanced")
            trap_risk = _as_float(psychology.get("trap_risk"), 0.5)
            grade = str(readability.get("grade") or "C")
            tradeability = str(readability.get("tradeability") or "fair")

            # Block signals that contradict extreme psychology
            if fg_label == "extreme_fear" and buy_signal:
                # Extreme fear + buy signal = potential capitulation bottom, let it through
                pass
            elif fg_label == "extreme_greed" and sell_signal:
                # Extreme greed + sell signal = potential FOMO top, let it through
                pass
            elif fg_label == "extreme_fear" and sell_signal:
                subtract("bearish", 0.10, "Psychology conflict: selling into extreme fear/capitulation")
            elif fg_label == "extreme_greed" and buy_signal:
                subtract("bullish", 0.10, "Psychology conflict: buying into extreme greed/FOMO")

            # Emotional extremes that contradict signals
            if emotional == "panic" and sell_signal:
                subtract("bearish", 0.06, "Psychology conflict: selling during panic")
            elif emotional == "euphoric" and buy_signal:
                subtract("bullish", 0.06, "Psychology conflict: buying during euphoria")

            # High trap risk blocks breakout signals
            if trap_risk > 0.75:
                subtract("bullish", 0.05, f"Psychology: high trap risk ({trap_risk:.0%})")
                subtract("bearish", 0.05, f"Psychology: high trap risk ({trap_risk:.0%})")

            # Poor readability = reduce confidence in all signals
            if grade in ("D", "F"):
                subtract("bullish", 0.06, f"Readability: poor clarity (grade {grade})")
                subtract("bearish", 0.06, f"Readability: poor clarity (grade {grade})")
            elif grade == "C":
                subtract("bullish", 0.02, f"Readability: moderate clarity (grade {grade})")
                subtract("bearish", 0.02, f"Readability: moderate clarity (grade {grade})")

            # Avoid tradeability = strong block
            if tradeability == "avoid":
                subtract("bullish", 0.08, "Readability: market conditions suggest avoiding trades")
                subtract("bearish", 0.08, "Readability: market conditions suggest avoiding trades")
            elif tradeability == "poor":
                subtract("bullish", 0.04, "Readability: poor tradeability")
                subtract("bearish", 0.04, "Readability: poor tradeability")

        projection_direction = str(projection.get("direction") or "neutral")
        if projection_direction in {"bullish", "bearish"}:
            projection_confidence = float(projection.get("probability") or 0.5)
            if projection_confidence >= 0.55:
                add(projection_direction, projection_confidence * 0.10, f"Projection {projection_confidence:.0%}")

        regime_phase = str(regime.get("phase") or "")
        regime_bias = str(regime.get("bias") or "")
        regime_confidence = float(regime.get("confidence") or 0.0)
        if regime_phase == "accumulation":
            add("bullish", 0.08 + regime_confidence * 0.04, f"Accumulation {regime_confidence:.0%}")
        elif regime_phase == "distribution":
            add("bearish", 0.08 + regime_confidence * 0.04, f"Distribution {regime_confidence:.0%}")
        elif regime_phase in {"consolidation", "range_bound"}:
            subtract("bullish", 0.06, "Consolidation phase")
            subtract("bearish", 0.06, "Consolidation phase")

        if sentiment_label in {"bullish", "bearish"}:
            add(sentiment_label, sentiment.confidence * 0.05, f"AI sentiment {sentiment_label}")

        # BTC patterns
        btc_patterns = _dict(payload.get("btc_patterns"))
        if btc_patterns:
            pat_signal = str(btc_patterns.get("pattern_signal") or "neutral")
            bull_pat_score = float(btc_patterns.get("bullish_pattern_score") or 0.0)
            bear_pat_score = float(btc_patterns.get("bearish_pattern_score") or 0.0)
            if pat_signal == "bullish" and bull_pat_score > 0.15:
                add("bullish", min(bull_pat_score * 0.12, 0.12), f"BTC patterns score {bull_pat_score:.3f}")
            elif pat_signal == "bearish" and bear_pat_score > 0.15:
                add("bearish", min(bear_pat_score * 0.12, 0.12), f"BTC patterns score {bear_pat_score:.3f}")

        # ── Statistical evidence factors ──
        close = float(candle.get("close") or 0.0) or _as_float(candles[-1].get("close")) if candles else 0.0
        vwap = _as_float(metrics.get("vwap"), close)
        vwap_dev_pct = (close - vwap) / vwap if vwap > 0 else 0.0
        rsi14 = _as_float(metrics.get("rsi14"), 50.0)
        volume_z = _as_float(metrics.get("volume_zscore"), 0.0)
        bb_upper = _as_float(metrics.get("bb_upper"), close)
        bb_lower = _as_float(metrics.get("bb_lower"), close)
        bb_width = bb_upper - bb_lower
        bb_b = (close - bb_lower) / bb_width if bb_width > 0 else 0.5
        trend_score_val = _as_float(metrics.get("trend_score"), 0.0)
        atr14 = _as_float(metrics.get("atr14"), 0.0)

        close_series = [float(c.get("close") or 0.0) for c in candles if float(c.get("close") or 0.0) > 0]

        # ── Advanced institutional math ──
        if len(close_series) >= 50:
            returns = [math.log(close_series[i] / close_series[i - 1]) for i in range(1, len(close_series))]
            garch_vol, garch_persistence = _garch11_forecast(returns[-60:] if len(returns) >= 60 else returns)
            kalman = _kalman_filter_trend(close_series[-80:] if len(close_series) >= 80 else close_series)
            markov = _markov_regime_switching(returns[-60:] if len(returns) >= 60 else returns)
            mc_results = _monte_carlo_paths(close_series[-1], kalman["trend"], garch_vol if garch_vol > 0 else 0.01, steps=20, simulations=200)
            dominant_period, cycle_strength = _fourier_dominant_cycle(close_series[-100:] if len(close_series) >= 100 else close_series)
            vol_profile = _volume_profile_analysis(candles[-50:] if len(candles) >= 50 else candles)
            skew, kurt = _skewness_kurtosis(returns[-60:] if len(returns) >= 60 else returns)
            fractal_dim = _fractal_dimension(close_series[-80:] if len(close_series) >= 80 else close_series)

            hurst = _hurst_exponent(close_series)
            entropy = _shannon_entropy(close_series)

            # Hurst regime
            if hurst < 0.4:
                add("bullish" if vwap_dev_pct < -0.005 else "bearish" if vwap_dev_pct > 0.005 else "", 0.04, f"Hurst {hurst:.2f} mean-reverting")
            elif hurst > 0.6:
                add("bullish" if trend_score_val > 0.1 else "bearish" if trend_score_val < -0.1 else "", 0.04, f"Hurst {hurst:.2f} trending")

            # Kalman trend
            if kalman["trend_strength"] > 0.7:
                trend_dir = "bullish" if kalman["trend"] > 0 else "bearish"
                add(trend_dir, kalman["trend_strength"] * 0.03, f"Kalman {trend_dir} {kalman['trend_strength']:.2f}")

            # Markov regime
            if markov["regime_certainty"] > 0.6:
                regime_dir = "bullish" if markov["bull_prob"] > markov["bear_prob"] else "bearish"
                add(regime_dir, markov["regime_certainty"] * 0.03, f"Markov {regime_dir} {markov['regime_certainty']:.2f}")

            # Monte Carlo VaR penalty
            if mc_results["var95"] > 0.06:
                subtract("bullish", 0.04, f"MC VaR95 {mc_results['var95']:.2%}")
                subtract("bearish", 0.04, f"MC VaR95 {mc_results['var95']:.2%}")

            # Volume profile
            if abs(vol_profile["volume_imbalance"]) > 0.35:
                vol_dir = "bullish" if vol_profile["volume_imbalance"] > 0 else "bearish"
                add(vol_dir, abs(vol_profile["volume_imbalance"]) * 0.03, f"Vol imbalance {vol_profile['volume_imbalance']:.2f}")

            # Skewness
            if abs(skew) > 1.2:
                skew_dir = "bullish" if skew > 0 else "bearish"
                add(skew_dir, 0.02, f"Skew {skew:.2f}")

            # Fractal dimension
            if fractal_dim < 1.25:
                add("bullish" if trend_score_val > 0.1 else "bearish" if trend_score_val < -0.1 else "", 0.02, f"Fractal {fractal_dim:.2f}")
            elif fractal_dim > 1.75:
                subtract("bullish", 0.02, f"Fractal chaos {fractal_dim:.2f}")
                subtract("bearish", 0.02, f"Fractal chaos {fractal_dim:.2f}")

        # VWAP deviation: only significant deviations matter
        if abs(vwap_dev_pct) >= 0.008:
            vwap_factor = min(abs(vwap_dev_pct) * 1.2, 0.10)
            vwap_dir = "bullish" if vwap_dev_pct < 0 else "bearish"
            add(vwap_dir, vwap_factor, f"VWAP dev {vwap_dev_pct*100:.2f}%")

        # Bollinger Band %b: only at extremes
        if bb_b <= 0.10:
            add("bullish", 0.05 + (0.10 - bb_b) * 0.15, f"BB extreme low %b={bb_b:.2f}")
        elif bb_b >= 0.90:
            add("bearish", 0.05 + (bb_b - 0.90) * 0.15, f"BB extreme high %b={bb_b:.2f}")

        # RSI: only at true extremes
        if rsi14 <= 28:
            add("bullish", 0.06 + (28 - rsi14) * 0.004, f"RSI deeply oversold {rsi14:.1f}")
        elif rsi14 >= 72:
            add("bearish", 0.06 + (rsi14 - 72) * 0.004, f"RSI deeply overbought {rsi14:.1f}")

        # Trend score: only significant trends
        if abs(trend_score_val) >= 0.25:
            trend_dir = "bullish" if trend_score_val > 0 else "bearish"
            add(trend_dir, min(abs(trend_score_val) * 0.10, 0.08), f"Trend {trend_dir} {trend_score_val:.3f}")

        # Volume confirmation
        if volume_z >= 1.5:
            vol_dir = "bullish" if scorecard["bullish"] >= scorecard["bearish"] else "bearish"
            add(vol_dir, min(volume_z * 0.02, 0.04), f"Volume spike z={volume_z:.1f}")

        volume_pulse = _live_volume_pulse(candle, candles)
        if volume_pulse >= 1.5:
            pulse_dir = "bullish" if scorecard["bullish"] >= scorecard["bearish"] else "bearish"
            add(pulse_dir, min(0.03, (volume_pulse - 1.0) * 0.05), f"Vol pulse {volume_pulse:.1f}x")

        # Premium/discount
        premium_discount = _as_float(metrics.get("premium_discount"), 0.0)
        if premium_discount <= -0.30:
            add("bullish", 0.03, "Deep discount pricing")
        elif premium_discount >= 0.30:
            add("bearish", 0.03, "Deep premium pricing")

        # ── Conflict detection: penalize when subsystems disagree ──
        direction = "bullish" if scorecard["bullish"] > scorecard["bearish"] else "bearish" if scorecard["bearish"] > scorecard["bullish"] else "neutral"
        opposite = "bearish" if direction == "bullish" else "bullish" if direction == "bearish" else ""

        # Check for conflicts between signal and regime
        if buy_signal and sell_signal:
            subtract("bullish", 0.08, "Both buy and sell signals active")
            subtract("bearish", 0.08, "Both buy and sell signals active")

        # Check for conflict between projection and regime
        if projection_direction != "neutral" and regime_bias != "neutral" and projection_direction != regime_bias:
            subtract(projection_direction, 0.06, f"Projection conflicts with regime ({regime_bias})")

        # Check sentiment conflict
        if sentiment_label in {"bullish", "bearish"} and sentiment_label != direction and direction != "neutral":
            subtract(direction, 0.05, f"Sentiment conflict: {sentiment_label}")

        # ── Multi-timeframe confluence check ──
        mtf = _dict(payload.get("mtf_confluence"))
        if mtf and mtf.get("confluence_factor"):
            confluence_factor = float(mtf["confluence_factor"])
            higher_tf = str(mtf.get("higher_tf_bias", "neutral"))
            alignment = float(mtf.get("alignment_score", 0.5))
            if direction == "bullish" and higher_tf == "bullish" and alignment > 0.6:
                add("bullish", 0.06, f"MTF aligned bullish ({alignment:.0%} across {mtf.get('timeframes_checked', 0)} TFs)")
            elif direction == "bearish" and higher_tf == "bearish" and alignment > 0.6:
                add("bearish", 0.06, f"MTF aligned bearish ({alignment:.0%} across {mtf.get('timeframes_checked', 0)} TFs)")
            elif direction != "neutral" and higher_tf not in {"neutral", direction}:
                subtract(direction, 0.08, f"MTF conflict: higher TF {higher_tf}")
            # Apply confluence factor to final score
            if confluence_factor != 1.0 and direction != "neutral":
                scorecard[direction] *= confluence_factor

        # ── Final scoring ──
        separation = abs(scorecard[direction] - scorecard[opposite]) if direction != "neutral" else 0
        score = _clamp(scorecard[direction] + separation * 0.35, 0.0, 0.92) if direction != "neutral" else 0.0
        confirmations = evidence[direction][:7] if direction != "neutral" else []
        blockers: list[str] = []

        # Strict thresholds for execution
        if scorecard[direction] < 0.45:
            blockers.append("Combined confluence below execution threshold")
        if separation < 0.20:
            blockers.append("Bullish and bearish evidence too close (no clear edge)")
        execution_block = _phase_block_reason(payload, direction)
        if execution_block:
            blockers.append(execution_block)
        if execution_block:
            direction = "neutral"
            score = min(score, 0.45)
            confirmations = []
            blockers = _prepend_unique(blockers, execution_block)
        elif scorecard[direction] < 0.30:
            direction = "neutral"
            score = min(score, 0.45)
            confirmations = []
            blockers.append("No execution-grade directional edge")

        if direction in {"bullish", "bearish"}:
            active_signal = buy_signal if direction == "bullish" else sell_signal
            if active_signal is None:
                blockers.append(f"No active {direction.upper()} signal")
                direction = "neutral"
                score = min(score, 0.45)
                confirmations = []

        price_plan = _build_price_plan(
            payload=payload,
            direction=direction,
            signal=buy_signal if direction == "bullish" else sell_signal if direction == "bearish" else None,
            candle=candle,
            candles=candles,
            metrics=metrics,
            projection=projection,
        )
        score = _clamp(score, 0.0, 0.92)
        grade, readiness = _grade(score)
        confidence = min(0.92, score * 0.94)

        if grade == "NO_TRADE":
            readiness = "avoid"
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
            f"ATR14 {atr14:.2f}",
            f"VWAP {vwap:.2f}",
            f"RSI14 {rsi14:.1f}",
            f"BB %b {bb_b:.2f}",
            f"VWAP dev {vwap_dev_pct*100:.2f}%",
            f"Volume z-score {volume_z:.2f}",
            f"Trend slope {trend_score_val:.3f}",
            f"Premium/discount {premium_discount:.2f}",
            f"Live volume pulse {volume_pulse:.2f}x",
            f"Phase {regime_phase or 'unknown'}",
            f"BTC patterns: {len(btc_patterns.get('patterns',[])) if btc_patterns else 0} patterns, signal {btc_patterns.get('pattern_signal','neutral') if btc_patterns else 'neutral'}",
            *price_plan["calculations"],
        ]

        action = "WAIT" if direction == "neutral" or grade == "NO_TRADE" else ("BUY" if direction == "bullish" else "SELL")
        behavior_context = ""
        if btc_patterns:
            behaviors = btc_patterns.get("investor_behaviors", [])
            if behaviors:
                best_b = max(behaviors, key=lambda b: float(b.get("confidence") or 0))
                behavior_context = f" {best_b.get('behavior_type','').replace('_',' ')} detected ({best_b.get('confidence',0):.0%} conf);"

        if action == "WAIT":
            wait_reason = blockers[0] if blockers else "Execution-grade confirmation not present"
            summary = f"WAIT setup: NO_TRADE / avoid. Phase {regime_phase or 'unknown'};{behavior_context} {wait_reason}."
        else:
            summary = f"{action} setup: {grade} / {readiness}. Phase {regime_phase or 'unknown'};{behavior_context} one 1:3 plan from VWAP, Bollinger, RSI, volume, trend, and statistical confluence."

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
    psychology = payload.get("psychology")
    readability = payload.get("readability")
    return {
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "latest_candle": payload.get("candle"),
        "metrics": payload.get("metrics"),
        "projection": payload.get("projection"),
        "regime": payload.get("regime"),
        "latest_signals": payload.get("signals", [])[-8:],
        "btc_patterns": payload.get("btc_patterns"),
        "psychology": {
            "fear_greed_label": psychology.get("fear_greed_label") if psychology else None,
            "fear_greed_score": psychology.get("fear_greed_score") if psychology else None,
            "emotional_state": psychology.get("emotional_state") if psychology else None,
            "retail_participation": psychology.get("retail_participation") if psychology else None,
            "smart_money_activity": psychology.get("smart_money_activity") if psychology else None,
            "trap_risk": psychology.get("trap_risk") if psychology else None,
            "conviction_score": psychology.get("conviction_score") if psychology else None,
            "summary": psychology.get("summary") if psychology else None,
        } if psychology else None,
        "readability": {
            "grade": readability.get("grade") if readability else None,
            "overall_score": readability.get("overall_score") if readability else None,
            "tradeability": readability.get("tradeability") if readability else None,
            "noise_level": readability.get("noise_level") if readability else None,
            "dominant_pattern": readability.get("dominant_pattern") if readability else None,
            "structure_reliability": readability.get("structure_reliability") if readability else None,
            "key_observations": readability.get("key_observations") if readability else None,
        } if readability else None,
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
        entry_reason = "AI selected primary signal entry"
    else:
        entry, entry_reason = _derive_entry(direction, close, metrics)

    if signal_stop is not None and _stop_is_valid(direction, entry, signal_stop):
        stop_loss = signal_stop
        stop_reason = "primary signal invalidation"
    else:
        stop_loss, stop_reason = _derive_stop(direction, entry, close, atr, metrics, candles, projection)

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
) -> tuple[float, str]:
    candidates: list[tuple[float, float, str]] = []

    def add(price: float, reason: str, weight: float = 1.0) -> None:
        if price <= 0:
            return
        if direction == "bullish" and price <= close:
            candidates.append((price, abs(close - price) * weight, reason))
        if direction == "bearish" and price >= close:
            candidates.append((price, abs(close - price) * weight, reason))

    add(_as_float(metrics.get("vwap"), 0.0), "VWAP", 1.0)

    sma20 = _as_float(metrics.get("sma20"), 0.0)
    if sma20 > 0:
        add(sma20, "SMA20", 0.95)

    bb_lower = _as_float(metrics.get("bb_lower"), 0.0)
    if bb_lower > 0 and direction == "bullish":
        add(bb_lower, "BB lower", 0.90)

    bb_upper = _as_float(metrics.get("bb_upper"), 0.0)
    if bb_upper > 0 and direction == "bearish":
        add(bb_upper, "BB upper", 0.90)

    if not candidates:
        return close, "market close"
    price, _, reason = min(candidates, key=lambda item: item[1])
    return price, reason


def _derive_stop(
    direction: str,
    entry: float,
    close: float,
    atr: float,
    metrics: dict[str, Any],
    candles: list[dict[str, Any]],
    projection: dict[str, Any],
) -> tuple[float, str]:
    buffer = max(atr * 0.22, _as_float(metrics.get("expected_move"), atr) * 0.08, close * 0.00035)
    recent = candles[-14:]
    if direction == "bullish":
        anchors = [_as_float(item.get("low"), entry) for item in recent if _as_float(item.get("low"), entry) < entry]
        projection_invalid = _as_float(projection.get("invalidation"), entry)
        if projection_invalid < entry:
            anchors.append(projection_invalid)
        if anchors:
            return min(anchors) - buffer, "below recent swing low"
        return entry - max(atr * 1.2, close * 0.0012), "ATR-based stop"

    anchors = [_as_float(item.get("high"), entry) for item in recent if _as_float(item.get("high"), entry) > entry]
    projection_invalid = _as_float(projection.get("invalidation"), entry)
    if projection_invalid > entry:
        anchors.append(projection_invalid)
    if anchors:
        return max(anchors) + buffer, "above recent swing high"
    return entry + max(atr * 1.2, close * 0.0012), "ATR-based stop"


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


def _phase_block_reason(payload: dict[str, Any], direction: str) -> str | None:
    if direction not in {"bullish", "bearish"}:
        return None

    regime = _dict(payload.get("regime"))
    phase = str(regime.get("phase") or "")
    confidence = _as_float(regime.get("confidence"), 0.0)

    if phase == "accumulation" and direction == "bearish" and confidence >= 0.55:
        return "Accumulation phase blocks shorts until bearish breakdown confirms"
    if phase == "distribution" and direction == "bullish" and confidence >= 0.55:
        return "Distribution phase blocks longs until bullish reclaim confirms"
    if phase in {"consolidation", "range_bound"}:
        return f"Market phase is {phase}; wait for statistical breakout confirmation"
    return None


def _prepend_unique(items: list[str], first: str) -> list[str]:
    result = [first]
    result.extend(item for item in items if item != first)
    return result


def _sentiment_aligns(direction: str, sentiment_label: str) -> bool:
    return (direction == "bullish" and sentiment_label == "bullish") or (
        direction == "bearish" and sentiment_label == "bearish"
    )


def _grade(score: float) -> tuple[str, str]:
    if score >= 0.90:
        return "A+", "premium"
    if score >= 0.80:
        return "A", "premium"
    if score >= 0.70:
        return "B", "qualified"
    if score >= 0.60:
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
