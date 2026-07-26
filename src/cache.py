"""In-memory TTL cache for hot-path study pages.

No external dependencies — uses a plain dict with timestamps.
Thread-safe via GIL for CPython; sufficient for single-worker FastAPI.
"""

from __future__ import annotations

import time
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")

_DEFAULT_TTL: float = 60.0  # seconds


class TTLCache(Generic[T]):
    """Simple per-key TTL cache.

    Usage::

        cache = TTLCache[str](ttl=30)
        cache.set("key", "value")         # expires in 30 s
        cache.get("key")                  # -> "value" or None
        cache.invalidate("key")           # manual eviction
        cache.clear()                     # drop everything
    """

    def __init__(self, ttl: float = _DEFAULT_TTL) -> None:
        self._ttl: float = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    # ── public API ──────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[T]:
        """Return cached value if present and not expired, else ``None``."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.monotonic() > expires:
            del self._store[key]
            return None
        return value  # type: ignore[return-value]

    def set(self, key: str, value: T, ttl: float | None = None) -> None:
        """Store *value* under *key*; override default TTL per-key if desired."""
        effective_ttl: float = ttl if ttl is not None else self._ttl
        self._store[key] = (time.monotonic() + effective_ttl, value)

    def invalidate(self, key: str) -> None:
        """Remove a single key (no-op if absent)."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Drop all entries."""
        self._store.clear()

    def __len__(self) -> int:
        """Count of non-expired entries (approximate — expired entries are lazy-evicted)."""
        now = time.monotonic()
        return sum(1 for expires, _ in self._store.values() if now <= expires)
