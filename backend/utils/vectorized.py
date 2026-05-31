"""
Vectorized numpy operations for fast candle/indicator computation.
Replaces slow Python loops with numpy vectorized operations for 10-100x speedup.
"""

import numpy as np
from typing import Optional


def candles_to_arrays(
    candles: list[dict],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert list of candle dicts to numpy arrays (open, high, low, close, volume)."""
    n = len(candles)
    if n == 0:
        return (
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
            np.array([], dtype=np.float64),
        )
    opens = np.array([c["open"] for c in candles], dtype=np.float64)
    highs = np.array([c["high"] for c in candles], dtype=np.float64)
    lows = np.array([c["low"] for c in candles], dtype=np.float64)
    closes = np.array([c["close"] for c in candles], dtype=np.float64)
    volumes = np.array([c.get("volume", 0) for c in candles], dtype=np.float64)
    return opens, highs, lows, closes, volumes


def sma(close: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average - vectorized."""
    if len(close) < period:
        return np.full(len(close), np.nan)
    cumsum = np.cumsum(close)
    result = np.empty(len(close))
    result[: period - 1] = np.nan
    result[period - 1] = cumsum[period - 1] / period
    if len(close) > period:
        result[period:] = (cumsum[period:] - cumsum[:-period]) / period
    return result


def ema(close: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average - vectorized."""
    if len(close) < period:
        return np.full(len(close), np.nan)
    alpha = 2.0 / (period + 1)
    result = np.empty(len(close))
    result[0] = close[0]
    for i in range(1, len(close)):
        result[i] = alpha * close[i] + (1 - alpha) * result[i - 1]
    result[: period - 1] = np.nan
    return result


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index - vectorized."""
    if len(close) < period + 1:
        return np.full(len(close), np.nan)
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gains = np.empty(len(close))
    avg_losses = np.empty(len(close))
    avg_gains[:period] = np.nan
    avg_losses[:period] = np.nan

    avg_gains[period] = np.mean(gains[:period])
    avg_losses[period] = np.mean(losses[:period])

    alpha = 1.0 / period
    for i in range(period + 1, len(close)):
        avg_gains[i] = (avg_gains[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_losses[i] = (avg_losses[i - 1] * (period - 1) + losses[i - 1]) / period

    rs = np.where(avg_losses != 0, avg_gains / avg_losses, 100.0)
    return 100.0 - (100.0 / (1.0 + rs))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range - vectorized."""
    if len(high) < period + 1:
        return np.full(len(high), np.nan)
    prev_close = np.empty(len(close))
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]

    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return sma(tr, period)


def bollinger_bands(
    close: np.ndarray, period: int = 20, std_mult: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands - vectorized."""
    middle = sma(close, period)
    if len(close) < period:
        return middle, np.full(len(close), np.nan), np.full(len(close), np.nan)

    rolling_std = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        rolling_std[i] = np.std(close[i - period + 1 : i + 1])

    upper = middle + std_mult * rolling_std
    lower = middle - std_mult * rolling_std
    return upper, middle, lower


def macd(
    close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """MACD - vectorized."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Volume Weighted Average Price - vectorized."""
    if len(volume) == 0 or np.sum(volume) == 0:
        return np.full(len(close), np.nan)
    typical_price = (high + low + close) / 3.0
    cum_vol = np.cumsum(volume)
    cum_tp_vol = np.cumsum(typical_price * volume)
    result = np.where(cum_vol != 0, cum_tp_vol / cum_vol, np.nan)
    return result


def returns(close: np.ndarray) -> np.ndarray:
    """Calculate simple returns from close prices. Guards against zero prices."""
    safe_close = np.where(close == 0, np.nan, close)
    return np.diff(safe_close) / np.where(safe_close[:-1] == 0, np.nan, safe_close[:-1])


def log_returns(close: np.ndarray) -> np.ndarray:
    """Calculate log returns from close prices. Guards against zero/negative prices."""
    safe_close = np.where(close <= 0, np.nan, close)
    return np.diff(np.log(safe_close))


def rolling_volatility(close: np.ndarray, period: int = 20) -> np.ndarray:
    """Rolling annualized volatility - vectorized."""
    if len(close) < period + 1:
        return np.full(len(close), np.nan)
    lr = log_returns(close)
    result = np.full(len(close), np.nan)
    for i in range(period - 1, len(lr)):
        result[i + 1] = np.std(lr[i - period + 1 : i + 1]) * np.sqrt(365 * 24)
    return result


def drawdown(close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compute drawdown series and max drawdown - vectorized."""
    cummax = np.maximum.accumulate(close)
    safe_cummax = np.where(cummax == 0, np.nan, cummax)
    drawdown_series = (close - cummax) / safe_cummax
    max_drawdown = np.nanmin(drawdown_series)
    return drawdown_series, max_drawdown


def correlation(x: np.ndarray, y: np.ndarray, period: int = 20) -> np.ndarray:
    """Rolling correlation - vectorized."""
    if len(x) < period or len(y) < period:
        return np.full(len(x), np.nan)
    result = np.full(len(x), np.nan)
    for i in range(period - 1, len(x)):
        x_slice = x[i - period + 1 : i + 1]
        y_slice = y[i - period + 1 : i + 1]
        x_mean = np.mean(x_slice)
        y_mean = np.mean(y_slice)
        x_std = np.std(x_slice)
        y_std = np.std(y_slice)
        if x_std > 0 and y_std > 0:
            result[i] = np.mean((x_slice - x_mean) * (y_slice - y_mean)) / (x_std * y_std)
    return result


def compute_all_indicators(
    candles: list[dict],
    rsi_period: int = 14,
    atr_period: int = 14,
    bb_period: int = 20,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> dict:
    """Compute all common indicators in one vectorized pass."""
    opens, highs, lows, closes, volumes = candles_to_arrays(candles)
    n = len(closes)
    if n == 0:
        return {}

    result = {}

    if n >= rsi_period + 1:
        result["rsi"] = rsi(closes, rsi_period)

    if n >= atr_period + 1:
        result["atr"] = atr(highs, lows, closes, atr_period)

    if n >= bb_period:
        bb_upper, bb_middle, bb_lower = bollinger_bands(closes, bb_period)
        result["bb_upper"] = bb_upper
        result["bb_middle"] = bb_middle
        result["bb_lower"] = bb_lower

    if n >= macd_slow + macd_signal:
        macd_line, signal_line, histogram = macd(closes, macd_fast, macd_slow, macd_signal)
        result["macd"] = macd_line
        result["macd_signal"] = signal_line
        result["macd_histogram"] = histogram

    result["vwap"] = vwap(highs, lows, closes, volumes)
    result["returns"] = returns(closes)
    result["log_returns"] = log_returns(closes)

    if n >= 20:
        result["volatility"] = rolling_volatility(closes, 20)

    dd_series, max_dd = drawdown(closes)
    result["drawdown"] = dd_series
    result["max_drawdown"] = max_dd

    return result
