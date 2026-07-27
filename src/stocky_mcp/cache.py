"""A small in-memory TTL cache for search results.

Search results are stable enough over short windows that repeating an
identical query against a provider is wasted quota. This cache is deliberately
tiny: no background eviction thread, no persistence, no external dependency.
Expired entries are dropped lazily on access, and a size cap bounds memory by
evicting the oldest entry when full.

It is used for searches only. Downloads are never cached.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_MAX_ENTRIES = 256


class TTLCache:
    """A bounded mapping whose entries expire after a fixed time to live.

    Args:
        ttl: Seconds an entry remains valid. ``0`` or negative disables the
            cache entirely: every ``get`` misses and ``set`` stores nothing.
        max_entries: Maximum number of live entries. When exceeded, the
            least recently inserted entry is evicted.
        time_fn: Clock used for expiry, injectable so tests need not sleep.
    """

    def __init__(
        self,
        ttl: float,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl = ttl
        self._max_entries = max_entries
        self._time = time_fn
        # key -> (expires_at, value); ordered oldest-first for eviction.
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        """Whether this cache stores anything at all."""
        return self._ttl > 0

    @property
    def ttl(self) -> float:
        """Configured time to live, in seconds."""
        return self._ttl

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> Any | None:
        """Return the cached value for ``key``, or ``None`` if absent/expired.

        A stored value of ``None`` is indistinguishable from a miss. Callers
        must not cache ``None``; the manager only caches result dictionaries.
        """
        if not self.enabled:
            self.misses += 1
            return None

        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            logger.debug("Cache miss: %s", key)
            return None

        expires_at, value = entry
        if self._time() >= expires_at:
            # Lazy eviction: drop on read rather than sweeping in background.
            del self._entries[key]
            self.misses += 1
            logger.debug("Cache expired: %s", key)
            return None

        self.hits += 1
        logger.debug("Cache hit: %s", key)
        return value

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key`` for the configured TTL."""
        if not self.enabled:
            return

        # Re-inserting must refresh position so eviction stays oldest-first.
        if key in self._entries:
            del self._entries[key]
        elif len(self._entries) >= self._max_entries:
            evicted_key, _ = self._entries.popitem(last=False)
            logger.debug("Cache evicted (full): %s", evicted_key)

        self._entries[key] = (self._time() + self._ttl, value)
        logger.debug("Cache set: %s", key)

    def delete(self, key: str) -> bool:
        """Remove ``key``. Returns whether it was present."""
        return self._entries.pop(key, None) is not None

    def clear(self) -> None:
        """Drop all entries and reset hit/miss counters."""
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict[str, Any]:
        """Return a snapshot of cache activity, for diagnostics."""
        total = self.hits + self.misses
        return {
            "enabled": self.enabled,
            "ttl_seconds": self._ttl,
            "entries": len(self._entries),
            "max_entries": self._max_entries,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }
