"""Tests for the direct Galileo Luna evaluator and client."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent_control_models import EvaluatorResult
from pydantic import ValidationError


class TestLunaEvaluatorConfig:
    """Tests for direct Luna evaluator configuration."""

    def test_config_accepts_direct_scorer_fields(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        # Given: a direct scorer config with local thresholding
        config = LunaEvaluatorConfig(
            metric="toxicity",
            project_id="12345678-1234-5678-1234-567812345678",
            threshold=0.7,
            operator="gte",
            luna_model="luna-2",
            config={"temperature": 0},
        )

        # Then: config is retained without Protect concepts
        assert config.metric == "toxicity"
        assert str(config.project_id) == "12345678-1234-5678-1234-567812345678"
        assert config.threshold == 0.7
        assert config.operator == "gte"
        assert config.luna_model == "luna-2"
        assert config.scorer_config == {"temperature": 0}

    def test_numeric_operator_requires_numeric_threshold(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        # Given/When/Then: numeric local comparison rejects non-numeric thresholds
        with pytest.raises(ValidationError, match="numeric threshold"):
            LunaEvaluatorConfig(metric="toxicity", threshold="high", operator="gte")


class TestGalileoLunaClient:
    """Tests for the GalileoLunaClient HTTP contract."""

    def test_client_uses_protect_api_url_derivation(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: the same console URL shape used by Protect
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}):
            client = GalileoLunaClient(console_url="https://console.demo-v2.galileocloud.io")

        # Then: the API URL is derived the same way
        assert client.api_base == "https://api.demo-v2.galileocloud.io"

    @pytest.mark.asyncio
    async def test_client_posts_to_scorers_invoke_without_protect_fields(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "metric": "toxicity",
                    "score": 0.82,
                    "status": "success",
                    "execution_time": 0.12,
                },
            )

        # Given: a Luna client with a mock HTTP transport
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}):
            client = GalileoLunaClient(console_url="https://console.demo-v2.galileocloud.io")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={
                "Galileo-API-Key": client.api_key,
                "Content-Type": "application/json",
            },
        )

        try:
            # When: invoking a scorer
            response = await client.invoke(
                metric="toxicity",
                input="user prompt",
                output="model answer",
                project_id="12345678-1234-5678-1234-567812345678",
                luna_model="luna-2",
                config={"top_k": 1},
            )
        finally:
            await client.close()

        # Then: the direct scorer endpoint and body are used
        assert response.score == 0.82
        assert captured["url"] == "https://api.demo-v2.galileocloud.io/scorers/invoke"
        assert captured["body"] == {
            "input": "user prompt",
            "output": "model answer",
            "metric": "toxicity",
            "project_id": "12345678-1234-5678-1234-567812345678",
            "luna_model": "luna-2",
            "config": {"top_k": 1},
        }
        assert "stage_name" not in captured["body"]
        assert "prioritized_rulesets" not in captured["body"]
        headers = captured["headers"]
        assert isinstance(headers, dict)
        assert headers["galileo-api-key"] == "test-key"


class TestLunaEvaluator:
    """Tests for direct Luna evaluator behavior."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    def test_evaluator_metadata(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        assert LunaEvaluator.metadata.name == "galileo.luna"
        assert LunaEvaluator.metadata.requires_api_key is True

    @patch.dict(os.environ, {}, clear=True)
    def test_evaluator_init_without_api_key_raises(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        with pytest.raises(ValueError, match="GALILEO_API_KEY"):
            LunaEvaluator.from_dict({"metric": "toxicity", "threshold": 0.5})

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    async def test_evaluator_applies_threshold_locally_to_raw_score(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        # Given: a direct Luna evaluator and a raw successful scorer response
        evaluator = LunaEvaluator.from_dict(
            {
                "metric": "toxicity",
                "project_id": "12345678-1234-5678-1234-567812345678",
                "threshold": 0.7,
                "operator": "gte",
                "timeout_ms": 5000,
            }
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(
                metric="toxicity",
                score=0.82,
                status="success",
                execution_time=0.1,
            )

            # When: evaluating a full step payload
            result = await evaluator.evaluate(
                {
                    "input": "user prompt",
                    "output": "model answer",
                }
            )

        # Then: the raw score is thresholded locally and no Protect fields are sent
        assert isinstance(result, EvaluatorResult)
        assert result.matched is True
        assert result.confidence == 0.82
        assert result.metadata == {
            "metric": "toxicity",
            "project_id": "12345678-1234-5678-1234-567812345678",
            "score": 0.82,
            "threshold": 0.7,
            "operator": "gte",
            "status": "success",
            "execution_time_seconds": 0.1,
            "error_message": None,
        }
        mock_invoke.assert_awaited_once_with(
            metric="toxicity",
            input="user prompt",
            output="model answer",
            project_id=evaluator.config.project_id,
            luna_model=None,
            config=None,
            timeout=5.0,
        )

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    async def test_evaluator_returns_non_match_below_threshold(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        # Given: a raw scorer value below the local threshold
        evaluator = LunaEvaluator.from_dict(
            {"metric": "toxicity", "threshold": 0.7, "operator": "gte"}
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(
                metric="toxicity",
                score=0.2,
                status="success",
            )

            # When: evaluating selected scalar data
            result = await evaluator.evaluate("hello")

        # Then: the control does not match
        assert result.matched is False
        assert result.confidence == 0.2
        mock_invoke.assert_awaited_once_with(
            metric="toxicity",
            input="hello",
            output=None,
            project_id=None,
            luna_model=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    async def test_evaluator_does_not_call_api_for_empty_data(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        # Given: an evaluator and empty selected data
        evaluator = LunaEvaluator.from_dict({"metric": "toxicity", "threshold": 0.5})

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            # When: evaluating empty data
            result = await evaluator.evaluate("")

        # Then: no remote scorer call is made
        assert result.matched is False
        assert result.confidence == 1.0
        assert result.message == "No data to score with Luna"
        mock_invoke.assert_not_called()

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    async def test_evaluator_fail_open_sets_error(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        # Given: default fail-open behavior
        evaluator = LunaEvaluator.from_dict({"metric": "toxicity", "threshold": 0.5})

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = RuntimeError("service unavailable")

            # When: the scorer call fails
            result = await evaluator.evaluate("hello")

        # Then: the evaluator reports an infrastructure error without matching
        assert result.matched is False
        assert result.error == "service unavailable"
        assert result.metadata is not None
        assert result.metadata["fallback_action"] == "allow"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    async def test_evaluator_fail_closed_matches_without_error_field(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        # Given: fail-closed behavior for scorer errors
        evaluator = LunaEvaluator.from_dict(
            {"metric": "toxicity", "threshold": 0.5, "on_error": "deny"}
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = RuntimeError("service unavailable")

            # When: the scorer call fails
            result = await evaluator.evaluate("hello")

        # Then: the control matches so deny/steer actions can be applied by the engine
        assert result.matched is True
        assert result.error is None
        assert result.metadata is not None
        assert result.metadata["fallback_action"] == "deny"
