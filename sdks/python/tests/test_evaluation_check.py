"""Tests for check_evaluation function in evaluation.py.

These tests verify:
1. check_evaluation raises HumanReviewRequiredError when human_review_required=True
2. check_evaluation raises ControlViolationError when is_safe=False with deny action
3. raise_on_violation parameter controls exception behavior
4. Proper exception details (control_id, control_name, message, metadata)
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from agent_control.client import AgentControlClient
from agent_control.control_decorators import ControlViolationError, HumanReviewRequiredError
from agent_control.evaluation import check_evaluation

try:
    from agent_control_models import LlmCall, ToolCall
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def agent_uuid() -> UUID:
    """Test agent UUID."""
    return UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def mock_client():
    """Mock AgentControlClient."""
    client = MagicMock(spec=AgentControlClient)
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock()
    return client


@pytest.fixture
def safe_response():
    """Safe evaluation response."""
    return {
        "is_safe": True,
        "confidence": 1.0,
        "human_review_required": False,
        "matches": [],
        "errors": []
    }


@pytest.fixture
def human_review_response():
    """Response requiring human review with match."""
    return {
        "is_safe": False,
        "confidence": 0.85,
        "human_review_required": True,
        "matches": [
            {
                "control_id": 10,
                "control_name": "sensitive-data-control",
                "action": "human_review",
                "result": {
                    "matched": True,
                    "confidence": 0.85,
                    "message": "PII detected in query",
                    "metadata": {"pii_types": ["email", "phone"]}
                }
            }
        ],
        "errors": []
    }


@pytest.fixture
def human_review_no_match_response():
    """Response requiring human review without explicit match."""
    return {
        "is_safe": False,
        "confidence": 0.9,
        "human_review_required": True,
        "matches": [],
        "errors": []
    }


@pytest.fixture
def deny_response():
    """Response with deny action."""
    return {
        "is_safe": False,
        "confidence": 0.95,
        "human_review_required": False,
        "matches": [
            {
                "control_id": 5,
                "control_name": "sql-injection-control",
                "action": "deny",
                "result": {
                    "matched": True,
                    "confidence": 0.95,
                    "message": "SQL injection detected",
                    "metadata": {"pattern": "DROP TABLE"}
                }
            }
        ],
        "errors": []
    }


@pytest.fixture
def warn_response():
    """Response with warn action."""
    return {
        "is_safe": False,
        "confidence": 0.7,
        "human_review_required": False,
        "matches": [
            {
                "control_id": 3,
                "control_name": "warning-control",
                "action": "warn",
                "result": {
                    "matched": True,
                    "confidence": 0.7,
                    "message": "Potential issue detected"
                }
            }
        ],
        "errors": []
    }


@pytest.fixture
def tool_call_payload():
    """Sample ToolCall payload."""
    if MODELS_AVAILABLE:
        return ToolCall(
            tool_name="query_database",
            arguments={"sql": "SELECT * FROM users"},
            output=None
        )
    else:
        # Simple dict for when models not available
        return {
            "tool_name": "query_database",
            "arguments": {"sql": "SELECT * FROM users"},
            "output": None
        }


@pytest.fixture
def llm_call_payload():
    """Sample LlmCall payload."""
    if MODELS_AVAILABLE:
        return LlmCall(input="What is the weather?", output=None)
    else:
        return {"input": "What is the weather?", "output": None}


# =============================================================================
# HUMAN REVIEW REQUIRED TESTS
# =============================================================================

class TestCheckEvaluationHumanReview:
    """Tests for check_evaluation raising HumanReviewRequiredError."""

    @pytest.mark.asyncio
    async def test_raises_human_review_error_with_match(
        self, mock_client, agent_uuid, tool_call_payload, human_review_response
    ):
        """Test that check_evaluation raises HumanReviewRequiredError with detailed match."""
        mock_response = MagicMock()
        mock_response.json.return_value = human_review_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        with pytest.raises(HumanReviewRequiredError) as exc_info:
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=tool_call_payload,
                check_stage="pre"
            )

        # Verify exception details
        assert exc_info.value.control_id == 10
        assert exc_info.value.control_name == "sensitive-data-control"
        assert "PII detected in query" in exc_info.value.message
        assert exc_info.value.metadata == {"pii_types": ["email", "phone"]}

    @pytest.mark.asyncio
    async def test_raises_human_review_error_without_match(
        self, mock_client, agent_uuid, llm_call_payload, human_review_no_match_response
    ):
        """Test that check_evaluation raises HumanReviewRequiredError even without explicit match."""
        mock_response = MagicMock()
        mock_response.json.return_value = human_review_no_match_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        with pytest.raises(HumanReviewRequiredError) as exc_info:
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=llm_call_payload,
                check_stage="pre"
            )

        # Should raise with generic message
        assert "Human review required" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_human_review_no_raise_returns_result(
        self, mock_client, agent_uuid, tool_call_payload, human_review_response
    ):
        """Test that raise_on_violation=False returns result without raising."""
        mock_response = MagicMock()
        mock_response.json.return_value = human_review_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        # Should not raise when raise_on_violation=False
        result = await check_evaluation(
            client=mock_client,
            agent_uuid=agent_uuid,
            payload=tool_call_payload,
            check_stage="pre",
            raise_on_violation=False
        )

        assert result.human_review_required is True
        assert result.is_safe is False

    @pytest.mark.asyncio
    async def test_human_review_in_post_check(
        self, mock_client, agent_uuid, tool_call_payload, human_review_response
    ):
        """Test human review detection in post-execution check."""
        # Modify payload to have output (post-check)
        if MODELS_AVAILABLE:
            payload_with_output = ToolCall(
                tool_name="query_database",
                arguments={"sql": "SELECT * FROM users"},
                output={"rows": [{"id": 1, "email": "test@example.com"}]}
            )
        else:
            payload_with_output = {
                "tool_name": "query_database",
                "arguments": {"sql": "SELECT * FROM users"},
                "output": {"rows": [{"id": 1, "email": "test@example.com"}]}
            }

        mock_response = MagicMock()
        mock_response.json.return_value = human_review_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        with pytest.raises(HumanReviewRequiredError):
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=payload_with_output,
                check_stage="post"
            )


# =============================================================================
# CONTROL VIOLATION (DENY) TESTS
# =============================================================================

class TestCheckEvaluationDeny:
    """Tests for check_evaluation raising ControlViolationError."""

    @pytest.mark.asyncio
    async def test_raises_control_violation_error(
        self, mock_client, agent_uuid, tool_call_payload, deny_response
    ):
        """Test that check_evaluation raises ControlViolationError for deny action."""
        mock_response = MagicMock()
        mock_response.json.return_value = deny_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        with pytest.raises(ControlViolationError) as exc_info:
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=tool_call_payload,
                check_stage="pre"
            )

        # Verify exception details
        assert exc_info.value.control_id == 5
        assert exc_info.value.control_name == "sql-injection-control"
        assert "SQL injection detected" in exc_info.value.message
        assert exc_info.value.metadata == {"pattern": "DROP TABLE"}

    @pytest.mark.asyncio
    async def test_deny_no_raise_returns_result(
        self, mock_client, agent_uuid, tool_call_payload, deny_response
    ):
        """Test that raise_on_violation=False returns result for deny."""
        mock_response = MagicMock()
        mock_response.json.return_value = deny_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        result = await check_evaluation(
            client=mock_client,
            agent_uuid=agent_uuid,
            payload=tool_call_payload,
            check_stage="pre",
            raise_on_violation=False
        )

        assert result.is_safe is False
        assert len(result.matches) == 1


# =============================================================================
# SAFE RESPONSE TESTS
# =============================================================================

class TestCheckEvaluationSafe:
    """Tests for check_evaluation with safe responses."""

    @pytest.mark.asyncio
    async def test_safe_response_no_exception(
        self, mock_client, agent_uuid, tool_call_payload, safe_response
    ):
        """Test that safe evaluation returns without raising."""
        mock_response = MagicMock()
        mock_response.json.return_value = safe_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        result = await check_evaluation(
            client=mock_client,
            agent_uuid=agent_uuid,
            payload=tool_call_payload,
            check_stage="pre"
        )

        assert result.is_safe is True
        assert result.human_review_required is False

    @pytest.mark.asyncio
    async def test_warn_action_no_exception(
        self, mock_client, agent_uuid, llm_call_payload, warn_response
    ):
        """Test that warn action doesn't raise exception."""
        mock_response = MagicMock()
        mock_response.json.return_value = warn_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        # Warn should not raise
        result = await check_evaluation(
            client=mock_client,
            agent_uuid=agent_uuid,
            payload=llm_call_payload,
            check_stage="pre"
        )

        assert result.is_safe is False
        assert len(result.matches) == 1


# =============================================================================
# PRECEDENCE TESTS
# =============================================================================

class TestExceptionPrecedence:
    """Tests for exception precedence (human review takes priority)."""

    @pytest.mark.asyncio
    async def test_human_review_takes_precedence_over_deny(
        self, mock_client, agent_uuid, tool_call_payload
    ):
        """Test that human_review_required=True raises HumanReviewRequiredError even with deny matches."""
        # Response with both human_review and deny
        mixed_response = {
            "is_safe": False,
            "confidence": 0.8,
            "human_review_required": True,
            "matches": [
                {
                    "control_id": 1,
                    "control_name": "review-control",
                    "action": "human_review",
                    "result": {
                        "matched": True,
                        "confidence": 0.8,
                        "message": "Review needed"
                    }
                },
                {
                    "control_id": 2,
                    "control_name": "deny-control",
                    "action": "deny",
                    "result": {
                        "matched": True,
                        "confidence": 0.9,
                        "message": "Blocked"
                    }
                }
            ],
            "errors": []
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mixed_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        # Should raise HumanReviewRequiredError, not ControlViolationError
        with pytest.raises(HumanReviewRequiredError) as exc_info:
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=tool_call_payload,
                check_stage="pre"
            )

        assert exc_info.value.control_name == "review-control"


# =============================================================================
# ERROR HANDLING TESTS (FAIL-CLOSED BEHAVIOR)
# =============================================================================

class TestErrorHandling:
    """Tests for fail-closed behavior when evaluation errors occur."""

    @pytest.mark.asyncio
    async def test_errors_raise_runtime_error(
        self, mock_client, agent_uuid, tool_call_payload
    ):
        """Test that evaluation errors raise RuntimeError (fail-closed)."""
        error_response = {
            "is_safe": True,  # Even if safe, errors should raise
            "confidence": 0.0,
            "human_review_required": False,
            "matches": [],
            "errors": [
                {
                    "control_id": 99,
                    "control_name": "regex-control",
                    "action": "deny",
                    "result": {
                        "matched": False,
                        "confidence": 0.0,
                        "message": "Regex pattern compilation failed"
                    }
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.json.return_value = error_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        with pytest.raises(RuntimeError) as exc_info:
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=tool_call_payload,
                check_stage="pre"
            )

        assert "Control evaluation failed on server" in str(exc_info.value)
        assert "regex-control" in str(exc_info.value)
        assert "Regex pattern compilation failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_multiple_errors_all_included(
        self, mock_client, agent_uuid, tool_call_payload
    ):
        """Test that multiple errors are all included in the exception message."""
        error_response = {
            "is_safe": False,
            "confidence": 0.0,
            "human_review_required": False,
            "matches": [],
            "errors": [
                {
                    "control_id": 100,
                    "control_name": "control-1",
                    "action": "deny",
                    "result": {
                        "matched": False,
                        "confidence": 0.0,
                        "message": "Error 1"
                    }
                },
                {
                    "control_id": 101,
                    "control_name": "control-2",
                    "action": "deny",
                    "result": {
                        "matched": False,
                        "confidence": 0.0,
                        "message": "Error 2"
                    }
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.json.return_value = error_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        with pytest.raises(RuntimeError) as exc_info:
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=tool_call_payload,
                check_stage="pre"
            )

        error_message = str(exc_info.value)
        assert "control-1" in error_message
        assert "Error 1" in error_message
        assert "control-2" in error_message
        assert "Error 2" in error_message

    @pytest.mark.asyncio
    async def test_errors_take_precedence_over_all(
        self, mock_client, agent_uuid, tool_call_payload
    ):
        """Test that errors take precedence over human_review and deny."""
        error_response = {
            "is_safe": False,
            "confidence": 0.8,
            "human_review_required": True,  # Even with human review
            "matches": [
                {
                    "control_id": 1,
                    "control_name": "deny-control",
                    "action": "deny",
                    "result": {
                        "matched": True,
                        "confidence": 0.9,
                        "message": "Denied"
                    }
                }
            ],
            "errors": [
                {
                    "control_id": 102,
                    "control_name": "failed-control",
                    "action": "deny",
                    "result": {
                        "matched": False,
                        "confidence": 0.0,
                        "message": "Control failed"
                    }
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.json.return_value = error_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        # Should raise RuntimeError, not HumanReviewRequiredError or ControlViolationError
        with pytest.raises(RuntimeError) as exc_info:
            await check_evaluation(
                client=mock_client,
                agent_uuid=agent_uuid,
                payload=tool_call_payload,
                check_stage="pre"
            )

        assert "Control evaluation failed" in str(exc_info.value)
        assert "failed-control" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_raise_on_violation_still_returns_errors(
        self, mock_client, agent_uuid, tool_call_payload
    ):
        """Test that raise_on_violation=False returns result with errors (doesn't raise)."""
        error_response = {
            "is_safe": False,
            "confidence": 0.0,
            "human_review_required": False,
            "matches": [],
            "errors": [
                {
                    "control_id": 103,
                    "control_name": "failed-control",
                    "action": "deny",
                    "result": {
                        "matched": False,
                        "confidence": 0.0,
                        "message": "Control failed"
                    }
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.json.return_value = error_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        # With raise_on_violation=False, should return result (not raise)
        result = await check_evaluation(
            client=mock_client,
            agent_uuid=agent_uuid,
            payload=tool_call_payload,
            check_stage="pre",
            raise_on_violation=False
        )

        assert len(result.errors) == 1
        assert result.is_safe is False


# =============================================================================
# PAYLOAD TYPE TESTS
# =============================================================================

class TestPayloadTypes:
    """Tests for different payload types (ToolCall vs LlmCall)."""

    @pytest.mark.asyncio
    async def test_tool_call_pre_check(
        self, mock_client, agent_uuid, tool_call_payload, safe_response
    ):
        """Test check_evaluation with ToolCall payload in pre-check."""
        mock_response = MagicMock()
        mock_response.json.return_value = safe_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        result = await check_evaluation(
            client=mock_client,
            agent_uuid=agent_uuid,
            payload=tool_call_payload,
            check_stage="pre"
        )

        assert result.is_safe is True
        # Verify the API was called
        assert mock_client.http_client.post.called

    @pytest.mark.asyncio
    async def test_llm_call_pre_check(
        self, mock_client, agent_uuid, llm_call_payload, safe_response
    ):
        """Test check_evaluation with LlmCall payload in pre-check."""
        mock_response = MagicMock()
        mock_response.json.return_value = safe_response
        mock_response.raise_for_status = MagicMock()
        mock_client.http_client.post.return_value = mock_response

        result = await check_evaluation(
            client=mock_client,
            agent_uuid=agent_uuid,
            payload=llm_call_payload,
            check_stage="pre"
        )

        assert result.is_safe is True
