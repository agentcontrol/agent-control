"""Unit tests for Google ADK plugin integration."""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_control import ControlSteerError, ControlViolationError
from agent_control._state import state


class MockBasePlugin:
    def __init__(self, name: str | None = None):
        self.base_name = name


class MockPart:
    def __init__(self, text: str | None = None):
        self.text = text


class MockContent:
    def __init__(self, role: str = "user", parts: list[object] | None = None):
        self.role = role
        self.parts = parts or []


class MockConfig:
    def __init__(self, system_instruction: str | None = None):
        self.system_instruction = system_instruction


class MockLlmRequest:
    def __init__(self, text: str = "hello", config: object | None = None):
        self.contents = [SimpleNamespace(parts=[MockPart(text)])]
        self.config = config if config is not None else MockConfig()


class MockLlmResponse:
    def __init__(self, content: object):
        self.content = content


class MockTool:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description

    def run(self, city: str) -> dict[str, str]:
        return {"city": city}


class MockToolContext:
    def __init__(self, agent_name: str | None = None):
        self.agent_name = agent_name


class MockCallbackContext:
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.agent = SimpleNamespace(name=agent_name, description=f"{agent_name} desc")


def _install_google_modules() -> None:
    google_mod = ModuleType("google")
    adk_mod = ModuleType("google.adk")
    callback_context_mod = ModuleType("google.adk.agents.callback_context")
    models_mod = ModuleType("google.adk.models")
    plugins_mod = ModuleType("google.adk.plugins")
    tools_mod = ModuleType("google.adk.tools")
    tool_context_mod = ModuleType("google.adk.tools.tool_context")
    genai_mod = ModuleType("google.genai")
    types_mod = ModuleType("google.genai.types")

    callback_context_mod.CallbackContext = MockCallbackContext
    models_mod.LlmRequest = MockLlmRequest
    models_mod.LlmResponse = MockLlmResponse
    plugins_mod.BasePlugin = MockBasePlugin
    tools_mod.BaseTool = MockTool
    tool_context_mod.ToolContext = MockToolContext
    types_mod.Content = MockContent
    types_mod.Part = MockPart
    genai_mod.types = types_mod

    sys.modules["google"] = google_mod
    sys.modules["google.adk"] = adk_mod
    sys.modules["google.adk.agents.callback_context"] = callback_context_mod
    sys.modules["google.adk.models"] = models_mod
    sys.modules["google.adk.plugins"] = plugins_mod
    sys.modules["google.adk.tools"] = tools_mod
    sys.modules["google.adk.tools.tool_context"] = tool_context_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod


@pytest.fixture
def plugin_module():
    _install_google_modules()
    for name in (
        "agent_control.integrations.google_adk._extractors",
        "agent_control.integrations.google_adk.plugin",
    ):
        sys.modules.pop(name, None)
    module = importlib.import_module("agent_control.integrations.google_adk.plugin")
    yield module
    for name in (
        "agent_control.integrations.google_adk._extractors",
        "agent_control.integrations.google_adk.plugin",
    ):
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def reset_state():
    original_agent = state.current_agent
    original_server_url = state.server_url
    original_api_key = state.api_key
    original_controls = state.server_controls
    state.current_agent = None
    state.server_url = None
    state.api_key = None
    state.server_controls = None
    yield
    state.current_agent = original_agent
    state.server_url = original_server_url
    state.api_key = original_api_key
    state.server_controls = original_controls


def test_init_rejects_mismatched_current_agent(plugin_module):
    state.current_agent = SimpleNamespace(agent_name="different-agent")

    with pytest.raises(ValueError, match="must match"):
        plugin_module.AgentControlPlugin(agent_name="test-agent01")


@pytest.mark.asyncio
async def test_before_model_safe(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("researcher")
    request = MockLlmRequest("hello")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ) as mock_eval, patch.object(plugin, "_schedule_step_sync") as mock_schedule:
        result = await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert result is None
    assert request.config.system_instruction is None
    mock_schedule.assert_called_once()
    assert mock_eval.await_args.args[1] == "researcher"


@pytest.mark.asyncio
async def test_before_model_deny_returns_blocked_response(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer")
    request = MockLlmRequest("hello")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(side_effect=ControlViolationError(control_name="c1", message="Denied")),
    ):
        result = await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert isinstance(result, MockLlmResponse)
    assert result.content.parts[0].text == "Denied"


@pytest.mark.asyncio
async def test_before_model_steer_injects_guidance(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer")
    request = MockLlmRequest("hello", config=MockConfig("Existing"))

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(
            side_effect=ControlSteerError(
                control_name="c1",
                message="Steer",
                steering_context="Rewrite safely",
            )
        ),
    ):
        result = await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert result is None
    assert "Rewrite safely" in request.config.system_instruction


@pytest.mark.asyncio
async def test_before_model_steer_falls_back_to_blocked_response(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer")
    request = MockLlmRequest("hello")
    request.config = None

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(
            side_effect=ControlSteerError(
                control_name="c1",
                message="Steer",
                steering_context="Rewrite safely",
            )
        ),
    ):
        result = await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert isinstance(result, MockLlmResponse)
    assert result.content.parts[0].text == "Rewrite safely"


@pytest.mark.asyncio
async def test_after_model_steer_returns_replacement_response(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer")
    response = MockLlmResponse(MockContent(role="model", parts=[MockPart("unsafe")]))
    plugin._request_text_by_context_key[plugin._context_key(context)] = "hello"

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(
            side_effect=ControlSteerError(
                control_name="c1",
                message="Steer",
                steering_context="Please rewrite",
            )
        ),
    ):
        result = await plugin.after_model_callback(
            callback_context=context,
            llm_response=response,
        )

    assert isinstance(result, MockLlmResponse)
    assert result.content.parts[0].text == "Please rewrite"


@pytest.mark.asyncio
async def test_before_tool_deny_returns_blocked_dict(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    tool = MockTool("get_weather", "Weather tool")
    tool_context = MockToolContext()

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(side_effect=ControlViolationError(control_name="c1", message="Nope")),
    ):
        result = await plugin.before_tool_callback(
            tool=tool,
            tool_args={"city": "Pyongyang"},
            tool_context=tool_context,
        )

    assert result == {"status": "blocked", "message": "Nope"}


@pytest.mark.asyncio
async def test_after_tool_unexpected_error_blocks(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    tool = MockTool("get_weather")
    tool_context = MockToolContext()

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await plugin.after_tool_callback(
            tool=tool,
            tool_args={"city": "Paris"},
            tool_context=tool_context,
            result={"city": "Paris"},
        )

    assert result["status"] == "blocked"
    assert "could not evaluate" in result["message"]


@pytest.mark.asyncio
async def test_enabled_hooks_skip_evaluation(plugin_module):
    plugin = plugin_module.AgentControlPlugin(
        agent_name="test-agent01",
        enabled_hooks={"before_tool"},
    )
    context = MockCallbackContext("writer")
    request = MockLlmRequest("hello")

    with patch.object(plugin_module, "_evaluate_and_enforce", AsyncMock()) as mock_eval:
        result = await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert result is None
    mock_eval.assert_not_called()


@pytest.mark.asyncio
async def test_step_name_overrides_apply(plugin_module):
    plugin = plugin_module.AgentControlPlugin(
        agent_name="test-agent01",
        step_name_overrides={"writer": "compliance-writer"},
    )
    context = MockCallbackContext("writer")
    request = MockLlmRequest("hello")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ) as mock_eval:
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert mock_eval.await_args.args[1] == "compliance-writer"


@pytest.mark.asyncio
async def test_step_name_resolver_applies(plugin_module):
    plugin = plugin_module.AgentControlPlugin(
        agent_name="test-agent01",
        step_name_resolver=lambda **kwargs: f"resolved:{kwargs['default_name']}",
    )
    context = MockCallbackContext("writer")
    request = MockLlmRequest("hello")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ) as mock_eval:
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert mock_eval.await_args.args[1] == "resolved:writer"


def test_bind_discovers_root_sub_agents_and_tools(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    root = SimpleNamespace(
        name="planner",
        tools=[MockTool("search_docs")],
        sub_agents=[SimpleNamespace(name="writer", tools=[MockTool("save_draft")])],
    )

    with patch.object(plugin, "_sync_steps_blocking") as mock_sync:
        plugin.bind(root)

    assert ("llm", "planner") in plugin._known_steps
    assert ("llm", "writer") in plugin._known_steps
    assert ("tool", "search_docs") in plugin._known_steps
    assert ("tool", "save_draft") in plugin._known_steps
    mock_sync.assert_called_once()


@pytest.mark.asyncio
async def test_lazy_step_sync_when_bind_skipped(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer")
    request = MockLlmRequest("hello")

    with patch.object(plugin, "_schedule_step_sync") as mock_schedule, patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ):
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    mock_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_lazy_step_sync_deduplicates_inflight_task(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    step = plugin._build_llm_step_schema("writer")

    gate = asyncio.Future()

    async def slow_sync(steps):
        await gate

    with patch.object(plugin, "_sync_steps_async", side_effect=slow_sync):
        plugin._ensure_step_known(step)
        plugin._ensure_step_known(step)

        assert len(plugin._step_sync_tasks) == 1

        gate.set_result(None)
        await asyncio.gather(*plugin._step_sync_tasks.values())

    assert not plugin._step_sync_tasks


def test_context_key_prefers_object_identity(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer")

    assert plugin._context_key(context) is context


def test_context_key_falls_back_to_id_for_unhashable_callback(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")

    class UnhashableCallback:
        __hash__ = None

    context = UnhashableCallback()

    assert plugin._context_key(context) == id(context)


@pytest.mark.asyncio
async def test_close_cancels_tasks_and_clears_request_cache(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    plugin._request_text_by_context_key["ctx"] = "hello"

    gate = asyncio.Future()

    async def slow_task():
        await gate

    task = asyncio.create_task(slow_task())
    plugin._step_sync_tasks[("llm", "writer")] = task

    await plugin.close()

    assert plugin._request_text_by_context_key == {}
    assert plugin._step_sync_tasks == {}
    assert task.cancelled()


@pytest.mark.asyncio
async def test_on_violation_callback_receives_metadata(plugin_module):
    callback = MagicMock()
    plugin = plugin_module.AgentControlPlugin(
        agent_name="test-agent01",
        on_violation_callback=callback,
    )
    tool = MockTool("get_weather")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(side_effect=ControlViolationError(control_name="c1", message="Denied")),
    ):
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"city": "Rome"},
            tool_context=MockToolContext(),
        )

    metadata, payload = callback.call_args.args
    assert metadata["step_name"] == "get_weather"
    assert metadata["stage"] == "pre"
    assert payload["action"] == "deny"
