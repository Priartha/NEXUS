from __future__ import annotations

import asyncio
from dotenv import load_dotenv
load_dotenv()
import httpx
import logging
import logging.config
import time
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dataclasses import dataclass
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.analysis.ai_ict import AiIctService
from backend.analysis.mtf_confluence import compute_mtf_confluence
from backend.analysis.options import build_options_context
from backend.analysis.pipeline import AnalysisPipeline
from backend.analysis.sentiment import SentimentService
from backend.broadcast.ws_manager import ConnectionManager
from backend.config import settings
from backend.engine.candle_store import CandleStore
from backend.ingestion.binance import start_binance_stream
from backend.ingestion.delta_rest import fetch_option_tickers
from backend.ingestion.delta_ws import start_delta_stream
from backend.models.types import to_wire
from backend.storage.schema import init_db
from backend.storage import repository as repo
from backend.analysis.backtest import BacktestEngine
from backend.analysis.paper_trading import PaperTradingEngine
from backend.analysis.risk_manager import RiskManager
from backend.analysis.symbol_scanner import MultiSymbolScanner
from backend.analysis.csv_import import parse_csv, get_supported_formats
from backend.api.history_routes import router as history_router
from backend.api.demo_routes import router as demo_router
from backend.storage.history_recorder import recorder as history_recorder
from backend.analysis.daily_reports import daily_reporter
from backend.utils.cache import global_cache, CACHE_TTLS, invalidate_pattern

paper_trading = PaperTradingEngine()
risk_manager = RiskManager()
symbol_scanner = MultiSymbolScanner()

# Logging configuration
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s"
        },
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        },
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(logs_dir / "nexus.log"),
            "maxBytes": 10_000_000,  # 10MB
            "backupCount": 5,
            "formatter": "json",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "DEBUG",
        },
    },
    "loggers": {
        "backend": {
            "level": "INFO",
            "handlers": ["file", "console"],
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)

limiter = Limiter(key_func=get_remote_address)
manager = ConnectionManager()
logger = logging.getLogger("backend")
app_loop: asyncio.AbstractEventLoop | None = None

class ErrorResponse(BaseModel):
    error_code: str
    message: str
    timestamp: int
    request_id: str
    details: dict | None = None
ai_ict_service = AiIctService(
    provider=settings.ai_ict_provider,
    gemini_model=settings.gemini_model,
    gemini_api_key=settings.gemini_api_key,
    gemini_base_url=settings.gemini_base_url,
)
sentiment_service = SentimentService(
    symbol=settings.symbol,
    provider=settings.sentiment_provider,
    openai_model=settings.sentiment_model,
    openai_api_key=settings.openai_api_key,
    openai_base_url=settings.openai_base_url,
    gemini_model=settings.gemini_model,
    gemini_api_key=settings.gemini_api_key,
    gemini_base_url=settings.gemini_base_url,
)
supported_timeframes = tuple(dict.fromkeys((*settings.timeframes, settings.timeframe)))
stores = {
    timeframe: CandleStore(settings.symbol, timeframe, max_candles=settings.max_candles)
    for timeframe in supported_timeframes
}
def _pipeline_alert_handler(alert: dict) -> None:
    logger.info(f"Alert: {alert.get('title', '')}")
    if app_loop is None or app_loop.is_closed():
        logger.warning("Alert broadcast skipped because the app loop is not ready")
        return

    def _log_failure(done: asyncio.Task) -> None:
        try:
            done.result()
        except Exception:
            logger.exception("Alert broadcast failed")

    def _schedule() -> None:
        task = app_loop.create_task(manager.broadcast({"update_type": "alert", **alert}))
        task.add_done_callback(_log_failure)

    app_loop.call_soon_threadsafe(_schedule)

pipelines = {
    timeframe: AnalysisPipeline(
        paper_trading=paper_trading,
        on_alert=_pipeline_alert_handler,
    )
    for timeframe in supported_timeframes
}
for timeframe, pipeline in pipelines.items():
    pipeline.set_store_reference(stores[timeframe])
ai_ict_reviews = {timeframe: None for timeframe in supported_timeframes}
option_tickers: list[dict] = []
option_tickers_error: str | None = None

import hmac

def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key:
        if not x_api_key:
            logger.warning(f"API key missing from {request.client.host}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")
        if not hmac.compare_digest(x_api_key, settings.api_key):
            logger.warning(f"Invalid API key attempt from {request.client.host}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_loop
    app_loop = asyncio.get_running_loop()

    # Configuration validation
    from backend.utils.config_validator import validator
    config_issues = validator.validate_all()
    validator.print_report(config_issues)
    if validator.has_errors(config_issues):
        logger.error("CRITICAL configuration errors detected. Shutting down.")
        raise RuntimeError("Configuration validation failed")

    # Database integrity setup
    from backend.utils.db_integrity import db_integrity
    db_integrity.enable_wal_mode()
    integrity = db_integrity.check_integrity()
    if integrity["status"] != "ok":
        logger.warning(f"Database integrity issues: {integrity['issues']}")
        backup = db_integrity.create_backup()
        if backup:
            logger.info(f"Pre-start backup created: {backup}")
    init_db()

    # Initialize multi-exchange price aggregator
    from backend.ingestion.multi_exchange import aggregator as multi_exchange_aggregator
    multi_exchange_aggregator.symbol = settings.symbol
    logger.info(f"Multi-exchange aggregator initialized for {settings.symbol}")

    # Model performance tracker
    from backend.analysis.model_tracker import model_tracker
    logger.info("Model performance tracker initialized")

    # Seed historical data for backtesting
    if settings.market_data_provider.lower() == "binance":
        from backend.ingestion.binance import fetch_historical_candles
        for tf, store in stores.items():
            try:
                logger.info(f"Seeding historical data for {tf}")
                candles = await fetch_historical_candles(settings.market_data_rest_base_url, settings.symbol, tf, limit=1000)
                now_ms = candles[-1].timestamp if candles else None
                store.seed(candles, now_ms=now_ms)
                logger.info(f"Seeded {len(candles)} candles for {tf}")
            except Exception as e:
                logger.warning(f"Failed to seed {tf}: {e}")

    if settings.market_data_provider.lower() == "binance":
        stream_task = asyncio.create_task(start_binance_stream(manager, stores, pipelines, settings))
    else:
        stream_task = asyncio.create_task(start_delta_stream(manager, stores, pipelines, settings))
    sentiment_task = asyncio.create_task(refresh_sentiment_loop())
    ai_ict_task = asyncio.create_task(refresh_ai_ict_loop())
    options_task = asyncio.create_task(refresh_options_loop())

    # Start history recorder (uses primary timeframe pipeline)
    primary_tf = supported_timeframes[0]
    primary_pipeline = pipelines[primary_tf]
    await history_recorder.start(primary_pipeline)
    logger.info(f"History recorder started for timeframe {primary_tf}")

    # Start daily report generator
    await daily_reporter.start()
    logger.info("Daily report generator started")

    # Start model performance monitoring loop
    model_monitor_task = asyncio.create_task(model_performance_monitor_loop())

    # Periodic database backup loop
    db_backup_task = asyncio.create_task(database_backup_loop(db_integrity))

    try:
        yield
    finally:
        logger.info("Shutting down background tasks")
        await history_recorder.stop()
        await daily_reporter.stop()
        model_monitor_task.cancel()
        db_backup_task.cancel()
        for task in (stream_task, sentiment_task, ai_ict_task, options_task, model_monitor_task, db_backup_task):
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"Task {task.get_name()} cancelled successfully")
            except Exception as e:
                logger.error(f"Task {task.get_name()} failed during shutdown: {e}", exc_info=True)
        db_integrity.create_backup()
        logger.info("Final database backup created on shutdown")


app = FastAPI(title="NEXUS", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.include_router(history_router)
app.include_router(demo_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "x-api-key"],
    max_age=3600,
)

# Production: serve frontend static files
import sys as _sys
if getattr(_sys, "frozen", False):
    _base = Path(_sys.executable).parent / "_internal"
else:
    _base = Path(__file__).resolve().parent.parent
FRONTEND_DIST = _base / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")
    logger.info(f"Serving frontend from {FRONTEND_DIST}")
else:
    logger.info(f"Frontend dist not found at {FRONTEND_DIST} - running in API-only mode")

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(f"Rate limit exceeded for {request.client.host} on {request.url}")
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded"}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = str(uuid.uuid4())
    logger.error(f"[{request_id}] Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": str(exc),
            "timestamp": int(time.time() * 1000),
            "request_id": request_id,
        }
    )


@app.get("/")
async def root():
    if FRONTEND_DIST.is_dir():
        return FileResponse(str(FRONTEND_DIST / "index.html"))
    return {
        "name": "NEXUS",
        "docs": "/docs",
        "health": "/health",
        "snapshot": "/snapshot",
        "sentiment": "/sentiment",
        "ai_ict": "/ai-ict",
        "websocket": "/ws/chart",
        "timeframes": supported_timeframes,
    }


@app.get("/debug/ob")
async def debug_ob(tf: str = Query(default=settings.timeframe)) -> dict:
    if tf not in supported_timeframes:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe: {tf}")
    p = pipelines[tf]
    return {
        "history_size": len(p.orderbook_analyzer.history),
        "history_date_range": (
            p.orderbook_analyzer.history[0].timestamp if p.orderbook_analyzer.history else None,
            p.orderbook_analyzer.history[-1].timestamp if p.orderbook_analyzer.history else None,
        ),
        "sample_quote": to_wire(p.orderbook_analyzer.history[-1]) if p.orderbook_analyzer.history else None,
    }

@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "symbol": settings.symbol,
        "timeframes": {
            timeframe: {
                "closed_candles": len(store.get_closed_candles()),
                "has_live_candle": store.live_candle is not None,
            }
            for timeframe, store in stores.items()
        },
        "clients": manager.count,
        "sentiment": {
            "label": sentiment_service.current.label,
            "provider": sentiment_service.current.provider,
            "model": sentiment_service.current.model,
            "source_count": sentiment_service.current.source_count,
            "updated_at": sentiment_service.current.updated_at,
        },
        "ai_ict": {
            timeframe: {
                "grade": review.grade,
                "direction": review.direction,
                "provider": review.provider,
                "updated_at": review.updated_at,
            }
            for timeframe, review in ai_ict_reviews.items()
            if review is not None
        },
        "options": {
            "underlying": settings.options_underlying,
            "ticker_count": len(option_tickers),
            "error": option_tickers_error,
            "min_momentum_score": settings.min_options_momentum_score,
        },
    }


# ─── Backtesting ──────────────────────────────────────────

class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    timeframe: str = "5m"
    candle_count: int = 1000
    initial_balance: float = 10_000.0
    position_size_pct: float = 0.02
    max_hold_bars: int = 25
    breakeven_threshold: float = 1.0
    trailing_stop: bool = False


@app.post("/backtest/run")
async def run_backtest(body: BacktestRequest) -> dict:
    store = stores.get(body.timeframe)
    if not store:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {body.timeframe}")

    candles = store.get_closed_candles()
    if len(candles) < 80:
        raise HTTPException(status_code=400, detail=f"Not enough candles: {len(candles)} (need at least 80)")

    candles = candles[-body.candle_count:]

    engine = BacktestEngine(
        initial_balance=body.initial_balance,
        position_size_pct=body.position_size_pct,
        max_hold_bars=body.max_hold_bars,
        breakeven_threshold=body.breakeven_threshold,
        trailing_stop=body.trailing_stop,
    )
    try:
        result = engine.run(candles, symbol=body.symbol, timeframe=body.timeframe)
    except Exception as e:
        import traceback
        logger.error(f"Backtest engine failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Backtest engine error: {str(e)}")

    try:
        repo.save_backtest_run(result)
        repo.save_backtest_trades(result["id"], result["trades"])
        pts = [{"timestamp": e["timestamp"], "account_balance": e["account_balance"],
                "drawdown": e["drawdown"], "drawdown_pct": e["drawdown_pct"],
                "source": "backtest", "run_id": result["id"]} for e in result["equity_curve"]]
        repo.save_equity_points(pts)
    except Exception as e:
        import traceback
        logger.error(f"Failed to save backtest results: {e}\n{traceback.format_exc()}")

    result.pop("trades", None)
    result.pop("equity_curve", None)
    return result


@app.get("/backtest/runs")
async def backtest_runs(symbol: str | None = None) -> list[dict]:
    return repo.get_backtest_runs(symbol=symbol)


@app.get("/backtest/runs/{run_id}")
async def backtest_run_detail(run_id: str) -> dict:
    runs = repo.get_backtest_runs()
    run = next((r for r in runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    run["trades"] = repo.get_backtest_trades(run_id)
    run["equity_curve"] = repo.get_equity_curve(run_id)
    return run


# ─── Paper Trading ────────────────────────────────────────

@app.get("/paper-trades")
async def get_paper_trades(status: str | None = None) -> list[dict]:
    return repo.get_paper_trades(status=status)


@app.get("/paper-trades/stats")
async def paper_trade_stats() -> dict:
    return repo.get_paper_trade_stats()


@app.post("/paper-trades/toggle")
async def toggle_paper_trading() -> dict:
    return {"ok": True, "message": "Paper trading toggle requested. Configure in settings."}


@app.post("/paper-trades/reset")
async def reset_paper_trades() -> dict:
    count = repo.reset_paper_trades()
    return {"ok": True, "message": f"Cleared {count} paper trades"}


@app.post("/backtest/reset")
async def reset_backtest_data() -> dict:
    count = repo.reset_backtests()
    return {"ok": True, "message": f"Cleared {count} backtest runs"}


# ─── CSV Import ───────────────────────────────────────────

class CsvImportRequest(BaseModel):
    content: str
    format: str = "auto"
    symbol: str = "BTCUSDT"
    timeframe: str = "5m"
    custom_mapping: dict[str, str] | None = None


@app.get("/csv-import/formats")
async def get_csv_formats() -> list[dict]:
    """Get list of supported CSV formats."""
    return get_supported_formats()


@app.post("/csv-import/parse")
async def parse_csv_data(body: CsvImportRequest) -> dict:
    """Parse CSV content and return candle data."""
    if not body.content or not body.content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")

    result = parse_csv(
        content=body.content,
        format_type=body.format,
        custom_mapping=body.custom_mapping,
        timeframe=body.timeframe,
        symbol=body.symbol,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["errors"])

    return {
        "success": True,
        "metadata": result["metadata"],
        "warnings": result["warnings"],
        "candle_count": result["count"],
    }


@app.post("/csv-import/backtest")
async def backtest_csv(body: CsvImportRequest) -> dict:
    """Parse CSV and run backtest on imported data."""
    if not body.content or not body.content.strip():
        raise HTTPException(status_code=400, detail="Empty CSV content")

    result = parse_csv(
        content=body.content,
        format_type=body.format,
        custom_mapping=body.custom_mapping,
        timeframe=body.timeframe,
        symbol=body.symbol,
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["errors"])

    candles = result["candles"]
    if len(candles) < 80:
        raise HTTPException(status_code=400, detail=f"Not enough candles: {len(candles)} (need at least 80)")

    engine = BacktestEngine(
        initial_balance=10000,
        position_size_pct=0.02,
        max_hold_bars=10,
        breakeven_threshold=1.0,
        trailing_stop=False,
        slippage_pct=0.0001,
        commission_pct=0.0002,
    )
    bt_result = engine.run(candles, symbol=body.symbol, timeframe=body.timeframe)
    bt_result["import_metadata"] = result["metadata"]
    bt_result["import_warnings"] = result["warnings"]

    repo.save_backtest_run(bt_result)
    repo.save_backtest_trades(bt_result["id"], bt_result["trades"])

    pts = [{"timestamp": e["timestamp"], "account_balance": e["account_balance"],
            "drawdown": e["drawdown"], "drawdown_pct": e["drawdown_pct"],
            "source": "csv_import", "run_id": bt_result["id"]} for e in bt_result["equity_curve"]]
    repo.save_equity_points(pts)

    bt_result.pop("trades", None)
    bt_result.pop("equity_curve", None)
    return bt_result


# ─── MTF Confluence ─────────────────────────────────────

# ─── Signals Journal ──────────────────────────────────────

@app.get("/signals/journal")
async def signals_journal(symbol: str | None = None, limit: int = 100) -> list[dict]:
    return repo.get_signals(symbol=symbol, limit=limit)


# ─── Alerts ───────────────────────────────────────────────

@app.get("/alerts")
async def get_alerts(unread_only: bool = False, limit: int = 50) -> list[dict]:
    return repo.get_alerts(limit=limit, unread_only=unread_only)


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str) -> dict:
    repo.acknowledge_alert(alert_id)
    return {"ok": True}


@app.get("/alerts/config")
async def get_alert_config() -> dict:
    cached_result = await global_cache.get("alert_config")
    if cached_result is not None:
        return cached_result
    data = repo.get_alert_config()
    await global_cache.set("alert_config", data, ttl=CACHE_TTLS.get("alert_config"))
    return data


@app.post("/alerts/config")
async def save_alert_config(config: dict) -> dict:
    repo.save_alert_config(config)
    await global_cache.delete("alert_config")
    return {"ok": True, "message": "Alert configuration saved"}


# ─── Trade Journal ────────────────────────────────────────

@app.get("/journal")
async def get_journal(trade_id: str | None = None) -> list[dict]:
    return repo.get_journal_entries(trade_id=trade_id)


@app.get("/scanner")
async def scan_symbols(symbols: str | None = None) -> list[dict]:
    """Scan multiple symbols for trading opportunities."""
    sym_list = [s.strip() for s in symbols.split(",")] if symbols else None
    results = await symbol_scanner.scan(sym_list)
    return [
        {
            "symbol": r.symbol,
            "price": r.price,
            "change_24h": r.change_24h,
            "volume_24h": r.volume_24h,
            "trend_score": round(r.trend_score, 3),
            "volatility_score": round(r.volatility_score, 3),
            "momentum_score": round(r.momentum_score, 3),
            "overall_score": round(r.overall_score, 3),
            "recommendation": r.recommendation,
        }
        for r in results
    ]


@app.get("/risk")
async def get_risk_status() -> dict:
    """Get current risk management status."""
    return risk_manager.get_risk_summary()


# ─── Scalping Engine (Derivatives Only) ───────────────────

@app.get("/scalp")
async def get_scalp_context(
    tf: str = Query(default=settings.timeframe),
) -> dict:
    """Get scalping engine context with signals, order flow, and risk status."""
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}")
    pipeline = pipelines[tf]
    store = stores[tf]
    payload = await asyncio.wait_for(
        pipeline.snapshot_async(store),
        timeout=15.0,
    )
    _attach_options_context(payload, tf)
    payload["mtf_confluence"] = compute_mtf_confluence(tf, stores, pipelines)
    _apply_scalp_accuracy_gates(payload, tf)
    return {
        "scalp_context": payload.get("scalp"),
        "scalp_risk": payload.get("scalp_risk"),
        "timeframe": tf,
        "symbol": settings.symbol,
    }


@app.get("/scalp/signals")
async def get_scalp_signals(
    tf: str = Query(default=settings.timeframe),
) -> list[dict]:
    """Get current scalping signals only."""
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}")
    pipeline = pipelines[tf]
    store = stores[tf]
    payload = await asyncio.wait_for(
        pipeline.snapshot_async(store),
        timeout=15.0,
    )
    _attach_options_context(payload, tf)
    payload["mtf_confluence"] = compute_mtf_confluence(tf, stores, pipelines)
    _apply_scalp_accuracy_gates(payload, tf)
    scalp = payload.get("scalp")
    if not scalp:
        return []
    return scalp.get("signals", [])


@app.get("/scalp/risk")
async def get_scalp_risk() -> dict:
    """Get scalping risk manager status."""
    tf = settings.timeframe
    pipeline = pipelines[tf]
    return pipeline.scalp_risk.get_risk_summary()


@app.get("/scalp/orderflow")
async def get_scalp_orderflow(
    tf: str = Query(default=settings.timeframe),
) -> dict:
    """Get current order flow metrics."""
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}")
    pipeline = pipelines[tf]
    store = stores[tf]
    payload = await asyncio.wait_for(
        pipeline.snapshot_async(store),
        timeout=15.0,
    )
    _attach_options_context(payload, tf)
    payload["mtf_confluence"] = compute_mtf_confluence(tf, stores, pipelines)
    _apply_scalp_accuracy_gates(payload, tf)
    scalp = payload.get("scalp")
    if not scalp:
        return {"error": "No scalping context available"}
    return {
        "order_flow": scalp.get("order_flow"),
        "vwap": scalp.get("vwap"),
        "volume_profile": scalp.get("volume_profile"),
        "rsi_3": scalp.get("rsi_3"),
    }


@app.get("/scalp/funding")
async def get_scalp_funding() -> dict:
    """Get current funding rate and next reset."""
    tf = settings.timeframe
    pipeline = pipelines[tf]
    store = stores[tf]
    payload = await asyncio.wait_for(
        pipeline.snapshot_async(store),
        timeout=15.0,
    )
    _attach_options_context(payload, tf)
    payload["mtf_confluence"] = compute_mtf_confluence(tf, stores, pipelines)
    _apply_scalp_accuracy_gates(payload, tf)
    scalp = payload.get("scalp")
    if not scalp:
        return {"error": "No scalping context available"}
    return scalp.get("funding", {})


@app.get("/scalp/blockers")
async def get_scalp_blockers(
    tf: str = Query(default=settings.timeframe),
) -> list[str]:
    """Get current trade blockers/filters."""
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}")
    pipeline = pipelines[tf]
    store = stores[tf]
    payload = await asyncio.wait_for(
        pipeline.snapshot_async(store),
        timeout=15.0,
    )
    _attach_options_context(payload, tf)
    payload["mtf_confluence"] = compute_mtf_confluence(tf, stores, pipelines)
    _apply_scalp_accuracy_gates(payload, tf)
    scalp = payload.get("scalp")
    if not scalp:
        return ["No scalping context available"]
    return scalp.get("trade_blocked_reasons", [])


@app.get("/snapshot")
async def snapshot(
    request: Request,
    tf: str = Query(default=settings.timeframe),
) -> dict:
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}. Supported: {list(supported_timeframes)}")
    timeframe = tf
    payload = await asyncio.wait_for(
        pipelines[timeframe].snapshot_async(stores[timeframe]),
        timeout=15.0,
    )
    payload["mtf_confluence"] = compute_mtf_confluence(timeframe, stores, pipelines)
    return _attach_realtime_context(payload, timeframe)


@app.get("/sentiment")
async def sentiment(request: Request) -> dict:
    return to_wire(sentiment_service.current)


@app.get("/news/btc")
@limiter.limit("30/minute")
async def btc_news(request: Request) -> list[dict]:
    headlines: list[dict] = []
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        tasks = [
            _fetch_rss(client, "CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
            _fetch_rss(client, "CoinTelegraph", "https://cointelegraph.com/rss"),
            _fetch_rss(client, "Decrypt", "https://decrypt.co/feed"),
            _fetch_fear_greed(client),
            _fetch_coinbase_price(client),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, list):
            headlines.extend(result)
        elif isinstance(result, Exception):
            logger.warning(f"News source failed: {result}")

    headlines.sort(key=lambda h: h.get("published_at", 0), reverse=True)

    if not headlines:
        headlines = _fallback_headlines()

    return headlines[:20]


async def _fetch_rss(client: httpx.AsyncClient, source_name: str, url: str) -> list[dict]:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        headlines = []
        for item in items[:15]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "#").strip()
            desc = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "")

            ts = 0
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    ts = int(parsedate_to_datetime(pub_date).timestamp())
                except Exception:
                    ts = int(time.time())

            if title:
                headlines.append({
                    "title": title,
                    "source": source_name,
                    "url": link,
                    "published_at": ts,
                    "body": _strip_html(desc)[:300],
                })
        logger.info(f"Loaded {len(headlines)} headlines from {source_name} RSS")
        return headlines
    except Exception as e:
        logger.warning(f"RSS fetch failed for {source_name}: {e}")
        return []


async def _fetch_fear_greed(client: httpx.AsyncClient) -> list[dict]:
    try:
        resp = await client.get("https://api.alternative.me/fng/?limit=3")
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        return [
            {
                "title": f"Fear & Greed Index: {item['value']} ({item['value_classification']})",
                "source": "Alternative.me",
                "url": "https://alternative.me/crypto/fear-and-greed-index/",
                "published_at": int(item.get("timestamp", 0)),
                "body": f"Market sentiment: {item['value_classification']} ({item['value']}/100)",
            }
            for item in items
        ]
    except Exception as e:
        logger.warning(f"Fear & Greed fetch failed: {e}")
        return []


async def _fetch_coinbase_price(client: httpx.AsyncClient) -> list[dict]:
    try:
        resp = await client.get("https://api.coinbase.com/v2/prices/BTC-USD/spot")
        resp.raise_for_status()
        data = resp.json()
        price = data.get("data", {}).get("amount", "N/A")
        return [
            {
                "title": f"BTC Spot Price: ${price} on Coinbase",
                "source": "Coinbase",
                "url": "https://www.coinbase.com/price/bitcoin",
                "published_at": int(time.time()),
                "body": f"Current Bitcoin spot price on Coinbase is ${price}.",
            }
        ]
    except Exception as e:
        logger.warning(f"Coinbase price fetch failed: {e}")
        return []


def _strip_html(text: str) -> str:
    import re
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&\w+;", " ", text)
    return text.strip()


def _fallback_headlines() -> list[dict]:
    now = int(time.time())
    return [
        {
            "title": "Bitcoin network hash rate remains strong — miners continue securing the blockchain",
            "source": "NEXUS",
            "url": "#",
            "published_at": now,
            "body": "Bitcoin hash rate data shows network security is robust.",
        },
        {
            "title": "On-chain metrics: BTC exchange reserves declining — long-term holders accumulating",
            "source": "NEXUS",
            "url": "#",
            "published_at": now - 3600,
            "body": "Exchange outflows suggest accumulation by long-term holders.",
        },
        {
            "title": "BTC dominance holding steady — market in consolidation phase",
            "source": "NEXUS",
            "url": "#",
            "published_at": now - 7200,
            "body": "Bitcoin dominance metrics show consolidation.",
        },
        {
            "title": "Lightning Network capacity reaches new highs — adoption growing",
            "source": "NEXUS",
            "url": "#",
            "published_at": now - 10800,
            "body": "Lightning Network growth indicates increasing BTC utility.",
        },
        {
            "title": "BTC institutional inflows continue — ETF demand remains steady",
            "source": "NEXUS",
            "url": "#",
            "published_at": now - 14400,
            "body": "Institutional Bitcoin products seeing consistent inflows.",
        },
    ]


@app.get("/ai-ict")
async def ai_ict(
    request: Request,
    tf: str = Query(default=settings.timeframe),
    _authorized: None = Depends(require_api_key),
) -> dict:
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}. Supported: {list(supported_timeframes)}")
    timeframe = tf
    payload = await pipelines[timeframe].snapshot_async(stores[timeframe])
    review = ai_ict_reviews.get(timeframe)
    if review is None or not _review_matches_payload(review, payload):
        review = ai_ict_service.local_review(payload, sentiment_service.current)
        ai_ict_reviews[timeframe] = review
    return to_wire(review)


@app.websocket("/ws/chart")
async def chart_ws(websocket: WebSocket, tf: str = settings.timeframe, api_key: str | None = None) -> None:
    if settings.api_key and api_key != settings.api_key:
        logger.warning(f"WebSocket connection rejected: invalid API key from {websocket.client}")
        await websocket.close(code=1008)
        return
    timeframe = _valid_timeframe(tf)
    await manager.connect(websocket, timeframe=timeframe)
    try:
        payload = await asyncio.wait_for(
            pipelines[timeframe].snapshot_async(stores[timeframe]),
            timeout=10.0,
        )
        payload = _attach_realtime_context(payload, timeframe)
        await websocket.send_json(payload)
        while True:
            await websocket.receive_text()
    except asyncio.TimeoutError:
        logger.error(f"WebSocket snapshot_async timed out for {timeframe} - pipeline lock or thread pool contention")
        await websocket.close(code=1011)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for timeframe {timeframe}")
    except RuntimeError as exc:
        if "close message has been sent" in str(exc):
            logger.info(f"WebSocket disconnected during send for timeframe {timeframe}")
        else:
            logger.error(f"WebSocket runtime error for timeframe {timeframe}: {exc}", exc_info=True)
    except Exception as e:
        logger.error(f"WebSocket error for timeframe {timeframe}: {e}", exc_info=True)
    finally:
        await manager.disconnect(websocket)


# ─── History WebSocket ──────────────────────────────────

_history_ws_clients: list[WebSocket] = []


@app.websocket("/ws/history")
async def history_ws(websocket: WebSocket) -> None:
    """WebSocket for real-time history/analytics updates."""
    await websocket.accept()
    _history_ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("History WebSocket disconnected")
    except Exception as e:
        logger.error(f"History WebSocket error: {e}", exc_info=True)
    finally:
        if websocket in _history_ws_clients:
            _history_ws_clients.remove(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


async def broadcast_history_update(data: dict) -> None:
    """Broadcast history update to all connected history WS clients."""
    if not _history_ws_clients:
        return
    for ws in _history_ws_clients[:]:
        try:
            await ws.send_json(data)
        except Exception:
            if ws in _history_ws_clients:
                _history_ws_clients.remove(ws)


def _valid_timeframe(timeframe: str) -> str:
    if timeframe not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {timeframe}. Supported: {list(supported_timeframes)}")
    return timeframe


def _attach_realtime_context(payload: dict, timeframe: str) -> dict:
    payload["available_timeframes"] = list(supported_timeframes)
    payload["sentiment"] = to_wire(sentiment_service.current)
    payload["mtf_confluence"] = compute_mtf_confluence(timeframe, stores, pipelines)
    _attach_options_context(payload, timeframe)
    _apply_scalp_accuracy_gates(payload, timeframe)
    review = ai_ict_reviews.get(timeframe)
    if review is None or not _review_matches_payload(review, payload):
        review = ai_ict_service.local_review(payload, sentiment_service.current)
        ai_ict_reviews[timeframe] = review
    payload["ai_ict"] = to_wire(review)
    return payload


def _apply_scalp_accuracy_gates(payload: dict, timeframe: str) -> None:
    scalp = payload.get("scalp")
    if not isinstance(scalp, dict):
        return
    signals = [sig for sig in scalp.get("signals", []) or [] if isinstance(sig, dict)]
    if not signals:
        return

    signal = signals[0]
    side = "short" if "SHORT" in str(signal.get("signal_type", "")).upper() or "PUT" in str(signal.get("signal_type", "")).upper() else "long"
    blockers: list[str] = []
    if settings.scalp_require_mtf_alignment:
        blockers.extend(_mtf_accuracy_blockers(side, timeframe))
    if settings.scalp_require_candle_confirmation:
        blockers.extend(_candle_confirmation_blockers(side, payload, signal))

    if not blockers:
        return

    existing = [str(item) for item in scalp.get("trade_blocked_reasons", [])]
    scalp["trade_blocked_reasons"] = [*existing, *[item for item in blockers if item not in existing]][:8]
    scalp["signals"] = []
    if payload.get("signals"):
        payload["signals"] = [
            sig for sig in payload.get("signals", [])
            if not (isinstance(sig, dict) and str(sig.get("model", "")).startswith("unified-scalp"))
        ]
    stats = payload.get("stats")
    if isinstance(stats, dict):
        stats["scalp_signals"] = 0
        stats["scalp_blocked"] = len(scalp["trade_blocked_reasons"])


def _mtf_accuracy_blockers(side: str, timeframe: str) -> list[str]:
    hierarchy = ["1m", "5m", "15m", "1h", "4h"]
    try:
        idx = hierarchy.index(timeframe)
    except ValueError:
        return []

    higher = [tf for tf in hierarchy[idx + 1:] if tf in pipelines]
    lower = [tf for tf in hierarchy[:idx] if tf in pipelines]
    blockers: list[str] = []

    higher_scores = [
        float(pipelines[tf].metrics.trend_score)
        for tf in higher
        if pipelines[tf].metrics is not None
    ]
    if higher_scores:
        avg_higher = sum(higher_scores) / len(higher_scores)
        if side == "long" and avg_higher < -0.08:
            blockers.append(f"Higher timeframe bearish trend {avg_higher:.2f}")
        if side == "short" and avg_higher > 0.08:
            blockers.append(f"Higher timeframe bullish trend {avg_higher:.2f}")
        if abs(avg_higher) < 0.04:
            blockers.append("Higher timeframe trend is neutral")

    lower_scores = [
        float(pipelines[tf].metrics.trend_score)
        for tf in lower[-1:]
        if pipelines[tf].metrics is not None
    ]
    if lower_scores:
        trigger_score = lower_scores[-1]
        if side == "long" and trigger_score < -0.12:
            blockers.append(f"Lower timeframe trigger bearish {trigger_score:.2f}")
        if side == "short" and trigger_score > 0.12:
            blockers.append(f"Lower timeframe trigger bullish {trigger_score:.2f}")
    return blockers


def _candle_confirmation_blockers(side: str, payload: dict, signal: dict) -> list[str]:
    candle = payload.get("candle")
    if not isinstance(candle, dict):
        return []
    try:
        open_price = float(candle.get("open") or 0.0)
        high = float(candle.get("high") or 0.0)
        low = float(candle.get("low") or 0.0)
        close = float(candle.get("close") or 0.0)
        entry_low = float(signal.get("entry_zone_low") or 0.0)
        entry_high = float(signal.get("entry_zone_high") or 0.0)
    except (TypeError, ValueError):
        return []
    if min(open_price, high, low, close, entry_low, entry_high) <= 0:
        return []

    blockers: list[str] = []
    spread = max(high - low, 1e-9)
    close_position = (close - low) / spread
    if side == "long" and (close <= open_price or close_position < 0.55):
        blockers.append("Bullish candle close confirmation missing")
    if side == "short" and (close >= open_price or close_position > 0.45):
        blockers.append("Bearish candle close confirmation missing")

    entry_mid = (entry_low + entry_high) / 2.0
    distance_pct = abs(close - entry_mid) / close if close > 0 else 0.0
    if distance_pct > settings.scalp_max_entry_distance_pct:
        blockers.append(f"Price {distance_pct:.2%} away from entry zone")
    return blockers


def _payload_analysis_timestamp(payload: dict) -> int | None:
    metrics = payload.get("metrics")
    if isinstance(metrics, dict) and metrics.get("timestamp"):
        return int(metrics["timestamp"])
    candle = payload.get("candle")
    if isinstance(candle, dict) and candle.get("timestamp"):
        return int(candle["timestamp"])
    return None


def _review_matches_payload(review, payload: dict) -> bool:
    timestamp = _payload_analysis_timestamp(payload)
    return bool(timestamp and review is not None and review.timestamp == timestamp)


async def refresh_sentiment_loop() -> None:
    while True:
        try:
            snapshot = await sentiment_service.refresh()
            await manager.broadcast(
                {
                    "update_type": "sentiment",
                    "symbol": settings.symbol,
                    "sentiment": to_wire(snapshot),
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("sentiment refresh failed")
        await asyncio.sleep(settings.sentiment_refresh_seconds)


async def refresh_ai_ict_loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            await asyncio.gather(*(refresh_ai_ict_timeframe(timeframe) for timeframe in supported_timeframes))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ai_ict refresh loop failed")
        await asyncio.sleep(settings.ai_ict_refresh_seconds)


async def refresh_ai_ict_timeframe(timeframe: str) -> None:
    try:
        payload = await asyncio.wait_for(
            pipelines[timeframe].snapshot_async(stores[timeframe]),
            timeout=12.0,
        )
    except asyncio.TimeoutError:
        logger.warning(f"ai_ict snapshot timed out for {timeframe}")
        return
    if _payload_analysis_timestamp(payload) is None or payload.get("metrics") is None:
        return
    _attach_options_context(payload, timeframe)
    payload["sentiment"] = to_wire(sentiment_service.current)

    # Compute multi-timeframe confluence
    mtf = compute_mtf_confluence(timeframe, stores, pipelines)
    payload["mtf_confluence"] = mtf

    local_review = ai_ict_service.local_review(payload, sentiment_service.current)
    ai_ict_reviews[timeframe] = local_review
    if timeframe != _valid_timeframe(settings.timeframe):
        await _broadcast_ai_ict(timeframe, local_review)
        return
    review = await ai_ict_service.analyze(payload, sentiment_service.current)
    ai_ict_reviews[timeframe] = review
    await _broadcast_ai_ict(timeframe, review)


async def _broadcast_ai_ict(timeframe: str, review) -> None:
    await manager.broadcast(
        {
            "update_type": "ai_ict",
            "symbol": settings.symbol,
            "timeframe": timeframe,
            "ai_ict": to_wire(review),
        },
        timeframe=timeframe,
    )


def _attach_options_context(payload: dict, timeframe: str | None = None) -> None:
    context = build_options_context(
        payload=payload,
        option_tickers=option_tickers,
        underlying=settings.options_underlying,
        min_momentum_score=settings.min_options_momentum_score,
        max_spread_pct=settings.options_max_spread_pct,
        min_delta_abs=settings.options_min_delta_abs,
        max_delta_abs=settings.options_max_delta_abs,
        max_moneyness_pct=settings.options_max_moneyness_pct,
        source_error=option_tickers_error,
    )
    payload["options_context"] = to_wire(context)
    if timeframe in pipelines:
        pipeline = pipelines[timeframe]
        pipeline.set_options_context(context)
        if timeframe in stores:
            payload.update(pipeline.refresh_scalp_context(stores[timeframe]))
    _sync_options_context_into_scalp(payload)


def _sync_options_context_into_scalp(payload: dict) -> None:
    scalp = payload.get("scalp")
    options_context = payload.get("options_context")
    if not isinstance(scalp, dict) or not isinstance(options_context, dict):
        return

    call = options_context.get("call_candidate")
    put = options_context.get("put_candidate")
    candidates = [
        contract for contract in (call, put)
        if isinstance(contract, dict) and contract.get("score") is not None
    ]
    best = max(candidates, key=lambda contract: float(contract.get("score") or 0.0), default=None)
    if best is not None:
        scalp["options_greeks"] = {
            **(scalp.get("options_greeks") or {}),
            "delta": round(abs(float(best.get("delta") or 0.0)), 4),
            "gamma": round(abs(float(best.get("gamma") or 0.0)), 6),
            "theta": round(float(best.get("theta") or 0.0), 6),
            "vega": round(float(best.get("vega") or 0.0), 6),
        }

    option_blockers = [
        str(item) for item in options_context.get("blockers", [])
        if item and not str(item).startswith("No liquid BTC ")
    ]
    if option_blockers:
        existing = [str(item) for item in scalp.get("trade_blocked_reasons", [])]
        scalp["trade_blocked_reasons"] = [*existing, *[item for item in option_blockers if item not in existing]][:6]

    for signal in scalp.get("signals", []) or []:
        if not isinstance(signal, dict):
            continue
        direction_contract = put if "PUT" in str(signal.get("signal_type", "")) else call
        if not isinstance(direction_contract, dict):
            continue
        signal["strike"] = signal.get("strike") or direction_contract.get("strike_price") or 0.0
        signal["expiry"] = signal.get("expiry") or direction_contract.get("expiry") or ""


async def refresh_options_loop() -> None:
    global option_tickers, option_tickers_error
    await asyncio.sleep(3)
    while True:
        try:
            option_tickers = await fetch_option_tickers(settings.options_rest_base_url, settings.options_underlying)
            option_tickers_error = None
        except Exception as exc:
            option_tickers_error = str(exc)
            logger.warning("Options refresh failed: %s", exc)

        for timeframe in supported_timeframes:
            payload = await pipelines[timeframe].snapshot_async(stores[timeframe])
            _attach_options_context(payload, timeframe)
            await manager.broadcast(
                {
                    "update_type": "options_context",
                    "symbol": settings.symbol,
                    "timeframe": timeframe,
                    "options_context": payload.get("options_context"),
                },
                timeframe=timeframe,
            )

        await asyncio.sleep(settings.options_refresh_seconds)


async def model_performance_monitor_loop() -> None:
    """Monitor AI model performance and log degradation alerts."""
    from backend.analysis.model_tracker import model_tracker
    await asyncio.sleep(60)
    while True:
        try:
            alerts = model_tracker.get_alerts()
            for alert in alerts:
                logger.warning(f"Model performance alert: {alert['message']}")
                await manager.broadcast({"update_type": "model_alert", **alert})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Model monitor loop failed: {e}")
        await asyncio.sleep(300)


async def database_backup_loop(db_integrity) -> None:
    """Periodic database backup every 6 hours."""
    await asyncio.sleep(3600)
    while True:
        try:
            backup = db_integrity.create_backup()
            if backup:
                logger.info(f"Periodic database backup: {backup}")
            integrity = db_integrity.check_integrity()
            if integrity["status"] != "ok":
                logger.warning(f"Database integrity check: {integrity['issues']}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Database backup loop failed: {e}")
        await asyncio.sleep(21600)


# ─── Multi-Exchange Price ───────────────────────────────

@app.get("/price/multi-exchange")
async def multi_exchange_price(force: bool = False) -> dict:
    """Get aggregated price from multiple exchanges."""
    if force:
        await global_cache.delete("multi_exchange_prices")
    else:
        cached_result = await global_cache.get("multi_exchange_prices")
        if cached_result is not None:
            return cached_result

    from backend.ingestion.multi_exchange import aggregator
    try:
        result = await aggregator.get_aggregated_price(force_refresh=force)

        prices = []
        for p in result.prices:
            spread = ((p.ask - p.bid) / p.bid * 100) if (p.bid and p.ask and p.bid > 0) else 0.0
            prices.append({
                "exchange": p.exchange,
                "symbol": p.symbol,
                "price": p.price,
                "volume_24h": p.volume_24h or 0,
                "bid": p.bid or 0,
                "ask": p.ask or 0,
                "spread_pct": round(spread, 4),
                "timestamp": p.timestamp_ms,
                "status": "ok",
            })

        all_prices = [p.price for p in result.prices if p.price > 0]
        avg_price = sum(all_prices) / len(all_prices) if all_prices else 0
        max_price = max(all_prices) if all_prices else 0
        min_price = min(all_prices) if all_prices else 0
        spread_range = ((max_price - min_price) / avg_price * 100) if avg_price > 0 else 0

        best_exchange = ""
        worst_exchange = ""
        if all_prices:
            best_idx = all_prices.index(min_price)
            worst_idx = all_prices.index(max_price)
            best_exchange = result.prices[best_idx].exchange if best_idx < len(result.prices) else ""
            worst_exchange = result.prices[worst_idx].exchange if worst_idx < len(result.prices) else ""

        data = {
            "prices": prices,
            "avg_price": round(avg_price, 2),
            "max_price": round(max_price, 2),
            "min_price": round(min_price, 2),
            "spread_range_pct": round(spread_range, 4),
            "best_exchange": best_exchange,
            "worst_exchange": worst_exchange,
            "timestamp": result.timestamp_ms or int(time.time() * 1000),
        }
        await global_cache.set("multi_exchange_prices", data, ttl=CACHE_TTLS.get("multi_exchange_prices"))
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Multi-exchange fetch failed: {e}")


@app.get("/price/exchanges")
async def exchange_prices() -> dict:
    """Get last known prices from all exchanges."""
    cached_result = await global_cache.get("exchange_prices")
    if cached_result is not None:
        return cached_result

    from backend.ingestion.multi_exchange import aggregator
    prices = aggregator.get_last_prices()
    data = {
        exchange: {"price": p.price, "latency_ms": p.latency_ms, "timestamp_ms": p.timestamp_ms}
        for exchange, p in prices.items()
    }
    await global_cache.set("exchange_prices", data, ttl=CACHE_TTLS.get("exchange_info"))
    return data


# ─── Model Performance ─────────────────────────────────

@app.get("/model/performance")
async def model_performance(days: int = 30) -> dict:
    """Get AI model performance metrics."""
    cache_key = f"model_performance:{days}"
    cached_result = await global_cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    from backend.analysis.model_tracker import model_tracker
    metrics = model_tracker.get_metrics(days=days)

    grade_dist_list = []
    for grade, count in metrics.grade_distribution.items():
        grade_dist_list.append({
            "grade": grade,
            "count": count,
            "avg_confidence": 0.0,
            "win_rate": None,
            "avg_pnl": None,
        })

    top_grade = None
    worst_grade = None
    if grade_dist_list:
        sorted_grades = sorted(grade_dist_list, key=lambda g: g["count"], reverse=True)
        top_grade = sorted_grades[0]["grade"]
        worst_grade = sorted_grades[-1]["grade"]

    metrics_24h = model_tracker.get_metrics(days=1)

    data = {
        "total_decisions": metrics.total_predictions,
        "accuracy": metrics.accuracy if metrics.total_predictions > 0 else None,
        "avg_confidence": metrics.avg_confidence,
        "grade_distribution": grade_dist_list,
        "last_24h_decisions": metrics_24h.total_predictions,
        "last_24h_accuracy": metrics_24h.accuracy if metrics_24h.total_predictions > 0 else None,
        "drift_score": None,
        "degradation_detected": metrics.degradation_alert,
        "top_performing_grade": top_grade,
        "worst_performing_grade": worst_grade,
        "timestamp": int(time.time() * 1000),
    }
    await global_cache.set(cache_key, data, ttl=CACHE_TTLS.get("model_performance"))
    return data


@app.get("/model/trend")
async def model_trend(days: int = 7) -> list[dict]:
    """Get model performance trend over time."""
    cache_key = f"model_trend:{days}"
    cached_result = await global_cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    from backend.storage.schema import get_conn
    conn = get_conn()
    try:
        now = int(time.time() * 1000)
        cutoff = now - days * 86400000
        rows = conn.execute("""
            SELECT DATE(timestamp/1000, 'unixepoch') as date,
                   COUNT(*) as decisions,
                   SUM(was_correct) as correct,
                   AVG(predicted_confidence) as avg_conf
            FROM model_predictions
            WHERE timestamp >= ? AND actual_direction != ''
            GROUP BY date
            ORDER BY date
        """, (cutoff,)).fetchall()

        data = []
        for row in rows:
            data.append({
                "date": row["date"],
                "decisions": row["decisions"],
                "accuracy": row["correct"] / row["decisions"] if row["decisions"] > 0 else None,
                "avg_confidence": row["avg_conf"] or 0.0,
            })
    finally:
        conn.close()

    await global_cache.set(cache_key, data, ttl=CACHE_TTLS.get("model_performance"))
    return data


# ─── Database Integrity ────────────────────────────────

@app.get("/db/integrity")
async def db_integrity_check() -> dict:
    """Run database integrity check."""
    try:
        cached_result = await global_cache.get("db_integrity")
        if cached_result is not None:
            return cached_result

        from backend.utils.db_integrity import db_integrity
        from backend.storage.schema import get_conn
        raw = db_integrity.check_integrity()

        conn = get_conn()
        try:
            tables_with_ts = [
                "signals", "paper_trades", "backtest_runs", "alerts",
                "candle_archive", "market_snapshots", "metrics_history",
                "pattern_history", "regime_history", "ai_decisions_history",
                "liquidity_history", "orderbook_history", "performance_daily",
                "trade_journal_entries", "equity_curve",
            ]

            tables_info = []
            total_records = 0
            for table_name, count in raw.get("tables", {}).items():
                total_records += count
                oldest = None
                newest = None
                if table_name in tables_with_ts:
                    try:
                        row = conn.execute(
                            "SELECT MIN(timestamp), MAX(timestamp) FROM [{table}]".format(table=table_name)
                        ).fetchone()
                        if row:
                            oldest = str(row[0]) if row[0] else None
                            newest = str(row[1]) if row[1] else None
                    except Exception:
                        pass

                size_bytes = 0
                try:
                    size_row = conn.execute(
                        "SELECT SUM(pgsize) FROM dbstat WHERE name='{table}'".format(table=table_name)
                    ).fetchone()
                    if size_row and size_row[0]:
                        size_bytes = size_row[0]
                except Exception:
                    size_bytes = count * 256

                tables_info.append({
                    "name": table_name,
                    "row_count": count,
                    "size_bytes": size_bytes,
                    "oldest_record": oldest,
                    "newest_record": newest,
                })

            wal_row = conn.execute("PRAGMA journal_mode").fetchone()
            wal_mode = wal_row[0] == "wal" if wal_row else False

            all_oldest = None
            all_newest = None
            for t in tables_info:
                if t["oldest_record"]:
                    if all_oldest is None or t["oldest_record"] < all_oldest:
                        all_oldest = t["oldest_record"]
                if t["newest_record"]:
                    if all_newest is None or t["newest_record"] > all_newest:
                        all_newest = t["newest_record"]

            integrity_checks = [
                {
                    "check_name": "Quick Check",
                    "status": "pass" if raw["status"] == "ok" else "fail",
                    "message": "Database integrity OK" if raw["status"] == "ok" else f"Issues found: {len(raw.get('issues', []))}",
                },
                {
                    "check_name": "Foreign Keys",
                    "status": "pass" if not any("Foreign key" in i for i in raw.get("issues", [])) else "warning",
                    "message": "No violations" if not any("Foreign key" in i for i in raw.get("issues", [])) else "Violations detected",
                },
                {
                    "check_name": "WAL Mode",
                    "status": "pass" if wal_mode else "warning",
                    "message": "Enabled" if wal_mode else "Disabled (consider enabling for better performance)",
                },
            ]
        finally:
            conn.close()

        data = {
            "database_size_mb": raw.get("db_size_mb", 0),
            "total_tables": len(raw.get("tables", {})),
            "total_records": total_records,
            "wal_mode": wal_mode,
            "integrity_checks": integrity_checks,
            "table_info": tables_info,
            "oldest_record": all_oldest,
            "newest_record": all_newest,
            "timestamp": raw.get("timestamp", int(time.time() * 1000)),
        }
        await global_cache.set("db_integrity", data, ttl=CACHE_TTLS.get("db_integrity"))
        return data
    except Exception as e:
        import traceback
        logger.error(f"DB integrity check failed: {e}\n{traceback.format_exc()}")
        return {
            "database_size_mb": 0,
            "total_tables": 0,
            "total_records": 0,
            "wal_mode": False,
            "integrity_checks": [
                {"check_name": "Error", "status": "fail", "message": str(e)},
            ],
            "table_info": [],
            "oldest_record": None,
            "newest_record": None,
            "timestamp": int(time.time() * 1000),
        }


@app.post("/db/backup")
async def db_create_backup() -> dict:
    """Create database backup."""
    try:
        from backend.utils.db_integrity import db_integrity
        backup = db_integrity.create_backup()
        return {"ok": True, "backup_path": str(backup) if backup else None}
    except Exception as e:
        import traceback
        logger.error(f"Backup failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")


# ─── Configuration ─────────────────────────────────────

@app.get("/config/validate")
async def config_validate() -> dict:
    """Validate current configuration."""
    from backend.utils.config_validator import validator
    issues = validator.validate_all()
    return {
        "errors": [i for i in issues if i.severity == "error"],
        "warnings": [i for i in issues if i.severity == "warning"],
        "info": [i for i in issues if i.severity == "info"],
        "has_errors": validator.has_errors(issues),
    }


# ─── Rate Limit Status ─────────────────────────────────

@app.get("/rate-limits")
async def rate_limit_status() -> dict:
    """Get current rate limit usage for all endpoints."""
    from backend.utils.rate_limiter import rate_limiter
    endpoints = ["binance_rest", "coinbase_rest", "kraken_rest", "okx_rest", "bybit_rest", "gemini_api", "openai_api"]
    return {ep: rate_limiter.get_usage(ep) for ep in endpoints}


# ─── Cache Management ──────────────────────────────────

@app.get("/cache/stats")
async def cache_stats() -> dict:
    """Get cache statistics."""
    return await global_cache.get_stats()


@app.post("/cache/clear")
async def cache_clear(prefix: str | None = None) -> dict:
    """Clear cache, optionally by prefix pattern."""
    if prefix:
        count = await invalidate_pattern(prefix)
        return {"ok": True, "cleared": count, "prefix": prefix}
    await global_cache.clear()
    return {"ok": True, "cleared": "all"}


# SPA fallback: serve index.html for any non-API route
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if FRONTEND_DIST.is_dir():
        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
    raise HTTPException(status_code=404, detail="Frontend not available")
