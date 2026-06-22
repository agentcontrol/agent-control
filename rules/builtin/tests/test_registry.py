"""Tests for the in-memory rule registry."""

from __future__ import annotations

from typing import Any

import pytest
from agent_control_rules import (
    Rule,
    RuleConfig,
    RuleMetadata,
    clear_rules,
    get_all_rules,
    get_rule,
    register_rule,
)
from agent_control_models import RuleResult


class _DummyConfig(RuleConfig):
    pass


def _make_class(*, name: str, available: bool = True) -> type[Rule[_DummyConfig]]:
    """Build a fresh Rule subclass with the supplied metadata name."""

    class _Dummy(Rule[_DummyConfig]):
        metadata = RuleMetadata(
            name=name,
            version="1.0.0",
            description="",
        )
        config_model = _DummyConfig

        @classmethod
        def is_available(cls) -> bool:
            return available

        async def evaluate(self, data: Any) -> RuleResult:
            return RuleResult(matched=False, confidence=1.0, message="")

    _Dummy.__name__ = f"Dummy_{name.replace('-', '_')}"
    return _Dummy


@pytest.fixture
def isolated_registry():
    """Snapshot and restore the global registry so tests don't leak state."""
    snapshot = dict(get_all_rules())
    clear_rules()
    yield
    clear_rules()
    for cls in snapshot.values():
        register_rule(cls)


def test_register_and_lookup_rule(isolated_registry):
    cls = _make_class(name="reg-a")

    register_rule(cls)

    assert get_rule("reg-a") is cls


def test_get_rule_returns_none_when_not_registered(isolated_registry):
    assert get_rule("does-not-exist") is None


def test_get_all_rules_returns_copy(isolated_registry):
    cls = _make_class(name="reg-copy")
    register_rule(cls)

    snapshot = get_all_rules()
    snapshot["evil"] = cls  # mutate the returned dict

    # Internal registry must not reflect external mutation.
    assert "evil" not in get_all_rules()


def test_register_is_idempotent_for_same_class(isolated_registry):
    cls = _make_class(name="reg-idem")

    register_rule(cls)
    # Registering the exact same class again must not raise.
    assert register_rule(cls) is cls


def test_register_rejects_name_collision_with_different_class(isolated_registry):
    first = _make_class(name="reg-conflict")
    second = _make_class(name="reg-conflict")
    register_rule(first)

    with pytest.raises(ValueError, match="already registered"):
        register_rule(second)


def test_register_skips_unavailable_rules(isolated_registry):
    cls = _make_class(name="reg-unavailable", available=False)

    # Should not raise and should not register.
    assert register_rule(cls) is cls
    assert get_rule("reg-unavailable") is None


def test_clear_rules_empties_registry(isolated_registry):
    register_rule(_make_class(name="reg-c1"))
    register_rule(_make_class(name="reg-c2"))
    assert len(get_all_rules()) == 2

    clear_rules()

    assert get_all_rules() == {}


def test_register_decorator_returns_class(isolated_registry):
    cls = _make_class(name="reg-decorator")
    # The function is documented as decorator-compatible: it must return the class.
    decorated = register_rule(cls)
    assert decorated is cls
