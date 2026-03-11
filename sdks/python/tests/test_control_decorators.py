"""Tests for @control decorator."""

from unittest.mock import MagicMock, patch

import pytest

from agent_control.control_decorators import ControlViolationError, ControlSteerError, control


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock()
    agent.agent_name = "550e8400-e29b-41d4-a716-446655440000"
    return agent


@pytest.fixture
def mock_safe_response():
    """Response when evaluation passes."""
    return {
        "is_safe": True,
        "confidence": 1.0,
        "matches": []
    }


@pytest.fixture
def mock_unsafe_response():
    """Response when evaluation fails with deny."""
    return {
        "is_safe": False,
        "confidence": 0.95,
        "matches": [
            {
                "control_id": 1,
                "control_name": "test-control",
                "action": "deny",
                "result": {
                    "matched": True,
                    "confidence": 0.95,
                    "message": "Control triggered: toxicity detected",
                    "metadata": {"score": 0.92}
                }
            }
        ]
    }


@pytest.fixture
def mock_warn_response():
    """Response when evaluation triggers warning."""
    return {
        "is_safe": False,
        "confidence": 0.7,
        "matches": [
            {
                "control_id": 1,
                "control_name": "warn-control",
                "action": "warn",
                "result": {
                    "matched": True,
                    "message": "Potential issue detected"
                }
            }
        ]
    }


@pytest.fixture
def mock_steer_response():
    """Response when evaluation triggers steer action with steering context."""
    return {
        "is_safe": False,
        "confidence": 0.85,
        "matches": [
            {
                "control_id": 2,
                "control_name": "steer-control",
                "action": "steer",
                "steering_context": {
                    "message": "Please rephrase your question using respectful language"
                },
                "result": {
                    "matched": True,
                    "message": "Inappropriate language detected",
                    "metadata": {"pattern": "offensive_word"}
                }
            }
        ]
    }


# =============================================================================
# BASIC FUNCTIONALITY TESTS
# =============================================================================

class TestControl:
    """Tests for @control decorator."""

    @pytest.mark.asyncio
    async def test_passes_when_safe(self, mock_agent, mock_safe_response):
        """Test that safe evaluation allows function execution."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_safe_response):

            @control()
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            result = await chat("Hello!")
            assert result == "Response to: Hello!"

    @pytest.mark.asyncio
    async def test_blocks_when_unsafe(self, mock_agent, mock_unsafe_response):
        """Test that unsafe evaluation blocks with ControlViolationError."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_unsafe_response):

            @control()
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            with pytest.raises(ControlViolationError) as exc_info:
                await chat("Toxic message")

            assert exc_info.value.control_name == "test-control"
            assert "toxicity" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_warns_without_blocking(self, mock_agent, mock_warn_response, caplog):
        """Test that warn action logs but allows execution."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_warn_response):

            @control()
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            result = await chat("Questionable message")
            assert result == "Response to: Questionable message"

    @pytest.mark.asyncio
    async def test_no_agent_runs_without_protection(self):
        """Test that decorator passes through if no agent initialized."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=None):

            @control()
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            result = await chat("Hello!")
            assert result == "Response to: Hello!"


# =============================================================================
# CONTROL NAME TESTS
# =============================================================================

class TestPolicyHandling:
    """Tests for policy-based control evaluation."""

    @pytest.mark.asyncio
    async def test_control_triggers_raise_exception(self, mock_agent, mock_unsafe_response):
        """Test that matching control triggers raise ControlViolationError."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_unsafe_response):

            @control()
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            with pytest.raises(ControlViolationError) as exc_info:
                await chat("Test")

            assert exc_info.value.control_name == "test-control"

    @pytest.mark.asyncio
    async def test_steer_action_raises_exception(self, mock_agent, mock_steer_response):
        """Test that steer action raises ControlSteerError with steering context."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_steer_response):

            @control()
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            with pytest.raises(ControlSteerError) as exc_info:
                await chat("Test offensive message")

            # Verify exception has all expected fields
            assert exc_info.value.control_name == "steer-control"
            assert exc_info.value.message == "Inappropriate language detected"
            assert exc_info.value.steering_context == "Please rephrase your question using respectful language"
            assert "steer-control" in str(exc_info.value)
            assert "Please rephrase" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_policy_evaluates_all_controls(self, mock_agent, mock_safe_response):
        """Test that policy evaluates all controls."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_safe_response) as mock_eval:

            @control()  # Apply agent's assigned policy
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            await chat("Hello!")

            # Verify evaluate was called
            assert mock_eval.called


# =============================================================================
# PRE AND POST EXECUTION TESTS
# =============================================================================

class TestPrePostExecution:
    """Tests for pre and post execution checks."""

    @pytest.mark.asyncio
    async def test_calls_pre_and_post(self, mock_agent, mock_safe_response):
        """Test that both pre and post checks are called."""
        call_stages = []

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            call_stages.append(stage)
            return mock_safe_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            @control()
            async def chat(message: str) -> str:
                return f"Response to: {message}"

            await chat("Hello!")

            assert "pre" in call_stages
            assert "post" in call_stages

    @pytest.mark.asyncio
    async def test_pre_block_prevents_execution(self, mock_agent, mock_safe_response, mock_unsafe_response):
        """Test that pre-check block prevents function execution."""
        function_executed = False

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            if stage == "pre":
                return mock_unsafe_response
            return mock_safe_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            @control()
            async def chat(message: str) -> str:
                nonlocal function_executed
                function_executed = True
                return f"Response to: {message}"

            with pytest.raises(ControlViolationError):
                await chat("Blocked message")

            assert not function_executed

    @pytest.mark.asyncio
    async def test_post_check_receives_output(self, mock_agent, mock_safe_response):
        """Test that post-check receives the function output."""
        captured_step = {}

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            if stage == "post":
                captured_step.update(step)
            return mock_safe_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            @control()
            async def chat(message: str) -> str:
                return "Generated response"

            await chat("Hello!")

            assert "output" in captured_step
            assert "Generated response" in captured_step["output"]


# =============================================================================
# INPUT EXTRACTION TESTS
# =============================================================================

class TestInputExtraction:
    """Tests for automatic input extraction from function arguments."""

    @pytest.mark.asyncio
    async def test_extracts_input_param(self, mock_agent, mock_safe_response):
        """Test extraction of 'input' parameter."""
        captured_step = {}

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            if stage == "pre":
                captured_step.update(step)
            return mock_safe_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            @control()
            async def process(input: str) -> str:
                return input.upper()

            await process("hello world")

            assert captured_step["input"] == "hello world"

    @pytest.mark.asyncio
    async def test_extracts_message_param(self, mock_agent, mock_safe_response):
        """Test extraction of 'message' parameter."""
        captured_step = {}

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            if stage == "pre":
                captured_step.update(step)
            return mock_safe_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            @control()
            async def chat(message: str, context: dict) -> str:
                return f"Response: {message}"

            await chat("Hello!", {"user": "test"})

            assert captured_step["input"] == "Hello!"

    @pytest.mark.asyncio
    async def test_extracts_query_param(self, mock_agent, mock_safe_response):
        """Test extraction of 'query' parameter."""
        captured_step = {}

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            if stage == "pre":
                captured_step.update(step)
            return mock_safe_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            @control()
            async def search(query: str, limit: int = 10) -> list:
                return [query]

            await search("test query")

            assert captured_step["input"] == "test query"


# =============================================================================
# SYNC FUNCTION TESTS
# =============================================================================

class TestSyncFunctions:
    """Tests for sync function support."""

    def test_sync_function_passes(self, mock_agent, mock_safe_response):
        """Test that sync functions work correctly."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_safe_response):

            @control()
            def process(input: str) -> str:
                return input.upper()

            result = process("hello")
            assert result == "HELLO"

    def test_sync_function_blocks(self, mock_agent, mock_unsafe_response):
        """Test that sync functions can be blocked."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_unsafe_response):

            @control()
            def process(input: str) -> str:
                return input.upper()

            with pytest.raises(ControlViolationError):
                process("blocked")


# =============================================================================
# STACKING TESTS
# =============================================================================

class TestStackedDecorators:
    """Tests for stacking multiple control decorators."""

    @pytest.mark.asyncio
    async def test_stacked_controls(self, mock_agent, mock_safe_response):
        """Test multiple decorators on same function."""
        call_count = 0

        async def mock_evaluate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_safe_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            @control(policy="policy-1")
            @control(policy="policy-2")
            async def process(input: str) -> str:
                return input

            await process("test")
            
            # Each decorator calls pre + post = 4 total
            assert call_count == 4


# =============================================================================
# CONTROL VIOLATION TESTS
# =============================================================================

class TestControlViolationError:
    """Tests for ControlViolationError exception."""

    def test_exception_creation(self):
        """Test ControlViolationError can be created with all fields."""
        violation = ControlViolationError(
            control_name="test-control",
            message="Test violation",
            metadata={"key": "value"}
        )
        
        assert violation.control_name == "test-control"
        assert violation.message == "Test violation"
        assert violation.metadata == {"key": "value"}

    def test_exception_string(self):
        """Test ControlViolationError string representation."""
        violation = ControlViolationError(control_name="my-control", message="Something bad")
        
        assert "my-control" in str(violation)
        assert "Something bad" in str(violation)

    def test_is_exception(self):
        """Test ControlViolationError is an Exception."""
        violation = ControlViolationError(control_name="test", message="message")
        assert isinstance(violation, Exception)

        with pytest.raises(ControlViolationError):
            raise violation


class TestControlSteerError:
    """Tests for ControlSteerError exception."""

    def test_exception_creation(self):
        """Test ControlSteerError can be created with all fields."""
        steer_error = ControlSteerError(
            control_name="steer-control",
            message="Need to adjust approach",
            metadata={"pattern": "offensive"},
            steering_context="Please rephrase using respectful language"
        )

        assert steer_error.control_name == "steer-control"
        assert steer_error.message == "Need to adjust approach"
        assert steer_error.metadata == {"pattern": "offensive"}
        assert steer_error.steering_context == "Please rephrase using respectful language"

    def test_exception_steering_context_fallback(self):
        """Test steering_context falls back to metadata if not provided."""
        steer_error = ControlSteerError(
            control_name="steer-control",
            message="Test message",
            metadata={"steering_context": "Fallback steering context from metadata"}
        )

        assert steer_error.steering_context == "Fallback steering context from metadata"

    def test_exception_steering_context_default(self):
        """Test steering_context defaults to 'No steering context provided' if not in metadata."""
        steer_error = ControlSteerError(
            control_name="steer-control",
            message="Test message",
            metadata={}
        )

        assert steer_error.steering_context == "No steering context provided"

    def test_exception_string(self):
        """Test ControlSteerError string representation."""
        steer_error = ControlSteerError(
            control_name="my-steer-control",
            message="Needs correction",
            steering_context="Use this approach instead"
        )

        assert "my-steer-control" in str(steer_error)
        assert "Needs correction" in str(steer_error)
        assert "Use this approach instead" in str(steer_error)

    def test_is_exception(self):
        """Test ControlSteerError is an Exception."""
        steer_error = ControlSteerError(control_name="test", message="message")
        assert isinstance(steer_error, Exception)

        with pytest.raises(ControlSteerError):
            raise steer_error

    def test_input_output_data(self):
        """Test ControlSteerError stores input/output data."""
        steer_error = ControlSteerError(
            control_name="test-control",
            message="Test",
            input_data={"query": "bad input"},
            output_data={"response": "bad output"}
        )

        assert steer_error.input_data == {"query": "bad input"}
        assert steer_error.output_data == {"response": "bad output"}


# =============================================================================
# STEP NAME TESTS
# =============================================================================

class TestStepName:
    """Tests for custom step_name parameter."""

    @pytest.mark.asyncio
    async def test_custom_step_name_used_in_payload(self, mock_agent, mock_safe_response):
        """Test that custom step_name is passed to evaluation payload."""
        # GIVEN: A mock evaluation function that captures step payloads
        captured_steps = []

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            captured_steps.append(step)
            return mock_safe_response

        # GIVEN: Agent control is initialized and evaluation is mocked
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            # GIVEN: A function decorated with custom step_name
            @control(step_name="custom_handler")
            async def my_function(message: str) -> str:
                return f"Response: {message}"

            # WHEN: The decorated function is called
            await my_function("test")

            # THEN: Both pre and post evaluation payloads should be captured
            assert len(captured_steps) == 2

            # THEN: Both payloads should use the custom step name
            assert captured_steps[0]["name"] == "custom_handler"
            assert captured_steps[1]["name"] == "custom_handler"

    @pytest.mark.asyncio
    async def test_default_step_name_uses_function_name(self, mock_agent, mock_safe_response):
        """Test that without step_name, function name is used."""
        # GIVEN: A mock evaluation function that captures step payloads
        captured_steps = []

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            captured_steps.append(step)
            return mock_safe_response

        # GIVEN: Agent control is initialized and evaluation is mocked
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            # GIVEN: A function decorated without custom step_name
            @control()
            async def my_special_function(message: str) -> str:
                return f"Response: {message}"

            # WHEN: The decorated function is called
            await my_special_function("test")

            # THEN: Both pre and post evaluation payloads should be captured
            assert len(captured_steps) == 2

            # THEN: Both payloads should use the function name as default step name
            assert captured_steps[0]["name"] == "my_special_function"
            assert captured_steps[1]["name"] == "my_special_function"

    @pytest.mark.asyncio
    async def test_step_name_with_tool_decorator(self, mock_agent, mock_safe_response):
        """Test step_name overrides tool name from @tool decorator."""
        # GIVEN: A mock evaluation function that captures step payloads
        captured_steps = []

        async def mock_evaluate(
            agent_name,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
            event_agent_name=None,
        ):
            captured_steps.append(step)
            return mock_safe_response

        # GIVEN: Agent control is initialized and evaluation is mocked
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate):

            # GIVEN: A function with tool_name attribute (simulating @tool decorator)
            async def search_tool(query: str) -> str:
                return f"Results for: {query}"

            # GIVEN: tool_name is added before @control (simulating decorator stacking)
            search_tool.tool_name = "search"

            # GIVEN: @control decorator is applied with custom step_name
            search_tool = control(step_name="custom_tool_name")(search_tool)

            # WHEN: The decorated function is called
            await search_tool("test query")

            # THEN: Both pre and post evaluation payloads should be captured
            assert len(captured_steps) == 2

            # THEN: Custom step_name should override tool_name in both payloads
            assert captured_steps[0]["name"] == "custom_tool_name"
            assert captured_steps[1]["name"] == "custom_tool_name"
            # THEN: Step should still be detected as tool type
            assert captured_steps[0]["type"] == "tool"


# =============================================================================
# STEERING CONTEXT TESTS
# =============================================================================

class TestSteeringContextHandling:
    """Tests for steering context extraction and handling."""

    @pytest.mark.asyncio
    async def test_steering_context_as_string(self, mock_agent):
        """Test steering_context extraction when it's a plain string."""
        response_with_string_context = {
            "is_safe": False,
            "confidence": 0.85,
            "matches": [
                {
                    "control_id": 2,
                    "control_name": "steer-control",
                    "action": "steer",
                    "steering_context": "Please use a different approach",  # String instead of dict
                    "result": {
                        "matched": True,
                        "message": "Issue detected",
                        "metadata": {}
                    }
                }
            ]
        }

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=response_with_string_context):

            @control()
            async def test_func():
                return "test"

            with pytest.raises(ControlSteerError) as exc_info:
                await test_func()

            # String steering context should be used directly
            assert exc_info.value.steering_context == "Please use a different approach"

    @pytest.mark.asyncio
    async def test_steering_context_fallback_to_message(self, mock_agent):
        """Test steering_context falls back to evaluator message when not provided."""
        response_without_context = {
            "is_safe": False,
            "confidence": 0.85,
            "matches": [
                {
                    "control_id": 2,
                    "control_name": "steer-control",
                    "action": "steer",
                    "steering_context": None,  # No steering context provided
                    "result": {
                        "matched": True,
                        "message": "Default evaluator message",
                        "metadata": {}
                    }
                }
            ]
        }

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=response_without_context):

            @control()
            async def test_func():
                return "test"

            with pytest.raises(ControlSteerError) as exc_info:
                await test_func()

            # Should fall back to evaluator message
            assert exc_info.value.steering_context == "Default evaluator message"


# =============================================================================
# EXCEPTION HANDLING TESTS
# =============================================================================

class TestExceptionHandling:
    """Tests for exception handling in pre/post execution checks."""

    @pytest.mark.asyncio
    async def test_control_steer_error_propagates_in_pre_execution(self, mock_agent, mock_steer_response):
        """Test that ControlSteerError is propagated (not caught) in pre-execution."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", return_value=mock_steer_response):

            @control()
            async def test_func():
                return "should not execute"

            # ControlSteerError should propagate to caller
            with pytest.raises(ControlSteerError) as exc_info:
                await test_func()

            assert exc_info.value.control_name == "steer-control"

    @pytest.mark.asyncio
    async def test_control_steer_error_propagates_in_post_execution(self, mock_agent, mock_safe_response, mock_steer_response):
        """Test that ControlSteerError is propagated (not caught) in post-execution."""
        call_count = [0]

        def mock_evaluate_side_effect(*args, **kwargs):
            call_count[0] += 1
            # First call (pre) is safe, second call (post) triggers steer
            if call_count[0] == 1:
                return mock_safe_response
            return mock_steer_response

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate_side_effect):

            @control()
            async def test_func():
                return "executed"

            # ControlSteerError from post-execution should propagate
            with pytest.raises(ControlSteerError) as exc_info:
                await test_func()

            assert exc_info.value.control_name == "steer-control"

    @pytest.mark.asyncio
    async def test_other_exceptions_wrapped_in_pre_execution(self, mock_agent):
        """Test that non-control exceptions are wrapped in RuntimeError in pre-execution."""
        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=ValueError("Unexpected error")):

            @control()
            async def test_func():
                return "should not execute"

            # Other exceptions should be wrapped in RuntimeError
            with pytest.raises(RuntimeError) as exc_info:
                await test_func()

            assert "Control check failed unexpectedly" in str(exc_info.value)
            assert "Unexpected error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_other_exceptions_wrapped_in_post_execution(self, mock_agent, mock_safe_response):
        """Test that non-control exceptions fail closed in post-execution."""
        call_count = [0]
        executed = {"value": False}

        def mock_evaluate_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_safe_response
            raise ValueError("Post-execution error")

        with patch("agent_control.control_decorators._get_current_agent", return_value=mock_agent), \
             patch("agent_control.control_decorators._evaluate", side_effect=mock_evaluate_side_effect), \
             patch("agent_control.control_decorators.logger") as mock_logger:

            @control()
            async def test_func():
                executed["value"] = True
                return "executed successfully"

            # Function still executes, but the result is withheld for safety.
            with pytest.raises(RuntimeError) as exc_info:
                await test_func()

            assert executed["value"] is True
            assert "Control check failed unexpectedly after execution" in str(exc_info.value)
            assert "Post-execution error" in str(exc_info.value)

            mock_logger.error.assert_called_once()
            assert mock_logger.error.call_args[0][0] == "%s-execution control check failed: %s"
            assert mock_logger.error.call_args[0][1] == "Post"
            assert str(mock_logger.error.call_args[0][2]) == "Post-execution error"
