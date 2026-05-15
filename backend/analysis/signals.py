from __future__ import annotations

import math
from scipy.stats import norm

from backend.analysis.ids import stable_id
from backend.models.types import (
    Candle,
    MarketMetrics,
    TradeSignal,
)


# ─── Statistical Helpers ─────────────────────────────────────────────


def _sma(data: list[float], period: int) -> list[float]:
    result: list[float] = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(0.0)
        else:
            result.append(sum(data[i - period + 1 : i + 1]) / period)
    return result


def _stdev(data: list[float], period: int, sma_vals: list[float] | None = None) -> list[float]:
    if sma_vals is None:
        sma_vals = _sma(data, period)
    result: list[float] = []
    for i in range(len(data)):
        if i < period - 1:
            result.append(0.0)
        else:
            variance = sum((data[j] - sma_vals[i]) ** 2 for j in range(i - period + 1, i + 1)) / period
            result.append(math.sqrt(variance))
    return result


def _zscore(value: float, mean: float, std: float) -> float:
    if std <= 0:
        return 0.0
    return (value - mean) / std


def _linear_regression_slope(y: list[float]) -> float:
    n = len(y)
    if n < 2:
        return 0.0
    x = list(range(n))
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi * xi for xi in x)
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def _pearson_r(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return 0.0
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(xi * yi for xi, yi in zip(x, y))
    sum_x2 = sum(xi * xi for xi in x)
    sum_y2 = sum(yi * yi for yi in y)
    denom = math.sqrt((n * sum_x2 - sum_x * sum_x) * (n * sum_y2 - sum_y * sum_y))
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def _atr(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    ranges: list[float] = []
    recent = candles[-(period + 1) :]
    for prev, cur in zip(recent, recent[1:]):
        ranges.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ─── Institutional Math: Hurst, Entropy, Bayesian Fusion ────────────


def _hurst_exponent(prices: list[float]) -> float:
    """Rescaled range (R/S) analysis for Hurst exponent.
    H < 0.4 → mean-reverting, H > 0.6 → trending, H ≈ 0.5 → random walk."""
    n = len(prices)
    if n < 50:
        return 0.5
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, n)]
    m = len(log_returns)
    min_lag = 10
    max_lag = m // 4
    lags = list(range(min_lag, max_lag + 1, max(1, (max_lag - min_lag) // 10)))
    rs_values: list[float] = []
    for lag in lags:
        segments = m // lag
        if segments < 1:
            continue
        rs_sum = 0.0
        for s in range(segments):
            segment = log_returns[s * lag : (s + 1) * lag]
            mean = sum(segment) / lag
            dev = [segment[i] - mean for i in range(lag)]
            y = [sum(dev[: i + 1]) for i in range(lag)]
            r = max(y) - min(y)
            std = math.sqrt(sum(d * d for d in dev) / lag)
            if std > 0:
                rs_sum += r / std
        rs_mean = rs_sum / segments
        rs_values.append(math.log(rs_mean) if rs_mean > 0 else 0.0)
    if len(rs_values) < 3:
        return 0.5
    log_lags = [math.log(lag) for lag in lags[: len(rs_values)]]
    n_lags = len(log_lags)
    sum_x = sum(log_lags)
    sum_y = sum(rs_values)
    sum_xy = sum(log_lags[i] * rs_values[i] for i in range(n_lags))
    sum_x2 = sum(x * x for x in log_lags)
    denom = n_lags * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.5
    h = (n_lags * sum_xy - sum_x * sum_y) / denom
    return _clamp(h, 0.01, 0.99)


def _shannon_entropy(prices: list[float], bins: int = 20) -> float:
    """Shannon entropy of log-return distribution. Lower = more structured/predictable."""
    if len(prices) < 10:
        return 1.0
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    if not log_returns:
        return 1.0
    r_min = min(log_returns)
    r_max = max(log_returns)
    if abs(r_max - r_min) < 1e-10:
        return 0.0
    bin_w = (r_max - r_min) / bins
    hist = [0.0] * bins
    for r in log_returns:
        idx = min(int((r - r_min) / bin_w), bins - 1)
        hist[idx] += 1.0
    total = len(log_returns)
    entropy = 0.0
    for count in hist:
        if count > 0:
            p = count / total
            entropy -= p * math.log(p)
    max_entropy = math.log(bins)
    return _clamp(entropy / max_entropy if max_entropy > 0 else 1.0, 0.0, 1.0)


def _bayesian_fuse(prior: float, likelihoods: list[float]) -> float:
    """Combine multiple independent signal confidences via Bayesian updating.
    Each likelihood is P(data|signal). Posterior = P(signal) * prod(P(data|signal)) normalized."""
    post = _clamp(prior, 0.01, 0.99)
    for l in likelihoods:
        l_clamped = _clamp(l, 0.01, 0.99)
        evidence = post * l_clamped + (1.0 - post) * (1.0 - l_clamped)
        if evidence > 0:
            post = (post * l_clamped) / evidence
    return _clamp(post, 0.01, 0.99)


def _expected_value_ratio(confidence: float, risk_reward: float) -> float:
    """EV = P(win)*R - P(loss). Returns ratio of EV to max possible gain."""
    win_prob = confidence
    ev = win_prob * risk_reward - (1.0 - win_prob)
    return _clamp(ev / max(risk_reward, 0.1), -1.0, 1.0)


def _regime_hurst_bias(h: float) -> str:
    """Map Hurst to regime bias for adaptive signal weighting."""
    if h < 0.4:
        return "mean_reverting"
    if h > 0.6:
        return "trending"
    return "random"


# ─── Advanced Institutional Math ───────────────────────────────────


def _garch11_forecast(returns: list[float], horizon: int = 5) -> tuple[float, float]:
    """GARCH(1,1) volatility forecasting.
    Returns (forecasted_volatility, persistence) where persistence indicates volatility clustering strength.
    σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}"""
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
    """Kalman filter for dynamic trend tracking.
    Returns dict with: level, trend, trend_strength, prediction_error, filter_gain."""
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
    trend_strength = _clamp(abs(trend) / max(avg_error, 0.001), 0.0, 1.0)
    return {"level": x, "trend": trend, "trend_strength": trend_strength, "prediction_error": avg_error, "filter_gain": K if 'K' in locals() else 0.0}


def _autocorrelation(series: list[float], lag: int = 1) -> float:
    """Compute autocorrelation at given lag for serial correlation detection."""
    n = len(series)
    if n < lag + 10:
        return 0.0
    mean = sum(series) / n
    var = sum((x - mean) ** 2 for x in series) / n
    if var == 0:
        return 0.0
    cov = sum((series[i] - mean) * (series[i + lag] - mean) for i in range(n - lag)) / (n - lag)
    return cov / var


def _acf_series(series: list[float], max_lag: int = 10) -> list[float]:
    """Compute autocorrelation function for multiple lags."""
    return [_autocorrelation(series, lag) for lag in range(1, max_lag + 1)]


def _ljung_box_test(acf: list[float], n: int) -> float:
    """Ljung-Box test statistic for serial correlation.
    Returns Q statistic. High values indicate significant autocorrelation."""
    if not acf or n < 10:
        return 0.0
    m = len(acf)
    q = n * (n + 2) * sum(r * r / (n - k) for k, r in enumerate(acf, 1))
    return q


def _monte_carlo_paths(
    initial_price: float,
    drift: float,
    volatility: float,
    steps: int = 30,
    simulations: int = 500,
) -> dict[str, float]:
    """Monte Carlo simulation for path-dependent risk analysis.
    Returns dict with: p5, p25, p50, p75, p95, expected_return, max_drawdown_prob, var95."""
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
    p25 = final_prices[int(0.25 * simulations)]
    p50 = final_prices[int(0.50 * simulations)]
    p75 = final_prices[int(0.75 * simulations)]
    p95 = final_prices[int(0.95 * simulations)]
    expected_return = (p50 - initial_price) / initial_price if initial_price > 0 else 0.0
    var95 = (initial_price - p5) / initial_price if initial_price > 0 else 0.0
    avg_max_dd = sum(max_drawdowns) / len(max_drawdowns)
    return {
        "p5": p5, "p25": p25, "p50": p50, "p75": p75, "p95": p95,
        "expected_return": expected_return,
        "max_drawdown_prob": avg_max_dd,
        "var95": var95,
    }


def _fourier_dominant_cycle(prices: list[float]) -> tuple[float, float]:
    """Fourier transform to detect dominant cycle period and strength.
    Returns (dominant_period, cycle_strength) where strength is [0,1]."""
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
    return float(dominant_period), _clamp(cycle_strength, 0.0, 1.0)


def _markov_regime_switching(returns: list[float]) -> dict[str, float]:
    """Simplified Markov regime switching model.
    Returns dict with: bull_prob, bear_prob, transition_prob, regime_certainty."""
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
        "bull_prob": _clamp(bull_post, 0.0, 1.0),
        "bear_prob": _clamp(bear_post, 0.0, 1.0),
        "transition_prob": _clamp(transition_prob, 0.0, 1.0),
        "regime_certainty": _clamp(regime_certainty, 0.0, 1.0),
    }


def _macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict[str, float]]:
    """MACD (Moving Average Convergence Divergence) calculation.
    Returns list of dicts with: macd, signal_line, histogram."""
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, signal)
    histogram = [m - s for m, s in zip(macd_line, signal_line)]
    return [{"macd": macd_line[i], "signal": signal_line[i], "histogram": histogram[i]} for i in range(len(closes))]


def _ema(data: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if not data:
        return []
    multiplier = 2.0 / (period + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        ema = (data[i] - result[-1]) * multiplier + result[-1]
        result.append(ema)
    return result


def _roc(closes: list[float], period: int = 10) -> list[float]:
    """Rate of Change momentum indicator."""
    return [(closes[i] - closes[i - period]) / closes[i - period] * 100 if i >= period and closes[i - period] > 0 else 0.0 for i in range(len(closes))]


def _tsi(closes: list[float], fast: int = 13, slow: int = 25) -> list[float]:
    """True Strength Index momentum oscillator."""
    if len(closes) < slow + fast:
        return [0.0] * len(closes)
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    abs_changes = [abs(c) for c in changes]
    pc = _ema(_ema(changes, slow), fast)
    apc = _ema(_ema(abs_changes, slow), fast)
    tsi = [100.0 * p / max(a, 1e-10) for p, a in zip(pc, apc)]
    return [0.0] * (slow + fast - 1) + tsi


def _volume_profile(candles: list[Candle], num_bins: int = 20) -> dict[str, float]:
    """Volume profile analysis: POC (Point of Control), VAH (Value Area High), VAL (Value Area Low).
    Returns dict with: poc, vah, val, volume_imbalance."""
    if not candles:
        return {"poc": 0.0, "vah": 0.0, "val": 0.0, "volume_imbalance": 0.0}
    prices = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    min_p = min(prices)
    max_p = max(prices)
    if max_p == min_p:
        return {"poc": min_p, "vah": min_p, "val": min_p, "volume_imbalance": 0.0}
    bin_width = (max_p - min_p) / num_bins
    bin_volumes = [0.0] * num_bins
    bin_centers = [min_p + (i + 0.5) * bin_width for i in range(num_bins)]
    for price, volume in zip(prices, volumes):
        idx = min(int((price - min_p) / bin_width), num_bins - 1)
        bin_volumes[idx] += volume
    total_volume = sum(bin_volumes)
    if total_volume == 0:
        return {"poc": min_p, "vah": max_p, "val": min_p, "volume_imbalance": 0.0}
    poc_idx = bin_volumes.index(max(bin_volumes))
    poc = bin_centers[poc_idx]
    sorted_bins = sorted(range(num_bins), key=lambda i: bin_volumes[i], reverse=True)
    cum_vol = 0.0
    value_area_bins = set()
    for idx in sorted_bins:
        value_area_bins.add(idx)
        cum_vol += bin_volumes[idx]
        if cum_vol >= total_volume * 0.7:
            break
    valid_va = [i for i in value_area_bins]
    vah = max(bin_centers[i] for i in valid_va) if valid_va else poc
    val = min(bin_centers[i] for i in valid_va) if valid_va else poc
    upper_vol = sum(bin_volumes[i] for i in range(poc_idx + 1, num_bins))
    lower_vol = sum(bin_volumes[i] for i in range(0, poc_idx))
    imbalance = (upper_vol - lower_vol) / max(total_volume, 1e-10)
    return {"poc": poc, "vah": vah, "val": val, "volume_imbalance": _clamp(imbalance, -1.0, 1.0)}


def _signal_decay(timestamp_ms: int, current_ts_ms: int, half_life_minutes: int = 15) -> float:
    """Exponential signal decay model. Confidence degrades over time.
    Returns decay factor [0, 1] where 1.0 = no decay, 0.0 = fully decayed."""
    elapsed_minutes = (current_ts_ms - timestamp_ms) / 60000.0
    half_life_ms = half_life_minutes * 60000.0
    decay = math.exp(-math.log(2) * elapsed_minutes / max(half_life_minutes, 1))
    return _clamp(decay, 0.3, 1.0)


def _fractal_dimension(prices: list[float]) -> float:
    """Fractal dimension via box-counting method.
    D ≈ 1.0 = smooth trend, D ≈ 2.0 = highly chaotic/ranging."""
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
    return _clamp(d, 1.0, 2.0)


def _skewness_kurtosis(returns: list[float]) -> tuple[float, float]:
    """Compute skewness and kurtosis of returns distribution.
    Skewness: negative = left tail risk, positive = right tail opportunity
    Kurtosis: >3 = fat tails (extreme events more likely)"""
    n = len(returns)
    if n < 10:
        return 0.0, 3.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(var) if var > 0 else 1e-10
    skew = sum((r - mean) ** 3 for r in returns) / (n * std ** 3)
    kurt = sum((r - mean) ** 4 for r in returns) / (n * std ** 4)
    return skew, kurt


# ─── Signal Detection ────────────────────────────────────────────────


def detect_trade_signals(
    candles: list[Candle],
    metrics: MarketMetrics | None = None,
    reward_multiple: float = 3.0,
) -> list[TradeSignal]:
    if len(candles) < 30:
        return []

    ordered = sorted(candles, key=lambda c: c.timestamp)
    closes = [c.close for c in ordered]
    highs = [c.high for c in ordered]
    lows = [c.low for c in ordered]
    volumes = [c.volume for c in ordered]

    # ── Core institutional metrics ──
    hurst = _hurst_exponent(closes)
    entropy = _shannon_entropy(closes)
    hurst_bias = _regime_hurst_bias(hurst)
    entropy_factor = _clamp(1.0 - entropy, 0.0, 1.0)

    # ── Advanced institutional metrics ──
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    garch_vol, garch_persistence = _garch11_forecast(returns[-60:] if len(returns) >= 60 else returns)
    kalman = _kalman_filter_trend(closes[-80:] if len(closes) >= 80 else closes)
    acf = _acf_series(returns[-50:] if len(returns) >= 50 else returns, max_lag=5)
    ljung_box = _ljung_box_test(acf, len(returns[-50:]))
    dominant_period, cycle_strength = _fourier_dominant_cycle(closes[-100:] if len(closes) >= 100 else closes)
    markov = _markov_regime_switching(returns[-60:] if len(returns) >= 60 else returns)
    vol_profile = _volume_profile(ordered[-50:] if len(ordered) >= 50 else ordered)
    skew, kurt = _skewness_kurtosis(returns[-60:] if len(returns) >= 60 else returns)
    fractal_dim = _fractal_dimension(closes[-80:] if len(closes) >= 80 else closes)

    # ── Momentum indicators ──
    macd_data = _macd(closes)
    roc_series = _roc(closes, 10)
    tsi_series = _tsi(closes)

    # ── Monte Carlo risk simulation ──
    latest_price = closes[-1]
    mc_drift = kalman["trend"]
    mc_vol = garch_vol if garch_vol > 0 else (returns[-1] if returns else 0.01)
    mc_results = _monte_carlo_paths(latest_price, mc_drift, mc_vol, steps=20, simulations=300)

    # ── Compute statistical series ──
    sma20 = _sma(closes, 20)
    std20 = _stdev(closes, 20, sma20)
    sma50 = _sma(closes, 50)
    vol_sma = _sma(volumes, 20)

    vwap_series = _compute_vwap(ordered)
    atr14 = _atr(ordered, 14)

    bollinger_upper = [sma20[i] + 2.0 * std20[i] if std20[i] > 0 else 0.0 for i in range(len(ordered))]
    bollinger_lower = [sma20[i] - 2.0 * std20[i] if std20[i] > 0 else 0.0 for i in range(len(ordered))]
    bb_width = [bollinger_upper[i] - bollinger_lower[i] for i in range(len(ordered))]
    bb_sma = _sma(bb_width, 20)

    rsi_series = _rsi(closes, 14)

    # ── Linear regression slope (activated dead code) ──
    trend_slope = _linear_regression_slope(closes[-30:] if len(closes) >= 30 else closes)
    # ── Pearson correlation between price and volume (activated dead code) ──
    price_vol_corr = _pearson_r(closes[-30:], volumes[-30:]) if len(closes) >= 30 else 0.0

    signals: list[TradeSignal] = []
    latest = ordered[-1]

    # Only scan the most recent lookback for signals
    lookback = min(80, len(ordered))
    scan_start = len(ordered) - lookback

    for i in range(scan_start, len(ordered)):
        c = ordered[i]
        cl = closes[i]
        hi = highs[i]
        lo = lows[i]
        sma20_i = sma20[i]
        std20_i = std20[i]
        vwap_i = vwap_series[i] if vwap_series else 0.0
        rsi_i = rsi_series[i]
        macd_i = macd_data[i] if i < len(macd_data) else {"macd": 0.0, "signal": 0.0, "histogram": 0.0}
        roc_i = roc_series[i] if i < len(roc_series) else 0.0
        tsi_i = tsi_series[i] if i < len(tsi_series) else 0.0

        prefix = ordered[: i + 1]
        prefix_closes = closes[: i + 1]

        # Statistical checks at this candle
        z = _zscore(cl, sma20_i, std20_i)
        bb_b = (cl - bollinger_lower[i]) / (bollinger_upper[i] - bollinger_lower[i]) if (bollinger_upper[i] - bollinger_lower[i]) > 0 else 0.5
        vwap_dev = ((cl - vwap_i) / vwap_i * 100) if vwap_i > 0 else 0.0
        vol_z = _zscore(volumes[i], vol_sma[i], math.sqrt(sum((volumes[j] - vol_sma[i]) ** 2 for j in range(max(0, i - 19), i + 1)) / 20)) if vol_sma[i] > 0 and i >= 19 else 0.0
        bb_squeeze = bb_width[i] < bb_sma[i] * 0.8 if bb_sma[i] > 0 else False

        # ── Adaptive regime alignment for signal boosting ──
        is_mean_reverting = hurst_bias == "mean_reverting"
        is_trending = hurst_bias == "trending"

        # ── Signal type 1: VWAP Mean Reversion ──
        if abs(vwap_dev) >= 0.5 and not _has_recent_signal(signals, c.timestamp, 5):
            side = "buy" if cl < vwap_i else "sell"
            entry = vwap_i
            entry_reason = f"VWAP reversion at {abs(vwap_dev):.2f}% deviation"
            stop = entry - atr14 * 1.5 if side == "buy" else entry + atr14 * 1.5
            risk = abs(entry - stop)
            target = entry + risk * reward_multiple if side == "buy" else entry - risk * reward_multiple
            confidence = _vwap_reversion_confidence(vwap_dev, vol_z, rsi_i, bb_b, hurst, entropy_factor, garch_vol, kalman["trend_strength"])
            _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

        # ── Signal type 2: Bollinger Band touch + continuation ──
        if (cl <= bollinger_lower[i] or cl >= bollinger_upper[i]) and bb_width[i] > (bb_sma[i] * 0.5 if bb_sma[i] > 0 else 0):
            side = "buy" if cl <= bollinger_lower[i] else "sell"
            entry = cl
            entry_reason = f"BB touch {'lower' if side == 'buy' else 'upper'} (z={z:.2f})"
            stop = entry - atr14 * 1.2 if side == "buy" else entry + atr14 * 1.2
            risk = abs(entry - stop)
            target = entry + risk * reward_multiple if side == "buy" else entry - risk * reward_multiple
            confidence = _bb_reversal_confidence(z, bb_b, rsi_i, vol_z, hurst, entropy_factor, skew, kurt)
            _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

        # ── Signal type 3: Volatility Squeeze Breakout ──
        if bb_squeeze and i > 0:
            prev_range = hi - lo
            cur_range = ordered[i - 1].high - ordered[i - 1].low if i > 0 else 0
            expansion = prev_range > cur_range * 1.8 and prev_range > atr14 * 0.5
            if expansion:
                body_dir = "bullish" if cl > ordered[i - 1].close else "bearish"
                side = "buy" if body_dir == "bullish" else "sell"
                entry = cl
                entry_reason = f"BB squeeze breakout {body_dir}"
                stop = entry - atr14 * 1.5 if side == "buy" else entry + atr14 * 1.5
                risk = abs(entry - stop)
                target = entry + risk * reward_multiple if side == "buy" else entry - risk * reward_multiple
                confidence = _squeeze_breakout_confidence(prev_range, atr14, vol_z, hurst, entropy_factor, garch_persistence, cycle_strength)
                _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

        # ── Signal type 4: Statistical Pullback ──
        if sma20_i > 0 and std20_i > 0:
            pullback_buy = cl < sma20_i - 0.5 * std20_i and rsi_i < 45 and sma20_i > sma50[i] if i >= 49 else False
            pullback_sell = cl > sma20_i + 0.5 * std20_i and rsi_i > 55 and sma20_i < sma50[i] if i >= 49 else False
            if pullback_buy:
                side = "buy"
                entry = cl
                entry_reason = f"Statistical pullback to SMA20 (z={z:.2f}, RSI={rsi_i:.0f})"
                stop = entry - atr14 * 1.5
                risk = abs(entry - stop)
                target = entry + risk * reward_multiple
                confidence = _pullback_confidence(z, rsi_i, vol_z, hurst, entropy_factor, trend_slope, kalman["trend_strength"])
                _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)
            elif pullback_sell:
                side = "sell"
                entry = cl
                entry_reason = f"Statistical pullback to SMA20 (z={z:.2f}, RSI={rsi_i:.0f})"
                stop = entry + atr14 * 1.5
                risk = abs(entry - stop)
                target = entry - risk * reward_multiple
                confidence = _pullback_confidence(z, rsi_i, vol_z, hurst, entropy_factor, trend_slope, kalman["trend_strength"])
                _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

        # ── Signal type 5: RSI Divergence ──
        if i >= 5:
            prev_rsi = rsi_series[i - 1]
            prev_close = closes[i - 1]
            divergence_bullish = cl < prev_close and rsi_i > prev_rsi and rsi_i < 40
            divergence_bearish = cl > prev_close and rsi_i < prev_rsi and rsi_i > 60
            if divergence_bullish:
                _add_signal(signals, ordered, "buy", c.timestamp, cl, cl - atr14 * 1.5, cl + atr14 * 1.5 * reward_multiple, 0.62, f"RSI bullish divergence (RSI {rsi_i:.0f} > {prev_rsi:.0f} while price fell)", metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)
            elif divergence_bearish:
                _add_signal(signals, ordered, "sell", c.timestamp, cl, cl + atr14 * 1.5, cl - atr14 * 1.5 * reward_multiple, 0.62, f"RSI bearish divergence (RSI {rsi_i:.0f} < {prev_rsi:.0f} while price rose)", metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

        # ── Signal type 6: MACD Momentum Crossover ──
        if i >= 30 and not _has_recent_signal(signals, c.timestamp, 5):
            macd_prev = macd_data[i - 1] if i - 1 < len(macd_data) else None
            if macd_prev and macd_i:
                macd_cross_bullish = macd_prev["histogram"] < 0 and macd_i["histogram"] > 0
                macd_cross_bearish = macd_prev["histogram"] > 0 and macd_i["histogram"] < 0
                if macd_cross_bullish:
                    side = "buy"
                    entry = cl
                    entry_reason = f"MACD bullish crossover (hist {macd_i['histogram']:.3f})"
                    stop = entry - atr14 * 1.5
                    risk = abs(entry - stop)
                    target = entry + risk * reward_multiple
                    confidence = _momentum_confidence(macd_i["histogram"], roc_i, tsi_i, vol_z, hurst, entropy_factor, fractal_dim)
                    _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)
                elif macd_cross_bearish:
                    side = "sell"
                    entry = cl
                    entry_reason = f"MACD bearish crossover (hist {macd_i['histogram']:.3f})"
                    stop = entry + atr14 * 1.5
                    risk = abs(entry - stop)
                    target = entry - risk * reward_multiple
                    confidence = _momentum_confidence(-macd_i["histogram"], -roc_i, -tsi_i, vol_z, hurst, entropy_factor, fractal_dim)
                    _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

        # ── Signal type 7: Volume Profile Support/Resistance ──
        if i >= 50 and not _has_recent_signal(signals, c.timestamp, 5):
            poc = vol_profile["poc"]
            vah = vol_profile["vah"]
            val = vol_profile["val"]
            if poc > 0 and abs(cl - poc) / poc < 0.005:
                side = "buy" if cl >= poc else "sell"
                entry = cl
                entry_reason = f"Volume POC test (POC={poc:.2f}, imbalance={vol_profile['volume_imbalance']:.2f})"
                stop = entry - atr14 * 1.5 if side == "buy" else entry + atr14 * 1.5
                risk = abs(entry - stop)
                target = entry + risk * reward_multiple if side == "buy" else entry - risk * reward_multiple
                confidence = _volume_profile_confidence(vol_profile["volume_imbalance"], z, vol_z, hurst, entropy_factor, markov["regime_certainty"])
                _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

        # ── Signal type 8: Cycle-Based Reversal ──
        if cycle_strength > 0.3 and dominant_period > 10 and i >= int(dominant_period) and not _has_recent_signal(signals, c.timestamp, 5):
            cycle_phase = (i % int(dominant_period)) / dominant_period
            if cycle_phase < 0.15 or cycle_phase > 0.85:
                side = "buy" if cycle_phase < 0.15 else "sell"
                entry = cl
                entry_reason = f"Cycle reversal (period={dominant_period:.0f}, strength={cycle_strength:.2f}, phase={cycle_phase:.2f})"
                stop = entry - atr14 * 1.5 if side == "buy" else entry + atr14 * 1.5
                risk = abs(entry - stop)
                target = entry + risk * reward_multiple if side == "buy" else entry - risk * reward_multiple
                confidence = _cycle_reversal_confidence(cycle_strength, dominant_period, cycle_phase, vol_z, hurst, entropy_factor)
                _add_signal(signals, ordered, side, c.timestamp, entry, stop, target, confidence, entry_reason, metrics, atr14, hurst, entropy_factor, garch_vol, markov, mc_results)

    # ── Bayesian fusion for same-side signal clusters ──
    fused: dict[str, TradeSignal] = {}
    side_groups: dict[str, list[TradeSignal]] = {"buy": [], "sell": []}
    for sig in signals:
        key = f"{sig.side}-{sig.timestamp}"
        if key not in fused or sig.confidence > fused[key].confidence:
            fused[key] = sig
        side_groups[sig.side].append(sig)

    # Apply Bayesian fusion: when multiple signals exist on same side,
    # use the posterior as a confidence boost for the best signal
    result: list[TradeSignal] = []
    for side in ("buy", "sell"):
        side_sigs = [s for s in fused.values() if s.side == side]
        if not side_sigs:
            continue
        side_sigs.sort(key=lambda s: s.confidence, reverse=True)
        best_sig = side_sigs[0]

        # Fuse confidences of all signals on this side (up to 5 most recent)
        cluster = side_groups[side][-5:]
        if len(cluster) > 1:
            likelihoods = [s.confidence for s in cluster if s.id != best_sig.id]
            fused_conf = _bayesian_fuse(best_sig.confidence, likelihoods)
            best_sig.confidence = round(max(best_sig.confidence, fused_conf), 2)
            best_sig.reason += f" | Bayesian fused ({len(cluster)} signals)"

        # Apply entropy filter: low entropy (structured market) boosts confidence
        if entropy_factor > 0.4:
            boost = _clamp(entropy_factor * 0.08, 0.0, 0.08)
            best_sig.confidence = round(_clamp(best_sig.confidence + boost, 0.2, 0.92), 2)

        # Apply Hurst alignment boost
        if is_mean_reverting and side == "buy" and best_sig.side == "buy":
            if "BB touch" in best_sig.reason or "VWAP reversion" in best_sig.reason:
                best_sig.confidence = round(_clamp(best_sig.confidence + 0.04, 0.2, 0.92), 2)
        if is_trending:
            if "squeeze breakout" in best_sig.reason or "pullback" in best_sig.reason:
                best_sig.confidence = round(_clamp(best_sig.confidence + 0.04, 0.2, 0.92), 2)

        # Apply GARCH volatility clustering boost
        if garch_persistence > 0.9:
            best_sig.confidence = round(_clamp(best_sig.confidence + 0.03, 0.2, 0.92), 2)
            best_sig.reason += f" | GARCH persistence {garch_persistence:.2f}"

        # Apply Markov regime certainty boost
        if markov["regime_certainty"] > 0.6:
            regime_side = "buy" if markov["bull_prob"] > markov["bear_prob"] else "sell"
            if regime_side == side:
                best_sig.confidence = round(_clamp(best_sig.confidence + 0.03, 0.2, 0.92), 2)
                best_sig.reason += f" | Markov {regime_side} {markov['regime_certainty']:.2f}"

        # Apply Monte Carlo VaR filter
        if mc_results["var95"] > 0.05:
            best_sig.confidence = round(_clamp(best_sig.confidence - 0.05, 0.2, 0.92), 2)
            best_sig.reason += f" | MC VaR95 {mc_results['var95']:.2%}"

        # Apply signal decay based on timestamp
        current_ts = ordered[-1].timestamp
        decay = _signal_decay(best_sig.timestamp, current_ts, half_life_minutes=15)
        if decay < 0.8:
            best_sig.confidence = round(_clamp(best_sig.confidence * decay, 0.2, 0.92), 2)

        result.append(best_sig)

    return result


# ─── Statistical Component Functions ────────────────────────────────


def _compute_vwap(candles: list[Candle]) -> list[float]:
    vwap_vals: list[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    for c in candles:
        typ = (c.high + c.low + c.close) / 3
        cum_pv += typ * c.volume
        cum_v += c.volume
        vwap_vals.append(cum_pv / cum_v if cum_v > 0 else 0.0)
    return vwap_vals


def _rsi(closes: list[float], period: int = 14) -> list[float]:
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result: list[float] = [50.0] * (period)
    for i in range(period, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        result.append(100.0 - 100.0 / (1.0 + rs))
    return result


def _has_recent_signal(signals: list[TradeSignal], timestamp: int, window_minutes: int = 5) -> bool:
    window_ms = window_minutes * 60 * 1000
    for s in signals:
        if abs(s.timestamp - timestamp) < window_ms:
            return True
    return False


def _add_signal(
    signals: list[TradeSignal],
    candles: list[Candle],
    side: str,
    timestamp: int,
    entry: float,
    stop: float,
    target: float,
    base_confidence: float,
    entry_reason: str,
    metrics: MarketMetrics | None,
    atr14: float,
    hurst: float = 0.5,
    entropy_factor: float = 0.5,
    garch_vol: float = 0.0,
    markov: dict[str, float] | None = None,
    mc_results: dict[str, float] | None = None,
) -> None:
    risk = abs(entry - stop)
    if risk <= 0 or risk < atr14 * 0.3:
        return
    rr = abs(target - entry) / risk
    if rr < 1.2:
        return

    confidence = _clamp(base_confidence, 0.2, 0.92)
    # Use institutional risk profile (activated dead code)
    profile = _institutional_risk_profile(entry, risk, rr, confidence, metrics)
    if profile["risk_of_ruin"] > 0.6 or profile["cvar95_loss"] > (risk * 3.0):
        return
    confidence = round(_clamp(confidence - profile["penalty"], 0.2, 0.92), 2)

    trailing = _compute_trailing_stop(side, entry, timestamp, candles, atr14)

    # Build enhanced reason string with institutional metrics
    reason_parts = [entry_reason, f"{rr:.1f}R target", f"H={hurst:.2f}", f"E={entropy_factor:.2f}"]
    if garch_vol > 0:
        reason_parts.append(f"GARCH vol {garch_vol:.4f}")
    if markov and markov.get("regime_certainty", 0) > 0.5:
        regime = "bull" if markov.get("bull_prob", 0.5) > 0.5 else "bear"
        reason_parts.append(f"Markov {regime} {markov['regime_certainty']:.2f}")
    if mc_results and mc_results.get("var95", 0) > 0:
        reason_parts.append(f"MC VaR {mc_results['var95']:.2%}")
    reason_parts.append(f"kelly {profile['kelly_fraction']:.3f}")

    signal = TradeSignal(
        id=stable_id("stat", side, timestamp, int(entry * 10), int(stop * 10)),
        timestamp=timestamp,
        side=side,
        entry=round(entry, 2),
        stop_loss=round(stop, 2),
        exit_price=round(target, 2),
        risk_reward=round(rr, 2),
        confidence=confidence,
        reason=", ".join(reason_parts),
        institutional_score=round(confidence * 1.1, 2),
        liquidity_score=round(abs(entry - stop) / atr14 * 0.05 if atr14 > 0 else 0.0, 2),
        bias_score=round(metrics.bias_score if metrics else 0.0, 3),
        expected_move=round(metrics.expected_move if metrics else atr14, 2),
        win_probability=round(profile["win_probability"], 3),
        kelly_fraction=round(profile["kelly_fraction"], 4),
        suggested_risk_fraction=round(profile["suggested_risk_fraction"], 4),
        cvar95_loss=round(profile["cvar95_loss"], 2),
        risk_of_ruin=round(profile["risk_of_ruin"], 3),
    )
    signal.trailing_stop = round(trailing, 2)
    _update_signal_status(signal, candles)
    signals.append(signal)


# ─── Confidence Models ──────────────────────────────────────────────


def _vwap_reversion_confidence(vwap_dev_pct: float, vol_z: float, rsi: float, bb_b: float, hurst: float = 0.5, entropy_factor: float = 0.5, garch_vol: float = 0.0, kalman_trend_strength: float = 0.0) -> float:
    dev_factor = min(abs(vwap_dev_pct) * 0.5, 0.25)
    vol_conf = min(abs(vol_z) * 0.05, 0.10)
    rsi_conf = 0.08 if rsi < 35 or rsi > 65 else 0.04 if rsi < 40 or rsi > 60 else 0.0
    bb_conf = 0.06 if bb_b < 0.1 or bb_b > 0.9 else 0.0
    hurst_boost = 0.04 if hurst < 0.4 else 0.0
    struct_boost = entropy_factor * 0.04
    garch_boost = 0.03 if garch_vol > 0 and garch_vol < 0.02 else 0.0
    kalman_boost = kalman_trend_strength * 0.02 if kalman_trend_strength > 0.5 else 0.0
    return _clamp(0.18 + dev_factor + vol_conf + rsi_conf + bb_conf + hurst_boost + struct_boost + garch_boost + kalman_boost, 0.2, 0.92)


def _bb_reversal_confidence(z: float, bb_b: float, rsi: float, vol_z: float, hurst: float = 0.5, entropy_factor: float = 0.5, skew: float = 0.0, kurt: float = 3.0) -> float:
    z_conf = min(abs(z) * 0.08, 0.20)
    rsi_conf = 0.10 if rsi < 30 or rsi > 70 else 0.05 if rsi < 40 or rsi > 60 else 0.0
    vol_conf = min(abs(vol_z) * 0.04, 0.08)
    hurst_boost = 0.04 if hurst < 0.4 else 0.0
    struct_boost = entropy_factor * 0.04
    skew_adj = 0.02 if abs(skew) > 1.0 else 0.0
    kurt_adj = 0.02 if kurt > 4.0 else 0.0
    return _clamp(0.20 + z_conf + rsi_conf + vol_conf + hurst_boost + struct_boost + skew_adj + kurt_adj, 0.2, 0.92)


def _squeeze_breakout_confidence(candle_range: float, atr14: float, vol_z: float, hurst: float = 0.5, entropy_factor: float = 0.5, garch_persistence: float = 0.0, cycle_strength: float = 0.0) -> float:
    expansion = min(candle_range / atr14 * 0.15, 0.20) if atr14 > 0 else 0.0
    vol_conf = min(abs(vol_z) * 0.06, 0.10)
    hurst_boost = 0.05 if hurst > 0.6 else 0.0
    struct_boost = entropy_factor * 0.04
    garch_boost = 0.03 if garch_persistence > 0.9 else 0.0
    cycle_boost = cycle_strength * 0.03 if cycle_strength > 0.3 else 0.0
    return _clamp(0.22 + expansion + vol_conf + hurst_boost + struct_boost + garch_boost + cycle_boost, 0.2, 0.92)


def _pullback_confidence(z: float, rsi: float, vol_z: float, hurst: float = 0.5, entropy_factor: float = 0.5, trend_slope: float = 0.0, kalman_trend_strength: float = 0.0) -> float:
    z_conf = min(abs(z) * 0.10, 0.15)
    rsi_conf = 0.08 if rsi < 35 or rsi > 65 else 0.04
    vol_conf = min(abs(vol_z) * 0.03, 0.06)
    hurst_boost = 0.04 if hurst > 0.55 else 0.0
    struct_boost = entropy_factor * 0.03
    trend_boost = min(abs(trend_slope) * 0.05, 0.04) if trend_slope != 0 else 0.0
    kalman_boost = kalman_trend_strength * 0.03 if kalman_trend_strength > 0.6 else 0.0
    return _clamp(0.16 + z_conf + rsi_conf + vol_conf + hurst_boost + struct_boost + trend_boost + kalman_boost, 0.2, 0.92)


def _momentum_confidence(macd_hist: float, roc: float, tsi: float, vol_z: float, hurst: float = 0.5, entropy_factor: float = 0.5, fractal_dim: float = 1.5) -> float:
    macd_conf = min(abs(macd_hist) * 2.0, 0.15)
    roc_conf = min(abs(roc) * 0.02, 0.10)
    tsi_conf = min(abs(tsi) * 0.005, 0.08)
    vol_conf = min(abs(vol_z) * 0.04, 0.06)
    hurst_boost = 0.05 if hurst > 0.6 else 0.0
    struct_boost = entropy_factor * 0.04
    fractal_boost = 0.03 if fractal_dim < 1.3 else 0.0
    return _clamp(0.20 + macd_conf + roc_conf + tsi_conf + vol_conf + hurst_boost + struct_boost + fractal_boost, 0.2, 0.92)


def _volume_profile_confidence(vol_imbalance: float, z: float, vol_z: float, hurst: float = 0.5, entropy_factor: float = 0.5, markov_certainty: float = 0.0) -> float:
    imbalance_conf = min(abs(vol_imbalance) * 0.15, 0.12)
    z_conf = min(abs(z) * 0.05, 0.10)
    vol_conf = min(abs(vol_z) * 0.03, 0.06)
    hurst_boost = 0.03 if hurst < 0.45 else 0.0
    struct_boost = entropy_factor * 0.03
    markov_boost = markov_certainty * 0.04 if markov_certainty > 0.6 else 0.0
    return _clamp(0.18 + imbalance_conf + z_conf + vol_conf + hurst_boost + struct_boost + markov_boost, 0.2, 0.92)


def _cycle_reversal_confidence(cycle_strength: float, dominant_period: float, phase: float, vol_z: float, hurst: float = 0.5, entropy_factor: float = 0.5) -> float:
    strength_conf = cycle_strength * 0.15
    phase_conf = 0.08 if phase < 0.1 or phase > 0.9 else 0.04
    vol_conf = min(abs(vol_z) * 0.03, 0.05)
    hurst_boost = 0.04 if hurst < 0.45 else 0.0
    struct_boost = entropy_factor * 0.04
    period_boost = 0.03 if 15 <= dominant_period <= 50 else 0.0
    return _clamp(0.16 + strength_conf + phase_conf + vol_conf + hurst_boost + struct_boost + period_boost, 0.2, 0.92)


# ─── Risk Profile ───────────────────────────────────────────────────


def _risk_profile(
    entry: float, risk: float, risk_reward: float, confidence: float, metrics: MarketMetrics | None
) -> dict[str, float]:
    if metrics is None:
        return {"win_probability": 0.5, "kelly_fraction": 0.0, "suggested_risk_fraction": 0.01, "cvar95_loss": risk * 2, "penalty": 0.0, "risk_of_ruin": 0.0}
    vol = metrics.realized_volatility
    atr_prop = risk / metrics.atr14 if metrics.atr14 > 0 else 1.0
    vol_adj = max(0.5, 1.0 - vol / 200.0)
    win_prob = _clamp(confidence * (1.0 - max(0, (atr_prop - 1.0) * 0.15)), 0.15, 0.92) * vol_adj
    payoff = risk_reward
    edge = win_prob * payoff - (1.0 - win_prob)
    kelly = _clamp(edge / payoff if payoff > 0 else 0.0, 0.0, 0.35)
    ruin = _clamp((1.0 - edge) ** 20 if edge > 0 else 1.0, 0.0, 1.0)
    cvar = risk * (1.0 + 1.645 * (vol / 100.0) / math.sqrt(3))
    cvar = max(cvar, metrics.atr14 * 2.5 if metrics.atr14 > 0 else risk * 2)
    frac = max(0.005, min(kelly * 0.5, 0.05))
    penalty = min(max(0.0, (1.0 - win_prob) * 0.15), 0.20)
    return {"win_probability": round(win_prob, 4), "kelly_fraction": round(kelly, 4), "suggested_risk_fraction": round(frac, 4), "cvar95_loss": round(cvar, 2), "penalty": round(penalty, 4), "risk_of_ruin": round(ruin, 4)}


def _compute_trailing_stop(side: str, entry: float, timestamp: int, candles: list[Candle], atr: float) -> float:
    recent = [c for c in candles if c.timestamp <= timestamp][-5:]
    if not recent:
        return entry - atr * 1.5 if side == "buy" else entry + atr * 1.5
    if side == "buy":
        best = max(c.close for c in recent)
        return max(entry + (best - entry) * 0.5, entry - atr * 1.5)
    else:
        best = min(c.close for c in recent)
        return min(entry - (entry - best) * 0.5, entry + atr * 1.5)


def _update_signal_status(signal: TradeSignal, candles: list[Candle]) -> None:
    for c in candles:
        if c.timestamp < signal.timestamp:
            continue
        if signal.side == "buy":
            if c.low <= signal.stop_loss and c.high >= signal.exit_price and c.close >= signal.exit_price:
                signal.status = "target_hit"
                signal.exit_timestamp = c.timestamp
                return
            if c.low <= signal.stop_loss:
                signal.status = "stopped"
                signal.exit_timestamp = c.timestamp
                return
            if c.high >= signal.exit_price:
                signal.status = "target_hit"
                signal.exit_timestamp = c.timestamp
                return
        else:
            if c.high >= signal.stop_loss and c.low <= signal.exit_price and c.close <= signal.exit_price:
                signal.status = "target_hit"
                signal.exit_timestamp = c.timestamp
                return
            if c.high >= signal.stop_loss:
                signal.status = "stopped"
                signal.exit_timestamp = c.timestamp
                return
            if c.low <= signal.exit_price:
                signal.status = "target_hit"
                signal.exit_timestamp = c.timestamp
                return


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
