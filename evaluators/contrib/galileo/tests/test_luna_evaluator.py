"""Tests for the direct Galileo Luna evaluator and client."""

from __future__ import annotations

import json
import os
from base64 import urlsafe_b64decode
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent_control_models import EvaluatorResult
from pydantic import ValidationError

RUNNERS_ENV = {
    "GALILEO_API_SECRET_KEY": "test-secret",
    "GALILEO_RUNNERS_API_URL": "http://runners-api:8090",
}


def _decode_jwt_payload(token: str) -> dict[str, object]:
    payload_segment = token.split(".")[1]
    padded = payload_segment + ("=" * (-len(payload_segment) % 4))
    return json.loads(urlsafe_b64decode(padded.encode()).decode())


class TestLunaEvaluatorConfig:
    """Tests for direct Luna evaluator configuration."""

    def test_config_accepts_scorer_id_with_all_optional_fields(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        config = LunaEvaluatorConfig(
            scorer_id="scorer-123",
            scorer_version_id="version-123",
            scorer_label="toxicity",
            threshold=0.7,
            operator="gte",
            config={"temperature": 0},
        )

        assert config.scorer_id == "scorer-123"
        assert config.scorer_version_id == "version-123"
        assert config.scorer_label == "toxicity"
        assert config.threshold == 0.7
        assert config.operator == "gte"
        assert config.scorer_config == {"temperature": 0}
        assert config.payload_field == "input"

    def test_config_accepts_scorer_id_without_label(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        config = LunaEvaluatorConfig(scorer_id="scorer-123")

        assert config.scorer_id == "scorer-123"
        assert config.scorer_label is None

    def test_config_requires_scorer_id(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        with pytest.raises(ValidationError, match="scorer_id"):
            LunaEvaluatorConfig(threshold=0.5)

    def test_config_rejects_label_only(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        with pytest.raises(ValidationError, match="scorer_id"):
            LunaEvaluatorConfig(scorer_label="toxicity", threshold=0.5)

    def test_config_rejects_version_only(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        with pytest.raises(ValidationError, match="scorer_id"):
            LunaEvaluatorConfig(scorer_version_id="version-123", threshold=0.5)

    def test_numeric_operator_requires_numeric_threshold(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        with pytest.raises(ValidationError, match="numeric threshold"):
            LunaEvaluatorConfig(scorer_id="scorer-123", threshold="high", operator="gte")


class TestGalileoLunaClient:
    """Tests for the GalileoLunaClient HTTP contract."""

    def test_scorer_invoke_request_requires_scorer_id(self) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeInputs, ScorerInvokeRequest

        with pytest.raises(ValidationError, match="scorer_id"):
            ScorerInvokeRequest(
                scorer_label="toxicity",
                inputs=ScorerInvokeInputs(query="hello"),
            )

    def test_scorer_invoke_request_shape_with_all_fields(self) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeInputs, ScorerInvokeRequest

        request = ScorerInvokeRequest(
            scorer_id="scorer-123",
            scorer_version_id="version-123",
            scorer_label="toxicity",
            inputs=ScorerInvokeInputs(query={"messages": [{"role": "user", "content": "hello"}]}),
            config={"top_k": 1},
        )

        assert request.to_dict() == {
            "scorer_id": "scorer-123",
            "scorer_version_id": "version-123",
            "scorer_label": "toxicity",
            "inputs": {
                "query": {"messages": [{"role": "user", "content": "hello"}]},
                "response": "",
            },
            "config": {"top_k": 1},
        }

    def test_scorer_invoke_request_omits_optional_fields_when_absent(self) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeInputs, ScorerInvokeRequest

        request = ScorerInvokeRequest(
            scorer_id="scorer-123",
            inputs=ScorerInvokeInputs(query="hello"),
        )

        body = request.to_dict()
        assert body["scorer_id"] == "scorer-123"
        assert "scorer_version_id" not in body
        assert "scorer_label" not in body
        assert body["config"] == {}

    @pytest.mark.parametrize("empty_value", ["", " ", {}, []])
    def test_scorer_invoke_request_requires_input_or_output(self, empty_value: object) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeRequest

        with pytest.raises(
            ValidationError, match="Either inputs.query or inputs.response must be set"
        ):
            ScorerInvokeRequest(
                scorer_id="scorer-123",
                inputs={"query": empty_value, "response": empty_value},
            )

    def test_scorer_invoke_response_shape(self) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeResponse

        response = ScorerInvokeResponse.from_dict(
            {
                "scorer_label": "toxicity",
                "score": 0.82,
                "status": "success",
                "execution_time": 0.12,
                "error_message": None,
            }
        )

        assert response.model_dump() == {
            "scorer_label": "toxicity",
            "score": 0.82,
            "status": "success",
            "execution_time": 0.12,
            "error_message": None,
        }
        assert response.raw_response["scorer_label"] == "toxicity"

    @pytest.mark.asyncio
    async def test_client_posts_to_runners_api_scorer_invoke(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "scorer_label": "toxicity",
                    "score": 0.82,
                    "status": "success",
                    "execution_time": 0.12,
                },
            )

        # Given: a Luna client pointing at runners-api
        with patch.dict(os.environ, RUNNERS_ENV, clear=True):
            client = GalileoLunaClient()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        try:
            response = await client.invoke(
                scorer_id="scorer-123",
                input="user prompt",
                output="model answer",
                config={"top_k": 1},
            )
        finally:
            await client.close()

        # Then: posts to runners-api /api/v1/scorers/invoke with JWT, no Galileo-API-Key
        assert response.score == 0.82
        assert captured["url"] == "http://runners-api:8090/api/v1/scorers/invoke"
        assert captured["body"] == {
            "scorer_id": "scorer-123",
            "inputs": {"query": "user prompt", "response": "model answer"},
            "config": {"top_k": 1},
        }
        headers = captured["headers"]
        assert isinstance(headers, dict)
        assert "galileo-api-key" not in headers
        auth_header = headers["authorization"]
        assert isinstance(auth_header, str)
        assert auth_header.startswith("Bearer ")
        payload = _decode_jwt_payload(auth_header.removeprefix("Bearer "))
        assert payload["internal"] is True
        assert payload["scope"] == "scorers.invoke"

    @pytest.mark.asyncio
    async def test_client_forwards_scorer_version_id_when_configured(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(
                200, json={"score": 0.5, "status": "success"}
            )

        with patch.dict(os.environ, RUNNERS_ENV, clear=True):
            client = GalileoLunaClient()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        try:
            await client.invoke(
                scorer_id="scorer-123",
                scorer_version_id="version-456",
                input="hello",
            )
        finally:
            await client.close()

        assert captured["body"]["scorer_version_id"] == "version-456"

    @pytest.mark.asyncio
    async def test_client_omits_galileo_api_key_even_when_env_is_set(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"score": 0.5, "status": "success"})

        env = {**RUNNERS_ENV, "GALILEO_API_KEY": "should-not-be-sent"}
        with patch.dict(os.environ, env, clear=True):
            client = GalileoLunaClient()
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        try:
            await client.invoke(scorer_id="scorer-123", input="hello")
        finally:
            await client.close()

        headers = captured["headers"]
        assert isinstance(headers, dict)
        assert "galileo-api-key" not in headers

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_value", ["", " ", {}, []])
    async def test_client_rejects_missing_input_and_output_values(
        self, empty_value: object
    ) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        with patch.dict(os.environ, RUNNERS_ENV, clear=True):
            client = GalileoLunaClient()

        with pytest.raises(ValueError, match="At least one of input or output must be provided"):
            await client.invoke(scorer_id="scorer-123", input=empty_value, output=empty_value)


class TestLunaEvaluator:
    """Tests for direct Luna evaluator behavior."""

    @patch.dict(os.environ, RUNNERS_ENV)
    def test_evaluator_metadata(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        assert LunaEvaluator.metadata.name == "galileo.luna"
        assert LunaEvaluator.metadata.requires_api_key is True

    @patch.dict(os.environ, {}, clear=True)
    def test_evaluator_init_without_auth_raises(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        with pytest.raises(ValueError, match="GALILEO_API_SECRET_KEY or GALILEO_API_SECRET"):
            LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

    @patch.dict(os.environ, RUNNERS_ENV, clear=True)
    def test_evaluator_init_accepts_api_secret(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

        assert evaluator.config.scorer_id == "scorer-123"

    @patch.dict(os.environ, RUNNERS_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_applies_threshold_locally_to_raw_score(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        evaluator = LunaEvaluator.from_dict(
            {
                "scorer_id": "scorer-123",
                "scorer_label": "toxicity",
                "threshold": 0.7,
                "operator": "gte",
                "timeout_ms": 5000,
            }
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(
                scorer_label="toxicity",
                score=0.82,
                status="success",
                execution_time=0.1,
            )

            result = await evaluator.evaluate(
                {
                    "input": "user prompt",
                    "output": "model answer",
                }
            )

        assert isinstance(result, EvaluatorResult)
        assert result.matched is True
        assert result.confidence == 0.82
        assert result.metadata == {
            "scorer_id": "scorer-123",
            "scorer_label": "toxicity",
            "score": 0.82,
            "threshold": 0.7,
            "operator": "gte",
            "status": "success",
            "execution_time_seconds": 0.1,
            "error_message": None,
        }
        mock_invoke.assert_awaited_once_with(
            scorer_id="scorer-123",
            scorer_label="toxicity",
            input="user prompt",
            output="model answer",
            config=None,
            timeout=5.0,
        )

    @patch.dict(os.environ, RUNNERS_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_does_not_forward_configured_scorer_version_id(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        evaluator = LunaEvaluator.from_dict(
            {
                "scorer_id": "scorer-123",
                "scorer_version_id": "version-456",
                "threshold": 0.5,
                "operator": "gte",
            }
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(
                score=0.82,
                status="success",
            )

            result = await evaluator.evaluate("hello")

        assert result.matched is True
        assert result.metadata["scorer_version_id"] == "version-456"
        mock_invoke.assert_awaited_once_with(
            scorer_id="scorer-123",
            input="hello",
            output=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, RUNNERS_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_returns_non_match_below_threshold(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        evaluator = LunaEvaluator.from_dict(
            {"scorer_id": "scorer-123", "threshold": 0.7, "operator": "gte"}
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(
                scorer_label="toxicity",
                score=0.2,
                status="success",
            )

            result = await evaluator.evaluate("hello")

        assert result.matched is False
        assert result.confidence == 0.2
        mock_invoke.assert_awaited_once_with(
            scorer_id="scorer-123",
            input="hello",
            output=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, RUNNERS_ENV)
    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["", "   "])
    async def test_evaluator_does_not_call_api_for_empty_data(self, data: str) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        evaluator = LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            result = await evaluator.evaluate(data)

        assert result.matched is False
        assert result.confidence == 1.0
        assert result.message == "No data to score with Luna"
        mock_invoke.assert_not_called()

    @patch.dict(os.environ, RUNNERS_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_fail_open_sets_error(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        evaluator = LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = RuntimeError("service unavailable")

            result = await evaluator.evaluate("hello")

        assert result.matched is False
        assert result.error == "service unavailable"
        assert result.metadata is not None
        assert "error" not in result.metadata
        assert result.metadata["error_type"] == "RuntimeError"
        assert "fallback_action" not in result.metadata
