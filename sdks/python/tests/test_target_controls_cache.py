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


def test_get_returns_none_on_miss(cache: TargetControlsCache) -> None:
    assert cache.get("env", "prod") is None


def test_put_then_get_returns_a_copy(cache: TargetControlsCache) -> None:
    payload = [_ctrl("a")]
    cache.put("env", "prod", payload)
    fetched = cache.get("env", "prod")
    assert fetched == payload
    fetched.append(_ctrl("b"))
    assert cache.get("env", "prod") == payload


def test_put_overwrites_existing_entry(cache: TargetControlsCache) -> None:
    cache.put("env", "prod", [_ctrl("old")])
    cache.put("env", "prod", [_ctrl("new")])
    assert cache.get("env", "prod") == [_ctrl("new")]


def test_lru_eviction_drops_oldest(cache: TargetControlsCache) -> None:
    cache.put("env", "a", [_ctrl("ca")])
    cache.put("env", "b", [_ctrl("cb")])
    cache.put("env", "c", [_ctrl("cc")])
    cache.put("env", "d", [_ctrl("cd")])

    assert cache.get("env", "a") is None
    assert cache.get("env", "b") == [_ctrl("cb")]
    assert cache.get("env", "c") == [_ctrl("cc")]
    assert cache.get("env", "d") == [_ctrl("cd")]


def test_get_marks_entry_as_recently_used(cache: TargetControlsCache) -> None:
    cache.put("env", "a", [_ctrl("ca")])
    cache.put("env", "b", [_ctrl("cb")])
    cache.put("env", "c", [_ctrl("cc")])
    cache.get("env", "a")
    cache.put("env", "d", [_ctrl("cd")])

    assert cache.get("env", "a") == [_ctrl("ca")]
    assert cache.get("env", "b") is None


def test_invalidate_removes_one_entry(cache: TargetControlsCache) -> None:
    cache.put("env", "a", [_ctrl("ca")])
    cache.put("env", "b", [_ctrl("cb")])
    cache.invalidate("env", "a")
    assert cache.get("env", "a") is None
    assert cache.get("env", "b") == [_ctrl("cb")]


def test_clear_removes_all_entries(cache: TargetControlsCache) -> None:
    cache.put("env", "a", [_ctrl("ca")])
    cache.put("env", "b", [_ctrl("cb")])
    cache.clear()
    assert len(cache) == 0


def test_keys_snapshot_returns_independent_copy(cache: TargetControlsCache) -> None:
    cache.put("env", "a", [_ctrl("ca")])
    cache.put("env", "b", [_ctrl("cb")])
    snapshot = cache.keys_snapshot()
    cache.invalidate("env", "a")
    assert ("env", "a") in snapshot
    assert ("env", "b") in snapshot


def test_configure_shrinks_capacity_evicting_oldest(cache: TargetControlsCache) -> None:
    cache.put("env", "a", [_ctrl("ca")])
    cache.put("env", "b", [_ctrl("cb")])
    cache.put("env", "c", [_ctrl("cc")])
    cache.configure(max_size=2)
    assert cache.get("env", "a") is None
    assert cache.get("env", "b") == [_ctrl("cb")]
    assert cache.get("env", "c") == [_ctrl("cc")]


def test_module_singleton_is_shared() -> None:
    assert get_target_controls_cache() is get_target_controls_cache()
