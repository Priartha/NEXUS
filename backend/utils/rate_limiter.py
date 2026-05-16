"""
Rate Limiter for NEXUS external API calls.

Tracks request counts per endpoint and enforces rate limits
with automatic backoff and quota warnings.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("backend")


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 1200
    requests_per_second: float = 30.0
    weight_per_request: int = 1
    max_weight_per_minute: int = 6000


@dataclass
class RateLimitState:
    requests: list[float] = field(default_factory=list)
    total_weight: int = 0
    last_warning_ts: float = 0.0


class RateLimiter:
    """Enforces rate limits across all external API calls."""

    def __init__(self):
        self._limits: dict[str, RateLimitConfig] = {
            "binance_rest": RateLimitConfig(requests_per_minute=1200, requests_per_second=30.0, max_weight_per_minute=6000),
            "binance_ws": RateLimitConfig(requests_per_minute=300, requests_per_second=5.0),
            "coinbase_rest": RateLimitConfig(requests_per_minute=600, requests_per_second=10.0),
            "kraken_rest": RateLimitConfig(requests_per_minute=900, requests_per_second=15.0),
            "okx_rest": RateLimitConfig(requests_per_minute=600, requests_per_second=20.0),
            "bybit_rest": RateLimitConfig(requests_per_minute=600, requests_per_second=20.0),
            "gemini_api": RateLimitConfig(requests_per_minute=60, requests_per_second=1.0),
            "openai_api": RateLimitConfig(requests_per_minute=200, requests_per_second=3.0),
            "default": RateLimitConfig(requests_per_minute=300, requests_per_second=5.0),
        }
        self._state: dict[str, RateLimitState] = defaultdict(RateLimitState)
        self._lock = asyncio.Lock()

    async def acquire(self, endpoint: str = "default", weight: int = 1) -> bool:
        """Try to acquire a rate limit slot. Returns True if allowed, False if rate limited."""
        async with self._lock:
            config = self._limits.get(endpoint, self._limits["default"])
            state = self._state[endpoint]
            now = time.time()

            state.requests = [t for t in state.requests if t > now - 60.0]
            state.requests.append(now)

            if len(state.requests) > config.requests_per_minute:
                self._maybe_warn(endpoint, config, state)
                return False

            recent_1s = [t for t in state.requests if t > now - 1.0]
            if len(recent_1s) > config.requests_per_second:
                return False

            state.total_weight += weight
            if state.total_weight > config.max_weight_per_minute:
                self._maybe_warn(endpoint, config, state)
                return False

            return True

    async def wait_for_slot(self, endpoint: str = "default", weight: int = 1, timeout: float = 10.0) -> bool:
        """Wait until a rate limit slot is available."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self.acquire(endpoint, weight):
                return True
            await asyncio.sleep(0.1)
        return False

    def get_usage(self, endpoint: str = "default") -> dict[str, Any]:
        """Get current rate limit usage stats."""
        config = self._limits.get(endpoint, self._limits["default"])
        state = self._state[endpoint]
        now = time.time()
        recent = [t for t in state.requests if t > now - 60.0]
        return {
            "endpoint": endpoint,
            "requests_last_minute": len(recent),
            "requests_limit": config.requests_per_minute,
            "usage_pct": round(len(recent) / config.requests_per_minute * 100, 1),
            "weight_used": state.total_weight,
            "weight_limit": config.max_weight_per_minute,
        }

    def reset(self, endpoint: str | None = None) -> None:
        """Reset rate limit counters."""
        if endpoint:
            self._state[endpoint] = RateLimitState()
        else:
            self._state.clear()

    def _maybe_warn(self, endpoint: str, config: RateLimitConfig, state: RateLimitState) -> None:
        now = time.time()
        if now - state.last_warning_ts > 60.0:
            logger.warning(f"Rate limit approaching for {endpoint}: {len(state.requests)}/{config.requests_per_minute} req/min")
            state.last_warning_ts = now


rate_limiter = RateLimiter()
