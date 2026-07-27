"""Tests for the TTL search cache."""

from __future__ import annotations

import pytest

from stocky_mcp.cache import TTLCache


class FakeClock:
    """A manually advanced clock, so tests never sleep."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def test_set_then_get_returns_value(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, time_fn=clock)
    cache.set("k", {"result": 1})

    assert cache.get("k") == {"result": 1}
    assert cache.hits == 1
    assert cache.misses == 0


def test_get_missing_key_returns_none(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, time_fn=clock)

    assert cache.get("absent") is None
    assert cache.misses == 1


def test_entry_expires_after_ttl(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, time_fn=clock)
    cache.set("k", "v")

    clock.advance(59.9)
    assert cache.get("k") == "v"

    clock.advance(0.2)
    assert cache.get("k") is None


def test_expiry_is_inclusive_at_the_boundary(clock: FakeClock) -> None:
    """An entry is dead exactly at its expiry instant, not a tick later."""
    cache = TTLCache(ttl=10, time_fn=clock)
    cache.set("k", "v")

    clock.advance(10.0)
    assert cache.get("k") is None


def test_expired_entry_is_dropped_from_storage(clock: FakeClock) -> None:
    cache = TTLCache(ttl=10, time_fn=clock)
    cache.set("k", "v")
    clock.advance(11)

    cache.get("k")

    assert len(cache) == 0


def test_zero_ttl_disables_the_cache(clock: FakeClock) -> None:
    cache = TTLCache(ttl=0, time_fn=clock)
    cache.set("k", "v")

    assert cache.enabled is False
    assert cache.get("k") is None
    assert len(cache) == 0


def test_negative_ttl_disables_the_cache(clock: FakeClock) -> None:
    cache = TTLCache(ttl=-5, time_fn=clock)
    cache.set("k", "v")

    assert cache.enabled is False
    assert cache.get("k") is None


def test_set_overwrites_existing_value(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, time_fn=clock)
    cache.set("k", "first")
    cache.set("k", "second")

    assert cache.get("k") == "second"
    assert len(cache) == 1


def test_set_refreshes_the_ttl(clock: FakeClock) -> None:
    cache = TTLCache(ttl=10, time_fn=clock)
    cache.set("k", "v")

    clock.advance(9)
    cache.set("k", "v2")
    clock.advance(9)

    assert cache.get("k") == "v2"


def test_eviction_removes_the_oldest_entry(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, max_entries=2, time_fn=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)

    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3
    assert len(cache) == 2


def test_overwrite_does_not_trigger_eviction(clock: FakeClock) -> None:
    """Re-setting an existing key must not evict a different entry."""
    cache = TTLCache(ttl=60, max_entries=2, time_fn=clock)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("a", 99)

    assert cache.get("a") == 99
    assert cache.get("b") == 2


def test_delete_removes_entry(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, time_fn=clock)
    cache.set("k", "v")

    assert cache.delete("k") is True
    assert cache.delete("k") is False
    assert cache.get("k") is None


def test_clear_resets_entries_and_counters(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, time_fn=clock)
    cache.set("k", "v")
    cache.get("k")
    cache.get("missing")

    cache.clear()

    assert len(cache) == 0
    assert cache.hits == 0
    assert cache.misses == 0


def test_max_entries_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_entries must be positive"):
        TTLCache(ttl=60, max_entries=0)


def test_stats_reports_hit_rate(clock: FakeClock) -> None:
    cache = TTLCache(ttl=60, time_fn=clock)
    cache.set("k", "v")
    cache.get("k")
    cache.get("k")
    cache.get("missing")

    stats = cache.stats()

    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate"] == pytest.approx(0.667, abs=0.001)
    assert stats["entries"] == 1
    assert stats["enabled"] is True


def test_stats_hit_rate_is_zero_when_unused(clock: FakeClock) -> None:
    assert TTLCache(ttl=60, time_fn=clock).stats()["hit_rate"] == 0.0
