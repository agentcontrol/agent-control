"""Unit tests for Strands steering integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from agent_control_models import EvaluationResult


@pytest.fixture
def mock_strands_steering_modules():
    """Mock the strands steering modules to avoid import errors."""
    Guide = type("Guide", (), {"__init__": lambda self, reason: setattr(self, "reason", reason)})  # noqa: N806
    Proceed = type("Proceed", (), {"__init__": lambda self, reason: setattr(self, "reason", reason)})  # noqa: N806, E501
    SteeringHandler = type("SteeringHandler", (), {"__init__": lambda self: None})  # noqa: N806

    with patch.dict(
        "sys.modules",
        {
            "strands": MagicMock(),
            "strands.experimental": MagicMock(),
            "strands.experimental.steering": MagicMock(
                Guide=Guide,
                Proceed=Proceed,
                SteeringHandler=SteeringHandler,
            ),
        },
    ):
        # Also patch the imports in the module
        with patch("agent_control.integrations.strands.steering.Guide", Guide):
            with patch("agent_control.integrations.strands.steering.Proceed", Proceed):
                with patch("agent_control.integrations.strands.steering.SteeringHandler", SteeringHandler):  # noqa: E501
                    yield {
                        "Guide": Guide,
                        "Proceed": Proceed,
                        "SteeringHandler": SteeringHandler,
                    }


@pytest.fixture
def steering_handler(mock_strands_steering_modules):
    """Create an AgentControlSteeringHandler instance."""
    from agent_control.integrations.strands.steering import AgentControlSteeringHandler

    return AgentControlSteeringHandler(agent_name="test-agent", enable_logging=False)


def test_steering_handler_initialization(mock_strands_steering_modules):
    """Test AgentControlSteeringHandler initialization."""
    from agent_control.integrations.strands.steering import AgentControlSteeringHandler

    handler = AgentControlSteeringHandler(agent_name="test-agent", enable_logging=True)

    assert handler.agent_name == "test-agent"
    assert handler.enable_logging is True
    assert handler.steers_applied == 0
    assert handler.last_steer_info is None


@pytest.mark.asyncio
async def test_steer_after_model_with_steer_match(steering_handler, mock_strands_steering_modules):
    """Test steer_after_model returns Guide when steer match found."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        # Mock a steer match
        mock_match = MagicMock()
        mock_match.action = "steer"
        mock_match.control_name = "test_control"
        mock_match.result.message = "Steering required"
        mock_match.steering_context.message = "Steering context"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.matches = [mock_match]
        mock_result.reason = None
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        # Create mock message
        message = {"content": [{"text": "test output"}]}

        result = await steering_handler.steer_after_model(
            agent=MagicMock(),
            message=message,
            stop_reason="end_turn"
        )

        # Check that Guide was returned
        assert result.__class__.__name__ == "Guide"
        assert result.reason == "Steering context"
        assert steering_handler.steers_applied == 1
        assert steering_handler.last_steer_info is not None
        assert steering_handler.last_steer_info["control_name"] == "test_control"


@pytest.mark.asyncio
async def test_steer_after_model_with_deny_match(steering_handler, mock_strands_steering_modules):
    """Test steer_after_model raises ControlViolationError on deny."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control import ControlViolationError

        # Mock a deny match
        mock_match = MagicMock()
        mock_match.action = "deny"
        mock_match.control_name = "test_control"
        mock_match.result.message = "Access denied"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.matches = [mock_match]
        mock_result.reason = None
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        # Create mock message
        message = {"content": [{"text": "test output"}]}

        with pytest.raises(ControlViolationError) as exc_info:
            await steering_handler.steer_after_model(
                agent=MagicMock(),
                message=message,
                stop_reason="end_turn"
            )

        assert "Control violation [test_control]" in str(exc_info.value)
        assert "Access denied" in str(exc_info.value)


@pytest.mark.asyncio
async def test_steer_after_model_deny_takes_precedence(steering_handler, mock_strands_steering_modules):
    """Test deny is enforced even if steer is also present."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        from agent_control import ControlViolationError

        deny_match = MagicMock()
        deny_match.action = "deny"
        deny_match.control_name = "deny_control"
        deny_match.control_id = 1
        deny_match.result.message = "Access denied"

        steer_match = MagicMock()
        steer_match.action = "steer"
        steer_match.control_name = "steer_control"
        steer_match.control_id = 2
        steer_match.result.message = "Steer required"
        steer_match.steering_context.message = "Context"

        mock_result = MagicMock(spec=EvaluationResult)
        # Steer first to ensure deny-first logic
        mock_result.matches = [steer_match, deny_match]
        mock_result.reason = None
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        message = {"content": [{"text": "test output"}]}

        with pytest.raises(ControlViolationError) as exc_info:
            await steering_handler.steer_after_model(
                agent=MagicMock(),
                message=message,
                stop_reason="end_turn"
            )

        assert "deny_control" in str(exc_info.value)


@pytest.mark.asyncio
async def test_steer_after_model_with_result_errors(steering_handler, mock_strands_steering_modules):
    """Test steer_after_model fails closed on evaluation errors."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        mock_error = MagicMock()
        mock_error.control_name = "error-control"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.errors = [mock_error]
        mock_result.matches = []
        mock_evaluate.return_value = mock_result

        message = {"content": [{"text": "test output"}]}

        with pytest.raises(RuntimeError):
            await steering_handler.steer_after_model(
                agent=MagicMock(),
                message=message,
                stop_reason="end_turn"
            )


@pytest.mark.asyncio
async def test_steer_after_model_no_matches(steering_handler, mock_strands_steering_modules):
    """Test steer_after_model returns Proceed when no matches."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        # Mock no matches
        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.matches = []
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        # Create mock message
        message = {"content": [{"text": "test output"}]}

        result = await steering_handler.steer_after_model(
            agent=MagicMock(),
            message=message,
            stop_reason="end_turn"
        )

        # Check that Proceed was returned
        assert result.__class__.__name__ == "Proceed"
        assert "No Agent Control steer detected" in result.reason
        assert steering_handler.last_steer_info is None


@pytest.mark.asyncio
async def test_steer_after_model_observe_match(steering_handler, mock_strands_steering_modules):
    """Test steer_after_model returns Proceed for observe action."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        # Mock an observe match
        mock_match = MagicMock()
        mock_match.action = "observe"
        mock_match.control_name = "test_control"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.matches = [mock_match]
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        # Create mock message
        message = {"content": [{"text": "test output"}]}

        result = await steering_handler.steer_after_model(
            agent=MagicMock(),
            message=message,
            stop_reason="end_turn"
        )

        # Check that Proceed was returned
        assert result.__class__.__name__ == "Proceed"
        assert steering_handler.last_steer_info is None


@pytest.mark.asyncio
async def test_steer_after_model_evaluation_error(steering_handler, mock_strands_steering_modules):
    """Test steer_after_model handles evaluation errors gracefully."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        # Mock an evaluation error
        mock_evaluate.side_effect = Exception("Evaluation failed")

        # Create mock message
        message = {"content": [{"text": "test output"}]}

        with pytest.raises(RuntimeError):
            await steering_handler.steer_after_model(
                agent=MagicMock(),
                message=message,
                stop_reason="end_turn"
            )


def test_build_steering_message_with_context(steering_handler):
    """Test _build_steering_message with steering context."""
    mock_match = MagicMock()
    mock_match.control_name = "test_control"
    mock_match.steering_context.message = "Context message"

    message = steering_handler._build_steering_message(mock_match, "fallback")

    assert message == "Context message"


def test_build_steering_message_with_result(steering_handler):
    """Test _build_steering_message with result message."""
    mock_match = MagicMock()
    mock_match.control_name = "test_control"
    mock_match.steering_context = None
    mock_match.result.message = "Result message"

    message = steering_handler._build_steering_message(mock_match, "fallback")

    assert message == "Result message"


def test_build_steering_message_with_fallback(steering_handler):
    """Test _build_steering_message with fallback reason."""
    mock_match = MagicMock()
    mock_match.control_name = "test_control"
    mock_match.steering_context = None
    mock_match.result.message = None

    message = steering_handler._build_steering_message(mock_match, "Fallback reason")

    assert message == "Fallback reason"


def test_build_steering_message_default(steering_handler):
    """Test _build_steering_message with default message."""
    mock_match = MagicMock()
    mock_match.control_name = "test_control"
    mock_match.steering_context = None
    mock_match.result.message = None

    message = steering_handler._build_steering_message(mock_match, None)

    assert message == "Control 'test_control' requires steering"


def test_extract_output_with_string(steering_handler):
    """Test _extract_output with string message."""
    result = steering_handler._extract_output("test string")
    assert result == "test string"


def test_extract_output_with_dict_content(steering_handler):
    """Test _extract_output with dict containing content."""
    message = {"content": [{"text": "test text"}]}
    result = steering_handler._extract_output(message)
    assert "test text" in result


def test_extract_output_with_object_content(steering_handler):
    """Test _extract_output with object having content attribute."""
    message = MagicMock()
    message.content = [{"text": "test text"}]
    result = steering_handler._extract_output(message)
    assert "test text" in result


def test_extract_output_with_list_content(steering_handler):
    """Test _extract_output with list content."""
    message = {"content": [{"text": "first"}, {"text": "second"}]}
    result = steering_handler._extract_output(message)
    assert "first" in result
    assert "second" in result


def test_extract_output_with_text_attribute(steering_handler):
    """Test _extract_output with blocks having text attribute."""
    block = MagicMock()
    block.text = "block text"
    message = {"content": [block]}
    result = steering_handler._extract_output(message)
    assert "block text" in result


def test_extract_input_with_input_kwarg(steering_handler):
    """Test _extract_input from kwargs input."""
    kwargs = {"input": {"text": "user input"}}
    assert steering_handler._extract_input(kwargs) == "user input"


def test_extract_input_with_messages(steering_handler):
    """Test _extract_input from messages list."""
    kwargs = {
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user input"},
        ]
    }
    assert steering_handler._extract_input(kwargs) == "user input"


def test_extract_input_with_invocation_state(steering_handler):
    """Test _extract_input from invocation_state."""
    kwargs = {"invocation_state": {"input": "invocation input"}}
    assert steering_handler._extract_input(kwargs) == "invocation input"


def test_extract_context_from_invocation_state(steering_handler):
    """Test _extract_context from invocation_state."""
    kwargs = {"invocation_state": {"context": {"request_id": "ctx-1"}}}
    assert steering_handler._extract_context(kwargs) == {"request_id": "ctx-1"}


def test_extract_output_with_empty_message(steering_handler):
    """Test _extract_output with empty message."""
    assert steering_handler._extract_output(None) == ""
    assert steering_handler._extract_output("") == ""


def test_extract_output_with_empty_content(steering_handler):
    """Test _extract_output with empty content."""
    message = {"content": ""}
    result = steering_handler._extract_output(message)
    assert result == ""


def test_extract_output_with_mixed_blocks(steering_handler):
    """Test _extract_output with mixed block types."""
    message = {
        "content": [
            {"text": "text block"},
            MagicMock(text="object block"),
            "string block"
        ]
    }
    result = steering_handler._extract_output(message)
    assert "text block" in result
    assert "object block" in result
    assert "string block" in result


def test_extract_output_with_citations(steering_handler):
    """Test _extract_output with citations content."""
    message = {
        "content": [
            {
                "citationsContent": {
                    "content": [
                        {"text": "citation 1"},
                        {"text": "citation 2"},
                    ]
                }
            }
        ]
    }
    result = steering_handler._extract_output(message)
    assert "citation 1" in result
    assert "citation 2" in result


def test_extract_output_with_tool_result(steering_handler):
    """Test _extract_output with tool result block."""
    message = {
        "content": [
            {
                "toolResult": {
                    "content": [{"text": "tool result text"}]
                }
            }
        ]
    }
    result = steering_handler._extract_output(message)
    assert "tool result text" in result


def test_extract_output_with_json(steering_handler):
    """Test _extract_output with json block."""
    message = {"content": [{"json": {"key": "value"}}]}
    result = steering_handler._extract_output(message)
    assert "key" in result
    assert "value" in result


@pytest.mark.asyncio
async def test_steer_after_model_with_logging(mock_strands_steering_modules):
    """Test steer_after_model with logging enabled."""
    from agent_control.integrations.strands.steering import AgentControlSteeringHandler

    handler = AgentControlSteeringHandler(agent_name="test-agent", enable_logging=True)

    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        with patch("agent_control.integrations.strands.steering.logger") as mock_logger:
            # Mock no matches
            mock_result = MagicMock(spec=EvaluationResult)
            mock_result.matches = []
            mock_result.errors = []
            mock_evaluate.return_value = mock_result

            # Create mock message
            message = {"content": [{"text": "test output"}]}

            await handler.steer_after_model(
                agent=MagicMock(),
                message=message,
                stop_reason="end_turn"
            )

            # Verify logging calls
            assert mock_logger.debug.call_count >= 2


@pytest.mark.asyncio
async def test_steer_after_model_updates_last_steer_info(
    steering_handler, mock_strands_steering_modules
):
    """Test that steer_after_model properly updates last_steer_info."""
    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        # Mock a steer match
        mock_match = MagicMock()
        mock_match.action = "steer"
        mock_match.control_name = "control_1"
        mock_match.result.message = "Steer 1"
        mock_match.steering_context.message = "Context 1"

        mock_result = MagicMock(spec=EvaluationResult)
        mock_result.matches = [mock_match]
        mock_result.reason = None
        mock_result.errors = []
        mock_evaluate.return_value = mock_result

        message = {"content": [{"text": "test"}]}

        await steering_handler.steer_after_model(
            agent=MagicMock(),
            message=message,
            stop_reason="end_turn"
        )

        assert steering_handler.last_steer_info["control_name"] == "control_1"
        assert steering_handler.last_steer_info["from_agentcontrol"] is True


def test_extract_output_none_content(steering_handler):
    """Test _extract_output when content is None."""
    message = {"content": None}
    result = steering_handler._extract_output(message)
    assert result == ""


@pytest.mark.asyncio
async def test_steer_after_model_steer_match_with_logging(mock_strands_steering_modules):
    """Test steer_after_model with steer match and logging enabled."""
    from agent_control.integrations.strands.steering import AgentControlSteeringHandler

    handler = AgentControlSteeringHandler(agent_name="test-agent", enable_logging=True)

    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        with patch("agent_control.integrations.strands.steering.logger") as mock_logger:
            # Mock a steer match
            mock_match = MagicMock()
            mock_match.action = "steer"
            mock_match.control_name = "test_control"
            mock_match.result.message = "Steer message"
            mock_match.steering_context.message = "Steering context"

            mock_result = MagicMock(spec=EvaluationResult)
            mock_result.matches = [mock_match]
            mock_result.reason = None
            mock_result.errors = []
            mock_evaluate.return_value = mock_result

            # Create mock message
            message = {"content": [{"text": "test output"}]}

            result = await handler.steer_after_model(
                agent=MagicMock(),
                message=message,
                stop_reason="end_turn"
            )

            # Verify Guide was returned
            assert result.__class__.__name__ == "Guide"
            # Verify logging was called for steer match
            debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
            assert any("returning guide" in str(call) for call in debug_calls)


@pytest.mark.asyncio
async def test_steer_after_model_deny_match_with_logging(mock_strands_steering_modules):
    """Test steer_after_model with deny match and logging enabled."""
    from agent_control.integrations.strands.steering import AgentControlSteeringHandler
    from agent_control import ControlViolationError

    handler = AgentControlSteeringHandler(agent_name="test-agent", enable_logging=True)

    with patch("agent_control.integrations.strands.steering.agent_control.evaluate_controls") as mock_evaluate:  # noqa: E501
        with patch("agent_control.integrations.strands.steering.logger") as mock_logger:
            # Mock a deny match
            mock_match = MagicMock()
            mock_match.action = "deny"
            mock_match.control_name = "test_control"
            mock_match.result.message = "Access denied"

            mock_result = MagicMock(spec=EvaluationResult)
            mock_result.matches = [mock_match]
            mock_result.reason = None
            mock_result.errors = []
            mock_evaluate.return_value = mock_result

            # Create mock message
            message = {"content": [{"text": "test output"}]}

            with pytest.raises(ControlViolationError):
                await handler.steer_after_model(
                    agent=MagicMock(),
                    message=message,
                    stop_reason="end_turn"
                )

            # Verify logging was called for deny match
            debug_calls = [str(call) for call in mock_logger.debug.call_args_list]
            assert any("deny raised" in str(call) for call in debug_calls)
