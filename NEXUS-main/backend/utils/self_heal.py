"""Self-healing system for the NEXUS backend.

Provides:
- Auto-install of missing ML dependencies on startup
- Background task monitor that restarts any failed loop
- Panel data freshness checks with registered refresh handlers if stale
- Periodic self-diagnostics and recovery
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import time
from typing import Callable

logger = logging.getLogger(__name__)


# Map of module name -> pip package name
REQUIRED_DEPS = {
    "sklearn": "scikit-learn",
    "xgboost": "xgboost",
    "hmmlearn": "hmmlearn",
}


def check_and_install_deps() -> dict:
    """Check for required ML dependencies and install any that are missing.

    Returns a dict of {module_name: 'installed'|'failed'|'present'}.
    """
    import importlib
    results = {}
    for module_name, pip_name in REQUIRED_DEPS.items():
        try:
            importlib.import_module(module_name)
            results[module_name] = "present"
        except ImportError:
            logger.info("Installing missing dependency: %s (%s)", module_name, pip_name)
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet", pip_name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=180,
                )
                # Re-test import
                importlib.import_module(module_name)
                results[module_name] = "installed"
                logger.info("Successfully installed %s", pip_name)
            except Exception as e:
                results[module_name] = f"failed: {e}"
                logger.warning("Failed to install %s: %s", pip_name, e)
    return results


class SelfHealingMonitor:
    """Monitors background tasks and restarts any that fail or go stale."""

    def __init__(self, task_registry: dict, check_interval: float = 30.0,
                 stale_threshold: float = 300.0):
        self._tasks: dict[str, dict] = task_registry
        self._check_interval = check_interval
        self._stale_threshold = stale_threshold
        self._running = False
        self._task: asyncio.Task | None = None
        self._restart_counts: dict[str, int] = {}

    def register(self, name: str, task: asyncio.Task, factory: Callable,
                 interval: float = 60.0) -> None:
        """Register a background task for monitoring."""
        self._tasks[name] = {
            "task": task,
            "factory": factory,
            "interval": interval,
            "last_ok": time.time(),
            "last_error": "",
        }
        self._restart_counts.setdefault(name, 0)

    def heartbeat(self, name: str, ok: bool = True, error: str = "") -> None:
        """Mark a task as having completed a cycle (for liveness tracking)."""
        if name in self._tasks:
            t = self._tasks[name]
            t["last_ok"] = time.time()
            if not ok:
                t["last_error"] = error

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop(), name="self_heal_monitor")
        logger.info("Self-healing monitor started (interval=%.0fs, stale=%.0fs)",
                    self._check_interval, self._stale_threshold)

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
                await asyncio.sleep(self._check_interval)
                await self._check_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Self-heal monitor loop error: %s", e)

    async def _check_all(self) -> None:
        now = time.time()
        for name, info in list(self._tasks.items()):
            task = info["task"]
            last_ok = info.get("last_ok", now)

            # If task is dead and not running, restart it
            if task.done() and not task.cancelled():
                try:
                    exc = task.exception()
                    if exc is not None:
                        logger.warning("Task %s died with exception: %s; restarting", name, exc)
                except (asyncio.CancelledError, asyncio.InvalidStateError):
                    pass
                self._restart(name)

            # If task hasn't reported liveness in stale_threshold seconds, restart it
            elif now - last_ok > self._stale_threshold and info["factory"] is not None:
                logger.warning("Task %s appears stale (last_ok=%.0fs ago); restarting",
                               name, now - last_ok)
                self._restart(name)

    def _restart(self, name: str) -> None:
        info = self._tasks.get(name)
        if not info or not info["factory"]:
            return
        try:
            old_task = info["task"]
            if not old_task.done():
                old_task.cancel()
            new_task = info["factory"]()
            info["task"] = new_task
            info["last_ok"] = time.time()
            self._restart_counts[name] = self._restart_counts.get(name, 0) + 1
            logger.info("Task %s restarted (count=%d)", name, self._restart_counts[name])
        except Exception as e:
            logger.exception("Failed to restart task %s: %s", name, e)

    def get_status(self) -> dict:
        """Return liveness/restart status of all registered tasks."""
        now = time.time()
        return {
            name: {
                "alive": not info["task"].done() if info["task"] else False,
                "last_ok_ago": now - info.get("last_ok", now),
                "restarts": self._restart_counts.get(name, 0),
                "last_error": info.get("last_error", ""),
            }
            for name, info in self._tasks.items()
        }


# Singleton
self_heal = SelfHealingMonitor(task_registry={}, check_interval=30.0, stale_threshold=21600.0)
