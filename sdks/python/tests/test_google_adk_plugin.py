"""Unit tests for Google ADK plugin integration."""

from __future__ import annotations

import asyncio
import importlib
import logging
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
    def __init__(
        self,
        text: str = "hello",
        config: object | None = None,
        request_id: str | None = None,
    ):
        self.contents = [SimpleNamespace(parts=[MockPart(text)])]
        self.config = config if config is not None else MockConfig()
        self.request_id = request_id


class MockLlmResponse:
    def __init__(self, content: object, request_id: str | None = None):
        self.content = content
        self.request_id = request_id


class MockTool:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description

    def run(self, city: str) -> dict[str, str]:
        return {"city": city}


class MockToolContext:
    def __init__(
        self,
        agent_name: str | None = None,
        callback_context: object | None = None,
    ):
        self.agent_name = agent_name
        self.callback_context = callback_context


class MockCallbackContext:
    def __init__(self, agent_name: str, invocation_id: str | None = None):
        self.agent_name = agent_name
        self.invocation_id = invocation_id
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
    context = MockCallbackContext("writer", invocation_id="inv-1")
    request = MockLlmRequest("hello", request_id="call-1")

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
    assert plugin._request_text_by_call_key == {}
    assert plugin._current_llm_call_ids == {}


@pytest.mark.asyncio
async def test_before_model_steer_injects_guidance(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer", invocation_id="inv-1")
    request = MockLlmRequest("hello", config=MockConfig("Existing"), request_id="call-1")

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
    assert plugin._request_text_by_call_key == {("inv-1", "call-1"): "hello"}
    assert plugin._current_llm_call_ids == {"inv-1": ["call-1"]}


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
    context = MockCallbackContext("writer", invocation_id="inv-1")
    request = MockLlmRequest("hello", request_id="call-1")
    response = MockLlmResponse(
        MockContent(role="model", parts=[MockPart("unsafe")]),
        request_id="call-1",
    )

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(
            side_effect=[
                MagicMock(),
                ControlSteerError(
                    control_name="c1",
                    message="Steer",
                    steering_context="Please rewrite",
                ),
            ],
        ),
    ):
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )
        result = await plugin.after_model_callback(
            callback_context=context,
            llm_response=response,
        )

    assert isinstance(result, MockLlmResponse)
    assert result.content.parts[0].text == "Please rewrite"
    assert plugin._request_text_by_call_key == {}
    assert plugin._current_llm_call_ids == {}


@pytest.mark.asyncio
async def test_after_model_uses_request_id_correlation_for_multiple_inflight_calls(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer", invocation_id="inv-1")
    first_request = MockLlmRequest("first", request_id="call-1")
    second_request = MockLlmRequest("second", request_id="call-2")
    response = MockLlmResponse(
        MockContent(role="model", parts=[MockPart("done")]),
        request_id="call-1",
    )

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ) as mock_eval:
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=first_request,
        )
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=second_request,
        )
        await plugin.after_model_callback(
            callback_context=context,
            llm_response=response,
        )

    assert mock_eval.await_args_list[2].kwargs["input"] == "first"
    assert plugin._request_text_by_call_key == {("inv-1", "call-2"): "second"}
    assert plugin._current_llm_call_ids == {"inv-1": ["call-2"]}


@pytest.mark.asyncio
async def test_on_model_error_clears_pending_request_state(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer", invocation_id="inv-1")
    request = MockLlmRequest("hello", request_id="call-1")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ):
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    await plugin.on_model_error_callback(
        callback_context=context,
        llm_request=request,
        error=RuntimeError("boom"),
    )

    assert plugin._request_text_by_call_key == {}
    assert plugin._current_llm_call_ids == {}


@pytest.mark.asyncio
async def test_tool_callbacks_scope_step_name_by_agent(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    tool = MockTool("get_weather")
    tool_context = MockToolContext(agent_name="writer")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ) as mock_eval:
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"city": "Rome"},
            tool_context=tool_context,
        )

    assert mock_eval.await_args.args[1] == "writer.get_weather"


@pytest.mark.asyncio
async def test_tool_step_name_overrides_can_map_raw_name(plugin_module):
    plugin = plugin_module.AgentControlPlugin(
        agent_name="test-agent01",
        step_name_overrides={"get_weather": "weather-guard"},
    )
    tool = MockTool("get_weather")
    tool_context = MockToolContext(agent_name="writer")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ) as mock_eval:
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"city": "Rome"},
            tool_context=tool_context,
        )

    assert mock_eval.await_args.args[1] == "weather-guard"


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
async def test_before_model_without_after_model_does_not_cache_request_state(plugin_module):
    plugin = plugin_module.AgentControlPlugin(
        agent_name="test-agent01",
        enabled_hooks={"before_model"},
    )
    context = MockCallbackContext("writer", invocation_id="inv-1")
    request = MockLlmRequest("hello", request_id="call-1")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ):
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )

    assert plugin._request_text_by_call_key == {}
    assert plugin._current_llm_call_ids == {}


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
    assert ("tool", "planner.search_docs") in plugin._known_steps
    assert ("tool", "writer.save_draft") in plugin._known_steps
    mock_sync.assert_called_once()


def test_bind_keeps_duplicate_tool_names_distinct_across_sub_agents(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    root = SimpleNamespace(
        name="planner",
        sub_agents=[
            SimpleNamespace(name="researcher", tools=[MockTool("search_docs")]),
            SimpleNamespace(name="writer", tools=[MockTool("search_docs")]),
        ],
    )

    with patch.object(plugin, "_sync_steps_blocking"):
        plugin.bind(root)

    assert ("tool", "researcher.search_docs") in plugin._known_steps
    assert ("tool", "writer.search_docs") in plugin._known_steps


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
async def test_after_model_clears_generated_invocation_id_fallback(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")

    class UnhashableCallback:
        __hash__ = None

        def __init__(self, agent_name: str):
            self.agent_name = agent_name
            self.agent = SimpleNamespace(name=agent_name, description=f"{agent_name} desc")

    context = UnhashableCallback("writer")
    request = MockLlmRequest("hello", request_id="call-1")
    response = MockLlmResponse(
        MockContent(role="model", parts=[MockPart("done")]),
        request_id="call-1",
    )

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(return_value=MagicMock()),
    ):
        await plugin.before_model_callback(
            callback_context=context,
            llm_request=request,
        )
        await plugin.after_model_callback(
            callback_context=context,
            llm_response=response,
        )

    assert plugin._generated_invocation_ids_by_context_id == {}
    assert plugin._generated_context_ids_by_invocation_id == {}


@pytest.mark.asyncio
async def test_close_cancels_tasks_and_clears_request_cache(plugin_module):
    plugin = plugin_module.AgentControlPlugin(agent_name="test-agent01")
    context = MockCallbackContext("writer")
    plugin._generated_invocation_ids[context] = "inv-1"
    plugin._generated_invocation_ids_by_context_id[123] = "inv-2"
    plugin._generated_context_ids_by_invocation_id["inv-2"] = 123
    plugin._request_text_by_call_key[("inv-1", "call-1")] = "hello"
    plugin._request_object_ids_by_call_key[("inv-1", "call-1")] = 123
    plugin._current_llm_call_ids["inv-1"] = ["call-1"]
    plugin._stored_llm_call_ids[123] = "call-1"

    gate = asyncio.Future()

    async def slow_task():
        await gate

    task = asyncio.create_task(slow_task())
    plugin._step_sync_tasks[("llm", "writer")] = task

    await plugin.close()

    assert len(plugin._generated_invocation_ids) == 0
    assert plugin._generated_invocation_ids_by_context_id == {}
    assert plugin._generated_context_ids_by_invocation_id == {}
    assert plugin._request_text_by_call_key == {}
    assert plugin._request_object_ids_by_call_key == {}
    assert plugin._current_llm_call_ids == {}
    assert plugin._stored_llm_call_ids == {}
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
    tool_context = MockToolContext(agent_name="writer")

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(side_effect=ControlViolationError(control_name="c1", message="Denied")),
    ):
        await plugin.before_tool_callback(
            tool=tool,
            tool_args={"city": "Rome"},
            tool_context=tool_context,
        )

    metadata, payload = callback.call_args.args
    assert metadata["step_name"] == "writer.get_weather"
    assert metadata["stage"] == "pre"
    assert payload["action"] == "deny"


@pytest.mark.asyncio
async def test_on_violation_callback_failure_does_not_break_blocking_response(
    plugin_module,
    caplog,
):
    callback = MagicMock(side_effect=RuntimeError("telemetry down"))
    plugin = plugin_module.AgentControlPlugin(
        agent_name="test-agent01",
        on_violation_callback=callback,
    )
    tool = MockTool("get_weather")
    tool_context = MockToolContext(agent_name="writer")
    caplog.set_level(logging.WARNING)

    with patch.object(
        plugin_module,
        "_evaluate_and_enforce",
        AsyncMock(side_effect=ControlViolationError(control_name="c1", message="Denied")),
    ):
        result = await plugin.before_tool_callback(
            tool=tool,
            tool_args={"city": "Rome"},
            tool_context=tool_context,
        )

    assert result == {"status": "blocked", "message": "Denied"}
    assert "Google ADK on_violation_callback failed" in caplog.text
