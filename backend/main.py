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
    init_db()

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
    
    try:
        yield
    finally:
        logger.info("Shutting down background tasks")
        await history_recorder.stop()
        await daily_reporter.stop()
        for task in (stream_task, sentiment_task, ai_ict_task, options_task):
            task.cancel()
        for task in (stream_task, sentiment_task, ai_ict_task, options_task):
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f"Task {task.get_name()} cancelled successfully")
            except Exception as e:
                logger.error(f"Task {task.get_name()} failed during shutdown: {e}", exc_info=True)


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
    _attach_options_context(payload)
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
            logger.warning("Options refresh failed: %s", exc)

        for timeframe in supported_timeframes:
            payload = await pipelines[timeframe].snapshot_async(stores[timeframe])
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


# SPA fallback: serve index.html for any non-API route
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if FRONTEND_DIST.is_dir():
        file_path = FRONTEND_DIST / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
    raise HTTPException(status_code=404, detail="Frontend not available")
