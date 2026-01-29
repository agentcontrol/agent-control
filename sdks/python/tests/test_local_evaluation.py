"""Tests for local control execution in SDK.

These tests verify the check_evaluation_with_local function:
1. Local-only controls execute locally without server call
2. Server-only controls call server
3. Mixed controls: local first, then server
4. Deny short-circuit: local deny skips server call
5. Result merging: combines matches/errors from both
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from agent_control_models import (
    ControlMatch,
    EvaluationResponse,
    EvaluationResult,
    EvaluatorResult,
    Step,
)

from agent_control.client import AgentControlClient
from agent_control.evaluation import (
    _merge_results,
    check_evaluation_with_local,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def agent_uuid() -> UUID:
    """Test agent UUID."""
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def llm_payload() -> Step:
    """Sample LLM call payload."""
    return Step(type="llm", name="test-step", input="test input", output=None)


@pytest.fixture
def tool_payload() -> Step:
    """Sample tool step payload."""
    return Step(type="tool", name="test_tool", input={"query": "test"}, output=None)


def make_control_dict(
    control_id: int,
    name: str,
    *,
    execution: str = "server",
    evaluator: str = "regex",
    pattern: str = r"test",
    action: str = "deny",
    step_type: str = "llm",
    stage: str = "pre",
    path: str | None = None,
) -> dict[str, Any]:
    """Create a control dict like what initAgent returns."""
    # Default path based on payload type
    if path is None:
        path = "input"
    return {
        "id": control_id,
        "name": name,
        "control": {
            "description": f"Test control {name}",
            "enabled": True,
            "execution": execution,
            "scope": {"step_types": [step_type], "stages": [stage]},
            "selector": {"path": path},
            "evaluator": {
                "name": evaluator,
                "config": {"pattern": pattern},
            },
            "action": {"decision": action},
        },
    }


# =============================================================================
# Test: _merge_results
# =============================================================================


class TestMergeResults:
    """Tests for result merging logic."""

    def test_merge_both_safe(self):
        """Merging two safe results should be safe."""
        local = EvaluationResponse(is_safe=True, confidence=0.9)
        server = EvaluationResponse(is_safe=True, confidence=0.8)

        result = _merge_results(local, server)

        assert result.is_safe is True
        assert result.confidence == 0.8  # min of both

    def test_merge_local_deny(self):
        """Local deny should make merged result unsafe."""
        local = EvaluationResponse(is_safe=False, confidence=1.0)
        server = EvaluationResponse(is_safe=True, confidence=0.9)

        result = _merge_results(local, server)

        assert result.is_safe is False
        assert result.confidence == 0.9  # min of both

    def test_merge_server_deny(self):
        """Server deny should make merged result unsafe."""
        local = EvaluationResponse(is_safe=True, confidence=0.9)
        server = EvaluationResponse(is_safe=False, confidence=1.0)

        result = _merge_results(local, server)

        assert result.is_safe is False
        assert result.confidence == 0.9  # min of both

    def test_merge_both_deny(self):
        """Both denying should make merged result unsafe."""
        local = EvaluationResponse(is_safe=False, confidence=1.0)
        server = EvaluationResponse(is_safe=False, confidence=1.0)

        result = _merge_results(local, server)

        assert result.is_safe is False
        assert result.confidence == 1.0

    def test_merge_combines_matches(self):
        """Matches from both should be combined."""
        local_match = ControlMatch(
            control_id=1,
            control_name="local_ctrl",
            action="deny",
            result=EvaluatorResult(matched=True, confidence=1.0),
        )
        server_match = ControlMatch(
            control_id=2,
            control_name="server_ctrl",
            action="deny",
            result=EvaluatorResult(matched=True, confidence=1.0),
        )

        local = EvaluationResponse(is_safe=False, confidence=1.0, matches=[local_match])
        server = EvaluationResponse(is_safe=False, confidence=1.0, matches=[server_match])

        result = _merge_results(local, server)

        assert result.matches is not None
        assert len(result.matches) == 2
        assert result.matches[0].control_name == "local_ctrl"
        assert result.matches[1].control_name == "server_ctrl"

    def test_merge_combines_errors(self):
        """Errors from both should be combined."""
        local_error = ControlMatch(
            control_id=1,
            control_name="local_err",
            action="deny",
            result=EvaluatorResult(matched=False, confidence=0.0, error="local error"),
        )
        server_error = ControlMatch(
            control_id=2,
            control_name="server_err",
            action="deny",
            result=EvaluatorResult(matched=False, confidence=0.0, error="server error"),
        )

        local = EvaluationResponse(is_safe=False, confidence=0.0, errors=[local_error])
        server = EvaluationResponse(is_safe=False, confidence=0.0, errors=[server_error])

        result = _merge_results(local, server)

        assert result.errors is not None
        assert len(result.errors) == 2

    def test_merge_combines_reasons(self):
        """Reasons from both should be combined."""
        local = EvaluationResponse(is_safe=True, confidence=0.9, reason="Local reason")
        server = EvaluationResponse(is_safe=True, confidence=0.8, reason="Server reason")

        result = _merge_results(local, server)

        assert result.reason == "Local reason; Server reason"


# =============================================================================
# Test: check_evaluation_with_local
# =============================================================================


class TestCheckEvaluationWithLocal:
    """Tests for check_evaluation_with_local function."""

    @pytest.mark.asyncio
    async def test_local_only_controls_no_server_call(self, agent_uuid, llm_payload):
        """When only local controls exist, server should not be called."""
        controls = [
            make_control_dict(1, "local_ctrl", execution="sdk", pattern=r"never_match"),
        ]

        # Mock client
        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock()

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Server should not be called
        client.http_client.post.assert_not_called()

        # Result should be safe (pattern doesn't match)
        assert result.is_safe is True

    @pytest.mark.asyncio
    async def test_server_only_controls_calls_server(self, agent_uuid, llm_payload):
        """When only server controls exist, server should be called."""
        controls = [
            make_control_dict(1, "server_ctrl", execution="server"),
        ]

        # Mock client with server response
        client = MagicMock(spec=AgentControlClient)
        mock_response = MagicMock()
        mock_response.json.return_value = {"is_safe": True, "confidence": 1.0}
        mock_response.raise_for_status = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_response)

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Server should be called
        client.http_client.post.assert_called_once()
        assert "/api/v1/evaluation" in str(client.http_client.post.call_args)

        assert result.is_safe is True

    @pytest.mark.asyncio
    async def test_local_deny_short_circuits(self, agent_uuid, llm_payload):
        """Local deny should return immediately without calling server."""
        controls = [
            # Local control that will match (deny)
            make_control_dict(1, "local_deny", execution="sdk", pattern=r"test"),
            # Server control (should not be called)
            make_control_dict(2, "server_ctrl", execution="server"),
        ]

        # Mock client
        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock()

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Server should NOT be called (short-circuit on local deny)
        client.http_client.post.assert_not_called()

        # Result should be unsafe
        assert result.is_safe is False
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "local_deny"

    @pytest.mark.asyncio
    async def test_mixed_controls_local_passes_then_server(self, agent_uuid, llm_payload):
        """When local controls pass, server controls should still be called."""
        controls = [
            # Local control that won't match
            make_control_dict(1, "local_allow", execution="sdk", pattern=r"never_match"),
            # Server control
            make_control_dict(2, "server_ctrl", execution="server"),
        ]

        # Mock client with server response
        client = MagicMock(spec=AgentControlClient)
        mock_response = MagicMock()
        mock_response.json.return_value = {"is_safe": True, "confidence": 0.9}
        mock_response.raise_for_status = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_response)

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Server should be called
        client.http_client.post.assert_called_once()

        # Result should be safe
        assert result.is_safe is True

    @pytest.mark.asyncio
    async def test_no_controls_returns_safe(self, agent_uuid, llm_payload):
        """When no controls exist, result should be safe."""
        controls: list[dict[str, Any]] = []

        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock()

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # No server call
        client.http_client.post.assert_not_called()

        # Safe with full confidence
        assert result.is_safe is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_invalid_local_control_skipped(self, agent_uuid, llm_payload):
        """Invalid local controls should be skipped."""
        controls = [
            # Invalid control (missing required fields)
            {"id": 1, "name": "invalid", "control": {"execution": "sdk"}},
            # Valid server control
            make_control_dict(2, "server_ctrl", execution="server"),
        ]

        # Mock client with server response
        client = MagicMock(spec=AgentControlClient)
        mock_response = MagicMock()
        mock_response.json.return_value = {"is_safe": True, "confidence": 1.0}
        mock_response.raise_for_status = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_response)

        # Should not raise, just skip invalid control
        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Server should be called for valid control
        client.http_client.post.assert_called_once()
        assert result.is_safe is True

    @pytest.mark.asyncio
    async def test_tool_step_local_evaluation(self, agent_uuid, tool_payload):
        """Local evaluation should work with Step payloads."""
        controls = [
            make_control_dict(
                1,
                "local_tool_ctrl",
                execution="sdk",
                pattern=r"test",
                step_type="tool",
            ),
        ]

        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock()

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=tool_payload,
            stage="pre",
            controls=controls,
        )

        # No server call
        client.http_client.post.assert_not_called()

        # Local control should have matched on Step input
        assert result.is_safe is False

    @pytest.mark.asyncio
    async def test_mixed_controls_merged_results(self, agent_uuid, llm_payload):
        """Results from local and server should be merged."""
        controls = [
            # Local control (action=log, will match but not deny)
            make_control_dict(1, "local_log", execution="sdk", pattern=r"test", action="log"),
            # Server control
            make_control_dict(2, "server_ctrl", execution="server"),
        ]

        # Mock server response with a match
        server_match = {
            "control_id": 2,
            "control_name": "server_ctrl",
            "action": "log",
            "result": {"matched": True, "confidence": 1.0},
        }
        client = MagicMock(spec=AgentControlClient)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "is_safe": True,
            "confidence": 0.9,
            "matches": [server_match],
        }
        mock_response.raise_for_status = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_response)

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Both local and server should have run
        client.http_client.post.assert_called_once()

        # Matches should be merged
        assert result.matches is not None
        # Local match + server match
        assert len(result.matches) == 2

    @pytest.mark.asyncio
    async def test_tool_step_mixed_local_and_server_controls(self, agent_uuid, tool_payload):
        """Test mixed local/server controls for same tool step.

        Given: A tool step with both local and server controls
        When: Local control passes (no deny)
        Then: Server is called, results merged
        """
        controls = [
            # Local control that won't match (pattern doesn't match)
            make_control_dict(
                1,
                "local_tool_ctrl",
                execution="sdk",
                pattern=r"never_match_xyz",
                action="deny",
                step_type="tool",
            ),
            # Server control
            make_control_dict(
                2,
                "server_tool_ctrl",
                execution="server",
                pattern=r"test",
                action="log",
                step_type="tool",
            ),
        ]

        # Mock server response
        server_match = {
            "control_id": 2,
            "control_name": "server_tool_ctrl",
            "action": "log",
            "result": {"matched": True, "confidence": 1.0},
        }
        client = MagicMock(spec=AgentControlClient)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "is_safe": True,
            "confidence": 1.0,
            "matches": [server_match],
        }
        mock_response.raise_for_status = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_response)

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=tool_payload,
            stage="pre",
            controls=controls,
        )

        # Server should be called (local didn't deny)
        client.http_client.post.assert_called_once()

        # Result should be safe with server match
        assert result.is_safe is True
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "server_tool_ctrl"

    @pytest.mark.asyncio
    async def test_tool_step_local_deny_skips_server(self, agent_uuid, tool_payload):
        """Test that local deny on tool step short-circuits server call.

        Given: A tool step with local deny control that matches
        When: Local control matches and denies
        Then: Server is NOT called, result is unsafe
        """
        controls = [
            # Local control that WILL match and deny
            make_control_dict(
                1,
                "local_deny_ctrl",
                execution="sdk",
                pattern=r"test",  # matches tool_payload input
                action="deny",
                step_type="tool",
            ),
            # Server control (should not be called)
            make_control_dict(
                2,
                "server_tool_ctrl",
                execution="server",
                pattern=r"test",
                action="deny",
                step_type="tool",
            ),
        ]

        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock()

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=tool_payload,
            stage="pre",
            controls=controls,
        )

        # Server should NOT be called (short-circuit on local deny)
        client.http_client.post.assert_not_called()

        # Result should be unsafe from local deny
        assert result.is_safe is False
        assert result.matches is not None
        assert len(result.matches) == 1
        assert result.matches[0].control_name == "local_deny_ctrl"

    @pytest.mark.asyncio
    async def test_local_control_with_missing_evaluator_raises(self, agent_uuid, llm_payload):
        """Test that local control with unavailable evaluator raises RuntimeError.

        Given: A local control referencing an evaluator that doesn't exist
        When: check_evaluation_with_local is called
        Then: RuntimeError is raised with helpful message
        """
        controls = [
            make_control_dict(
                1,
                "local_missing_evaluator",
                execution="sdk",
                evaluator="nonexistent-evaluator-xyz",
                pattern=r"test",
            ),
        ]

        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()

        with pytest.raises(RuntimeError) as exc_info:
            await check_evaluation_with_local(
                client=client,
                agent_uuid=agent_uuid,
                step=llm_payload,
                stage="pre",
                controls=controls,
            )

        assert "local_missing_evaluator" in str(exc_info.value)
        assert "nonexistent-evaluator-xyz" in str(exc_info.value)
        assert "not available" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_local_control_with_agent_scoped_evaluator_raises(self, agent_uuid, llm_payload):
        """Test that local control with agent-scoped evaluator raises RuntimeError.

        Given: A local control referencing an agent-scoped evaluator (agent:evaluator)
        When: check_evaluation_with_local is called
        Then: RuntimeError is raised explaining agent-scoped evaluators are server-only
        """
        controls = [
            make_control_dict(
                1,
                "local_agent_scoped",
                execution="sdk",
                evaluator="my-agent:custom-evaluator",
                pattern=r"test",
            ),
        ]

        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()

        with pytest.raises(RuntimeError) as exc_info:
            await check_evaluation_with_local(
                client=client,
                agent_uuid=agent_uuid,
                step=llm_payload,
                stage="pre",
                controls=controls,
            )

        assert "local_agent_scoped" in str(exc_info.value)
        assert "my-agent:custom-evaluator" in str(exc_info.value)
        assert "server-only" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_server_control_with_missing_evaluator_allowed(self, agent_uuid, llm_payload):
        """Test that server control with unavailable evaluator is allowed (server handles it).

        Given: A server control (execution="server") referencing an evaluator that doesn't exist locally
        When: check_evaluation_with_local is called
        Then: No error, server is called to handle it
        """
        controls = [
            make_control_dict(
                1,
                "server_custom_evaluator",
                execution="server",
                evaluator="server-only-evaluator",
                pattern=r"test",
            ),
        ]

        # Mock server response
        client = MagicMock(spec=AgentControlClient)
        mock_response = MagicMock()
        mock_response.json.return_value = {"is_safe": True, "confidence": 1.0}
        mock_response.raise_for_status = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_response)

        # Should not raise - server handles unavailable evaluators
        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Server should be called
        client.http_client.post.assert_called_once()
        assert result.is_safe is True

    @pytest.mark.asyncio
    async def test_invalid_local_control_populates_errors(self, agent_uuid, llm_payload):
        """Test that invalid local controls appear in result.errors.

        Given: A local control that fails validation
        When: check_evaluation_with_local is called
        Then: The parse error should appear in result.errors
        """
        controls = [
            # Invalid control (missing required evaluator field)
            {"id": 999, "name": "bad_control", "control": {"execution": "sdk"}},
        ]

        client = MagicMock(spec=AgentControlClient)
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock()

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Should still be safe (invalid control skipped)
        assert result.is_safe is True

        # Errors should contain the parse error
        assert result.errors is not None
        assert len(result.errors) == 1
        assert result.errors[0].control_id == 999
        assert result.errors[0].control_name == "bad_control"
        # Error message is in result.error field
        assert result.errors[0].result is not None
        assert "Failed to parse local control" in (result.errors[0].result.error or "")

    @pytest.mark.asyncio
    async def test_malformed_server_control_still_calls_server(self, agent_uuid, llm_payload):
        """Test that malformed server control data still triggers server call.

        Given: A server control (execution="server") with missing/malformed 'control' data
        When: check_evaluation_with_local is called
        Then: Server is still called (server will handle parsing)

        This tests the fix for the bug where has_server_controls was only set
        after successfully parsing controls, causing server call to be skipped
        if all server controls failed to parse locally.
        """
        controls = [
            # Malformed server control - missing 'control' key entirely
            {"id": 1, "name": "malformed_server"},
            # Malformed server control - empty control dict (execution defaults to server)
            {"id": 2, "name": "empty_server", "control": {}},
        ]

        # Mock server response
        client = MagicMock(spec=AgentControlClient)
        mock_response = MagicMock()
        mock_response.json.return_value = {"is_safe": True, "confidence": 1.0}
        mock_response.raise_for_status = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_response)

        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent_uuid,
            step=llm_payload,
            stage="pre",
            controls=controls,
        )

        # Server MUST be called even though control data is malformed
        # (the server will handle/reject the malformed controls)
        client.http_client.post.assert_called_once()
        assert result.is_safe is True
