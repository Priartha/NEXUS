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
    random.seed(42)
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
                                "slope, options Greeks, and sentiment.\n\n"
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
        candles = [_dict(item) for item in payload.get("candles", [])]
        candle = _dict(payload.get("candle"))
        timeframe = str(payload.get("timeframe") or "5m")
        timestamp = int(candle.get("timestamp") or projection.get("timestamp") or metrics.get("timestamp") or int(time.time() * 1000))

        scorecard = {"bullish": 0.18, "bearish": 0.18}
        evidence: dict[str, list[str]] = {"bullish": [], "bearish": []}
        sentiment_label = sentiment.label

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
            add(projection_direction, projection_confidence * 0.14, f"Statistical projection {projection_confidence:.0%}")

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

        # BTC movement & investor behavior patterns
        btc_patterns = _dict(payload.get("btc_patterns"))
        if btc_patterns:
            pat_signal = str(btc_patterns.get("pattern_signal") or "neutral")
            bull_pat_score = float(btc_patterns.get("bullish_pattern_score") or 0.0)
            bear_pat_score = float(btc_patterns.get("bearish_pattern_score") or 0.0)
            if pat_signal == "bullish":
                add("bullish", min(bull_pat_score * 0.18, 0.18), f"BTC pattern cluster: {len(btc_patterns.get('patterns',[]))} patterns score {bull_pat_score:.3f}")
                for b in btc_patterns.get("investor_behaviors", [])[-3:]:
                    b_side = str(b.get("side") or "")
                    b_type = str(b.get("behavior_type") or "")
                    b_conf = float(b.get("confidence") or 0.0)
                    b_intensity = float(b.get("intensity") or 0.0)
                    if b_side == "bullish":
                        add("bullish", min(b_intensity * 0.1, 0.1), f"Investor behavior: {b_type} ({b_conf:.0%} conf)")
            elif pat_signal == "bearish":
                add("bearish", min(bear_pat_score * 0.18, 0.18), f"BTC pattern cluster: {len(btc_patterns.get('patterns',[]))} patterns score {bear_pat_score:.3f}")
                for b in btc_patterns.get("investor_behaviors", [])[-3:]:
                    b_side = str(b.get("side") or "")
                    b_type = str(b.get("behavior_type") or "")
                    b_conf = float(b.get("confidence") or 0.0)
                    b_intensity = float(b.get("intensity") or 0.0)
                    if b_side == "bearish":
                        add("bearish", min(b_intensity * 0.1, 0.1), f"Investor behavior: {b_type} ({b_conf:.0%} conf)")

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

        # ── Institutional math: Hurst, Entropy, Expected Value ──
        close_series = [float(c.get("close") or 0.0) for c in candles if float(c.get("close") or 0.0) > 0]
        if len(close_series) >= 50:
            hurst = _hurst_exponent(close_series)
            entropy = _shannon_entropy(close_series)
            hurst_bias = "mean_reverting" if hurst < 0.4 else "trending" if hurst > 0.6 else "random"
            # Hurst regime alignment boosts conviction
            if hurst < 0.4:
                add("bullish" if vwap_dev_pct < 0 else "bearish", 0.05, f"Hurst {hurst:.2f} mean-reverting regime")
            elif hurst > 0.6:
                add("bullish" if trend_score_val > 0 else "bearish", 0.05, f"Hurst {hurst:.2f} trending regime")
            # Low entropy = structured market = higher signal trust
            if entropy < 0.6:
                add("bullish" if scorecard.get("bullish", 0) >= scorecard.get("bearish", 0) else "bearish", 0.04, f"Entropy {entropy:.2f} structured market")
        else:
            hurst = 0.5
            entropy = 1.0

        # ── Advanced institutional math: GARCH, Kalman, Markov, Monte Carlo, Fourier, Volume Profile ──
        if len(close_series) >= 50:
            # GARCH(1,1) volatility forecast
            returns = [math.log(close_series[i] / close_series[i - 1]) for i in range(1, len(close_series))]
            garch_vol, garch_persistence = _garch11_forecast(returns[-60:] if len(returns) >= 60 else returns)
            if garch_vol > 0:
                vol_extreme = "high" if garch_vol > 0.02 else "low" if garch_vol < 0.005 else "normal"
                if vol_extreme == "low":
                    add("bullish" if vwap_dev_pct < 0 else "bearish", 0.03, f"GARCH vol low {garch_vol:.4f} (reversion edge)")
                elif vol_extreme == "high" and garch_persistence > 0.9:
                    add("bullish" if trend_score_val > 0 else "bearish", 0.03, f"GARCH vol clustering {garch_persistence:.2f}")

            # Kalman filter trend strength
            kalman = _kalman_filter_trend(close_series[-80:] if len(close_series) >= 80 else close_series)
            if kalman["trend_strength"] > 0.6:
                trend_dir = "bullish" if kalman["trend"] > 0 else "bearish"
                add(trend_dir, kalman["trend_strength"] * 0.04, f"Kalman trend {trend_dir} strength {kalman['trend_strength']:.2f}")

            # Markov regime switching
            markov = _markov_regime_switching(returns[-60:] if len(returns) >= 60 else returns)
            if markov["regime_certainty"] > 0.5:
                regime_dir = "bullish" if markov["bull_prob"] > markov["bear_prob"] else "bearish"
                add(regime_dir, markov["regime_certainty"] * 0.04, f"Markov {regime_dir} certainty {markov['regime_certainty']:.2f}")

            # Monte Carlo VaR
            mc_results = _monte_carlo_paths(close_series[-1], kalman["trend"], garch_vol if garch_vol > 0 else 0.01, steps=20, simulations=200)
            if mc_results["var95"] < 0.03:
                add("bullish" if scorecard.get("bullish", 0) >= scorecard.get("bearish", 0) else "bearish", 0.03, f"MC VaR95 low {mc_results['var95']:.2%}")
            elif mc_results["var95"] > 0.06:
                scorecard["bullish"] -= 0.03
                scorecard["bearish"] -= 0.03

            # Fourier cycle detection
            dominant_period, cycle_strength = _fourier_dominant_cycle(close_series[-100:] if len(close_series) >= 100 else close_series)
            if cycle_strength > 0.4 and 15 <= dominant_period <= 50:
                add("bullish" if vwap_dev_pct < 0 else "bearish", cycle_strength * 0.03, f"Fourier cycle {dominant_period:.0f} strength {cycle_strength:.2f}")

            # Volume profile
            vol_profile = _volume_profile_analysis(candles[-50:] if len(candles) >= 50 else candles)
            if vol_profile["volume_imbalance"] > 0.3:
                add("bullish", vol_profile["volume_imbalance"] * 0.03, f"Volume profile bullish imbalance {vol_profile['volume_imbalance']:.2f}")
            elif vol_profile["volume_imbalance"] < -0.3:
                add("bearish", abs(vol_profile["volume_imbalance"]) * 0.03, f"Volume profile bearish imbalance {vol_profile['volume_imbalance']:.2f}")

            # Skewness/Kurtosis
            skew, kurt = _skewness_kurtosis(returns[-60:] if len(returns) >= 60 else returns)
            if abs(skew) > 1.0:
                skew_dir = "bullish" if skew > 0 else "bearish"
                add(skew_dir, 0.02, f"Return skewness {skew:.2f} ({skew_dir} tail)")
            if kurt > 4.0:
                add("bullish" if scorecard.get("bullish", 0) >= scorecard.get("bearish", 0) else "bearish", 0.02, f"Fat tails kurtosis {kurt:.2f}")

            # Fractal dimension
            fractal_dim = _fractal_dimension(close_series[-80:] if len(close_series) >= 80 else close_series)
            if fractal_dim < 1.3:
                add("bullish" if trend_score_val > 0 else "bearish", 0.02, f"Fractal dim {fractal_dim:.2f} (smooth trend)")
            elif fractal_dim > 1.7:
                scorecard["bullish"] -= 0.02
                scorecard["bearish"] -= 0.02

        # Expected value from signal confidence and risk/reward
        for side_key, sig in (("bullish", buy_signal), ("bearish", sell_signal)):
            if sig:
                sig_side = "bullish" if sig.get("side") == "buy" else "bearish"
                sc = float(sig.get("confidence") or 0.0)
                rr = float(sig.get("risk_reward") or 0.0)
                ev = sc * rr - (1.0 - sc)
                ev_ratio = ev / max(rr, 0.1)
                if ev_ratio > 0.15:
                    add(sig_side, min(ev_ratio * 0.08, 0.08), f"Expected value {ev_ratio:.2f}R (EV={ev:.3f})")

        # VWAP deviation z-score: large deviation = mean reversion edge
        if abs(vwap_dev_pct) >= 0.003:
            vwap_factor = min(abs(vwap_dev_pct) * 1.5, 0.12)
            vwap_dir = "bullish" if vwap_dev_pct < 0 else "bearish"
            add(vwap_dir, vwap_factor, f"VWAP deviation {vwap_dev_pct*100:.2f}% ({vwap_dir})")

        # Bollinger Band %b: extremes signal reversal pressure
        if bb_b <= 0.15:
            add("bullish", 0.06 + (0.15 - bb_b) * 0.2, f"BB lower touch (%b={bb_b:.2f})")
        elif bb_b >= 0.85:
            add("bearish", 0.06 + (bb_b - 0.85) * 0.2, f"BB upper touch (%b={bb_b:.2f})")

        # RSI regime
        if rsi14 <= 35:
            add("bullish", 0.08 + (35 - rsi14) * 0.005, f"RSI oversold {rsi14:.1f}")
        elif rsi14 <= 42:
            add("bullish", 0.04, f"RSI near oversold {rsi14:.1f}")
        elif rsi14 >= 65:
            add("bearish", 0.08 + (rsi14 - 65) * 0.005, f"RSI overbought {rsi14:.1f}")
        elif rsi14 >= 58:
            add("bearish", 0.04, f"RSI near overbought {rsi14:.1f}")

        # Trend score: positive = bullish, negative = bearish
        if abs(trend_score_val) >= 0.15:
            trend_dir = "bullish" if trend_score_val > 0 else "bearish"
            add(trend_dir, min(abs(trend_score_val) * 0.12, 0.10), f"Regression trend slope {trend_score_val:.3f} ({trend_dir})")

        # Volume confirmation
        if volume_z >= 1.0:
            vol_dir = "bullish" if scorecard["bullish"] >= scorecard["bearish"] else "bearish"
            add(vol_dir, min(volume_z * 0.03, 0.06), f"Volume z-score {volume_z:.2f} ({vol_dir})")

        volume_pulse = _live_volume_pulse(candle, candles)
        if volume_pulse >= 1.35:
            pulse_dir = "bullish" if scorecard["bullish"] >= scorecard["bearish"] else "bearish"
            add(pulse_dir, min(0.05, (volume_pulse - 1.0) * 0.08), f"Live volume pulse {volume_pulse:.2f}x")

        # Premium/discount pricing extreme
        premium_discount = _as_float(metrics.get("premium_discount"), 0.0)
        if premium_discount <= -0.25:
            add("bullish", 0.035, "Discount-side pricing extreme")
        elif premium_discount >= 0.25:
            add("bearish", 0.035, "Premium-side pricing extreme")

        # Options momentum
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
        phase_block = _phase_block_reason(payload, direction)
        if phase_block:
            blockers.append(phase_block)
        options_block = _options_block_reason(payload, direction)
        if options_block:
            blockers.append(options_block)
        if sentiment_label in {"bullish", "bearish"} and not _sentiment_aligns(direction, sentiment_label):
            blockers.append(f"AI sentiment conflict: {sentiment_label}")

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
            f"Options momentum {_directional_momentum(payload, direction):.0%}",
            *(_option_calculations(selected_option) if selected_option else []),
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
            wait_reason = blockers[0] if blockers else "Execution-grade confirmation is not present"
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
        "btc_patterns": payload.get("btc_patterns"),
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
        if _option_for_direction(payload, direction):
            return None
        return f"Market phase is {phase}; wait for statistical breakout confirmation"
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
