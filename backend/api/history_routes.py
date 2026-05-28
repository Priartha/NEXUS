from __future__ import annotations

from fastapi import APIRouter, Query
from typing import Optional

from backend.storage.history_repository import (
    get_market_snapshots,
    get_pattern_history,
    get_pattern_stats,
    get_regime_history,
    get_regime_distribution,
    get_metrics_history,
    get_candles,
    get_ai_decisions,
    get_ai_accuracy,
    get_liquidity_history,
    get_daily_performance,
    get_storage_stats,
    cleanup_old_data,
)
from backend.analysis.pattern_performance import compute_pattern_performance
from backend.storage.export_utils import export_to_csv, export_to_json, VALID_EXPORT_TABLES
from backend.analysis.daily_reports import get_daily_reports, daily_reporter
from fastapi.responses import Response

router = APIRouter(prefix="/history", tags=["history"])


# ─── Market Snapshots ─────────────────────────────────────

@router.get("/snapshots")
def api_market_snapshots(
    symbol: Optional[str] = Query(None),
    timeframe: Optional[str] = Query(None),
    start_ts: Optional[int] = Query(None),
    end_ts: Optional[int] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Get market state snapshots."""
    return get_market_snapshots(
        symbol=symbol,
        timeframe=timeframe,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
    )


# ─── Pattern History ──────────────────────────────────────

@router.get("/patterns")
def api_pattern_history(
    name: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    start_ts: Optional[int] = Query(None),
    end_ts: Optional[int] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
):
    """Get pattern detection history."""
    return get_pattern_history(
        name=name,
        direction=direction,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
    )


@router.get("/patterns/stats")
def api_pattern_stats(days: int = Query(7, ge=1, le=365)):
    """Get pattern statistics."""
    return get_pattern_stats(days=days)


# ─── Regime History ───────────────────────────────────────

@router.get("/regimes")
def api_regime_history(
    symbol: Optional[str] = Query(None),
    start_ts: Optional[int] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
):
    """Get market regime history."""
    return get_regime_history(symbol=symbol, start_ts=start_ts, limit=limit)


@router.get("/regimes/distribution")
def api_regime_distribution(days: int = Query(7, ge=1, le=365)):
    """Get regime phase distribution."""
    return get_regime_distribution(days=days)


# ─── Metrics History ──────────────────────────────────────

@router.get("/metrics")
def api_metrics_history(
    symbol: Optional[str] = Query(None),
    start_ts: Optional[int] = Query(None),
    end_ts: Optional[int] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Get market metrics history."""
    return get_metrics_history(
        symbol=symbol,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
    )


# ─── Candle Archive ───────────────────────────────────────

@router.get("/candles")
def api_candles(
    symbol: str = Query("BTCUSDT"),
    timeframe: str = Query("5m"),
    start_ts: Optional[int] = Query(None),
    end_ts: Optional[int] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
):
    """Get archived candles."""
    return get_candles(
        symbol=symbol,
        timeframe=timeframe,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
    )


# ─── AI Decisions ─────────────────────────────────────────

@router.get("/ai")
def api_ai_decisions(
    symbol: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    start_ts: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get AI decision history."""
    return get_ai_decisions(
        symbol=symbol,
        grade=grade,
        start_ts=start_ts,
        limit=limit,
    )


@router.get("/ai/accuracy")
def api_ai_accuracy(
    days: int = Query(7, ge=1, le=365),
    timeframe: Optional[str] = Query(None),
):
    """Get AI decision accuracy stats."""
    return get_ai_accuracy(days=days, timeframe=timeframe)


# ─── Liquidity History ────────────────────────────────────

@router.get("/liquidity")
def api_liquidity_history(
    symbol: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    start_ts: Optional[int] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
):
    """Get liquidity event history."""
    return get_liquidity_history(
        symbol=symbol,
        side=side,
        start_ts=start_ts,
        limit=limit,
    )


# ─── Daily Performance ────────────────────────────────────

@router.get("/performance")
def api_daily_performance(
    symbol: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(90, ge=1, le=365),
):
    """Get daily performance stats."""
    return get_daily_performance(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


# ─── Storage Management ───────────────────────────────────

@router.get("/stats")
def api_storage_stats():
    """Get storage statistics."""
    return get_storage_stats()


@router.post("/cleanup")
def api_cleanup(
    keep_days_snapshots: int = Query(90),
    keep_days_patterns: int = Query(180),
    keep_days_metrics: int = Query(60),
    keep_days_candles: int = Query(365),
    keep_days_ai: int = Query(180),
    keep_days_liquidity: int = Query(90),
    keep_days_orderbook: int = Query(30),
):
    """Run data retention cleanup."""
    return cleanup_old_data(
        keep_days_snapshots=keep_days_snapshots,
        keep_days_patterns=keep_days_patterns,
        keep_days_metrics=keep_days_metrics,
        keep_days_candles=keep_days_candles,
        keep_days_ai=keep_days_ai,
        keep_days_liquidity=keep_days_liquidity,
        keep_days_orderbook=keep_days_orderbook,
    )


# ─── Pattern Performance ──────────────────────────────────

@router.get("/patterns/performance")
def api_pattern_performance(days: int = Query(30, ge=1, le=365)):
    """Get pattern performance analysis."""
    return compute_pattern_performance(days=days)


# ─── Data Export ──────────────────────────────────────────

@router.get("/export/{table}")
def api_export(
    table: str,
    format: str = Query("json", pattern="^(csv|json)$"),
    symbol: Optional[str] = Query(None),
):
    """Export table data as CSV or JSON."""
    if table not in VALID_EXPORT_TABLES:
        return {"error": f"Invalid table. Valid tables: {list(VALID_EXPORT_TABLES)}"}

    filters = {"symbol": symbol} if symbol else None

    if format == "csv":
        csv_data = export_to_csv(table, filters)
        return Response(content=csv_data, media_type="text/csv", headers={
            "Content-Disposition": f"attachment; filename={table}.csv"
        })
    else:
        json_data = export_to_json(table, filters)
        return Response(content=json_data, media_type="application/json", headers={
            "Content-Disposition": f"attachment; filename={table}.json"
        })


# ─── Daily Reports ────────────────────────────────────────

@router.get("/reports/daily")
def api_daily_reports(limit: int = Query(30, ge=1, le=365)):
    """Get daily reports."""
    return get_daily_reports(limit=limit)


@router.post("/reports/daily/generate")
def api_generate_report_now():
    """Generate daily report immediately."""
    return daily_reporter.generate_now()
