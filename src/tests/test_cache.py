"""Tests for the in-memory TTL cache."""

from __future__ import annotations

import sys
import time
from pathlib import Path

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from cache import TTLCache


class TestTTLCache:
    def test_set_and_get(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_get_missing_key(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        assert cache.get("nonexistent") is None

    def test_expiry(self):
        cache: TTLCache[str] = TTLCache(ttl=0.01)
        cache.set("key", "value")
        time.sleep(0.02)
        assert cache.get("key") is None

    def test_invalidate(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        cache.set("key", "value")
        cache.invalidate("key")
        assert cache.get("key") is None

    def test_invalidate_missing_key(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        cache.invalidate("nonexistent")
        assert cache.get("nonexistent") is None

    def test_clear(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        cache.set("a", "1")
        cache.set("b", "2")
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_len(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        cache.set("a", "1")
        cache.set("b", "2")
        assert len(cache) == 2

    def test_len_excludes_expired(self):
        cache: TTLCache[str] = TTLCache(ttl=0.01)
        cache.set("a", "1")
        cache.set("b", "2")
        time.sleep(0.02)
        assert len(cache) == 0

    def test_custom_ttl_per_key(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        cache.set("short", "val", ttl=0.01)
        cache.set("long", "val", ttl=10.0)
        time.sleep(0.02)
        assert cache.get("short") is None
        assert cache.get("long") == "val"

    def test_overwrite(self):
        cache: TTLCache[str] = TTLCache(ttl=10.0)
        cache.set("key", "old")
        cache.set("key", "new")
        assert cache.get("key") == "new"
