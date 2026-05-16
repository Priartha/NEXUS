from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from backend.storage.history_repository import (
    save_market_snapshot,
    save_pattern,
    save_regime,
    save_metrics,
    save_candles,
    save_ai_decision,
    save_liquidity_event,
    save_orderbook_snapshot,
    save_daily_performance,
    cleanup_old_data,
)

logger = logging.getLogger(__name__)


class HistoryRecorder:
    """Background service that periodically snapshots pipeline state into the DB."""

    def __init__(
        self,
        snapshot_interval: int = 60,
        candle_sync_interval: int = 300,
        cleanup_interval: int = 86400,
    ):
        self.snapshot_interval = snapshot_interval
        self.candle_sync_interval = candle_sync_interval
        self.cleanup_interval = cleanup_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_snapshot = 0
        self._last_candle_sync = 0
        self._last_cleanup = 0

    async def start(self, pipeline: Any) -> None:
        """Start the background recorder."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(pipeline))
        logger.info("HistoryRecorder started")

    async def stop(self) -> None:
        """Stop the background recorder."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("HistoryRecorder stopped")

    async def _run_loop(self, pipeline: Any) -> None:
        """Main recording loop."""
        while self._running:
            try:
                now = time.time()

                # Snapshot pipeline state
                if now - self._last_snapshot >= self.snapshot_interval:
                    await self._record_snapshot(pipeline)
                    self._last_snapshot = now

                # Sync candles
                if now - self._last_candle_sync >= self.candle_sync_interval:
                    await self._sync_candles(pipeline)
                    self._last_candle_sync = now

                # Run cleanup
                if now - self._last_cleanup >= self.cleanup_interval:
                    self._run_cleanup()
                    self._last_cleanup = now

                await asyncio.sleep(5)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"HistoryRecorder error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def _record_snapshot(self, pipeline: Any) -> None:
        """Record current pipeline state to history tables."""
        try:
            state = pipeline.get_state()
            if not state:
                return

            now_ms = int(time.time() * 1000)

            # Market snapshot
            snapshot = {
                "timestamp": now_ms,
                "symbol": state.get("symbol", "BTCUSDT"),
                "timeframe": state.get("timeframe", "5m"),
                "price": state.get("price", 0),
                "change_pct": state.get("change_pct", 0),
                "regime_phase": state.get("regime", {}).get("phase"),
                "regime_bias": state.get("regime", {}).get("bias"),
                "regime_confidence": state.get("regime", {}).get("confidence"),
                "ai_direction": state.get("ai_decision", {}).get("direction"),
                "ai_grade": state.get("ai_decision", {}).get("grade"),
                "ai_confidence": state.get("ai_decision", {}).get("confidence"),
                "pattern_count": len(state.get("patterns", [])),
                "bullish_patterns": sum(
                    1 for p in state.get("patterns", []) if p.get("direction") == "bullish"
                ),
                "bearish_patterns": sum(
                    1 for p in state.get("patterns", []) if p.get("direction") == "bearish"
                ),
                "active_fvgs": len(state.get("fvgs", [])),
                "active_order_blocks": len(state.get("order_blocks", [])),
                "active_liquidity_levels": len(state.get("liquidity", [])),
                "sentiment_label": state.get("sentiment", {}).get("label"),
                "sentiment_score": state.get("sentiment", {}).get("score"),
                "rsi14": state.get("metrics", {}).get("rsi14"),
                "atr14": state.get("metrics", {}).get("atr14"),
                "vwap": state.get("metrics", {}).get("vwap"),
                "trend_score": state.get("metrics", {}).get("trend_score"),
                "volume_zscore": state.get("metrics", {}).get("volume_zscore"),
                "candle_count": state.get("candle_count", 0),
                "session": state.get("session"),
                "halving_phase": state.get("halving_phase"),
                "volatility_regime": state.get("volatility_regime"),
                "raw_data": state,
            }
            save_market_snapshot(snapshot)

            # Regime
            regime = state.get("regime", {})
            if regime.get("phase"):
                regime["timestamp"] = now_ms
                save_regime(regime)

            # Metrics
            metrics = state.get("metrics", {})
            if metrics:
                metrics["timestamp"] = now_ms
                metrics["symbol"] = state.get("symbol", "BTCUSDT")
                metrics["timeframe"] = state.get("timeframe", "5m")
                metrics["price"] = state.get("price")
                save_metrics(metrics)

            # Patterns
            for pattern in state.get("patterns", []):
                pattern["timestamp"] = now_ms
                pattern["symbol"] = state.get("symbol", "BTCUSDT")
                pattern["timeframe"] = state.get("timeframe", "5m")
                pattern["session"] = state.get("session")
                pattern["regime_phase"] = regime.get("phase")
                save_pattern(pattern)

            # AI Decision
            ai = state.get("ai_decision", {})
            if ai and ai.get("grade") and ai.get("grade") != "NO_TRADE":
                ai["timestamp"] = now_ms
                ai["symbol"] = state.get("symbol", "BTCUSDT")
                ai["timeframe"] = state.get("timeframe", "5m")
                save_ai_decision(ai)

            # Liquidity events
            for event in state.get("liquidity_events", []):
                event["timestamp"] = now_ms
                event["symbol"] = state.get("symbol", "BTCUSDT")
                event["timeframe"] = state.get("timeframe", "5m")
                save_liquidity_event(event)

            # Orderbook snapshot
            ob = state.get("orderbook", {})
            if ob:
                ob["timestamp"] = now_ms
                ob["symbol"] = state.get("symbol", "BTCUSDT")
                save_orderbook_snapshot(ob)

            logger.debug(f"Snapshot recorded at {now_ms}")

        except Exception as e:
            logger.error(f"Failed to record snapshot: {e}", exc_info=True)

    async def _sync_candles(self, pipeline: Any) -> None:
        """Sync closed candles from pipeline to archive."""
        try:
            candles = pipeline.get_closed_candles()
            if candles:
                save_candles(candles)
                logger.debug(f"Synced {len(candles)} candles to archive")
        except Exception as e:
            logger.error(f"Failed to sync candles: {e}", exc_info=True)

    def _run_cleanup(self) -> None:
        """Run data retention cleanup."""
        try:
            deleted = cleanup_old_data()
            logger.info(f"Cleanup completed: {deleted}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}", exc_info=True)


# Global recorder instance
recorder = HistoryRecorder()
