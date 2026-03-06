"""Unit tests for Strands hook integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from agent_control_models import EvaluationResult


@pytest.fixture
def mock_strands_modules():
    """Mock the strands modules to avoid import errors."""
    with patch.dict(
        "sys.modules",
        {
            "strands": MagicMock(),
            "strands.hooks": MagicMock(),
        },
    ):
        yield


@pytest.fixture
def mock_event_classes():
    """Create mock event classes."""
    BeforeInvocationEvent = type("BeforeInvocationEvent", (), {})  # noqa: N806
    BeforeModelCallEvent = type("BeforeModelCallEvent", (), {})  # noqa: N806
    AfterModelCallEvent = type("AfterModelCallEvent", (), {})  # noqa: N806
    BeforeToolCallEvent = type("BeforeToolCallEvent", (), {})  # noqa: N806
    AfterToolCallEvent = type("AfterToolCallEvent", (), {})  # noqa: N806
    BeforeNodeCallEvent = type("BeforeNodeCallEvent", (), {})  # noqa: N806
    AfterNodeCallEvent = type("AfterNodeCallEvent", (), {})  # noqa: N806
    HookProvider = type("HookProvider", (), {"__init__": lambda self: None})  # noqa: N806
    HookRegistry = type("HookRegistry", (), {})  # noqa: N806

    return {
        "BeforeInvocationEvent": BeforeInvocationEvent,
        "BeforeModelCallEvent": BeforeModelCallEvent,
        "AfterModelCallEvent": AfterModelCallEvent,
        "BeforeToolCallEvent": BeforeToolCallEvent,
        "AfterToolCallEvent": AfterToolCallEvent,
        "BeforeNodeCallEvent": BeforeNodeCallEvent,
        "AfterNodeCallEvent": AfterNodeCallEvent,
        "HookProvider": HookProvider,
        "HookRegistry": HookRegistry,
    }


@pytest.fixture
def agent_control_hook(mock_strands_modules, mock_event_classes):
    """Create an AgentControlHook instance with mocked dependencies."""
    import importlib
    import sys
    import agent_control.integrations.strands.hook as hook_module

    hooks_mod = sys.modules["strands.hooks"]
    for name, cls in mock_event_classes.items():
        setattr(hooks_mod, name, cls)

    importlib.reload(hook_module)
    AgentControlHook = hook_module.AgentControlHook

    return AgentControlHook(agent_name="test-agent")


def test_action_error_with_deny_match():
    """Test _action_error returns deny error for deny action."""
    from agent_control.integrations.strands.hook import _action_error

    # Create a mock match with deny action
    mock_match = MagicMock()
    mock_match.action = "deny"
    mock_match.control_name = "test_control"
    mock_match.result.message = "Access denied"

    # Create a mock result
    result = MagicMock(spec=EvaluationResult)
    result.matches = [mock_match]
    result.reason = None

    action_type, error = _action_error(result)

    assert action_type == "deny"
    assert "Control violation [test_control]" in str(error)
    assert "Access denied" in str(error)


def test_action_error_with_steer_match():
    """Test _action_error returns steer error for steer action."""
    from agent_control.integrations.strands.hook import _action_error

    # Create a mock match with steer action
    mock_match = MagicMock()
    mock_match.action = "steer"
    mock_match.control_name = "test_control"
    mock_match.result.message = "Steering required"
    mock_match.steering_context.message = "Context message"

    # Create a mock result
    result = MagicMock(spec=EvaluationResult)
    result.matches = [mock_match]
    result.reason = None

    action_type, error = _action_error(result)

    assert action_type == "steer"
    assert "Steering required [test_control]" in str(error)


def test_action_error_with_no_blocking_match():
    """Test _action_error returns None when no blocking matches."""
    from agent_control.integrations.strands.hook import _action_error

    # Create a mock match with allow action
    mock_match = MagicMock()
    mock_match.action = "allow"

    # Create a mock result
    result = MagicMock(spec=EvaluationResult)
    result.matches = [mock_match]

    assert _action_error(result) is None


def test_action_error_with_empty_matches():
    """Test _action_error returns None with empty matches."""
    from agent_control.integrations.strands.hook import _action_error

    result = MagicMock(spec=EvaluationResult)
    result.matches = []

    assert _action_error(result) is None


def test_action_error_with_none_matches():
    """Test _action_error returns None with None matches."""
    from agent_control.integrations.strands.hook import _action_error

    result = MagicMock(spec=EvaluationResult)
    result.matches = None

    assert _action_error(result) is None


def test_action_error_deny_takes_precedence():
    """Test deny takes precedence over steer regardless of order."""
    from agent_control.integrations.strands.hook import _action_error
    from agent_control import ControlViolationError

    deny = MagicMock()
    deny.action = "deny"
    deny.control_name = "deny-control"
    deny.control_id = 1
    deny.result.message = "Denied"

    steer = MagicMock()
    steer.action = "steer"
    steer.control_name = "steer-control"
    steer.control_id = 2
    steer.result.message = "Steer"

    result = MagicMock(spec=EvaluationResult)
    # Steer appears first to ensure deny-first behavior
    result.matches = [steer, deny]
    result.reason = None

    action, err = _action_error(result)

    assert action == "deny"
    assert isinstance(err, ControlViolationError)
    assert err.control_name == "deny-control"


@pytest.mark.asyncio
async def test_evaluate_and_enforce_safe_result(agent_control_hook):
    """Test _evaluate_and_enforce with safe result."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        # Mock a safe result
        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        # Should not raise
        await agent_control_hook._evaluate_and_enforce(
            step_name="test_step",
            input="test input",
            step_type="llm",
            stage="pre"
        )


@pytest.mark.asyncio
async def test_evaluate_and_enforce_with_errors(agent_control_hook):
    """Test _evaluate_and_enforce fails closed on evaluation errors."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        mock_error = MagicMock()
        mock_error.control_name = "error-control"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.errors = [mock_error]
        mock_result.is_safe = True
        mock_result.matches = []
        mock_evaluate.return_value = mock_result

        with pytest.raises(RuntimeError):
            await agent_control_hook._evaluate_and_enforce(
                step_name="test_step",
                input="test input",
                step_type="llm",
                stage="pre"
            )


@pytest.mark.asyncio
async def test_evaluate_and_enforce_with_deny(agent_control_hook):
    """Test _evaluate_and_enforce raises error on deny action."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control import ControlViolationError

        # Mock a deny result
        mock_match = MagicMock()
        mock_match.action = "deny"
        mock_match.control_name = "test_control"
        mock_match.result.message = "Denied"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = [mock_match]
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        with pytest.raises(ControlViolationError):
            await agent_control_hook._evaluate_and_enforce(
                step_name="test_step",
                input="test input",
                step_type="llm",
                stage="pre"
            )


@pytest.mark.asyncio
async def test_evaluate_and_enforce_with_steer(agent_control_hook):
    """Test _evaluate_and_enforce raises error on steer action."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control import ControlSteerError

        # Mock a steer result
        mock_match = MagicMock()
        mock_match.action = "steer"
        mock_match.control_name = "test_control"
        mock_match.control_id = 42
        mock_match.result.message = "Steer required"
        mock_match.result.metadata = {"risk": "high"}
        mock_match.steering_context.message = "Context"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = [mock_match]
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        with pytest.raises(ControlSteerError) as exc_info:
            await agent_control_hook._evaluate_and_enforce(
                step_name="test_step",
                input="test input",
                step_type="llm",
                stage="pre"
            )

        err = exc_info.value
        assert err.control_name == "test_control"
        assert err.control_id == 42
        assert err.metadata == {"risk": "high"}
        assert "Context" in err.steering_context


@pytest.mark.asyncio
async def test_evaluate_and_enforce_unsafe_result(agent_control_hook):
    """Test _evaluate_and_enforce raises error on unsafe result."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control import ControlViolationError

        # Mock an unsafe result
        mock_match = MagicMock()
        mock_match.action = "log"
        mock_match.control_name = "test_control"
        mock_match.result.message = "Unsafe"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = False
        mock_result.matches = [mock_match]
        mock_result.reason = "Test reason"
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        with pytest.raises(ControlViolationError) as exc_info:
            await agent_control_hook._evaluate_and_enforce(
                step_name="test_step",
                input="test input",
                step_type="llm",
                stage="pre"
            )

        assert "test_control" in str(exc_info.value)


def test_extract_content_text_with_string(agent_control_hook):
    """Test _extract_content_text with string input."""
    result = agent_control_hook._extract_content_text("test string")
    assert result == "test string"


def test_extract_content_text_with_dict_text(agent_control_hook):
    """Test _extract_content_text with dict containing text."""
    result = agent_control_hook._extract_content_text({"text": "test text"})
    assert result == "test text"


def test_extract_content_text_with_dict_json(agent_control_hook):
    """Test _extract_content_text with dict containing json."""
    result = agent_control_hook._extract_content_text({"json": {"key": "value"}})
    assert "key" in result
    assert "value" in result


def test_extract_content_text_with_list(agent_control_hook):
    """Test _extract_content_text with list of content blocks."""
    content = [
        {"text": "First text"},
        {"text": "Second text"},
    ]
    result = agent_control_hook._extract_content_text(content)
    assert "First text" in result
    assert "Second text" in result


def test_extract_content_text_with_tool_use(agent_control_hook):
    """Test _extract_content_text with tool use block."""
    content = [
        {"toolUse": {"name": "test_tool"}},
    ]
    result = agent_control_hook._extract_content_text(content)
    assert "[tool_use: test_tool]" in result


def test_extract_content_text_with_empty_content(agent_control_hook):
    """Test _extract_content_text with empty content."""
    assert agent_control_hook._extract_content_text("") == ""
    assert agent_control_hook._extract_content_text(None) == ""
    assert agent_control_hook._extract_content_text([]) == ""


def test_extract_tool_data_before_tool(agent_control_hook):
    """Test _extract_tool_data with BeforeToolCallEvent."""
    from agent_control.integrations.strands.hook import BeforeToolCallEvent

    # Create a mock with the right spec so isinstance works
    event = MagicMock(spec=BeforeToolCallEvent)
    event.selected_tool = MagicMock()
    event.selected_tool.tool_name = "test_tool"
    event.tool_use = {"name": "test_tool", "input": {"param": "value"}}

    tool_name, tool_data = agent_control_hook._extract_tool_data(event)

    assert tool_name == "test_tool"
    assert tool_data == {"param": "value"}


def test_extract_tool_data_after_tool_success(agent_control_hook):
    """Test _extract_tool_data with AfterToolCallEvent (success)."""
    from agent_control.integrations.strands.hook import AfterToolCallEvent

    # Create a mock with the right spec so isinstance works
    event = MagicMock(spec=AfterToolCallEvent)
    event.selected_tool = MagicMock()
    event.selected_tool.tool_name = "test_tool"
    event.tool_use = {"name": "test_tool"}
    event.exception = None
    event.result = {"content": [{"text": "result text"}]}

    tool_name, tool_data = agent_control_hook._extract_tool_data(event)

    assert tool_name == "test_tool"
    assert "result text" in tool_data


def test_extract_tool_data_after_tool_error(agent_control_hook):
    """Test _extract_tool_data with AfterToolCallEvent (error)."""
    from agent_control.integrations.strands.hook import AfterToolCallEvent

    # Create a mock with the right spec so isinstance works
    event = MagicMock(spec=AfterToolCallEvent)
    event.selected_tool = MagicMock()
    event.selected_tool.tool_name = "test_tool"
    event.tool_use = {"name": "test_tool"}
    event.exception = Exception("Tool failed")
    event.result = {}

    tool_name, tool_data = agent_control_hook._extract_tool_data(event)

    assert tool_name == "test_tool"
    assert "ERROR" in tool_data
    assert "Tool failed" in tool_data


def test_hook_initialization():
    """Test AgentControlHook initialization."""
    from agent_control.integrations.strands.hook import AgentControlHook

    hook = AgentControlHook(
        agent_name="test-agent",
        event_control_list=None,
        on_violation_callback=None,
        enable_logging=False
    )

    assert hook.agent_name == "test-agent"
    assert hook.event_control_list is None
    assert hook.on_violation_callback is None
    assert hook.enable_logging is False


def test_hook_with_callback():
    """Test AgentControlHook with violation callback."""
    from agent_control.integrations.strands.hook import AgentControlHook

    callback = MagicMock()
    hook = AgentControlHook(
        agent_name="test-agent",
        on_violation_callback=callback
    )

    # Test callback invocation
    mock_result = MagicMock(spec=EvaluationResult)
    hook._invoke_callback("test_control", "pre", mock_result)

    callback.assert_called_once()
    call_args = callback.call_args[0]
    assert call_args[0]["agent"] == "test-agent"
    assert call_args[0]["control_name"] == "test_control"
    assert call_args[0]["stage"] == "pre"


def test_raise_error_with_runtime_error(agent_control_hook):
    """Test _raise_error with use_runtime_error=True."""
    from agent_control import ControlViolationError

    error = ControlViolationError(message="Test error")

    with pytest.raises(RuntimeError) as exc_info:
        agent_control_hook._raise_error(error, use_runtime_error=True)

    assert "Test error" in str(exc_info.value)


def test_raise_error_without_runtime_error(agent_control_hook):
    """Test _raise_error with use_runtime_error=False."""
    from agent_control import ControlViolationError

    error = ControlViolationError(message="Test error")

    with pytest.raises(ControlViolationError):
        agent_control_hook._raise_error(error, use_runtime_error=False)


def test_extract_user_message_from_list(agent_control_hook):
    """Test _extract_user_message_from_list."""
    messages = [
        {"role": "system", "content": "System message"},
        {"role": "user", "content": "User message"},
        {"role": "assistant", "content": "Assistant message"},
    ]

    result = agent_control_hook._extract_user_message_from_list(messages)
    assert result == "User message"


def test_extract_context(agent_control_hook):
    """Test _extract_context from invocation_state."""
    class DummyEvent:
        invocation_state = {"context": {"request_id": "abc123"}}

    assert agent_control_hook._extract_context(DummyEvent()) == {"request_id": "abc123"}


def test_extract_context_missing(agent_control_hook):
    """Test _extract_context returns None when missing."""
    class DummyEvent:
        invocation_state = {}

    assert agent_control_hook._extract_context(DummyEvent()) is None


def test_extract_user_message_from_list_reverse(agent_control_hook):
    """Test _extract_user_message_from_list with reverse=True."""
    messages = [
        {"role": "user", "content": "First user message"},
        {"role": "assistant", "content": "Assistant message"},
        {"role": "user", "content": "Last user message"},
    ]

    result = agent_control_hook._extract_user_message_from_list(messages, reverse=True)
    assert result == "Last user message"


def test_extract_user_message_from_list_empty(agent_control_hook):
    """Test _extract_user_message_from_list with empty list."""
    assert agent_control_hook._extract_user_message_from_list([]) == ""
    assert agent_control_hook._extract_user_message_from_list(None) == ""


def test_extract_user_message_no_user_role(agent_control_hook):
    """Test _extract_user_message_from_list when no user role messages exist."""
    messages = [
        {"role": "system", "content": "System message"},
        {"role": "assistant", "content": "Assistant message"},
    ]
    assert agent_control_hook._extract_user_message_from_list(messages) == ""


@pytest.mark.asyncio
async def test_evaluate_and_enforce_unsafe_no_reason_with_match(agent_control_hook):
    """Test _evaluate_and_enforce with unsafe result, no reason, but has match."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control import ControlViolationError

        # Mock an unsafe result with no reason but with a match that has a message
        mock_match = MagicMock()
        mock_match.action = "log"
        mock_match.control_name = "test_control"
        mock_match.result.message = "Match message"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = False
        mock_result.matches = [mock_match]
        mock_result.reason = None  # No reason
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        with pytest.raises(ControlViolationError) as exc_info:
            await agent_control_hook._evaluate_and_enforce(
                step_name="test_step",
                input="test input",
                step_type="llm",
                stage="pre"
            )

        assert "test_control" in str(exc_info.value)
        assert "Match message" in str(exc_info.value)


def test_register_hooks_with_custom_event_list(mock_strands_modules, mock_event_classes):
    """Test register_hooks with custom event_control_list."""
    with patch("agent_control.integrations.strands.hook.BeforeInvocationEvent", mock_event_classes["BeforeInvocationEvent"]):  # noqa: E501
        with patch("agent_control.integrations.strands.hook.BeforeModelCallEvent", mock_event_classes["BeforeModelCallEvent"]):  # noqa: E501
            with patch("agent_control.integrations.strands.hook.BeforeToolCallEvent", mock_event_classes["BeforeToolCallEvent"]):  # noqa: E501
                with patch("agent_control.integrations.strands.hook.AfterToolCallEvent", mock_event_classes["AfterToolCallEvent"]):  # noqa: E501
                    with patch("agent_control.integrations.strands.hook.AfterModelCallEvent", mock_event_classes["AfterModelCallEvent"]):  # noqa: E501
                        with patch("agent_control.integrations.strands.hook.BeforeNodeCallEvent", mock_event_classes["BeforeNodeCallEvent"]):  # noqa: E501
                            with patch("agent_control.integrations.strands.hook.AfterNodeCallEvent", mock_event_classes["AfterNodeCallEvent"]):  # noqa: E501
                                with patch("agent_control.integrations.strands.hook.HookProvider", mock_event_classes["HookProvider"]):  # noqa: E501
                                    from agent_control.integrations.strands.hook import (
                                        AgentControlHook,
                                        BeforeModelCallEvent,
                                        AfterModelCallEvent,
                                    )

                                    # Create hook with custom event list
                                    hook = AgentControlHook(
                                        agent_name="test-agent",
                                        event_control_list=[BeforeModelCallEvent, AfterModelCallEvent],
                                        enable_logging=True
                                    )

                                    # Create mock registry with add_callback method
                                    registry = MagicMock()
                                    registry.add_callback = MagicMock()

                                    # Register hooks
                                    hook.register_hooks(registry)

                                    # Verify only specified events were registered
                                    assert registry.add_callback.call_count == 2


@pytest.mark.asyncio
async def test_check_before_invocation(agent_control_hook):
    """Test check_before_invocation hook."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control.integrations.strands.hook import BeforeInvocationEvent

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        event = MagicMock(spec=BeforeInvocationEvent)
        event.messages = [{"role": "user", "content": "test message"}]

        await agent_control_hook.check_before_invocation(event)

        mock_evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_check_before_model(agent_control_hook):
    """Test check_before_model hook."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control.integrations.strands.hook import BeforeModelCallEvent

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        event = MagicMock(spec=BeforeModelCallEvent)
        event.invocation_state = {"messages": [{"role": "user", "content": "test"}]}

        await agent_control_hook.check_before_model(event)

        mock_evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_check_after_model(agent_control_hook):
    """Test check_after_model hook."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control.integrations.strands.hook import AfterModelCallEvent

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        event = MagicMock(spec=AfterModelCallEvent)
        event.stop_response = MagicMock()
        event.stop_response.message = {"content": [{"text": "model output"}]}
        event.invocation_state = {
            "messages": [{"role": "user", "content": "test input"}],
            "context": {"request_id": "ctx-1"},
        }

        await agent_control_hook.check_after_model(event)

        mock_evaluate.assert_called_once()
        assert mock_evaluate.call_args.kwargs["input"] == "test input"
        assert mock_evaluate.call_args.kwargs["context"] == {"request_id": "ctx-1"}


@pytest.mark.asyncio
async def test_check_before_tool(agent_control_hook):
    """Test check_before_tool hook."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control.integrations.strands.hook import BeforeToolCallEvent

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        event = MagicMock(spec=BeforeToolCallEvent)
        event.selected_tool = MagicMock()
        event.selected_tool.tool_name = "test_tool"
        event.tool_use = {"name": "test_tool", "input": {"param": "value"}}

        await agent_control_hook.check_before_tool(event)

        mock_evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_check_after_tool(agent_control_hook):
    """Test check_after_tool hook."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control.integrations.strands.hook import AfterToolCallEvent

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        event = MagicMock(spec=AfterToolCallEvent)
        event.selected_tool = MagicMock()
        event.selected_tool.tool_name = "test_tool"
        event.tool_use = {"name": "test_tool"}
        event.exception = None
        event.result = {"content": [{"text": "result"}]}

        await agent_control_hook.check_after_tool(event)

        mock_evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_check_before_node(agent_control_hook):
    """Test check_before_node hook."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control.integrations.strands.hook import BeforeNodeCallEvent

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        event = MagicMock(spec=BeforeNodeCallEvent)
        event.node_id = "test_node"
        event.invocation_state = {"messages": [{"role": "user", "content": "test"}]}

        await agent_control_hook.check_before_node(event)

        mock_evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_check_after_node(agent_control_hook):
    """Test check_after_node hook."""
    with patch("agent_control.integrations.strands.hook.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control.integrations.strands.hook import AfterNodeCallEvent

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.is_safe = True
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        event = MagicMock(spec=AfterNodeCallEvent)
        event.node_id = "test_node"
        event.invocation_state = {"output": "test output", "input": "node input"}

        await agent_control_hook.check_after_node(event)

        mock_evaluate.assert_called_once()
        assert mock_evaluate.call_args.kwargs["input"] == "node input"


def test_extract_tool_data_no_selected_tool(agent_control_hook):
    """Test _extract_tool_data when selected_tool is None."""
    from agent_control.integrations.strands.hook import BeforeToolCallEvent

    event = MagicMock(spec=BeforeToolCallEvent)
    event.selected_tool = None
    event.tool_use = {"name": "fallback_tool", "input": {"key": "value"}}

    tool_name, tool_data = agent_control_hook._extract_tool_data(event)

    assert tool_name == "fallback_tool"
    assert tool_data == {"key": "value"}


def test_extract_content_text_with_citations(agent_control_hook):
    """Test _extract_content_text with citations content."""
    content = [
        {
            "citationsContent": {
                "content": [
                    {"text": "citation text 1"},
                    {"text": "citation text 2"}
                ]
            }
        }
    ]

    result = agent_control_hook._extract_content_text(content)
    assert "citation text 1" in result
    assert "citation text 2" in result


def test_extract_content_text_with_tool_result(agent_control_hook):
    """Test _extract_content_text with tool result block."""
    content = [
        {
            "toolResult": {
                "content": [{"text": "tool result text"}]
            }
        }
    ]

    result = agent_control_hook._extract_content_text(content)
    assert "tool result text" in result


def test_extract_content_text_with_non_dict_block(agent_control_hook):
    """Test _extract_content_text with non-dict blocks."""
    content = [
        "string block",
        {"text": "dict block"}
    ]

    result = agent_control_hook._extract_content_text(content)
    assert "string block" in result
    assert "dict block" in result


def test_extract_content_text_with_unknown_type(agent_control_hook):
    """Test _extract_content_text with unknown content type."""
    content = 12345  # Some other type

    result = agent_control_hook._extract_content_text(content)
    assert result == "12345"


def test_extract_messages_before_model_with_input(agent_control_hook):
    """Test _extract_messages with BeforeModelCallEvent using input field."""
    from agent_control.integrations.strands.hook import BeforeModelCallEvent

    event = MagicMock(spec=BeforeModelCallEvent)
    event.invocation_state = {"input": "direct input text"}

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == "direct input text"
    assert output_text == ""


def test_extract_messages_after_model_no_response(agent_control_hook):
    """Test _extract_messages with AfterModelCallEvent when stop_response is None."""
    from agent_control.integrations.strands.hook import AfterModelCallEvent

    event = MagicMock(spec=AfterModelCallEvent)
    event.stop_response = None
    event.invocation_state = {}

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == ""
    assert output_text == ""


def test_extract_messages_after_model_missing_invocation_state(agent_control_hook):
    """Test _extract_messages handles missing invocation_state."""
    from agent_control.integrations.strands.hook import AfterModelCallEvent

    event = MagicMock(spec=AfterModelCallEvent)
    event.stop_response = None
    event.invocation_state = None

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == ""
    assert output_text == ""


def test_extract_messages_after_model_with_response(agent_control_hook):
    """Test _extract_messages with AfterModelCallEvent when stop_response exists."""
    from agent_control.integrations.strands.hook import AfterModelCallEvent

    event = MagicMock(spec=AfterModelCallEvent)
    event.stop_response = MagicMock()
    event.stop_response.message = {"content": [{"text": "output text"}]}
    event.invocation_state = {"messages": [{"role": "user", "content": "user input"}]}

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == "user input"
    assert output_text == "output text"


def test_extract_messages_after_model_with_input_field(agent_control_hook):
    """Test _extract_messages with AfterModelCallEvent using input field."""
    from agent_control.integrations.strands.hook import AfterModelCallEvent

    event = MagicMock(spec=AfterModelCallEvent)
    event.stop_response = MagicMock()
    event.stop_response.message = {"content": [{"text": "output text"}]}
    event.invocation_state = {"input": "input text"}

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == "input text"
    assert output_text == "output text"


def test_extract_messages_before_node_with_input(agent_control_hook):
    """Test _extract_messages with BeforeNodeCallEvent using input field."""
    from agent_control.integrations.strands.hook import BeforeNodeCallEvent

    event = MagicMock(spec=BeforeNodeCallEvent)
    event.invocation_state = {"input": "node input"}

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == "node input"
    assert output_text == ""


def test_extract_messages_after_node_with_result(agent_control_hook):
    """Test _extract_messages with AfterNodeCallEvent using result field."""
    from agent_control.integrations.strands.hook import AfterNodeCallEvent

    event = MagicMock(spec=AfterNodeCallEvent)
    event.invocation_state = {"result": "node result", "input": "node input"}

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == "node input"
    assert output_text == "node result"


def test_extract_messages_after_node_with_response(agent_control_hook):
    """Test _extract_messages with AfterNodeCallEvent using response field."""
    from agent_control.integrations.strands.hook import AfterNodeCallEvent

    event = MagicMock(spec=AfterNodeCallEvent)
    event.invocation_state = {"response": "node response"}

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == ""
    assert output_text == "node response"


def test_extract_messages_after_node_with_messages(agent_control_hook):
    """Test _extract_messages with AfterNodeCallEvent using messages field."""
    from agent_control.integrations.strands.hook import AfterNodeCallEvent

    event = MagicMock(spec=AfterNodeCallEvent)
    # When messages is in the state, it's treated as content to extract
    event.invocation_state = {
        "messages": [
            {"role": "user", "content": "user msg"},
            {"role": "assistant", "content": "assistant msg"},
        ]
    }

    input_text, output_text = agent_control_hook._extract_messages(event)

    assert input_text == "user msg"
    assert output_text == "user msg\nassistant msg"
