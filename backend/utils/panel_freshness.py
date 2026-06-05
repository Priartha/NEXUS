"""Panel data freshness monitor.

Tracks when each major data source was last updated.
If a panel's data is stale (> X minutes old), triggers a registered refresh.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PanelFreshnessMonitor:
    """Tracks data freshness for each panel and triggers refresh on staleness."""

    # Stale thresholds (seconds) per panel
    DEFAULTS = {
        "nlp_sentiment": 300.0,       # 5 min - news changes slowly
        "onchain_metrics": 600.0,     # 10 min - on-chain data updates slowly
        "hmm_regime": 180.0,          # 3 min - regime should update per candle
        "ml_xgboost": 1200.0,         # 20 min - trains every 15 min
        "transformer_forecast": 1500.0,  # 25 min
        "optimizer": 900.0,           # 15 min - should run on every paper trade close
        "ensemble": 600.0,            # 10 min
        "anomaly_detector": 300.0,    # 5 min
        "ai_lab": 300.0,              # 5 min
    }

    def __init__(self):
        self._last_update: dict[str, float] = {}
        self._refresh_handlers: dict[str, Callable] = {}
        self._bootstrap_handlers: dict[str, Callable] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    def register_panel(self, name: str, refresh_fn: Callable = None,
                       bootstrap_fn: Callable = None, threshold: float = None) -> None:
        """Register a panel with optional refresh and bootstrap functions."""
        self._last_update[name] = time.time()  # Initialize as fresh
        if refresh_fn:
            self._refresh_handlers[name] = refresh_fn
        if bootstrap_fn:
            self._bootstrap_handlers[name] = bootstrap_fn
        if threshold:
            self.DEFAULTS[name] = threshold

    def mark_updated(self, name: str) -> None:
        """Mark a panel as having been updated (call after refresh/calculation)."""
        self._last_update[name] = time.time()

    def is_stale(self, name: str) -> bool:
        threshold = self.DEFAULTS.get(name, 300.0)
        last = self._last_update.get(name, 0)
        return (time.time() - last) > threshold

    def age_seconds(self, name: str) -> float:
        last = self._last_update.get(name, 0)
        return time.time() - last

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop(), name="panel_freshness")
        logger.info("Panel freshness monitor started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(60.0)  # check every minute
                await self._check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Panel freshness monitor error: %s", e)

    async def _check_all(self) -> None:
        for name in list(self.DEFAULTS.keys()):
            if self.is_stale(name):
                threshold = self.DEFAULTS[name]
                age = self.age_seconds(name)
                logger.warning("Panel '%s' is stale (%.0fs old, threshold=%.0fs); refreshing",
                               name, age, threshold)
                # Try refresh first
                handler = self._refresh_handlers.get(name)
                if handler:
                    try:
                        result = handler()
                        if asyncio.iscoroutine(result):
                            await result
                        self.mark_updated(name)
                        logger.info("Refreshed panel '%s'", name)
                        continue
                    except Exception as e:
                        logger.warning("Refresh of panel '%s' failed: %s", name, e)
                # Fall back to bootstrap
                bootstrap = self._bootstrap_handlers.get(name)
                if bootstrap:
                    try:
                        result = bootstrap()
                        if asyncio.iscoroutine(result):
                            await result
                        self.mark_updated(name)
                        logger.info("Ran fallback handler for panel '%s'", name)
                    except Exception as e:
                        logger.warning("Bootstrap of panel '%s' failed: %s", name, e)

    def get_status(self) -> dict:
        return {
            name: {
                "age_seconds": self.age_seconds(name),
                "threshold": self.DEFAULTS.get(name, 300.0),
                "is_stale": self.is_stale(name),
            }
            for name in self.DEFAULTS
        }


# Singleton
panel_freshness = PanelFreshnessMonitor()
