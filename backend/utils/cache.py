"""
In-memory caching layer with TTL support for expensive computations.
Thread-safe, async-compatible, and supports per-key TTL configuration.
"""

import time
import asyncio
import hashlib
from typing import Any, Callable, Optional
from functools import wraps


class CacheEntry:
    __slots__ = ("value", "expires_at", "created_at", "hits")

    def __init__(self, value: Any, ttl_seconds: float):
        self.value = value
        self.created_at = time.monotonic()
        self.expires_at = self.created_at + ttl_seconds
        self.hits = 0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at


class TTLCache:
    """Thread-safe in-memory cache with per-key TTL support."""

    def __init__(self, default_ttl: float = 60.0, max_size: int = 1000):
        self._store: dict[str, CacheEntry] = {}
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.is_expired:
                del self._store[key]
                return None
            entry.hits += 1
            return entry.value

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        async with self._lock:
            if len(self._store) >= self._max_size:
                self._evict_expired()
                if len(self._store) >= self._max_size:
                    oldest_key = min(self._store, key=lambda k: self._store[k].created_at)
                    del self._store[oldest_key]
            self._store[key] = CacheEntry(value, ttl or self._default_ttl)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def get_stats(self) -> dict:
        async with self._lock:
            total = len(self._store)
            expired = sum(1 for e in self._store.values() if e.is_expired)
            total_hits = sum(e.hits for e in self._store.values())
            return {
                "total_entries": total,
                "expired_entries": expired,
                "active_entries": total - expired,
                "total_hits": total_hits,
                "max_size": self._max_size,
                "default_ttl": self._default_ttl,
            }

    def _evict_expired(self) -> None:
        expired_keys = [k for k, e in self._store.items() if e.is_expired]
        for k in expired_keys:
            del self._store[k]

    def _make_key(self, prefix: str, *args: Any, **kwargs: Any) -> str:
        raw = f"{prefix}:{args}:{sorted(kwargs.items())}"
        return hashlib.md5(raw.encode()).hexdigest()


global_cache = TTLCache(default_ttl=30.0, max_size=500)


def cached(prefix: str, ttl: Optional[float] = None):
    """Decorator to cache async function results."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = global_cache._make_key(prefix, *args, **kwargs)
            result = await global_cache.get(key)
            if result is not None:
                return result
            result = await func(*args, **kwargs)
            await global_cache.set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator


def cached_sync(prefix: str, ttl: Optional[float] = None):
    """Decorator to cache synchronous function results."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = global_cache._make_key(prefix, *args, **kwargs)
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(global_cache.get(key))
            if result is not None:
                return result
            result = func(*args, **kwargs)
            loop.run_until_complete(global_cache.set(key, result, ttl=ttl))
            return result
        return wrapper
    return decorator


CACHE_TTLS = {
    "multi_exchange_prices": 15.0,
    "model_performance": 60.0,
    "db_integrity": 120.0,
    "alert_config": 30.0,
    "exchange_info": 300.0,
    "price_snapshot": 5.0,
    "orderbook": 3.0,
    "recent_trades": 10.0,
    "candles": 30.0,
    "analysis": 60.0,
}


async def invalidate_pattern(prefix: str) -> int:
    """Invalidate all cache entries matching a prefix pattern."""
    count = 0
    async with global_cache._lock:
        keys_to_delete = [k for k in global_cache._store.keys() if k.startswith(prefix)]
        for k in keys_to_delete:
            del global_cache._store[k]
            count += 1
    return count
