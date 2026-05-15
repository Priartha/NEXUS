from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.engine.candle_store import CandleStore
    from backend.analysis.pipeline import AnalysisPipeline


def compute_mtf_confluence(
    current_tf: str,
    all_stores: dict[str, "CandleStore"],
    all_pipelines: dict[str, "AnalysisPipeline"],
) -> dict:
    """Multi-timeframe confluence check.
    Compares trend direction across timeframes to boost or reduce confidence.
    Returns dict with: alignment_score, higher_tf_bias, lower_tf_bias, confluence_factor."""
    timeframe_hierarchy = ["1m", "5m", "15m", "1h", "4h"]

    try:
        current_idx = timeframe_hierarchy.index(current_tf)
    except ValueError:
        return {"alignment_score": 0.5, "higher_tf_bias": "neutral", "lower_tf_bias": "neutral", "confluence_factor": 1.0, "timeframes_checked": 0}

    higher_tf_bias = "neutral"
    lower_tf_bias = "neutral"
    aligned_count = 0
    total_count = 0

    # Check higher timeframes
    for tf in timeframe_hierarchy[current_idx + 1:]:
        if tf not in all_pipelines or tf not in all_stores:
            continue
        pipeline = all_pipelines[tf]
        if pipeline.metrics is None:
            continue
        total_count += 1
        ts = pipeline.metrics.trend_score
        if ts > 0.15:
            higher_tf_bias = "bullish" if higher_tf_bias != "bearish" else "mixed"
            aligned_count += 1
        elif ts < -0.15:
            higher_tf_bias = "bearish" if higher_tf_bias != "bullish" else "mixed"
            aligned_count += 1

    # Check lower timeframes
    for tf in timeframe_hierarchy[:current_idx]:
        if tf not in all_pipelines or tf not in all_stores:
            continue
        pipeline = all_pipelines[tf]
        if pipeline.metrics is None:
            continue
        total_count += 1
        ts = pipeline.metrics.trend_score
        if ts > 0.15:
            lower_tf_bias = "bullish" if lower_tf_bias != "bearish" else "mixed"
        elif ts < -0.15:
            lower_tf_bias = "bearish" if lower_tf_bias != "bullish" else "mixed"

    # Confluence factor: 1.15 if all aligned, 0.85 if conflicting
    if total_count == 0:
        confluence_factor = 1.0
    else:
        alignment_ratio = aligned_count / total_count
        confluence_factor = 0.85 + alignment_ratio * 0.30

    return {
        "alignment_score": round(alignment_ratio, 3) if total_count > 0 else 0.5,
        "higher_tf_bias": higher_tf_bias,
        "lower_tf_bias": lower_tf_bias,
        "confluence_factor": round(confluence_factor, 3),
        "timeframes_checked": total_count,
    }
