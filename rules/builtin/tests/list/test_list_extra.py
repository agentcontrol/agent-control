"""Targeted tests covering match_mode branches and edge-case messages."""

from __future__ import annotations

import pytest
from agent_control_rules.list.config import ListRuleConfig
from agent_control_rules.list.rule import ListRule


@pytest.mark.asyncio
async def test_match_mode_contains_uses_word_boundary():
    """contains mode matches whole words but rejects sub-word matches."""
    config = ListRuleConfig(values=["admin"], match_mode="contains")
    rule = ListRule(config)

    matched = await rule.evaluate("the admin user logged in")
    assert matched.matched is True

    not_matched = await rule.evaluate("administrator")  # sub-word, no boundary
    assert not_matched.matched is False


@pytest.mark.asyncio
async def test_match_mode_exact_is_the_default():
    """No explicit mode uses anchored exact matching."""
    config = ListRuleConfig(values=["admin"])
    rule = ListRule(config)

    exact = await rule.evaluate("admin")
    assert exact.matched is True

    partial = await rule.evaluate("admin user")  # not anchored end
    assert partial.matched is False


@pytest.mark.asyncio
async def test_data_none_returns_empty_input_message():
    """None input is treated as empty and the control is ignored."""
    config = ListRuleConfig(values=["x"])
    rule = ListRule(config)

    result = await rule.evaluate(None)

    assert result.matched is False
    assert result.message == "Empty input - control ignored"
    assert result.metadata["input_count"] == 0


@pytest.mark.asyncio
async def test_message_truncates_match_list_at_five():
    """More than five matches collapse into a ``(+N more)`` suffix."""
    config = ListRuleConfig(
        values=["a", "b", "c", "d", "e", "f", "g"],
        logic="any",
    )
    rule = ListRule(config)

    result = await rule.evaluate(["a", "b", "c", "d", "e", "f", "g"])

    assert result.matched is True
    # First five matches appear, the rest summarized.
    assert "a, b, c, d, e" in result.message
    assert "(+2 more)" in result.message
