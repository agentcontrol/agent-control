"""Tests for init() step merge wiring into register_agent."""

from __future__ import annotations

from collections.abc import Generator
import logging
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

import agent_control
from agent_control._control_registry import clear, register


@pytest.fixture(autouse=True)
def _clean_registry() -> Generator[None, None, None]:
    """Ensure each test starts with an empty step registry."""
    clear()
    yield
    clear()


def test_init_passes_merged_steps_to_register_agent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given one auto-discovered step and explicit steps including a conflicting override.
    def auto_llm(query: str) -> str:
        """Auto-discovered step."""
        ...

    register(auto_llm)
    explicit_steps = [
        {
            "type": "llm",
            "name": "auto_llm",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "output_schema": {"type": "string"},
            "description": "Explicit override for auto_llm.",
        },
        {
            "type": "tool",
            "name": "manual_tool",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
            "output_schema": {"type": "string"},
        },
    ]

    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})

    # When init() performs registration with patched network-facing calls.
    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ):
        with caplog.at_level(logging.WARNING):
            agent_control.init(
                agent_name="Init Merge Agent",
                agent_id=str(uuid4()),
                steps=explicit_steps,
            )

    # Then register_agent() receives merged steps with explicit precedence on conflicts.
    assert register_agent_mock.await_count == 1
    assert register_agent_mock.await_args is not None
    merged_steps = register_agent_mock.await_args.kwargs["steps"]

    llm_entries = [s for s in merged_steps if (s["type"], s["name"]) == ("llm", "auto_llm")]
    assert len(llm_entries) == 1
    assert llm_entries[0]["description"] == "Explicit override for auto_llm."
    assert any((s["type"], s["name"]) == ("tool", "manual_tool") for s in merged_steps)
    assert "Skipping 1 auto-discovered step(s) overridden by explicit steps" in caplog.text
