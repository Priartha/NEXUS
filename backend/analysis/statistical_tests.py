"""
Statistical Testing Module for NEXUS.

Provides statistical significance testing for backtest results:
- Student's t-test for mean returns
- Monte Carlo permutation tests
- Deflated Sharpe Ratio (DSR)
- Probability of Backtest Overfitting (PBO)
- Confidence intervals
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any


@dataclass
class StatisticalResult:
    sharpe_ratio: float
    deflated_sharpe: float
    p_value: float
    is_significant: bool
    confidence_interval_95: tuple[float, float]
    monte_carlo_p_value: float
    probability_of_overfitting: float
    min_track_record_length: int
    trials_tested: int = 0


def compute_t_test(returns: list[float]) -> dict[str, float]:
    """One-sample t-test: H0 = mean return is zero."""
    n = len(returns)
    if n < 10:
        return {"t_stat": 0.0, "p_value": 1.0, "mean": 0.0, "std": 0.0}

    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0:
        return {"t_stat": 0.0, "p_value": 1.0, "mean": mean, "std": 0.0}

    se = std / math.sqrt(n)
    t_stat = mean / se
    p_value = _t_to_pvalue(t_stat, n - 1)
    return {"t_stat": round(t_stat, 4), "p_value": round(p_value, 4), "mean": round(mean, 6), "std": round(std, 6)}


def compute_sharpe_ratio(returns: list[float], risk_free_rate: float = 0.0, periods_per_year: int = 252 * 288) -> float:
    """Annualized Sharpe ratio."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    excess = mean - risk_free_rate / periods_per_year
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return round(excess / std * math.sqrt(periods_per_year), 4)


def monte_carlo_permutation_test(
    returns: list[float],
    strategy_returns: list[float],
    n_simulations: int = 10000,
) -> float:
    """
    Monte Carlo permutation test: shuffle strategy returns to test
    if observed performance could occur by random chance.
    Returns p-value (fraction of simulations where shuffled >= observed).
    """
    if len(strategy_returns) < 10:
        return 1.0

    observed_sharpe = compute_sharpe_ratio(strategy_returns)
    combined = returns + strategy_returns
    n_strat = len(strategy_returns)
    count_better = 0

    for _ in range(n_simulations):
        random.shuffle(combined)
        shuffled = combined[:n_strat]
        shuffled_sharpe = compute_sharpe_ratio(shuffled)
        if shuffled_sharpe >= observed_sharpe:
            count_better += 1

    return round(count_better / n_simulations, 4)


def deflated_sharpe_ratio(
    sharpe_observed: float,
    n_trials: int,
    returns: list[float],
    skewness: float | None = None,
    kurtosis: float | None = None,
) -> float:
    """
    Deflated Sharpe Ratio (DSR) per Bailey & Lopez de Prado (2014).
    Adjusts Sharpe for multiple testing / data mining bias.
    """
    n = len(returns)
    if n < 10 or n_trials < 1:
        return 0.0

    if skewness is None:
        mean = sum(returns) / n
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1)) if n > 1 else 1.0
        if std > 0:
            skewness = sum((r - mean) ** 3 for r in returns) / (n * std ** 3)
        else:
            skewness = 0.0

    if kurtosis is None:
        mean = sum(returns) / n
        std = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1)) if n > 1 else 1.0
        if std > 0:
            kurtosis = sum((r - mean) ** 4 for r in returns) / (n * std ** 4)
        else:
            kurtosis = 3.0

    var_sr = (1 + 0.5 * sharpe_observed ** 2 - skewness * sharpe_observed + (kurtosis - 3) / 4 * sharpe_observed ** 2) / (n - 1)
    std_sr = math.sqrt(max(var_sr, 1e-10))

    expected_max = _expected_max_sharpe(n_trials)
    threshold = expected_max * std_sr

    dsr = _normal_cdf((sharpe_observed - threshold) / std_sr)
    return round(dsr, 4)


def probability_of_backtest_overfitting(
    returns_matrix: list[list[float]],
    n_folds: int = 10,
    n_simulations: int = 500,
) -> float:
    """
    Probability of Backtest Overfitting (PBO) per Bailey & Lopez de Prado (2015).
    Split returns into N combinations, find best strategy in-sample,
    test if it underperforms out-of-sample.
    """
    if not returns_matrix or len(returns_matrix) < 2:
        return 0.0

    n_strategies = len(returns_matrix)
    n_periods = len(returns_matrix[0])
    half = n_periods // 2
    if half < 5:
        return 0.0

    underperform_count = 0

    for _ in range(n_simulations):
        indices = list(range(n_periods))
        random.shuffle(indices)
        train_idx = set(indices[:half])
        test_idx = set(indices[half:])

        train_sharpes = []
        for s in range(n_strategies):
            train_rets = [returns_matrix[s][i] for i in range(n_periods) if i in train_idx]
            train_sharpes.append(compute_sharpe_ratio(train_rets))

        best_idx = train_sharpes.index(max(train_sharpes))
        test_rets_best = [returns_matrix[best_idx][i] for i in range(n_periods) if i in test_idx]
        test_sharpe_best = compute_sharpe_ratio(test_rets_best)

        median_test = sorted([
            compute_sharpe_ratio([returns_matrix[s][i] for i in range(n_periods) if i in test_idx])
            for s in range(n_strategies)
        ])[n_strategies // 2]

        if test_sharpe_best < median_test:
            underperform_count += 1

    return round(underperform_count / n_simulations, 4)


def confidence_interval(returns: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Bootstrap confidence interval for mean return."""
    n = len(returns)
    if n < 10:
        return (0.0, 0.0)

    mean = sum(returns) / n
    n_boot = 5000
    boot_means = []

    for _ in range(n_boot):
        sample = [returns[random.randint(0, n - 1)] for _ in range(n)]
        boot_means.append(sum(sample) / n)

    boot_means.sort()
    alpha = 1 - confidence
    lower_idx = int(alpha / 2 * n_boot)
    upper_idx = int((1 - alpha / 2) * n_boot)
    return (round(boot_means[lower_idx], 6), round(boot_means[upper_idx], 6))


def min_track_record_length(sharpe: float, confidence: float = 0.95) -> int:
    """
    Minimum track record length (MinTRL) to distinguish Sharpe from zero.
    Per Lopez de Prado: MinTRL = 1 + (1 - confidence_level) * z / sharpe^2
    """
    if sharpe == 0:
        return 999999
    z = _normal_ppf(confidence)
    min_periods = int(math.ceil((1 + z * sharpe) / (sharpe ** 2)))
    return max(min_periods, 30)


def compute_full_statistics(
    returns: list[float],
    strategy_returns: list[float] | None = None,
    returns_matrix: list[list[float]] | None = None,
    n_trials: int = 1,
) -> StatisticalResult:
    """Compute all statistical tests at once."""
    sharpe = compute_sharpe_ratio(returns)
    t_result = compute_t_test(returns)
    ci = confidence_interval(returns)
    mintrl = min_track_record_length(sharpe)

    mc_p = 1.0
    if strategy_returns and len(strategy_returns) >= 10:
        mc_p = monte_carlo_permutation_test(returns, strategy_returns, n_simulations=5000)

    dsr = deflated_sharpe_ratio(sharpe, n_trials, returns) if n_trials > 1 else sharpe

    pbo = 0.0
    if returns_matrix and len(returns_matrix) >= 2:
        pbo = probability_of_backtest_overfitting(returns_matrix, n_simulations=200)

    return StatisticalResult(
        sharpe_ratio=sharpe,
        deflated_sharpe=round(dsr, 4),
        p_value=t_result["p_value"],
        is_significant=t_result["p_value"] < 0.05,
        confidence_interval_95=ci,
        monte_carlo_p_value=mc_p,
        probability_of_overfitting=pbo,
        min_track_record_length=mintrl,
        trials_tested=n_trials,
    )


def _expected_max_sharpe(n_trials: int) -> float:
    """Expected maximum Sharpe ratio under the null hypothesis."""
    if n_trials <= 1:
        return 0.0
    euler = 0.5772156649
    return math.sqrt(2 * math.log(n_trials)) - (euler / math.sqrt(2 * math.log(n_trials)))


def _normal_cdf(x: float) -> float:
    """Standard normal CDF approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _normal_ppf(p: float) -> float:
    """Inverse normal CDF (percent point function) approximation."""
    if p <= 0:
        return -10.0
    if p >= 1:
        return 10.0
    if p == 0.5:
        return 0.0
    a = [
        -3.969683028665376e+01, 2.209460984245205e+02,
        -2.759285104469687e+02, 1.383577518672690e+02,
        -3.066479806614716e+01, 2.506628277459239e+00,
    ]
    b = [
        -5.447609879822406e+01, 1.615858368580409e+02,
        -1.556989798598866e+02, 6.680131188771972e+01,
        -1.328068155288572e+01,
    ]
    c = [
        -7.784894002430293e-03, -3.223964580411365e-01,
        -2.400758277161838e+00, -2.549732539343734e+00,
        4.374664141464968e+00, 2.938163982698783e+00,
    ]
    d = [
        7.784695709041462e-03, 3.224671290700398e-01,
        2.445134137142996e+00, 3.754408661907416e+00,
    ]
    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _t_to_pvalue(t: float, df: int) -> float:
    """Approximate two-tailed p-value from t-statistic using normal approximation for large df."""
    if df >= 30:
        z = abs(t)
        return 2 * (1 - _normal_cdf(z))
    else:
        z = abs(t)
        return 2 * (1 - _normal_cdf(z * math.sqrt(df / (df - 2)))) if df > 2 else 1.0
