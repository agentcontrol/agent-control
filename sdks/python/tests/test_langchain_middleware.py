"""Unit tests for LangChain AgentMiddleware integration."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_control_models import Agent, ControlMatch, EvaluationResult, EvaluatorResult, SteeringContext
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolRuntime

from agent_control.integrations.langchain.middleware import AgentControlMiddleware


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


def _tool_request(
    tool_obj: Any,
    *,
    text: str = "hello",
    tool_call_id: str = "call-1",
) -> ToolCallRequest:
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


def _model_request(tools: list[Any]) -> Any:
    return SimpleNamespace(tools=tools)


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
def langchain_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch Agent Control environment and registration dependencies."""
    from agent_control.integrations import _tool_controls as shared

    current_agent = Agent(
        agent_name="test-agent-123",
        agent_description="Test agent",
        agent_version="1.0.0",
    )
    register_agent = AsyncMock(return_value={})
    refresh_controls = MagicMock(return_value=[])
    refresh_controls_async = AsyncMock(return_value=[])
    evaluate_controls = AsyncMock(return_value=_safe_result())

    monkeypatch.setattr(shared.agent_control, "current_agent", lambda: current_agent)
    monkeypatch.setattr(shared.sdk_state, "server_url", "http://example.test")
    monkeypatch.setattr(shared.sdk_state, "api_key", "secret")
    monkeypatch.setattr(shared, "AgentControlClient", _DummyClient)
    monkeypatch.setattr(shared.agents, "register_agent", register_agent)
    monkeypatch.setattr(shared.agent_control, "refresh_controls", refresh_controls)
    monkeypatch.setattr(shared.agent_control, "refresh_controls_async", refresh_controls_async)
    monkeypatch.setattr(shared.agent_control, "evaluate_controls", evaluate_controls)

    return {
        "agent": current_agent,
        "register_agent": register_agent,
        "refresh_controls": refresh_controls,
        "refresh_controls_async": refresh_controls_async,
        "evaluate_controls": evaluate_controls,
    }


def test_model_wrapper_registers_full_tool_list(langchain_env: dict[str, Any]) -> None:
    middleware = AgentControlMiddleware()
    request = _model_request([echo_tool, other_tool])
    handler = MagicMock(return_value="model-response")

    response = middleware.wrap_model_call(request, handler)

    assert response == "model-response"
    register_agent = langchain_env["register_agent"]
    assert register_agent.await_count == 1
    _, kwargs = register_agent.await_args
    assert kwargs["conflict_mode"] == "overwrite"
    assert {step["name"] for step in kwargs["steps"]} == {"echo_tool", "other_tool"}
    langchain_env["refresh_controls"].assert_called_once_with()


def test_sync_tool_wrapper_allows_tool_output(langchain_env: dict[str, Any]) -> None:
    middleware = AgentControlMiddleware()
    middleware.wrap_model_call(_model_request([echo_tool]), MagicMock(return_value="ok"))
    request = _tool_request(echo_tool)
    handler = MagicMock(
        return_value=ToolMessage(content="allowed", name="echo_tool", tool_call_id="call-1")
    )

    response = middleware.wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.content == "allowed"
    assert langchain_env["evaluate_controls"].await_count == 2


@pytest.mark.asyncio
async def test_async_tool_wrapper_allows_tool_output(langchain_env: dict[str, Any]) -> None:
    middleware = AgentControlMiddleware()
    await middleware.awrap_model_call(
        _model_request([echo_tool]),
        AsyncMock(return_value="ok"),
    )
    request = _tool_request(echo_tool)

    async def handler(_: Any) -> ToolMessage:
        return ToolMessage(content="allowed", name="echo_tool", tool_call_id="call-1")

    response = await middleware.awrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.content == "allowed"
    assert langchain_env["evaluate_controls"].await_count == 2


def test_deny_returns_error_tool_message(langchain_env: dict[str, Any]) -> None:
    langchain_env["evaluate_controls"].return_value = _deny_result("Query blocked")
    middleware = AgentControlMiddleware()
    middleware.wrap_model_call(_model_request([echo_tool]), MagicMock(return_value="ok"))
    request = _tool_request(echo_tool)
    handler = MagicMock()

    response = middleware.wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.status == "error"
    assert response.tool_call_id == "call-1"
    assert "blocked due to security policy" in str(response.content)
    assert "Query blocked" in str(response.content)
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_steer_returns_error_tool_message_with_guidance(
    langchain_env: dict[str, Any]
) -> None:
    langchain_env["evaluate_controls"].return_value = _steer_result("Try a safer query")
    middleware = AgentControlMiddleware()
    await middleware.awrap_model_call(_model_request([echo_tool]), AsyncMock(return_value="ok"))
    request = _tool_request(echo_tool)

    async def handler(_: Any) -> ToolMessage:
        return ToolMessage(content="allowed", name="echo_tool", tool_call_id="call-1")

    response = await middleware.awrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.status == "error"
    assert "Guidance: Try a safer query" in str(response.content)


def test_evaluation_errors_fail_closed(langchain_env: dict[str, Any]) -> None:
    langchain_env["evaluate_controls"].return_value = _error_result()
    middleware = AgentControlMiddleware()
    middleware.wrap_model_call(_model_request([echo_tool]), MagicMock(return_value="ok"))
    request = _tool_request(echo_tool)
    handler = MagicMock()

    response = middleware.wrap_tool_call(request, handler)

    assert isinstance(response, ToolMessage)
    assert response.status == "error"
    assert "policy evaluation failed" in str(response.content)
    handler.assert_not_called()


def test_model_resync_failure_is_fail_open_and_logged(
    langchain_env: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_agent = langchain_env["register_agent"]
    register_agent.side_effect = [{}, RuntimeError("resync failed")]
    middleware = AgentControlMiddleware()
    middleware.wrap_model_call(_model_request([echo_tool]), MagicMock(return_value="ok"))
    handler = MagicMock(return_value="model-response")

    response = middleware.wrap_model_call(_model_request([echo_tool, other_tool]), handler)

    assert response == "model-response"
    assert register_agent.await_count == 2
    assert "re-registration failed" in caplog.text


def test_omitted_agent_name_resolves_from_current_agent(langchain_env: dict[str, Any]) -> None:
    middleware = AgentControlMiddleware()
    middleware.wrap_model_call(_model_request([echo_tool]), MagicMock(return_value="ok"))

    args, _ = langchain_env["register_agent"].await_args
    assert args[1].agent_name == langchain_env["agent"].agent_name


def test_missing_initialized_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_control.integrations import _tool_controls as shared

    monkeypatch.setattr(shared.agent_control, "current_agent", lambda: None)

    with pytest.raises(RuntimeError, match="Call agent_control.init"):
        AgentControlMiddleware()
