"""Unit tests for LangGraph ToolNode integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_control_models import Agent, ControlMatch, EvaluationResult, EvaluatorResult, SteeringContext
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolRuntime

from agent_control.integrations.langgraph.tool_node import create_controlled_tool_node


class _DummyClient:
    """Minimal async client used to patch AgentControlClient in tests."""

    def __init__(self, *, base_url: str, api_key: str | None) -> None:
        self.base_url = base_url
        self.api_key = api_key

    async def __aenter__(self) -> "_DummyClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


@tool
def echo_tool(text: str) -> str:
    """Echo text."""
    return text


@tool
def other_tool(text: str) -> str:
    """Return a second tool result."""
    return f"other:{text}"


def _tool_request(tool_obj: Any, *, text: str = "hello", tool_call_id: str = "call-1") -> ToolCallRequest:
    runtime = ToolRuntime(
        state={},
        context=None,
        config={},
        stream_writer=lambda *_args, **_kwargs: None,
        tool_call_id=tool_call_id,
        store=None,
    )
    tool_call = {
        "name": tool_obj.name,
        "args": {"text": text},
        "id": tool_call_id,
        "type": "tool_call",
    }
    return ToolCallRequest(tool_call=tool_call, tool=tool_obj, state={}, runtime=runtime)


def _safe_result() -> EvaluationResult:
    return EvaluationResult(is_safe=True, confidence=1.0, reason=None, matches=None, errors=None)


def _deny_result(message: str = "Not allowed") -> EvaluationResult:
    return EvaluationResult(
        is_safe=False,
        confidence=1.0,
        reason=None,
        matches=[
            ControlMatch(
                control_id=1,
                control_name="deny-control",
                action="deny",
                result=EvaluatorResult(matched=True, confidence=1.0, message=message),
            )
        ],
        errors=None,
    )


def _steer_result(message: str = "Adjust the tool call") -> EvaluationResult:
    return EvaluationResult(
        is_safe=False,
        confidence=1.0,
        reason=None,
        matches=[
            ControlMatch(
                control_id=2,
                control_name="steer-control",
                action="steer",
                result=EvaluatorResult(matched=True, confidence=1.0, message="Steer required"),
                steering_context=SteeringContext(message=message),
            )
        ],
        errors=None,
    )


def _error_result() -> EvaluationResult:
    return EvaluationResult(
        is_safe=True,
        confidence=1.0,
        reason=None,
        matches=None,
        errors=[
            ControlMatch(
                control_id=3,
                control_name="error-control",
                action="log",
                result=EvaluatorResult(
                    matched=False,
                    confidence=0.0,
                    message="broken",
                    error="broken",
                ),
            )
        ],
    )


@pytest.fixture
def langgraph_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch Agent Control environment and registration dependencies."""
    from agent_control.integrations.langgraph import tool_node as module

    current_agent = Agent(
        agent_name="test-agent-123",
        agent_description="Test agent",
        agent_version="1.0.0",
    )
    register_agent = AsyncMock(return_value={})
    refresh_controls = MagicMock(return_value=[])
    refresh_controls_async = AsyncMock(return_value=[])
    evaluate_controls = AsyncMock(return_value=_safe_result())

    monkeypatch.setattr(module.agent_control, "current_agent", lambda: current_agent)
    monkeypatch.setattr(module.sdk_state, "server_url", "http://example.test")
    monkeypatch.setattr(module.sdk_state, "api_key", "secret")
    monkeypatch.setattr(module, "AgentControlClient", _DummyClient)
    monkeypatch.setattr(module.agents, "register_agent", register_agent)
    monkeypatch.setattr(module.agent_control, "refresh_controls", refresh_controls)
    monkeypatch.setattr(module.agent_control, "refresh_controls_async", refresh_controls_async)
    monkeypatch.setattr(module.agent_control, "evaluate_controls", evaluate_controls)

    return {
        "module": module,
        "agent": current_agent,
        "register_agent": register_agent,
        "refresh_controls": refresh_controls,
        "refresh_controls_async": refresh_controls_async,
        "evaluate_controls": evaluate_controls,
    }


def test_initial_registration_sends_full_tool_list(langgraph_env: dict[str, Any]) -> None:
    node = create_controlled_tool_node([echo_tool, other_tool])

    assert node.tools_by_name.keys() == {"echo_tool", "other_tool"}
    register_agent = langgraph_env["register_agent"]
    assert register_agent.await_count == 1

    _, kwargs = register_agent.await_args
    assert kwargs["conflict_mode"] == "overwrite"
    assert {step["name"] for step in kwargs["steps"]} == {"echo_tool", "other_tool"}
    assert all(step["type"] == "tool" for step in kwargs["steps"])


def test_successful_registration_triggers_public_refresh(langgraph_env: dict[str, Any]) -> None:
    create_controlled_tool_node([echo_tool])

    langgraph_env["refresh_controls"].assert_called_once_with()


def test_sync_wrapper_allows_tool_output(langgraph_env: dict[str, Any]) -> None:
    node = create_controlled_tool_node([echo_tool])
    request = _tool_request(node.tools_by_name["echo_tool"])
    handler = MagicMock(
        return_value=ToolMessage(
            content="allowed",
            name="echo_tool",
            tool_call_id="call-1",
        )
    )

    response = node._wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.content == "allowed"
    assert langgraph_env["evaluate_controls"].await_count == 2


@pytest.mark.asyncio
async def test_async_wrapper_allows_tool_output(langgraph_env: dict[str, Any]) -> None:
    node = create_controlled_tool_node([echo_tool])
    request = _tool_request(node.tools_by_name["echo_tool"])

    async def handler(_: Any) -> ToolMessage:
        return ToolMessage(content="allowed", name="echo_tool", tool_call_id="call-1")

    response = await node._awrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.content == "allowed"
    assert langgraph_env["evaluate_controls"].await_count == 2


def test_deny_returns_error_tool_message(langgraph_env: dict[str, Any]) -> None:
    langgraph_env["evaluate_controls"].return_value = _deny_result("Query blocked")
    node = create_controlled_tool_node([echo_tool])
    request = _tool_request(node.tools_by_name["echo_tool"])
    handler = MagicMock()

    response = node._wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.status == "error"
    assert response.tool_call_id == "call-1"
    assert "blocked due to security policy" in str(response.content)
    assert "Query blocked" in str(response.content)
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_steer_returns_error_tool_message_with_guidance(
    langgraph_env: dict[str, Any]
) -> None:
    langgraph_env["evaluate_controls"].return_value = _steer_result("Try a safer query")
    node = create_controlled_tool_node([echo_tool])
    request = _tool_request(node.tools_by_name["echo_tool"])

    async def handler(_: Any) -> ToolMessage:
        return ToolMessage(content="allowed", name="echo_tool", tool_call_id="call-1")

    response = await node._awrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.status == "error"
    assert "Guidance: Try a safer query" in str(response.content)


def test_evaluation_errors_fail_closed(langgraph_env: dict[str, Any]) -> None:
    langgraph_env["evaluate_controls"].return_value = _error_result()
    node = create_controlled_tool_node([echo_tool])
    request = _tool_request(node.tools_by_name["echo_tool"])
    handler = MagicMock()

    response = node._wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.status == "error"
    assert "policy evaluation failed" in str(response.content)
    handler.assert_not_called()


def test_evaluation_exception_fails_closed(langgraph_env: dict[str, Any]) -> None:
    langgraph_env["evaluate_controls"].side_effect = RuntimeError("boom")
    node = create_controlled_tool_node([echo_tool])
    request = _tool_request(node.tools_by_name["echo_tool"])
    handler = MagicMock()

    response = node._wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.status == "error"
    assert "policy evaluation failed" in str(response.content)
    handler.assert_not_called()


def test_resync_failure_is_fail_open_and_logged(
    langgraph_env: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_agent = langgraph_env["register_agent"]
    register_agent.side_effect = [{}, RuntimeError("resync failed")]
    node = create_controlled_tool_node([echo_tool])
    node.tools_by_name["other_tool"] = other_tool
    request = _tool_request(node.tools_by_name["echo_tool"])
    handler = MagicMock(
        return_value=ToolMessage(content="allowed", name="echo_tool", tool_call_id="call-1")
    )

    response = node._wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.content == "allowed"
    assert register_agent.await_count == 2
    assert "re-registration failed" in caplog.text


def test_tool_name_change_causes_full_reregistration(langgraph_env: dict[str, Any]) -> None:
    node = create_controlled_tool_node([echo_tool])
    node.tools_by_name["other_tool"] = other_tool
    request = _tool_request(node.tools_by_name["echo_tool"])
    handler = MagicMock(
        return_value=ToolMessage(content="allowed", name="echo_tool", tool_call_id="call-1")
    )

    node._wrap_tool_call(request, handler)

    register_agent = langgraph_env["register_agent"]
    assert register_agent.await_count == 2
    _, kwargs = register_agent.await_args
    assert {step["name"] for step in kwargs["steps"]} == {"echo_tool", "other_tool"}


def test_omitted_agent_name_resolves_from_current_agent(langgraph_env: dict[str, Any]) -> None:
    create_controlled_tool_node([echo_tool])

    args, _ = langgraph_env["register_agent"].await_args
    assert args[1].agent_name == langgraph_env["agent"].agent_name


def test_missing_initialized_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_control.integrations.langgraph import tool_node as module

    monkeypatch.setattr(module.agent_control, "current_agent", lambda: None)

    with pytest.raises(RuntimeError, match="Call agent_control.init"):
        create_controlled_tool_node([echo_tool])
