"""Targeted tests covering match_mode branches and edge-case messages."""

from __future__ import annotations

import pytest
from agent_control_evaluators.list.config import ListEvaluatorConfig
from agent_control_evaluators.list.evaluator import ListEvaluator


@pytest.mark.asyncio
async def test_match_mode_contains_uses_word_boundary():
    """contains mode matches whole words but rejects sub-word matches."""
    config = ListEvaluatorConfig(values=["admin"], match_mode="contains")
    evaluator = ListEvaluator(config)

    matched = await evaluator.evaluate("the admin user logged in")
    assert matched.matched is True

    not_matched = await evaluator.evaluate("administrator")  # sub-word, no boundary
    assert not_matched.matched is False


@pytest.mark.asyncio
async def test_match_mode_exact_is_the_default():
    """No explicit mode uses anchored exact matching."""
    config = ListEvaluatorConfig(values=["admin"])
    evaluator = ListEvaluator(config)

    exact = await evaluator.evaluate("admin")
    assert exact.matched is True

    partial = await evaluator.evaluate("admin user")  # not anchored end
    assert partial.matched is False


@pytest.mark.asyncio
async def test_data_none_returns_empty_input_message():
    """None input is treated as empty and the control is ignored."""
    config = ListEvaluatorConfig(values=["x"])
    evaluator = ListEvaluator(config)

    result = await evaluator.evaluate(None)

    assert result.matched is False
    assert result.message == "Empty input - control ignored"
    assert result.metadata["input_count"] == 0


@pytest.mark.asyncio
async def test_message_truncates_match_list_at_five():
    """More than five matches collapse into a ``(+N more)`` suffix."""
    config = ListEvaluatorConfig(
        values=["a", "b", "c", "d", "e", "f", "g"],
        logic="any",
    )
    evaluator = ListEvaluator(config)

    result = await evaluator.evaluate(["a", "b", "c", "d", "e", "f", "g"])

    assert result.matched is True
    # First five matches appear, the rest summarized.
    assert "a, b, c, d, e" in result.message
    assert "(+2 more)" in result.message
