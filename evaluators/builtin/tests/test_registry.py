"""Tests for the in-memory evaluator registry."""

from __future__ import annotations

from typing import Any

import pytest
from agent_control_evaluators import (
    Evaluator,
    EvaluatorConfig,
    EvaluatorMetadata,
    clear_evaluators,
    get_all_evaluators,
    get_evaluator,
    register_evaluator,
)
from agent_control_models import EvaluatorResult


class _DummyConfig(EvaluatorConfig):
    pass


def _make_class(*, name: str, available: bool = True) -> type[Evaluator[_DummyConfig]]:
    """Build a fresh Evaluator subclass with the supplied metadata name."""

    class _Dummy(Evaluator[_DummyConfig]):
        metadata = EvaluatorMetadata(
            name=name,
            version="1.0.0",
            description="",
        )
        config_model = _DummyConfig

        @classmethod
        def is_available(cls) -> bool:
            return available

        async def evaluate(self, data: Any) -> EvaluatorResult:
            return EvaluatorResult(matched=False, confidence=1.0, message="")

    _Dummy.__name__ = f"Dummy_{name.replace('-', '_')}"
    return _Dummy


@pytest.fixture
def isolated_registry():
    """Snapshot and restore the global registry so tests don't leak state."""
    snapshot = dict(get_all_evaluators())
    clear_evaluators()
    yield
    clear_evaluators()
    for cls in snapshot.values():
        register_evaluator(cls)


def test_register_and_lookup_evaluator(isolated_registry):
    cls = _make_class(name="reg-a")

    register_evaluator(cls)

    assert get_evaluator("reg-a") is cls


def test_get_evaluator_returns_none_when_not_registered(isolated_registry):
    assert get_evaluator("does-not-exist") is None


def test_get_all_evaluators_returns_copy(isolated_registry):
    cls = _make_class(name="reg-copy")
    register_evaluator(cls)

    snapshot = get_all_evaluators()
    snapshot["evil"] = cls  # mutate the returned dict

    # Internal registry must not reflect external mutation.
    assert "evil" not in get_all_evaluators()


def test_register_is_idempotent_for_same_class(isolated_registry):
    cls = _make_class(name="reg-idem")

    register_evaluator(cls)
    # Registering the exact same class again must not raise.
    assert register_evaluator(cls) is cls


def test_register_rejects_name_collision_with_different_class(isolated_registry):
    first = _make_class(name="reg-conflict")
    second = _make_class(name="reg-conflict")
    register_evaluator(first)

    with pytest.raises(ValueError, match="already registered"):
        register_evaluator(second)


def test_register_skips_unavailable_evaluators(isolated_registry):
    cls = _make_class(name="reg-unavailable", available=False)

    # Should not raise and should not register.
    assert register_evaluator(cls) is cls
    assert get_evaluator("reg-unavailable") is None


def test_clear_evaluators_empties_registry(isolated_registry):
    register_evaluator(_make_class(name="reg-c1"))
    register_evaluator(_make_class(name="reg-c2"))
    assert len(get_all_evaluators()) == 2

    clear_evaluators()

    assert get_all_evaluators() == {}


def test_register_decorator_returns_class(isolated_registry):
    cls = _make_class(name="reg-decorator")
    # The function is documented as decorator-compatible: it must return the class.
    decorated = register_evaluator(cls)
    assert decorated is cls
