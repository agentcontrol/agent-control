"""Tests for @control decorator."""

from unittest.mock import MagicMock, patch

import pytest

from agent_control.control_decorators import ControlViolationError, control


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_agent():
    """Create a mock agent."""
    agent = MagicMock()
    agent.agent_id = "550e8400-e29b-41d4-a716-446655440000"
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
            agent_uuid,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
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
            agent_uuid,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
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
            agent_uuid,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
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
            agent_uuid,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
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
            agent_uuid,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
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
            agent_uuid,
            step,
            stage,
            server_url,
            trace_id=None,
            span_id=None,
            controls=None,
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
