"""Tests for the LRU-cached evaluator factory."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from agent_control_evaluators import (
    Evaluator,
    EvaluatorConfig,
    EvaluatorMetadata,
    clear_evaluator_cache,
    clear_evaluators,
    get_all_evaluators,
    get_evaluator_instance,
    register_evaluator,
)
from agent_control_evaluators import _factory as factory_module
from agent_control_models import EvaluatorResult, EvaluatorSpec


class _FactoryConfig(EvaluatorConfig):
    payload: str = "default"


class _FactoryEvaluator(Evaluator[_FactoryConfig]):
    metadata = EvaluatorMetadata(name="factory-dummy", version="1.0.0", description="")
    config_model = _FactoryConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        return EvaluatorResult(matched=False, confidence=1.0, message="")


@pytest.fixture
def isolated_factory():
    """Snapshot registry/cache so factory tests don't leak state."""
    snapshot = dict(get_all_evaluators())
    clear_evaluators()
    clear_evaluator_cache()
    register_evaluator(_FactoryEvaluator)
    yield
    clear_evaluator_cache()
    clear_evaluators()
    for cls in snapshot.values():
        register_evaluator(cls)


def test_get_evaluator_instance_returns_evaluator(isolated_factory):
    spec = EvaluatorSpec(name="factory-dummy", config={"payload": "p1"})

    instance = get_evaluator_instance(spec)

    assert isinstance(instance, _FactoryEvaluator)
    assert instance.config.payload == "p1"


def test_get_evaluator_instance_caches_by_config(isolated_factory):
    spec_a = EvaluatorSpec(name="factory-dummy", config={"payload": "same"})
    spec_b = EvaluatorSpec(name="factory-dummy", config={"payload": "same"})

    first = get_evaluator_instance(spec_a)
    second = get_evaluator_instance(spec_b)

    # Same config = same cached instance.
    assert first is second


def test_get_evaluator_instance_treats_different_configs_separately(isolated_factory):
    spec_a = EvaluatorSpec(name="factory-dummy", config={"payload": "a"})
    spec_b = EvaluatorSpec(name="factory-dummy", config={"payload": "b"})

    instance_a = get_evaluator_instance(spec_a)
    instance_b = get_evaluator_instance(spec_b)

    assert instance_a is not instance_b
    assert instance_a.config.payload == "a"
    assert instance_b.config.payload == "b"


def test_get_evaluator_instance_raises_for_unknown_evaluator(isolated_factory):
    with pytest.raises(ValueError, match="not found"):
        get_evaluator_instance(EvaluatorSpec(name="no-such-evaluator", config={}))


def test_clear_evaluator_cache_forces_recreation(isolated_factory):
    spec = EvaluatorSpec(name="factory-dummy", config={"payload": "p"})

    first = get_evaluator_instance(spec)
    clear_evaluator_cache()
    second = get_evaluator_instance(spec)

    assert first is not second


def test_get_evaluator_instance_evicts_oldest_when_full(isolated_factory, monkeypatch):
    """LRU eviction: when cache is full, the least-recently-used entry is dropped."""
    # Force a tiny cache so we can observe eviction without overhead.
    monkeypatch.setattr(factory_module, "EVALUATOR_CACHE_SIZE", 2)

    spec_a = EvaluatorSpec(name="factory-dummy", config={"payload": "a"})
    spec_b = EvaluatorSpec(name="factory-dummy", config={"payload": "b"})
    spec_c = EvaluatorSpec(name="factory-dummy", config={"payload": "c"})

    first_a = get_evaluator_instance(spec_a)
    get_evaluator_instance(spec_b)
    # Insert third → "a" is the LRU and must be evicted.
    get_evaluator_instance(spec_c)

    re_a = get_evaluator_instance(spec_a)
    # "a" was evicted: new instance must NOT be the original.
    assert re_a is not first_a


def test_get_evaluator_instance_moves_hit_to_most_recent(
    isolated_factory, monkeypatch
):
    """Cache hit must refresh LRU recency so the touched entry isn't evicted next."""
    monkeypatch.setattr(factory_module, "EVALUATOR_CACHE_SIZE", 2)

    spec_a = EvaluatorSpec(name="factory-dummy", config={"payload": "a"})
    spec_b = EvaluatorSpec(name="factory-dummy", config={"payload": "b"})
    spec_c = EvaluatorSpec(name="factory-dummy", config={"payload": "c"})

    first_a = get_evaluator_instance(spec_a)
    get_evaluator_instance(spec_b)
    # Touch "a" so "b" becomes the LRU.
    re_a = get_evaluator_instance(spec_a)
    assert re_a is first_a

    # Inserting "c" should evict "b", not "a".
    get_evaluator_instance(spec_c)

    refetched_a = get_evaluator_instance(spec_a)
    assert refetched_a is first_a  # still cached


def test_parse_cache_size_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("EVALUATOR_CACHE_SIZE", raising=False)
    reloaded = importlib.reload(factory_module)
    try:
        assert reloaded.EVALUATOR_CACHE_SIZE == factory_module.DEFAULT_CACHE_SIZE
    finally:
        importlib.reload(factory_module)


def test_parse_cache_size_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("EVALUATOR_CACHE_SIZE", "not-a-number")
    reloaded = importlib.reload(factory_module)
    try:
        assert reloaded.EVALUATOR_CACHE_SIZE == reloaded.DEFAULT_CACHE_SIZE
    finally:
        importlib.reload(factory_module)


def test_parse_cache_size_clamps_to_minimum(monkeypatch):
    monkeypatch.setenv("EVALUATOR_CACHE_SIZE", "0")
    reloaded = importlib.reload(factory_module)
    try:
        # Anything below MIN_CACHE_SIZE is clamped to avoid infinite eviction loops.
        assert reloaded.EVALUATOR_CACHE_SIZE >= reloaded.MIN_CACHE_SIZE
    finally:
        importlib.reload(factory_module)


def test_parse_cache_size_accepts_valid_int(monkeypatch):
    monkeypatch.setenv("EVALUATOR_CACHE_SIZE", "42")
    reloaded = importlib.reload(factory_module)
    try:
        assert reloaded.EVALUATOR_CACHE_SIZE == 42
    finally:
        importlib.reload(factory_module)
