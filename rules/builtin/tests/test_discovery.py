"""Tests for entry-point-based rule discovery."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from agent_control_models import RuleResult
from agent_control_rules import (
    Rule,
    RuleConfig,
    RuleMetadata,
    clear_rules,
    discover_rules,
    ensure_rules_discovered,
    get_all_rules,
    list_rules,
    register_rule,
    reset_rule_discovery,
)
from agent_control_rules import _discovery as discovery_module


class _DiscoveryConfig(RuleConfig):
    pass


def _make_class(*, name: str, available: bool = True) -> type[Rule[_DiscoveryConfig]]:
    class _Dummy(Rule[_DiscoveryConfig]):
        metadata = RuleMetadata(name=name, version="1.0.0", description="")
        config_model = _DiscoveryConfig

        @classmethod
        def is_available(cls) -> bool:
            return available

        async def evaluate(self, data: Any) -> RuleResult:
            return RuleResult(matched=False, confidence=1.0, message="")

    _Dummy.__name__ = f"Discovery_{name.replace('-', '_')}"
    return _Dummy


@pytest.fixture
def isolated_discovery():
    """Snapshot registry + discovery flag, restore on teardown."""
    snapshot = dict(get_all_rules())
    clear_rules()
    reset_rule_discovery()
    yield
    clear_rules()
    reset_rule_discovery()
    for cls in snapshot.values():
        register_rule(cls)


def _make_fake_entry_point(name: str, rule_class: type[Any]) -> MagicMock:
    """Build a MagicMock that mimics importlib.metadata.EntryPoint."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = rule_class
    return ep


def test_discover_rules_registers_available_classes(isolated_discovery):
    """Discover walks the entry-point group and registers each available class."""
    cls = _make_class(name="disc-a")
    fake_ep = _make_fake_entry_point("disc-a", cls)

    with patch.object(discovery_module, "entry_points", return_value=[fake_ep]):
        count = discover_rules()

    assert count == 1
    assert get_all_rules().get("disc-a") is cls


def test_discover_rules_skips_unavailable_classes(isolated_discovery):
    """Rules whose is_available() is False must NOT be registered."""
    cls = _make_class(name="disc-unavailable", available=False)
    fake_ep = _make_fake_entry_point("disc-unavailable", cls)

    with patch.object(discovery_module, "entry_points", return_value=[fake_ep]):
        count = discover_rules()

    assert count == 0
    assert "disc-unavailable" not in get_all_rules()


def test_discover_rules_skips_already_registered(isolated_discovery):
    """Already-registered names are skipped without raising."""
    cls = _make_class(name="disc-existing")
    register_rule(cls)

    fake_ep = _make_fake_entry_point("disc-existing", cls)
    with patch.object(discovery_module, "entry_points", return_value=[fake_ep]):
        count = discover_rules()

    assert count == 0


def test_discover_rules_only_runs_once(isolated_discovery):
    """Repeat calls short-circuit on the _DISCOVERY_COMPLETE flag."""
    cls = _make_class(name="disc-once")
    fake_ep = _make_fake_entry_point("disc-once", cls)

    with patch.object(
        discovery_module, "entry_points", return_value=[fake_ep]
    ) as patched:
        first = discover_rules()
        second = discover_rules()

    # First call discovers, second returns 0 without consulting entry_points.
    assert first == 1
    assert second == 0
    assert patched.call_count == 1


def test_discover_rules_swallows_load_failures(isolated_discovery):
    """A broken entry point is logged and skipped, not propagated."""
    bad_ep = MagicMock()
    bad_ep.name = "broken"
    bad_ep.load.side_effect = RuntimeError("boom")

    good_cls = _make_class(name="disc-good")
    good_ep = _make_fake_entry_point("disc-good", good_cls)

    with patch.object(discovery_module, "entry_points", return_value=[bad_ep, good_ep]):
        count = discover_rules()

    assert count == 1
    assert get_all_rules().get("disc-good") is good_cls


def test_discover_rules_handles_entry_points_failure(isolated_discovery):
    """If entry_points() itself raises, discovery completes with zero results."""
    with patch.object(
        discovery_module,
        "entry_points",
        side_effect=RuntimeError("entry-point system unavailable"),
    ):
        count = discover_rules()

    assert count == 0


def test_discover_rules_falls_back_to_builtin_source_imports(isolated_discovery):
    """Source-tree runs without entry point metadata still load builtin rules."""
    with patch.object(discovery_module, "entry_points", return_value=[]):
        count = discover_rules()

    assert count == 4
    assert set(get_all_rules()) == {"json", "list", "regex", "sql"}


def test_builtin_source_discovery_skips_broken_imports(
    isolated_discovery,
    monkeypatch: pytest.MonkeyPatch,
):
    """A broken builtin source import is logged and skipped."""
    monkeypatch.setattr(
        discovery_module,
        "_BUILTIN_RULES",
        (("broken", "agent_control_rules.does_not_exist", "MissingRule"),),
    )

    assert discovery_module._discover_builtin_rules_from_source() == 0
    assert get_all_rules() == {}


def test_reset_rule_discovery_allows_rerun(isolated_discovery):
    """reset_rule_discovery clears the completed flag so discover runs again."""
    cls = _make_class(name="disc-reset")
    fake_ep = _make_fake_entry_point("disc-reset", cls)

    with patch.object(
        discovery_module, "entry_points", return_value=[fake_ep]
    ) as patched:
        discover_rules()
        clear_rules()
        reset_rule_discovery()
        count = discover_rules()

    assert count == 1
    assert patched.call_count == 2


def test_ensure_rules_discovered_runs_once(isolated_discovery):
    """ensure_rules_discovered is the lazy-init entry point."""
    cls = _make_class(name="disc-ensure")
    fake_ep = _make_fake_entry_point("disc-ensure", cls)

    with patch.object(
        discovery_module, "entry_points", return_value=[fake_ep]
    ) as patched:
        ensure_rules_discovered()
        ensure_rules_discovered()

    assert patched.call_count == 1
    assert get_all_rules().get("disc-ensure") is cls


def test_list_rules_triggers_discovery(isolated_discovery):
    """list_rules is the convenience accessor; it must trigger discovery."""
    cls = _make_class(name="disc-list")
    fake_ep = _make_fake_entry_point("disc-list", cls)

    with patch.object(discovery_module, "entry_points", return_value=[fake_ep]):
        result = list_rules()

    assert result.get("disc-list") is cls
