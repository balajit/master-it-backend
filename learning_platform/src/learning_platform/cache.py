"""Unified in-memory cache for pipeline results.

Provides a typed, TTL-aware, max-size-limited cache shared between the
learning-platform document routes and the main-app mapping service.
Both import the module-level ``pipeline_cache`` singleton, which lives
in the same process because the LP is mounted as a sub-app.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PipelineCache[T]:
    """Typed, TTL-aware, max-size-limited cache.

    Uses an ``OrderedDict`` for O(1) LRU eviction when the cache is full.
    Each entry stores ``(value, expires_at)`` so lookups are O(1).

    Parameters
    ----------
    max_size:
        Maximum number of entries.  When exceeded, the oldest entry is evicted.
    ttl_seconds:
        Time-to-live in seconds.  ``None`` means entries never expire.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: float | None = 3600.0) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[T, float]] = OrderedDict()

    def get(self, key: str) -> T | None:
        """Return the cached value for *key*, or ``None`` if missing / expired."""
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if self._ttl is not None and time.monotonic() > expires_at:
            del self._store[key]
            logger.debug("Cache entry expired: %s", key)
            return None
        # Move to end (most-recently used) for LRU
        self._store.move_to_end(key)
        return value

    def set(self, key: str, value: T) -> None:
        """Insert or update a cache entry."""
        if key in self._store:
            del self._store[key]
        elif len(self._store) >= self._max_size:
            # Evict oldest (first) entry
            evicted_key, _ = self._store.popitem(last=False)
            logger.debug("Cache evicted (LRU): %s", evicted_key)
        expires_at = time.monotonic() + self._ttl if self._ttl is not None else float("inf")
        self._store[key] = (value, expires_at)

    def invalidate(self, key: str) -> None:
        """Remove a single entry."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Drop all entries."""
        self._store.clear()

    def keys(self) -> list[str]:
        """Return all non-expired keys."""
        now = time.monotonic()
        if self._ttl is None:
            return list(self._store.keys())
        return [
            k for k, (_, exp) in self._store.items()
            if now <= exp
        ]

    def __len__(self) -> int:
        now = time.monotonic()
        if self._ttl is None:
            return len(self._store)
        return sum(1 for _, exp in self._store.values() if now <= exp)


# ── Module-level singleton ───────────────────────────────────────────────────
# Shared between the LP document routes and the main-app mapping service.
# Both import this module; Python's module system ensures a single instance.

pipeline_cache: PipelineCache = PipelineCache(max_size=100, ttl_seconds=3600.0)
