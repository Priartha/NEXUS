"""
Circuit breaker for external API calls.

Implements a generic circuit breaker pattern with three states:
  - CLOSED: normal operation, calls pass through
  - OPEN: calls fail fast without attempting
  - HALF_OPEN: limited calls allowed to test recovery

Tracks failure rate within a rolling window and trips when
the threshold is exceeded for the configured minimum count.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: float = 0.5,
        min_failures: int = 5,
        window_seconds: float = 60.0,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.min_failures = min_failures
        self.window_seconds = window_seconds
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = CircuitState.CLOSED
        self._events: deque[tuple[float, bool]] = deque(maxlen=200)
        self._last_open_time: float = 0.0
        self._half_open_calls: int = 0
        self._last_failure_reason: str | None = None

    def _trim_window(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def _failure_rate(self, now: float) -> float:
        self._trim_window(now)
        if not self._events:
            return 0.0
        failures = sum(1 for _, ok in self._events if not ok)
        return failures / len(self._events)

    def _total_failures(self, now: float) -> int:
        self._trim_window(now)
        return sum(1 for _, ok in self._events if not ok)

    def allow_request(self) -> bool:
        now = time.time()

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if now - self._last_open_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN")
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False

        return True

    def record_success(self) -> None:
        now = time.time()
        self._events.append((now, True))

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self._half_open_calls = 0
            self._last_failure_reason = None
            logger.info(f"Circuit breaker '{self.name}' reset to CLOSED")

    def record_failure(self, reason: str | None = None) -> None:
        now = time.time()
        self._events.append((now, False))
        self._last_failure_reason = reason

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self._last_open_time = now
            self._half_open_calls = 0
            logger.warning(
                f"Circuit breaker '{self.name}' returned to OPEN (half-open probe failed: {reason})"
            )
            return

        if self.state != CircuitState.OPEN:
            failures = self._total_failures(now)
            rate = self._failure_rate(now)
            if failures >= self.min_failures and rate >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self._last_open_time = now
                logger.warning(
                    f"Circuit breaker '{self.name}' tripped OPEN "
                    f"(failures={failures}, rate={rate:.2f}, threshold={self.failure_threshold})"
                )

    async def call(
        self,
        coro_factory: Callable[[], Any],
        fallback: Any = None,
        raise_on_failure: bool = False,
    ) -> Any:
        if not self.allow_request():
            logger.warning(f"Circuit breaker '{self.name}' denying request (state={self.state.value})")
            if raise_on_failure:
                raise CircuitBreakerOpenError(self.name, self.state)
            return fallback

        try:
            result = await coro_factory()
            self.record_success()
            return result
        except Exception as e:
            self.record_failure(reason=str(e))
            if raise_on_failure:
                raise
            return fallback

    def get_state(self) -> dict:
        now = time.time()
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_rate": round(self._failure_rate(now), 4),
            "total_failures": self._total_failures(now),
            "total_events": len(self._events),
            "last_open_time": self._last_open_time,
            "last_failure_reason": self._last_failure_reason,
            "recovery_timeout": self.recovery_timeout,
            "half_open_max_calls": self.half_open_max_calls,
        }


class CircuitBreakerOpenError(Exception):
    def __init__(self, name: str, state: CircuitState) -> None:
        self.name = name
        self.state = state
        super().__init__(f"Circuit breaker '{name}' is {state.value}")



class CircuitBreakerRegistry:
    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str) -> CircuitBreaker | None:
        return self._breakers.get(name)

    def register(self, breaker: CircuitBreaker) -> None:
        self._breakers[breaker.name] = breaker

    def get_all_states(self) -> dict[str, dict]:
        return {name: cb.get_state() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        for cb in self._breakers.values():
            cb.state = CircuitState.CLOSED
            cb._events.clear()
            cb._last_open_time = 0.0
            cb._half_open_calls = 0
            cb._last_failure_reason = None


circuit_registry = CircuitBreakerRegistry()
