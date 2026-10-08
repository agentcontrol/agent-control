"""Tests for the direct Galileo LLM-as-judge evaluator and client."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from agent_control_models import Step

LLM_ENV = {
    "GALILEO_API_SECRET_KEY": "test-secret",
    "GALILEO_LUNA_INVOKE_URL": "http://luna-invoke:8090",
    "GALILEO_FEATURE_FLAG_LLM_INVOKE_RUNTIME": "enabled",
}


class TestGalileoLLMClient:
    """Tests for ``GalileoLLMClient`` and ``ScorerInvokeRequest``."""

    def test_execution_context_serializes_missing_optional_claims_as_null(self) -> None:
        from agent_control_evaluator_galileo.llm.client import (
            GalileoExecutionContext,
            ScorerInvokeInputs,
            ScorerInvokeRequest,
        )

        request = ScorerInvokeRequest(
            scorer_id="scorer-123",
            inputs=ScorerInvokeInputs(query="hello"),
            execution_context=GalileoExecutionContext(organization_id="org-1"),
        )

        assert request.to_dict()["execution_context"] == {
            "organization_id": "org-1",
            "user_id": None,
            "project_id": None,
            "run_id": None,
        }


class TestLlmEvaluator:
    """Tests for ``LlmEvaluator`` execution context handling."""

    @patch.dict(os.environ, LLM_ENV)
    @pytest.mark.asyncio
    @pytest.mark.parametrize("target_type", ["log_stream", "agent_stream"])
    async def test_evaluator_consumes_verified_opaque_extensions(self, target_type: str) -> None:
        from agent_control_evaluator_galileo.llm import LlmEvaluator
        from agent_control_evaluator_galileo.llm.client import (
            GalileoExecutionContext,
            GalileoLLMClient,
            ScorerInvokeResponse,
        )

        evaluator = LlmEvaluator.from_dict(
            {"scorer_id": "scorer-123", "threshold": 0.5, "operator": "gte"}
        )
        extensions = {
            "namespace_key": "org-1",
            "caller_id": "verified-user-2",
            "target_type": target_type,
            "target_id": "run-4",
            "metadata": {"project_id": "project-3"},
        }

        with patch.object(GalileoLLMClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(score=0.8, status="success")
            result = await evaluator.evaluate_with_extensions(
                "selected input", Step(type="llm", name="answer", input="prompt"), extensions
            )

        assert result.matched is True
        mock_invoke.assert_awaited_once_with(
            scorer_id="scorer-123",
            step=Step(type="llm", name="answer", input="prompt"),
            selected_data="selected input",
            selected_data_payload_field="input",
            execution_context=GalileoExecutionContext(
                organization_id="org-1",
                user_id="verified-user-2",
                project_id="project-3",
                run_id="run-4",
            ),
            input="selected input",
            output=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, LLM_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_allows_missing_caller_id(self) -> None:
        from agent_control_evaluator_galileo.llm import LlmEvaluator
        from agent_control_evaluator_galileo.llm.client import (
            GalileoExecutionContext,
            GalileoLLMClient,
            ScorerInvokeResponse,
        )

        evaluator = LlmEvaluator.from_dict({"scorer_id": "scorer-123"})
        extensions = {
            "namespace_key": "org-1",
            "target_type": "log_stream",
            "target_id": "run-4",
            "metadata": {},
        }

        with patch.object(GalileoLLMClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(score=0.8, status="success")
            result = await evaluator.evaluate_with_extensions(
                "selected input", Step(type="llm", name="answer", input="prompt"), extensions
            )

        assert result.error is None
        mock_invoke.assert_awaited_once_with(
            scorer_id="scorer-123",
            step=Step(type="llm", name="answer", input="prompt"),
            selected_data="selected input",
            selected_data_payload_field="input",
            execution_context=GalileoExecutionContext(
                organization_id="org-1",
                user_id=None,
                project_id=None,
                run_id="run-4",
            ),
            input="selected input",
            output=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, LLM_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_omits_run_id_for_unsupported_target_type(self) -> None:
        from agent_control_evaluator_galileo.llm import LlmEvaluator
        from agent_control_evaluator_galileo.llm.client import (
            GalileoExecutionContext,
            GalileoLLMClient,
            ScorerInvokeResponse,
        )

        evaluator = LlmEvaluator.from_dict({"scorer_id": "scorer-123"})
        extensions = {
            "namespace_key": "org-1",
            "caller_id": "verified-user-2",
            "target_type": "environment",
            "target_id": "prod",
            "metadata": {"project_id": "project-3"},
        }

        with patch.object(GalileoLLMClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(score=0.8, status="success")
            result = await evaluator.evaluate_with_extensions(
                "selected input", Step(type="llm", name="answer", input="prompt"), extensions
            )

        assert result.error is None
        mock_invoke.assert_awaited_once_with(
            scorer_id="scorer-123",
            step=Step(type="llm", name="answer", input="prompt"),
            selected_data="selected input",
            selected_data_payload_field="input",
            execution_context=GalileoExecutionContext(
                organization_id="org-1",
                user_id="verified-user-2",
                project_id="project-3",
                run_id=None,
            ),
            input="selected input",
            output=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, LLM_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_rejects_missing_organization_id(self) -> None:
        from agent_control_evaluator_galileo.llm import LlmEvaluator
        from agent_control_evaluator_galileo.llm.client import GalileoLLMClient

        evaluator = LlmEvaluator.from_dict({"scorer_id": "scorer-123"})
        extensions = {
            "target_type": "log_stream",
            "target_id": "run-4",
            "metadata": {"project_id": "project-3"},
        }

        with patch.object(GalileoLLMClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            result = await evaluator.evaluate_with_extensions(
                "selected input",
                Step(type="llm", name="answer", input="prompt"),
                extensions,
            )

        assert result.error is not None
        assert "organization_id" in result.error
        mock_invoke.assert_not_called()
