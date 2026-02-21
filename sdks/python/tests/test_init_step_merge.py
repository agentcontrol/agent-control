"""Tests for init() step merge wiring into register_agent."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import agent_control
import pytest
from agent_control._control_registry import clear, register

if TYPE_CHECKING:
    # Intentionally unavailable at runtime to trigger unresolved forward-ref fallback.
    class DoesNotExist: ...


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


def test_init_uses_auto_discovered_steps_from_control_decorator() -> None:
    # Given a real @control()-decorated async function and no explicit steps passed to init().
    from agent_control.control_decorators import control

    @control()
    async def auto_chat(message: str, temperature: float = 0.2) -> str:
        """Auto-discovered chat step."""
        return message

    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})

    # When init() performs registration.
    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ):
        agent_control.init(
            agent_name="Auto Discovery Agent",
            agent_id=str(uuid4()),
        )

    # Then register_agent() receives the auto-derived step schema payload.
    assert register_agent_mock.await_count == 1
    assert register_agent_mock.await_args is not None
    merged_steps = register_agent_mock.await_args.kwargs["steps"]

    auto_entries = [s for s in merged_steps if (s["type"], s["name"]) == ("llm", "auto_chat")]
    assert len(auto_entries) == 1
    auto_step = auto_entries[0]
    assert auto_step["description"] == "Auto-discovered chat step."
    assert auto_step["input_schema"]["properties"]["message"]["type"] == "string"
    assert auto_step["input_schema"]["properties"]["temperature"]["type"] == "number"
    assert auto_step["output_schema"]["type"] == "string"


def test_init_logs_fallback_warning_for_unresolved_type_hints(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given a decorated function whose forward reference cannot be resolved at runtime.
    from agent_control.control_decorators import control

    @control()
    async def unresolved(payload: DoesNotExist) -> str:
        """Function with unresolved forward reference."""
        return "ok"

    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})

    # When init() materializes auto-discovered steps.
    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ):
        with caplog.at_level(logging.WARNING):
            agent_control.init(
                agent_name="Fallback Warning Agent",
                agent_id=str(uuid4()),
            )

    # Then initialization continues, using fallback schemas and emitting a warning.
    assert register_agent_mock.await_count == 1
    assert register_agent_mock.await_args is not None
    merged_steps = register_agent_mock.await_args.kwargs["steps"]

    unresolved_entries = [
        s for s in merged_steps if (s["type"], s["name"]) == ("llm", "unresolved")
    ]
    assert len(unresolved_entries) == 1
    unresolved_step = unresolved_entries[0]
    assert unresolved_step["input_schema"] == {"type": "object", "additionalProperties": True}
    assert unresolved_step["output_schema"] == {}
    assert "failed to resolve type hints" in caplog.text
