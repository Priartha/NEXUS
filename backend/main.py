from __future__ import annotations

import asyncio
import logging
import logging.config
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dataclasses import dataclass
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.analysis.ai_ict import AiIctService
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
from backend.analysis.market_structure import detect_structure
from backend.analysis.paper_trading import PaperTradingEngine
from backend.analysis.volume_profile import compute_volume_profile

paper_trading = PaperTradingEngine()

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
            "filename": str(logs_dir / "ict-terminal.log"),
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

pipelines = {
    timeframe: AnalysisPipeline(
        paper_trading=paper_trading,
        on_alert=_pipeline_alert_handler,
    )
    for timeframe in supported_timeframes
}
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
    init_db()
    if settings.market_data_provider.lower() == "binance":
        stream_task = asyncio.create_task(start_binance_stream(manager, stores, pipelines, settings))
    else:
        stream_task = asyncio.create_task(start_delta_stream(manager, stores, pipelines, settings))
    sentiment_task = asyncio.create_task(refresh_sentiment_loop())
    ai_ict_task = asyncio.create_task(refresh_ai_ict_loop())
    options_task = asyncio.create_task(refresh_options_loop())
    try:
        yield
    finally:
        logger.info("Shutting down background tasks")
        for task in (stream_task, sentiment_task, ai_ict_task, options_task):
            task.cancel()
        for task in (stream_task, sentiment_task, ai_ict_task, options_task):
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"Task {task.get_name()} cancelled successfully")
            except Exception as e:
                logger.error(f"Task {task.get_name()} failed during shutdown: {e}", exc_info=True)


app = FastAPI(title="ICT Terminal", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "x-api-key"],
    max_age=3600,
)

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
    logger.error(f"[{request_id}] Unhandled exception: {exc}", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message=str(exc) if settings.log_level == "DEBUG" else "Internal server error",
            timestamp=int(time.time() * 1000),
            request_id=request_id,
        ).dict()
    )


@app.get("/")
async def root() -> dict:
    return {
        "name": "ICT Terminal",
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

@dataclass
class BacktestRequest:
    symbol: str = "BTC/USDT"
    timeframe: str = "5m"
    candle_count: int = 500
    initial_balance: float = 10_000.0
    position_size_pct: float = 0.02


@app.post("/backtest/run")
async def run_backtest(body: BacktestRequest) -> dict:
    engine = BacktestEngine(
        initial_balance=body.initial_balance,
        position_size_pct=body.position_size_pct,
    )
    store = stores[body.timeframe]
    candles = store.get_closed_candles()[-body.candle_count:]
    utcnow = int(time.time() * 1000)
    result = engine.run(candles, symbol=body.symbol, timeframe=body.timeframe)
    repo.save_backtest_run(result)
    repo.save_backtest_trades(result["id"], result["trades"])
    pts = [{"timestamp": e["timestamp"], "account_balance": e["account_balance"],
            "drawdown": e["drawdown"], "drawdown_pct": e["drawdown_pct"],
            "source": "backtest", "run_id": result["id"]} for e in result["equity_curve"]]
    repo.save_equity_points(pts)
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


# ─── Volume Profile ───────────────────────────────────────

@app.get("/volume-profile")
async def volume_profile(tf: str = Query(default=settings.timeframe),
                         candles: int = Query(default=100, le=500)) -> dict:
    tf = _valid_timeframe(tf)
    store = stores[tf]
    cs = store.get_chart_candles()[-candles:]
    return compute_volume_profile(cs)


# ─── MTF Confluence ─────────────────────────────────────

@app.get("/mtf-confluence")
async def mtf_confluence() -> dict:
    result: dict[str, dict] = {}
    for tf in supported_timeframes:
        store = stores[tf]
        pipe = pipelines[tf]
        candles = store.get_chart_candles()
        closed = store.get_closed_candles()
        pipe.run(store, force_full=False)
        sw = to_wire(pipe.swings[-40:])
        ml = to_wire(pipe.metrics)
        reg = to_wire(pipe.regime)
        result[tf] = {
            "candles": to_wire(candles[-40:]),
            "fvgs": to_wire([f for f in pipe.fvgs if not f.is_filled][-10:]),
            "order_blocks": to_wire([b for b in pipe.order_blocks if not b.is_breaker][-10:]),
            "liquidity": to_wire([l for l in pipe.liquidity if not l.swept][-10:]),
            "structure": to_wire(detect_structure(pipe.swings, closed)[-20:]),
            "swings": sw,
            "metrics": ml,
            "regime": reg,
            "current_price": candles[-1].close if candles else None,
        }
    return result


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


# ─── Trade Journal ────────────────────────────────────────

@app.get("/journal")
async def get_journal(trade_id: str | None = None) -> list[dict]:
    return repo.get_journal_entries(trade_id=trade_id)


@app.get("/snapshot")
@limiter.limit("30/minute")
async def snapshot(
    request: Request,
    tf: str = Query(default=settings.timeframe),
    _authorized: None = Depends(require_api_key),
) -> dict:
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}. Supported: {list(supported_timeframes)}")
    timeframe = tf
    payload = pipelines[timeframe].snapshot(stores[timeframe])
    return _attach_realtime_context(payload, timeframe)


@app.get("/sentiment")
async def sentiment(request: Request, _authorized: None = Depends(require_api_key)) -> dict:
    return to_wire(sentiment_service.current)


@app.get("/ai-ict")
async def ai_ict(
    request: Request,
    tf: str = Query(default=settings.timeframe),
    _authorized: None = Depends(require_api_key),
) -> dict:
    if tf not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {tf}. Supported: {list(supported_timeframes)}")
    timeframe = tf
    payload = pipelines[timeframe].snapshot(stores[timeframe])
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
        payload = pipelines[timeframe].snapshot(stores[timeframe])
        payload = _attach_realtime_context(payload, timeframe)
        await websocket.send_json(payload)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for timeframe {timeframe}")
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error for timeframe {timeframe}: {e}", exc_info=True)
        await manager.disconnect(websocket)


def _valid_timeframe(timeframe: str) -> str:
    if timeframe not in supported_timeframes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported timeframe: {timeframe}. Supported: {list(supported_timeframes)}")
    return timeframe


def _attach_realtime_context(payload: dict, timeframe: str) -> dict:
    payload["available_timeframes"] = list(supported_timeframes)
    payload["sentiment"] = to_wire(sentiment_service.current)
    _attach_options_context(payload)
    review = ai_ict_reviews.get(timeframe)
    if review is None or not _review_matches_payload(review, payload):
        review = ai_ict_service.local_review(payload, sentiment_service.current)
        ai_ict_reviews[timeframe] = review
    payload["ai_ict"] = to_wire(review)
    return payload


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
    payload = pipelines[timeframe].snapshot(stores[timeframe])
    if _payload_analysis_timestamp(payload) is None or payload.get("metrics") is None:
        return
    _attach_options_context(payload)
    payload["sentiment"] = to_wire(sentiment_service.current)
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


def _attach_options_context(payload: dict) -> None:
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


async def refresh_options_loop() -> None:
    global option_tickers, option_tickers_error
    await asyncio.sleep(3)
    while True:
        try:
            option_tickers = await fetch_option_tickers(settings.options_rest_base_url, settings.options_underlying)
            option_tickers_error = None
        except Exception as exc:
            option_tickers_error = str(exc)
            logger.exception("options refresh failed")

        for timeframe in supported_timeframes:
            payload = pipelines[timeframe].snapshot(stores[timeframe])
            _attach_options_context(payload)
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
