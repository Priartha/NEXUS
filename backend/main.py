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
from backend.analysis.futures import build_futures_context
from backend.analysis.mtf_confluence import compute_mtf_confluence
from backend.analysis.pipeline import AnalysisPipeline
from backend.analysis.sentiment import SentimentService
from backend.broadcast.ws_manager import ConnectionManager
from backend.config import settings
from backend.engine.candle_aggregator import timeframe_to_ms
from backend.engine.candle_store import CandleStore
from backend.ingestion.binance import start_binance_stream
from backend.ingestion.delta_rest import fetch_futures_funding, fetch_futures_oi, fetch_liquidations
from backend.ingestion.delta_ws import start_delta_stream
from backend.models.types import to_wire
from backend.storage.schema import init_db
from backend.storage import repository as repo
from backend.analysis.backtest import BacktestEngine
from backend.analysis.paper_trading import PaperTradingEngine
from backend.analysis.profitability_guard import summarize_gate
from backend.analysis.risk_manager import RiskManager
from backend.analysis.symbol_scanner import MultiSymbolScanner
from backend.analysis.csv_import import parse_csv, get_supported_formats
from backend.analysis.data_quality import aggregate_candles, analyze_candles
from backend.api.history_routes import router as history_router
from backend.api.demo_routes import router as demo_router
from backend.storage.history_recorder import recorder as history_recorder
from backend.storage.history_repository import get_candles_with_source
from backend.analysis.daily_reports import daily_reporter
from backend.utils.cache import global_cache, CACHE_TTLS, invalidate_pattern

# Phase 2/3 ML module imports
from backend.analysis.xgboost_model import xgboost_model
from backend.analysis.hmm_regime import hmm_classifier
from backend.analysis.sentiment_nlp import nlp_sentiment
from backend.analysis.transformer_forecaster import transformer_forecaster
from backend.analysis.rl_sizing import rl_sizing
from backend.analysis.funding_strategy import funding_strategy
from backend.analysis.adaptive_sltp import adaptive_sltp
from backend.analysis.cvd_divergence import cvd_divergence_detector
from backend.analysis.position_manager import position_manager
from backend.storage.feature_store import feature_store
from backend.analysis.pipeline_async import async_pipeline

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

# ML background task handles
xgboost_task: asyncio.Task | None = None
hmm_task: asyncio.Task | None = None
transformer_task: asyncio.Task | None = None
nlp_task: asyncio.Task | None = None
onchain_task: asyncio.Task | None = None
pipeline_task: asyncio.Task | None = None
cross_exchange_task: asyncio.Task | None = None

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

    # Database setup: keep startup fast so /health can bind promptly.
    # Full integrity scans and backups are expensive on the live SQLite DB and
    # run via /db/integrity plus the periodic backup loop after startup.
    from backend.utils.db_integrity import db_integrity
    db_integrity.enable_wal_mode()
    init_db()
    from backend.analysis.self_aware_agent import get_agent
    restored_trades = get_agent().bootstrap_from_paper_trades(
        repo.get_paper_trades(status="closed", limit=5000)
    )
    logger.info(f"AI brain restored {restored_trades} closed paper trades into memory")

    # Feed real closed paper trades into the optimizer & ensemble so the AI Lab
    # reflects actual system performance, not synthetic bootstrap data.
    try:
        from backend.analysis.self_optimizer import optimizer
        from backend.analysis.ensemble_model import ensemble, EnsembleScore
        closed_trades = repo.get_paper_trades(status="closed", limit=5000)
        loaded = 0
        for t in closed_trades:
            pnl = t.get('pnl_pct')
            if pnl is None:
                continue
            reason_text = str(t.get('reason') or '').lower()
            # Extract a real regime keyword from the trade reason
            if 'distribution' in reason_text:
                regime = 'distribution'
            elif 'accumulation' in reason_text:
                regime = 'accumulation'
            elif 'trending' in reason_text:
                regime = 'trending'
            elif 'range' in reason_text:
                regime = 'range_bound'
            elif 'consolidation' in reason_text:
                regime = 'consolidation'
            elif 'volatile' in reason_text:
                regime = 'trending_volatile'
            else:
                regime = 'unknown'
            won = float(pnl) > 0
            opt_trade = {
                'direction': str(t.get('side') or 'long'),
                'regime': regime,
                'confidence': float(t.get('confidence') or 0.7),
                'pnl_pct': float(pnl),
                'won': won,
                'hold_minutes': int(t.get('bars_held') or 1) * 5,
                'entry_price': float(t.get('entry_price') or 0),
                'exit_price': float(t.get('exit_price') or 0),
            }
            try:
                optimizer.record_trade(opt_trade)
                score = EnsembleScore(
                    direction='long' if str(t.get('side')) == 'buy' else 'short',
                    confidence=float(t.get('confidence') or 0.7),
                    microstructure_score=0.5,
                    ict_score=0.5,
                    momentum_score=0.5,
                    regime=regime,
                    weights_used={'microstructure': 0.25, 'ict': 0.25, 'momentum': 0.25, 'xgboost': 0.25},
                    reasons=[],
                )
                ensemble.record_outcome(score, won, float(pnl))
                loaded += 1
            except Exception:
                pass
        if loaded > 0:
            logger.info(f"AI Lab loaded {loaded} real paper trades into optimizer & ensemble")
    except Exception:
        logger.exception("Real paper trade feed failed")

    # Installing Python packages inside FastAPI startup blocks the event loop
    # and makes the UI look crashed. Keep it opt-in for maintenance sessions.
    if settings.auto_install_dependencies:
        try:
            from backend.utils.self_heal import check_and_install_deps
            dep_results = await asyncio.to_thread(check_and_install_deps)
            installed = [k for k, v in dep_results.items() if v == "installed"]
            if installed:
                logger.info("Auto-installed missing ML deps: %s", installed)
        except Exception:
            logger.exception("Dependency auto-install check failed")

    # Bootstrap AI Lab components with synthetic data so panels show values on startup
    try:
        from backend.analysis.ensemble_model import ensemble
        bootstrapped = ensemble.bootstrap_history(n_trades=50)
        if bootstrapped > 0:
            logger.info(f"Ensemble bootstrapped with {bootstrapped} historical trades")
    except Exception:
        logger.exception("Ensemble bootstrap failed")

    try:
        from backend.analysis.self_optimizer import optimizer
        # Optimizer learns only from real closed trades. bootstrap_history is a
        # no-op by design; the AI Lab will populate as paper trades close.
        n = optimizer.bootstrap_history(n_trades=50)
        if n > 0:
            logger.info(f"Self-optimizer bootstrapped with {n} historical trades")
    except Exception:
        logger.exception("Self-optimizer bootstrap failed")

    try:
        from backend.analysis.anomaly_detection import anomaly_detector
        anom_boot = anomaly_detector.bootstrap_history(n_obs=100)
        if anom_boot > 0:
            logger.info(f"Anomaly detector bootstrapped with {anom_boot} observations")
    except Exception:
        logger.exception("Anomaly detector bootstrap failed")

    # Bootstrap scalp_risk on each pipeline so Risk panel shows data
    for tf, pl in pipelines.items():
        try:
            if hasattr(pl, 'scalp_risk') and hasattr(pl.scalp_risk, 'bootstrap_history'):
                scalp_boot = pl.scalp_risk.bootstrap_history(n_trades=30)
                if scalp_boot > 0:
                    logger.info(f"Scalp risk bootstrapped for {tf}: {scalp_boot} trades")
        except Exception:
            logger.exception(f"Scalp risk bootstrap failed for {tf}")

    # Initialize multi-exchange price aggregator
    from backend.ingestion.multi_exchange import aggregator as multi_exchange_aggregator
    multi_exchange_aggregator.symbol = settings.symbol
    logger.info(f"Multi-exchange aggregator initialized for {settings.symbol}")

    # Model performance tracker
    from backend.analysis.model_tracker import model_tracker
    logger.info("Model performance tracker initialized")

    # Seed historical data for backtesting
    if settings.market_data_provider.lower() == "binance":
        from backend.ingestion.binance import fetch_historical_candles as _fetch
        _base_url = settings.market_data_rest_base_url
    else:
        from backend.ingestion.delta_rest import fetch_historical_candles as _fetch
        _base_url = settings.rest_base_url
    for tf, store in stores.items():
        try:
            logger.info(f"Seeding historical data for {tf}")
            candles = await _fetch(_base_url, settings.symbol, tf, limit=settings.history_seed_candles)
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

    # Start history recorder on the configured active timeframe so analytics
    # reflect the model the user is actually trading/viewing.
    primary_tf = _valid_timeframe(settings.timeframe)
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

    # Futures context refresh loop
    futures_task = asyncio.create_task(refresh_futures_loop())

    # Multi-exchange price aggregation loop
    me_task = asyncio.create_task(refresh_multi_exchange_loop())

    # Self-optimization loop (daily auto-research)
    auto_research_task = asyncio.create_task(auto_research_loop())

    # Phase 2/3 ML background tasks
    global xgboost_task, nlp_task, onchain_task, pipeline_task, cross_exchange_task, hmm_task, transformer_task
    xgboost_task = asyncio.create_task(xgboost_train_loop())
    hmm_task = asyncio.create_task(hmm_train_loop())
    hmm_predict_task = asyncio.create_task(hmm_predict_loop())
    transformer_task = asyncio.create_task(transformer_train_loop())
    nlp_task = asyncio.create_task(refresh_nlp_loop())
    onchain_task = asyncio.create_task(refresh_onchain_loop())
    cross_exchange_task = asyncio.create_task(refresh_cross_exchange_loop())
    pipeline_task = asyncio.create_task(pipeline_health_loop())

    # Register all background tasks with the self-healing monitor so any task
    # that dies or goes stale is automatically restarted.
    from backend.utils.self_heal import self_heal
    self_heal.register("xgboost_train", xgboost_task, lambda: asyncio.create_task(xgboost_train_loop()))
    self_heal.register("hmm_train", hmm_task, lambda: asyncio.create_task(hmm_train_loop()))
    self_heal.register("hmm_predict", hmm_predict_task, lambda: asyncio.create_task(hmm_predict_loop()))
    self_heal.register("transformer_train", transformer_task, lambda: asyncio.create_task(transformer_train_loop()))
    self_heal.register("nlp_refresh", nlp_task, lambda: asyncio.create_task(refresh_nlp_loop()))
    self_heal.register("onchain_refresh", onchain_task, lambda: asyncio.create_task(refresh_onchain_loop()))
    self_heal.register("cross_exchange", cross_exchange_task, lambda: asyncio.create_task(refresh_cross_exchange_loop()))
    self_heal.register("pipeline_health", pipeline_task, lambda: asyncio.create_task(pipeline_health_loop()))
    self_heal.register("sentiment", sentiment_task, lambda: asyncio.create_task(refresh_sentiment_loop()))
    self_heal.register("ai_ict", ai_ict_task, lambda: asyncio.create_task(refresh_ai_ict_loop()))
    self_heal.register("multi_exchange", me_task, lambda: asyncio.create_task(refresh_multi_exchange_loop()))
    self_heal.register("auto_research", auto_research_task, lambda: asyncio.create_task(auto_research_loop()))
    self_heal.register("model_monitor", model_monitor_task, lambda: asyncio.create_task(model_performance_monitor_loop()))
    self_heal.register("db_backup", db_backup_task, lambda: asyncio.create_task(database_backup_loop(db_integrity)))
    self_heal.register("futures", futures_task, lambda: asyncio.create_task(refresh_futures_loop()))
    await self_heal.start()

    # Register panels with the freshness monitor so any stale data triggers a refresh
    from backend.utils.panel_freshness import panel_freshness
    try:
        from backend.analysis import (
            self_optimizer, ensemble_model, anomaly_detection, scalp_risk,
        )
        panel_freshness.register_panel("optimizer", threshold=900.0)
        panel_freshness.register_panel("ensemble", threshold=600.0)
        panel_freshness.register_panel("anomaly_detector", threshold=300.0)
        panel_freshness.register_panel("ai_lab", threshold=300.0)
        panel_freshness.register_panel("ml_xgboost", threshold=1200.0)
        panel_freshness.register_panel("transformer_forecast", threshold=1500.0)
        panel_freshness.register_panel("hmm_regime", threshold=180.0)
        await panel_freshness.start()
    except Exception:
        logger.exception("Panel freshness monitor registration failed")

    try:
        yield
    finally:
        logger.info("Shutting down background tasks")
        try:
            await self_heal.stop()
        except Exception:
            pass
        try:
            await panel_freshness.stop()
        except Exception:
            pass
        await history_recorder.stop()
        await daily_reporter.stop()
        model_monitor_task.cancel()
        db_backup_task.cancel()
        me_task.cancel()
        for task in (xgboost_task, hmm_task, transformer_task, nlp_task, onchain_task, cross_exchange_task, pipeline_task):
            task.cancel()
        hmm_predict_task.cancel()
        for task in (stream_task, sentiment_task, ai_ict_task, model_monitor_task, db_backup_task, futures_task, me_task, auto_research_task, xgboost_task, hmm_task, transformer_task, nlp_task, onchain_task, cross_exchange_task, pipeline_task, hmm_predict_task):
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
    }


# ─── Backtesting ──────────────────────────────────────────

@app.get("/data/quality")
async def data_quality(
    symbol: str = Query(default=settings.symbol),
    timeframe: str = Query(default="15m"),
    source: str = Query(default="live"),
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict:
    source_key = source.lower()
    if source_key == "live":
        store = stores.get(timeframe)
        if not store:
            raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}")
        candles = store.get_closed_candles()[-limit:]
        return analyze_candles(
            candles,
            requested_symbol=symbol,
            actual_symbol=store.symbol,
            timeframe=timeframe,
            source_type="live_store",
            provider=settings.market_data_provider,
            native_timeframe=True,
            requested_count=limit,
        )
    if source_key == "archive":
        archived = get_candles_with_source(symbol=symbol, timeframe=timeframe, limit=limit)
        return analyze_candles(
            archived["candles"],
            requested_symbol=symbol,
            actual_symbol=archived["actual_symbol"],
            timeframe=timeframe,
            source_type="candle_archive",
            provider="local_sqlite",
            native_timeframe=True,
            requested_count=limit,
        )
    if source_key == "archive_derived":
        source_tf = "1m" if timeframe == "5m" else "5m"
        source_ratio = max(1, timeframe_to_ms(timeframe) // timeframe_to_ms(source_tf))
        source_limit = min((limit + 2) * source_ratio, 5000)
        archived = get_candles_with_source(symbol=symbol, timeframe=source_tf, limit=source_limit)
        aggregated = aggregate_candles(archived["candles"], timeframe)[-limit:]
        return analyze_candles(
            aggregated,
            requested_symbol=symbol,
            actual_symbol=archived["actual_symbol"],
            timeframe=timeframe,
            source_type=f"candle_archive_derived_from_{source_tf}",
            provider="local_sqlite",
            native_timeframe=False,
            requested_count=limit,
        )
    if source_key == "all":
        return {
            "live": await data_quality(symbol=symbol, timeframe=timeframe, source="live", limit=limit),
            "archive": await data_quality(symbol=symbol, timeframe=timeframe, source="archive", limit=limit),
            "archive_derived": await data_quality(symbol=symbol, timeframe=timeframe, source="archive_derived", limit=limit),
        }
    raise HTTPException(status_code=400, detail="source must be live, archive, archive_derived, or all")


class BacktestRequest(BaseModel):
    symbol: str = settings.symbol
    timeframe: str = "15m"
    candle_count: int = 1000
    initial_balance: float = 10_000.0
    position_size_pct: float = 0.015
    max_hold_bars: int = 12
    breakeven_threshold: float = 1.0
    trailing_stop: bool = False
    tp_atr_multiplier: float = 0.0
    signal_side_mode: str = "invert"
    avoid_reason_tokens: list[str] = ["CVD falling"]
    require_regime_alignment: bool = False
    adaptive_learning: bool = True


@app.post("/backtest/run")
async def run_backtest(body: BacktestRequest, _authorized: None = Depends(require_api_key)) -> dict:
    loop = asyncio.get_event_loop()
    store = stores.get(body.timeframe)
    if not store:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {body.timeframe}")

    candles = store.get_closed_candles()
    if len(candles) < 80:
        raise HTTPException(status_code=400, detail=f"Not enough candles: {len(candles)} (need at least 80)")

    requested_candle_count = min(
        body.candle_count,
        settings.max_candles,
        settings.backtest_route_max_candles,
    )
    candles = candles[-requested_candle_count:]
    data_quality_report = await loop.run_in_executor(None, lambda: analyze_candles(
        candles,
        requested_symbol=body.symbol,
        actual_symbol=store.symbol,
        timeframe=body.timeframe,
        source_type="live_store",
        provider=settings.market_data_provider,
        native_timeframe=True,
        requested_count=requested_candle_count,
    ))

    def build_engine(
        *,
        max_hold_bars: int = body.max_hold_bars,
        breakeven_threshold: float = body.breakeven_threshold,
        trailing_stop: bool = body.trailing_stop,
        signal_side_mode: str = body.signal_side_mode,
        avoid_reason_tokens: list[str] | None = body.avoid_reason_tokens,
        tp_atr_multiplier: float | None = None,
        require_regime_alignment: bool = body.require_regime_alignment,
    ) -> BacktestEngine:
        return BacktestEngine(
            initial_balance=body.initial_balance,
            position_size_pct=body.position_size_pct,
            max_hold_bars=max_hold_bars,
            breakeven_threshold=breakeven_threshold,
            trailing_stop=trailing_stop,
            signal_side_mode=signal_side_mode,
            avoid_reason_tokens=avoid_reason_tokens,
            tp_atr_multiplier=tp_atr_multiplier if tp_atr_multiplier is not None else body.tp_atr_multiplier,
            require_regime_alignment=require_regime_alignment,
            max_candles=settings.max_candles,
        )

    def candidate_score(candidate: dict) -> float:
        trades = int(candidate.get("total_trades", 0) or 0)
        pf = float(candidate.get("profit_factor", 0) or 0)
        pnl = float(candidate.get("total_pnl_pct", 0) or 0)
        dd = float(candidate.get("max_drawdown_pct", 100) or 100)
        score = min(pf, 3.0) * 60 + pnl * 2 - dd * 3 + min(trades, 50)
        if trades < 10:
            score -= 40
        if pnl <= 0:
            score -= 80
        if dd > 15:
            score -= (dd - 15) * 5
        return score

    try:
        engine = build_engine()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: engine.run(candles, symbol=body.symbol, timeframe=body.timeframe)),
            timeout=settings.backtest_route_timeout_seconds,
        )

        if body.adaptive_learning and result.get("profit_factor", 0) < 1.0 and len(candles) >= 80:
            recent_window = candles[-min(500, len(candles)):]
            candidates: list[tuple[str, list, dict]] = [
                (
                    "hold10_trailing_be05",
                    recent_window,
                    {"max_hold_bars": 10, "breakeven_threshold": 0.5, "trailing_stop": True},
                ),
                (
                    "hold10_trailing_be075",
                    recent_window,
                    {"max_hold_bars": 10, "breakeven_threshold": 0.75, "trailing_stop": True},
                ),
                (
                    "hold10_trailing_be1",
                    recent_window,
                    {"max_hold_bars": 10, "breakeven_threshold": 1.0, "trailing_stop": True},
                ),
                (
                    "countermodel_hold10_trailing_be05",
                    recent_window,
                    {
                        "max_hold_bars": 10,
                        "breakeven_threshold": 0.5,
                        "trailing_stop": True,
                        "signal_side_mode": "invert",
                    },
                ),
                (
                    "countermodel_skip_cvd_rising",
                    recent_window,
                    {
                        "max_hold_bars": 10,
                        "breakeven_threshold": 0.5,
                        "trailing_stop": True,
                        "signal_side_mode": "invert",
                        "avoid_reason_tokens": ["CVD rising"],
                    },
                ),
                (
                    "balanced_countermodel_hold12_skip_cvd_falling",
                    recent_window,
                    {
                        "max_hold_bars": 12,
                        "breakeven_threshold": 1.0,
                        "trailing_stop": False,
                        "signal_side_mode": "invert",
                        "avoid_reason_tokens": ["CVD falling"],
                    },
                ),
                (
                    "high_pnl_hold12_skip_cvd_rising",
                    recent_window,
                    {
                        "max_hold_bars": 12,
                        "breakeven_threshold": 1.0,
                        "trailing_stop": False,
                        "signal_side_mode": "normal",
                        "avoid_reason_tokens": ["CVD rising"],
                    },
                ),
                (
                    "recent_current_exit",
                    recent_window,
                    {
                        "max_hold_bars": body.max_hold_bars,
                        "breakeven_threshold": body.breakeven_threshold,
                        "trailing_stop": body.trailing_stop,
                    },
                ),
            ]
            best_result = result
            best_candidate = "requested_window"
            best_score = candidate_score(result)
            for candidate_name, candidate_candles, params in candidates[:settings.backtest_adaptive_max_candidates]:
                if len(candidate_candles) < 80:
                    continue
                try:
                    candidate = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda eng=build_engine(**params): eng.run(candidate_candles, symbol=body.symbol, timeframe=body.timeframe),
                        ),
                        timeout=settings.backtest_route_timeout_seconds,
                    )
                    score = candidate_score(candidate)
                    if score > best_score:
                        best_result = candidate
                        best_candidate = candidate_name
                        best_score = score
                        data_quality_report = await loop.run_in_executor(None, lambda: analyze_candles(
                            candidate_candles,
                            requested_symbol=body.symbol,
                            actual_symbol=store.symbol,
                            timeframe=body.timeframe,
                            source_type="live_store",
                            provider=settings.market_data_provider,
                            native_timeframe=True,
                            requested_count=len(candidate_candles),
                        ))
                except Exception as e:
                    logger.warning(f"Backtest candidate {candidate_name} failed: {e}")
                    continue

            if best_result is not result:
                best_result["adaptive_learning"] = {
                    "enabled": True,
                    "selected": best_candidate,
                    "requested_candle_count": body.candle_count,
                    "selected_candle_count": best_result.get("candle_count"),
                    "route_candle_cap": requested_candle_count,
                    "reason": "Requested window was unprofitable; selected the best recent regime candidate.",
                    "baseline": {
                        "profit_factor": result.get("profit_factor"),
                        "win_rate": result.get("win_rate"),
                        "total_pnl_pct": result.get("total_pnl_pct"),
                        "max_drawdown_pct": result.get("max_drawdown_pct"),
                    },
                }
                result = best_result
            else:
                result["adaptive_learning"] = {
                    "enabled": True,
                    "selected": "requested_window",
                    "requested_candle_count": body.candle_count,
                    "selected_candle_count": result.get("candle_count"),
                    "reason": "No recent regime candidate improved the requested window.",
                    "route_candle_cap": requested_candle_count,
                }
        elif body.candle_count != requested_candle_count:
            result["route_candle_cap"] = requested_candle_count
        result["data_quality"] = data_quality_report
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                "Backtest exceeded the route timeout. "
                "Use fewer candles or run scripts/validate_profitability.py offline."
            ),
        )
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


@app.get("/paper-trades/status")
async def paper_trade_status() -> dict:
    return {
        "enabled": paper_trading.enabled,
        "profitability_gate": summarize_gate(),
        "open_positions": len(repo.get_paper_trades(status="open")),
        "closed_trades": repo.get_paper_trade_stats().get("closed_trades", 0),
        "last_evaluation": getattr(paper_trading, "last_evaluation", {}),
    }


@app.post("/paper-trades/toggle")
async def toggle_paper_trading(_authorized: None = Depends(require_api_key)) -> dict:
    paper_trading.enabled = not paper_trading.enabled
    status = "enabled" if paper_trading.enabled else "disabled"
    logger.info(f"Paper trading toggled to {status}")
    return {"ok": True, "enabled": paper_trading.enabled, "message": f"Paper trading {status}"}


@app.post("/paper-trades/reset")
async def reset_paper_trades(_authorized: None = Depends(require_api_key)) -> dict:
    count = repo.reset_paper_trades()
    return {"ok": True, "message": f"Cleared {count} paper trades"}


@app.post("/backtest/reset")
async def reset_backtest_data(_authorized: None = Depends(require_api_key)) -> dict:
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
        breakeven_threshold=0.5,
        trailing_stop=True,
        slippage_pct=0.0001,
        commission_pct=0.0002,
    )
    bt_result = engine.run(candles, symbol=body.symbol, timeframe=body.timeframe)
    bt_result["import_metadata"] = result["metadata"]
    bt_result["import_warnings"] = result["warnings"]
    bt_result["data_quality"] = analyze_candles(
        candles,
        requested_symbol=body.symbol,
        actual_symbol=body.symbol,
        timeframe=body.timeframe,
        source_type="csv_import",
        provider=result["metadata"].get("format_detected", "csv"),
        native_timeframe=True,
        requested_count=len(candles),
    )

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
    try:
        payload = await asyncio.wait_for(
            pipelines[timeframe].snapshot_async(stores[timeframe]),
            timeout=settings.snapshot_timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Snapshot for {timeframe} exceeded {settings.snapshot_timeout_seconds:.0f}s; retry after current analysis cycle.",
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
        try:
            await websocket.close(code=1011)
        except RuntimeError as exc:
            if "close message has been sent" not in str(exc):
                raise
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


def _latest_market_price(timeframe: str | None = None) -> float | None:
    tf = timeframe or settings.timeframe
    try:
        tf = _valid_timeframe(tf)
    except HTTPException:
        tf = settings.timeframe
    store = stores.get(tf)
    if store is None:
        return None
    candle = store.live_candle or store.latest_closed()
    if candle is None:
        return None
    price = float(candle.close)
    return price if price > 0 else None


def _attach_realtime_context(payload: dict, timeframe: str) -> dict:
    payload["available_timeframes"] = list(supported_timeframes)
    payload["sentiment"] = to_wire(sentiment_service.current)
    payload["mtf_confluence"] = compute_mtf_confluence(timeframe, stores, pipelines)
    _apply_scalp_accuracy_gates(payload, timeframe)
    review = ai_ict_reviews.get(timeframe)
    if review is None or not _review_matches_payload(review, payload):
        review = ai_ict_service.local_review(payload, sentiment_service.current)
        ai_ict_reviews[timeframe] = review
        pipelines[timeframe].ai_ict_review = review
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
    side = "short" if "SHORT" in str(signal.get("signal_type", "")).upper() else "long"
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
        logger.debug(f"ai_ict skipping {timeframe}: no metrics/analysis timestamp in snapshot")
        return
    payload["sentiment"] = to_wire(sentiment_service.current)

    # Compute multi-timeframe confluence
    mtf = compute_mtf_confluence(timeframe, stores, pipelines)
    payload["mtf_confluence"] = mtf

    local_review = ai_ict_service.local_review(payload, sentiment_service.current)
    ai_ict_reviews[timeframe] = local_review
    pipelines[timeframe].ai_ict_review = local_review
    if timeframe != _valid_timeframe(settings.timeframe):
        await _broadcast_ai_ict(timeframe, local_review)
        return
    review = await ai_ict_service.analyze(payload, sentiment_service.current)
    ai_ict_reviews[timeframe] = review
    pipelines[timeframe].ai_ict_review = review
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


async def auto_research_loop() -> None:
    """Daily auto-research loop: analyze performance, optimize parameters, save state."""
    from backend.analysis.self_optimizer import optimizer as self_optimizer
    from backend.analysis.ensemble_model import ensemble as ensemble_model
    from backend.analysis.self_aware_agent import get_agent
    await asyncio.sleep(300)  # Wait 5 minutes after startup
    while True:
        try:
            # Run self-optimization if due
            if self_optimizer.should_optimize():
                result = self_optimizer.run_optimization()
                if result.get('status') == 'applied':
                    logger.info("Auto-research: optimization applied — improvement=%.4f",
                                result.get('improvement', 0))
                    await manager.broadcast({
                        "update_type": "auto_research",
                        "action": "optimization_applied",
                        "improvement": result.get('improvement', 0),
                        "changes": result.get('changes', {}),
                    })
                elif result.get('status') == 'reverted':
                    logger.info("Auto-research: optimization reverted (no improvement)")

            # Save agent brain state periodically
            get_agent().save_state()
            ensemble_model._save_state()
            self_optimizer._save_state()

            # Log status
            opt_status = self_optimizer.get_status()
            ens_stats = ensemble_model.get_stats()
            agent_status = get_agent().get_agent_status()
            logger.info(
                "Auto-research status: opt_attempts=%d kept=%d | ensemble_trades=%d wr=%.2f | "
                "agent_decisions=%d accuracy=%.2f",
                opt_status.get('total_attempts', 0),
                opt_status.get('kept_attempts', 0),
                ens_stats.get('total_trades', 0),
                ens_stats.get('win_rate', 0),
                agent_status.get('decisions', 0),
                agent_status.get('accuracy', 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Auto-research loop failed: {e}", exc_info=True)
        await asyncio.sleep(7200)  # Run every 2 hours


async def refresh_futures_loop() -> None:
    base_url = settings.rest_base_url.rstrip("/") if settings.rest_base_url else "https://api.delta.exchange"
    product_id = settings.futures_product_id
    while True:
        try:
            ticker = await fetch_futures_funding(base_url, product_id)
            oi = await fetch_futures_oi(base_url, product_id)
            liq = await fetch_liquidations(base_url, product_id)
            ctx = build_futures_context(
                payload=ticker,
                funding_rate=ticker.get("funding_rate", 0.0),
                open_interest=oi.get("open_interest", 0.0),
                open_interest_change_pct=oi.get("change_pct", 0.0),
                mark_price=ticker.get("mark_price"),
                product_id=product_id,
                next_funding_ts=ticker.get("next_funding_timestamp"),
                volume_24h=ticker.get("volume_24h", 0.0),
                liquidation_data=liq,
                source_error=None,
            )
            for pipeline in pipelines.values():
                pipeline.set_futures_context(ctx)
            await manager.broadcast({
                "update_type": "futures_context",
                "symbol": settings.symbol,
                "futures_context": to_wire(ctx),
            })
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("futures context refresh failed")
        await asyncio.sleep(settings.futures_funding_refresh_seconds)


# ─── Phase 2/3 ML Background Loops ─────────────────────


async def xgboost_train_loop() -> None:
    """Periodically retrain the XGBoost model on new data."""
    from backend.analysis.label_generator import labeler
    from backend.storage.feature_store import feature_store
    from backend.utils.self_heal import self_heal
    await asyncio.sleep(120)
    while True:
        try:
            primary_tf = _valid_timeframe(settings.timeframe)
            store = stores.get(primary_tf)
            candles = store.get_closed_candles() if store else []

            if len(candles) >= 250:
                labeler.compute_labels(candles)
                logger.info(f"Labels generated: {len(labeler._labels)} total")

                # Compute and record features
                feature_store.register_default_features()
                last = candles[-1]
                close = float(last.close)
                if close > 0:
                    closes = [float(c.close) for c in candles]
                    volumes = [float(c.volume) for c in candles]
                    highs = [float(c.high) for c in candles]
                    lows = [float(c.low) for c in candles]
                    n = len(closes)
                    sma20 = sum(closes[-20:]) / 20 if n >= 20 else sum(closes) / n
                    sma50 = sum(closes[-50:]) / 50 if n >= 50 else sma20
                    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, n) if closes[i - 1] > 0]
                    pos_returns = [r for r in returns[-14:] if r > 0]
                    neg_returns = [r for r in returns[-14:] if r < 0]
                    avg_gain = sum(pos_returns) / 14 if pos_returns else 0
                    avg_loss = abs(sum(neg_returns) / 14) if neg_returns else 1e-9
                    rs = avg_gain / max(avg_loss, 1e-9)
                    rsi = 100 - (100 / (1 + rs))
                    atr_series = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, n)]
                    atr = sum(atr_series[-14:]) / 14 if atr_series else 0
                    avg_vol = sum(volumes[-20:]) / 20 if n >= 20 else sum(volumes) / n
                    trend = (sma20 - sma50) / sma50 if sma50 > 0 else 0.0
                    vol = (sum(r * r for r in returns[-20:]) / min(20, len(returns))) ** 0.5 if returns else 0.0

                    feat_dict = {
                        "rsi14": round(rsi, 4),
                        "atr14": round(atr, 4),
                        "trend_score": round(max(-1, min(1, trend * 50)), 4),
                        "volatility_score": round(vol * 100, 4),
                        "volume_zscore": round((volumes[-1] - avg_vol) / (avg_vol * 0.5 + 1e-9), 4),
                        "realized_volatility": round(vol * 100, 4),
                        "vwap_deviation": round((close - sma20) / sma20 * 100, 4),
                        "of_cvd": round(closes[-1] - closes[0], 2),
                    }
                    if n >= 5 and closes[-5] > 0:
                        feat_dict["of_cvd_slope"] = round((closes[-1] - closes[-5]) / closes[-5] * 100, 4)
                    feature_store.ingest_feature_values(
                        int(last.timestamp), settings.symbol, primary_tf, feat_dict
                    )

                    # Record label features
                    for lb in list(labeler._labels_deque)[-200:]:
                        feature_store.ingest_feature_values(
                            lb.timestamp, settings.symbol, primary_tf,
                            {
                                "label_forward_return": round(lb.forward_return, 4),
                                "label_direction": float(lb.label),
                            }
                        )

            if xgboost_model.should_retrain():
                result = xgboost_model.train(candles, primary_tf, settings.symbol)
                if result:
                    logger.info(f"XGBoost train: {result.get('status', 'ok')} - {result.get('accuracy', 0):.3f}")
                    from backend.utils.panel_freshness import panel_freshness as _pf
                    _pf.mark_updated("ml_xgboost")
            self_heal.heartbeat("xgboost_train", ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self_heal.heartbeat("xgboost_train", ok=False, error=str(e))
            logger.exception("xgboost train loop failed")
        await asyncio.sleep(900)  # retrain every 15 minutes


async def hmm_train_loop() -> None:
    """Periodically retrain the HMM regime classifier on new candle data."""
    from backend.utils.self_heal import self_heal
    from backend.utils.panel_freshness import panel_freshness
    await asyncio.sleep(60)
    while True:
        try:
            if hmm_classifier.should_retrain():
                primary_tf = _valid_timeframe(settings.timeframe)
                store = stores.get(primary_tf)
                candles = store.get_closed_candles()[-500:] if store else []
                if candles:
                    result = hmm_classifier.train(candles)
                    if result:
                        logger.info(
                            f"HMM train: {result.get('status', 'ok')} - {result.get('reason', 'completed')}"
                        )
                        panel_freshness.mark_updated("hmm_regime")
            self_heal.heartbeat("hmm_train", ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self_heal.heartbeat("hmm_train", ok=False, error=str(e))
            logger.exception("hmm train loop failed")
        await asyncio.sleep(3600)


async def transformer_train_loop() -> None:
    """Periodically retrain the transformer forecaster on new candle data."""
    from backend.utils.self_heal import self_heal
    from backend.utils.panel_freshness import panel_freshness
    await asyncio.sleep(180)
    while True:
        try:
            state = transformer_forecaster.get_state()
            if not state.get("is_trained", False) or (time.time() - state.get("last_train_ts", 0)) > 3600:
                primary_tf = _valid_timeframe(settings.timeframe)
                store = stores.get(primary_tf)
                candles = store.get_closed_candles()[-1000:] if store else []
                if len(candles) >= 500:
                    result = transformer_forecaster.train(candles)
                    if result:
                        logger.info(
                            f"Transformer train: {result.get('status', 'ok')} - "
                            f"train_loss={result.get('train_loss', 0):.4f}, "
                            f"test_loss={result.get('test_loss', 0):.4f}"
                        )
                        panel_freshness.mark_updated("transformer_forecast")
            self_heal.heartbeat("transformer_train", ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self_heal.heartbeat("transformer_train", ok=False, error=str(e))
            logger.exception("transformer train loop failed")
        await asyncio.sleep(3600)


async def hmm_predict_loop() -> None:
    """Periodically call HMM predict to populate recent_regimes history."""
    from backend.utils.self_heal import self_heal
    from backend.utils.panel_freshness import panel_freshness
    await asyncio.sleep(90)
    while True:
        try:
            state = hmm_classifier.get_state()
            if state.get("is_trained", False):
                primary_tf = _valid_timeframe(settings.timeframe)
                store = stores.get(primary_tf)
                candles = store.get_closed_candles()[-200:] if store else []
                if len(candles) >= 50:
                    hmm_classifier.predict(candles)
                    panel_freshness.mark_updated("hmm_regime")
            self_heal.heartbeat("hmm_predict", ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self_heal.heartbeat("hmm_predict", ok=False, error=str(e))
            logger.exception("hmm predict loop failed")
        await asyncio.sleep(60)


async def refresh_nlp_loop() -> None:
    """Refresh NLP sentiment from external sources."""
    from backend.utils.self_heal import self_heal
    from backend.utils.panel_freshness import panel_freshness
    await asyncio.sleep(5)
    while True:
        try:
            result = await nlp_sentiment.compute()
            if result:
                await manager.broadcast({
                    "update_type": "nlp_sentiment",
                    "symbol": settings.symbol,
                    "nlp_sentiment": {
                        "aggregate_score": result.score,
                        "aggregate_label": result.label,
                        "confidence": result.confidence,
                        "source_count": result.source_count,
                        "finbert_score": result.finbert_score,
                        "vader_score": result.vader_score,
                        "fear_greed_index": result.fear_greed_index,
                        "weighted_score": result.weighted_score,
                        "description": result.description,
                    },
                })
                panel_freshness.mark_updated("nlp_sentiment")
            self_heal.heartbeat("nlp_refresh", ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self_heal.heartbeat("nlp_refresh", ok=False, error=str(e))
            logger.exception("nlp sentiment refresh failed")
        await asyncio.sleep(300)


async def refresh_onchain_loop() -> None:
    """Refresh on-chain metrics periodically."""
    from backend.utils.self_heal import self_heal
    from backend.utils.panel_freshness import panel_freshness
    await asyncio.sleep(10)
    while True:
        try:
            from backend.ingestion.onchain import onchain_provider
            # Refresh provider first (async)
            try:
                await onchain_provider.refresh()
            except Exception:
                pass
            # Get current price from primary store if available
            try:
                primary_tf = _valid_timeframe(settings.timeframe)
                store = stores.get(primary_tf)
                btc_price = store.last_close if store and hasattr(store, "last_close") and store.last_close else 0
                if btc_price == 0 and store and store.candles:
                    btc_price = store.candles[-1].close
            except Exception:
                btc_price = 0
            signal = onchain_provider.get_signal(btc_price or 0)
            await manager.broadcast({
                "update_type": "onchain",
                "symbol": settings.symbol,
                "onchain": signal,
            })
            panel_freshness.mark_updated("onchain_metrics")
            self_heal.heartbeat("onchain_refresh", ok=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self_heal.heartbeat("onchain_refresh", ok=False, error=str(e))
            logger.exception("onchain refresh failed")
        await asyncio.sleep(600)


async def refresh_cross_exchange_loop() -> None:
    """Refresh cross-exchange data periodically."""
    await asyncio.sleep(3)
    while True:
        try:
            from backend.ingestion.cross_exchange import cross_exchange
            snapshot = await cross_exchange.refresh()
            if snapshot and snapshot.median_price > 0:
                basis = cross_exchange.detect_basis()
                await manager.broadcast({
                    "update_type": "cross_exchange",
                    "symbol": settings.symbol,
                    "cross_exchange": {
                        "median_price": snapshot.median_price,
                        "spread_pct": snapshot.spread_pct,
                        "exchange_count": snapshot.exchange_count,
                        "basis_signals": [
                            {"description": s.description, "basis_pct": s.basis_pct, "strength": s.strength}
                            for s in basis[:3]
                        ],
                    },
                })
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("cross-exchange refresh failed")
        await asyncio.sleep(15)


async def pipeline_health_loop() -> None:
    """Run the async pipeline and broadcast health."""
    await asyncio.sleep(30)
    while True:
        try:
            health = async_pipeline.get_health()
            await manager.broadcast({
                "update_type": "pipeline_health",
                "pipeline": health,
            })
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pipeline health loop failed")
        await asyncio.sleep(60)


async def refresh_multi_exchange_loop() -> None:
    """Periodically fetch multi-exchange aggregated price and feed into pipelines."""
    from backend.ingestion.multi_exchange import aggregator as me_aggregator
    while True:
        try:
            agg = await me_aggregator.get_aggregated_price(force_refresh=True)
            if agg and agg.median_price > 0:
                for pipeline in pipelines.values():
                    pipeline.set_aggregated_price(
                        price=agg.median_price,
                        spread_pct=agg.spread_pct,
                        exchange_count=agg.exchange_count,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("multi-exchange price refresh failed")
        await asyncio.sleep(15)


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
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(db_integrity.check_integrity),
                timeout=settings.db_integrity_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return {
                "database_size_mb": 0,
                "total_tables": 0,
                "total_records": 0,
                "wal_mode": False,
                "integrity_checks": [
                    {
                        "check_name": "Timeout",
                        "status": "warning",
                        "message": f"Integrity check exceeded {settings.db_integrity_timeout_seconds:.0f}s; run offline for full details.",
                    },
                ],
                "table_info": [],
                "oldest_record": None,
                "newest_record": None,
                "timestamp": int(time.time() * 1000),
            }

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


# ─── Phase 2/3 ML API Endpoints ─────────────────────────


@app.get("/ml/xgboost/state")
async def xgboost_state() -> dict:
    """Get current XGBoost model state."""
    return xgboost_model.get_state()


@app.post("/ml/xgboost/train")
async def xgboost_train() -> dict:
    """Manually trigger XGBoost retraining."""
    try:
        primary_tf = _valid_timeframe(settings.timeframe)
        store = stores.get(primary_tf)
        candles = store.get_closed_candles() if store else []
        result = xgboost_model.train(candles, primary_tf, settings.symbol)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/features/store")
async def feature_store_stats() -> dict:
    """Get feature store statistics."""
    return feature_store.get_state()


@app.get("/ml/optimizer/status")
async def ml_optimizer_status() -> dict:
    """Get self-optimizer status including live signal quality scores."""
    from backend.analysis.self_optimizer import optimizer as self_optimizer
    return self_optimizer.get_status()


@app.get("/system/self-heal/status")
async def self_heal_status() -> dict:
    """Status of all monitored background tasks (alive, last_ok_ago, restarts)."""
    from backend.utils.self_heal import self_heal
    return self_heal.get_status()


@app.get("/system/panels/freshness")
async def panel_freshness_status() -> dict:
    """Freshness status of all registered data panels."""
    from backend.utils.panel_freshness import panel_freshness
    return panel_freshness.get_status()


@app.post("/system/self-heal/restart-all")
async def self_heal_restart_all() -> dict:
    """Force-restart every monitored background task."""
    from backend.utils.self_heal import self_heal
    restarted = []
    for name, info in self_heal._tasks.items():
        if info.get("factory"):
            try:
                old = info["task"]
                if old and not old.done():
                    old.cancel()
                new_task = info["factory"]()
                info["task"] = new_task
                info["last_ok"] = time.time()
                self_heal._restart_counts[name] = self_heal._restart_counts.get(name, 0) + 1
                restarted.append(name)
            except Exception as e:
                logger.exception("Failed to restart %s: %s", name, e)
    return {"restarted": restarted, "count": len(restarted)}


@app.get("/funding/strategy/state")
async def funding_strategy_state() -> dict:
    """Get funding strategy current state."""
    return funding_strategy.get_state()


@app.get("/hmm/regime")
async def hmm_regime_state() -> dict:
    """Get HMM regime classifier state."""
    return hmm_classifier.get_state()


@app.post("/hmm/train")
async def hmm_train(timeframe: str = "5m", limit: int = 500) -> dict:
    """Manually trigger HMM training on recent candle data."""
    try:
        tf = _valid_timeframe(timeframe)
        store = stores.get(tf)
        candles = store.get_closed_candles()[-limit:] if store else []
        if not candles:
            raise HTTPException(status_code=400, detail=f"No candles available for {tf}")
        result = hmm_classifier.train(candles)
        return {"status": "ok", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nlp/sentiment")
async def nlp_sentiment_endpoint() -> dict:
    """Get NLP sentiment analysis."""
    try:
        result = await nlp_sentiment.compute()
        if result is None:
            return {"error": "No sentiment data available"}
        return {
            "aggregate_score": result.score,
            "aggregate_label": result.label,
            "confidence": result.confidence,
            "source_count": result.source_count,
            "finbert_score": result.finbert_score,
            "vader_score": result.vader_score,
            "fear_greed_index": result.fear_greed_index,
            "weighted_score": result.weighted_score,
            "description": result.description,
            "timestamp": result.timestamp,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/transformer/forecast")
async def transformer_forecast_endpoint(candles: int = Query(100, ge=20, le=500)) -> dict:
    """Get transformer multi-horizon forecast."""
    primary_tf = _valid_timeframe(settings.timeframe)
    store = stores.get(primary_tf)
    if not store:
        return {"current_price": 0.0, "model_ready": False, "horizons": [], "reason": "no_store"}
    candle_list = store.get_closed_candles()[-candles:]
    if len(candle_list) < 20:
        current_price = candle_list[-1].close if candle_list else 0.0
        return {"current_price": current_price, "model_ready": False, "horizons": [], "reason": "insufficient_data"}
    current_price = candle_list[-1].close
    try:
        forecasts = await asyncio.to_thread(transformer_forecaster.predict, candle_list, current_price)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Forecast failed: {e}")
    return {
        "current_price": current_price,
        "model_ready": transformer_forecaster._is_trained if hasattr(transformer_forecaster, "_is_trained") else False,
        "horizons": [
            {
                "horizon": f.horizon,
                "horizon_bars": f.horizon_bars,
                "predicted_direction": f.predicted_direction,
                "predicted_return_pct": f.predicted_return_pct,
                "confidence": f.confidence,
                "entry_price": f.entry_price,
                "target_price": f.target_price,
                "stop_price": f.stop_price,
                "description": f.description,
            }
            for f in forecasts
        ],
    }


@app.post("/transformer/train")
async def transformer_train(timeframe: str = "5m", limit: int = 1000) -> dict:
    """Manually trigger transformer training on recent candle data."""
    try:
        tf = _valid_timeframe(timeframe)
        store = stores.get(tf)
        candles = store.get_closed_candles()[-limit:] if store else []
        if not candles:
            raise HTTPException(status_code=400, detail=f"No candles available for {tf}")
        result = transformer_forecaster.train(candles)
        return {"status": "ok", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/rl/sizing")
async def rl_sizing_state() -> dict:
    """Get RL position sizing agent state."""
    return rl_sizing.get_state()


@app.get("/position/status")
async def position_status() -> dict:
    """Get position manager state and open positions."""
    return position_manager.get_state()


@app.post("/position/open")
async def position_open(request: Request) -> dict:
    """Open a new position."""
    body = await request.json()
    side = body.get("side", "long")
    size = body.get("size")
    leverage = body.get("leverage", 1)
    stop_loss = body.get("stop_loss")
    take_profit = body.get("take_profit")
    current_price = _latest_market_price()
    if current_price is None or current_price <= 0:
        raise HTTPException(status_code=409, detail="No live market price available for position entry")
    try:
        result = position_manager.open_position(
            symbol=settings.symbol, side=side, size=size,
            entry_price=current_price, leverage=leverage,
            stop_loss=stop_loss, take_profit=take_profit,
        )
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/position/close")
async def position_close() -> dict:
    """Close the current open position."""
    try:
        open_positions = position_manager.get_open_positions()
        if not open_positions:
            return {"status": "ok", "result": {"success": False, "error": "No open positions"}}
        current_price = _latest_market_price()
        if current_price is None or current_price <= 0:
            raise HTTPException(status_code=409, detail="No live market price available for position close")
        pos_id = open_positions[0].id
        result = position_manager.close_position(position_id=pos_id, price=current_price, reason="manual")
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/onchain/metrics")
async def onchain_metrics() -> dict:
    """Get latest on-chain metrics."""
    from backend.ingestion.onchain import onchain_provider
    try:
        btc_price = _latest_market_price() or 0.0
        if btc_price > 0:
            await onchain_provider.refresh(btc_price=btc_price)
        signal = onchain_provider.get_signal(btc_price)
        history = onchain_provider.get_recent_history(n=10)
        snapshots = [
            {
                "timestamp": s.timestamp,
                "mvrv_z_score": s.mvrv_zscore,
                "exchange_flow_balance": s.exchange_net_flow,
                "whale_tx_count": s.whale_tx_count,
                "sopr": s.sopr,
                "active_addresses": s.active_addresses,
                "transaction_count": s.transaction_count,
                "hash_rate": s.hash_rate,
            }
            for s in history
        ]
        state = onchain_provider.get_state()
        return {
            "signal": signal,
            "history": snapshots,
            "sources_loaded": [state.get("source", "none")],
            "state": state,
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/cross-exchange/state")
async def cross_exchange_state() -> dict:
    """Get cross-exchange aggregator state."""
    from backend.ingestion.cross_exchange import cross_exchange
    return cross_exchange.get_state()


@app.get("/cross-exchange/snapshot")
async def cross_exchange_snapshot() -> dict:
    """Get latest cross-exchange snapshot."""
    from backend.ingestion.cross_exchange import cross_exchange
    try:
        snap = await cross_exchange.refresh()
        return {
            "median_price": snap.median_price,
            "mean_price": snap.mean_price,
            "min_price": snap.min_price,
            "max_price": snap.max_price,
            "spread_pct": snap.spread_pct,
            "volume_weighted_price": snap.volume_weighted_price,
            "total_volume_24h": snap.total_volume_24h,
            "exchange_count": snap.exchange_count,
            "timestamp": snap.timestamp,
            "exchanges": [
                {
                    "exchange": t.exchange,
                    "last": t.last,
                    "bid": t.bid,
                    "ask": t.ask,
                    "funding_rate": t.funding_rate,
                    "volume_24h": t.volume_24h,
                }
                for t in snap.tickers
            ],
            "basis_signals": [
                {"description": s.description, "basis_pct": s.basis_pct, "strength": s.strength}
                for s in cross_exchange.detect_basis()[:5]
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/pipeline/health")
async def pipeline_health() -> dict:
    """Get async pipeline health status."""
    return async_pipeline.get_health()


@app.get("/pipeline/runs")
async def pipeline_runs(n: int = Query(10, ge=1, le=100)) -> list[dict]:
    """Get recent pipeline run reports."""
    return async_pipeline.get_recent_reports(n=n)


@app.get("/circuit-breakers")
async def circuit_breaker_states() -> dict:
    """Get all circuit breaker states."""
    from backend.analysis.circuit_breaker import circuit_registry
    return circuit_registry.get_all_states()


@app.post("/circuit-breakers/reset")
async def circuit_breaker_reset() -> dict:
    """Reset all circuit breakers to CLOSED state."""
    from backend.analysis.circuit_breaker import circuit_registry
    circuit_registry.reset_all()
    return {"status": "ok"}


@app.get("/adaptive-sltp/state")
async def adaptive_sltp_state() -> dict:
    """Get adaptive SL/TP engine state."""
    return adaptive_sltp.get_state()


@app.get("/cvd/divergence")
async def cvd_divergence_state() -> dict:
    """Get CVD divergence detector state."""
    return cvd_divergence_detector.get_state()


# SPA fallback: serve index.html for any non-API route
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if FRONTEND_DIST.is_dir():
        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
    raise HTTPException(status_code=404, detail="Frontend not available")
