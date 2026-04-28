"""Unit tests for the per-target controls cache."""

from __future__ import annotations

import pytest

from agent_control._target_controls_cache import (
    TargetControlsCache,
    get_target_controls_cache,
)


@pytest.fixture
def cache() -> TargetControlsCache:
    return TargetControlsCache(max_size=3)


def _ctrl(name: str) -> dict[str, object]:
    return {"id": 1, "name": name, "control": {}}


def _put(cache: TargetControlsCache, target_type: str, target_id: str, controls) -> bool:
    """Helper that stamps the put with the cache's current epoch."""
    return cache.put(target_type, target_id, controls, epoch=cache.current_epoch())


def test_get_returns_none_on_miss(cache: TargetControlsCache) -> None:
    assert cache.get("env", "prod") is None


def test_put_then_get_returns_a_copy(cache: TargetControlsCache) -> None:
    payload = [_ctrl("a")]
    assert _put(cache, "env", "prod", payload) is True
    fetched = cache.get("env", "prod")
    assert fetched == payload
    fetched.append(_ctrl("b"))
    assert cache.get("env", "prod") == payload


def test_put_overwrites_existing_entry(cache: TargetControlsCache) -> None:
    _put(cache, "env", "prod", [_ctrl("old")])
    _put(cache, "env", "prod", [_ctrl("new")])
    assert cache.get("env", "prod") == [_ctrl("new")]


def test_lru_eviction_drops_oldest(cache: TargetControlsCache) -> None:
    _put(cache, "env", "a", [_ctrl("ca")])
    _put(cache, "env", "b", [_ctrl("cb")])
    _put(cache, "env", "c", [_ctrl("cc")])
    _put(cache, "env", "d", [_ctrl("cd")])

    assert cache.get("env", "a") is None
    assert cache.get("env", "b") == [_ctrl("cb")]
    assert cache.get("env", "c") == [_ctrl("cc")]
    assert cache.get("env", "d") == [_ctrl("cd")]


def test_get_marks_entry_as_recently_used(cache: TargetControlsCache) -> None:
    _put(cache, "env", "a", [_ctrl("ca")])
    _put(cache, "env", "b", [_ctrl("cb")])
    _put(cache, "env", "c", [_ctrl("cc")])
    cache.get("env", "a")
    _put(cache, "env", "d", [_ctrl("cd")])

    assert cache.get("env", "a") == [_ctrl("ca")]
    assert cache.get("env", "b") is None


def test_invalidate_removes_one_entry(cache: TargetControlsCache) -> None:
    _put(cache, "env", "a", [_ctrl("ca")])
    _put(cache, "env", "b", [_ctrl("cb")])
    cache.invalidate("env", "a")
    assert cache.get("env", "a") is None
    assert cache.get("env", "b") == [_ctrl("cb")]


def test_clear_removes_all_entries(cache: TargetControlsCache) -> None:
    _put(cache, "env", "a", [_ctrl("ca")])
    _put(cache, "env", "b", [_ctrl("cb")])
    cache.clear()
    assert len(cache) == 0


def test_keys_snapshot_returns_independent_copy(cache: TargetControlsCache) -> None:
    _put(cache, "env", "a", [_ctrl("ca")])
    _put(cache, "env", "b", [_ctrl("cb")])
    snapshot = cache.keys_snapshot()
    cache.invalidate("env", "a")
    assert ("env", "a") in snapshot
    assert ("env", "b") in snapshot


def test_configure_shrinks_capacity_evicting_oldest(cache: TargetControlsCache) -> None:
    _put(cache, "env", "a", [_ctrl("ca")])
    _put(cache, "env", "b", [_ctrl("cb")])
    _put(cache, "env", "c", [_ctrl("cc")])
    cache.configure(max_size=2)
    assert cache.get("env", "a") is None
    assert cache.get("env", "b") == [_ctrl("cb")]
    assert cache.get("env", "c") == [_ctrl("cc")]


def test_reset_advances_epoch_and_drops_entries(cache: TargetControlsCache) -> None:
    _put(cache, "env", "a", [_ctrl("ca")])
    epoch_before = cache.current_epoch()
    epoch_after = cache.reset()

    assert epoch_after == epoch_before + 1
    assert cache.get("env", "a") is None
    assert len(cache) == 0


def test_put_with_stale_epoch_is_rejected(cache: TargetControlsCache) -> None:
    """A write captured under the previous epoch must not land after reset."""
    stale_epoch = cache.current_epoch()
    cache.reset()  # bumps epoch; old in-flight callers still hold ``stale_epoch``

    stored = cache.put("env", "prod", [_ctrl("stale")], epoch=stale_epoch)
    assert stored is False
    assert cache.get("env", "prod") is None


def test_put_with_current_epoch_after_reset_succeeds(cache: TargetControlsCache) -> None:
    cache.reset()
    stored = cache.put(
        "env", "prod", [_ctrl("fresh")], epoch=cache.current_epoch()
    )
    assert stored is True
    assert cache.get("env", "prod") == [_ctrl("fresh")]


def test_module_singleton_is_shared() -> None:
    assert get_target_controls_cache() is get_target_controls_cache()
