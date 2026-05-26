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


def _decode_jwt_payload(token: str) -> dict[str, object]:
    payload_segment = token.split(".")[1]
    padded = payload_segment + ("=" * (-len(payload_segment) % 4))
    return json.loads(urlsafe_b64decode(padded.encode()).decode())


class TestLunaEvaluatorConfig:
    """Tests for direct Luna evaluator configuration."""

    def test_config_accepts_direct_scorer_fields(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        # Given: a direct scorer config with local thresholding
        config = LunaEvaluatorConfig(
            scorer_label="toxicity",
            scorer_id="scorer-123",
            scorer_version_id="version-123",
            threshold=0.7,
            operator="gte",
            config={"temperature": 0},
        )

        # Then: config is retained without Protect concepts
        assert config.scorer_label == "toxicity"
        assert config.scorer_id == "scorer-123"
        assert config.scorer_version_id == "version-123"
        assert config.threshold == 0.7
        assert config.operator == "gte"
        assert config.scorer_config == {"temperature": 0}
        assert config.payload_field == "input"

    def test_config_accepts_scorer_id_without_label(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        config = LunaEvaluatorConfig(scorer_id="scorer-123")

        assert config.scorer_id == "scorer-123"
        assert config.scorer_label is None

    def test_config_requires_a_scorer_identifier(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        with pytest.raises(ValidationError, match="one of scorer_label"):
            LunaEvaluatorConfig(threshold=0.5)

    def test_numeric_operator_requires_numeric_threshold(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluatorConfig

        # Given/When/Then: numeric local comparison rejects non-numeric thresholds
        with pytest.raises(ValidationError, match="numeric threshold"):
            LunaEvaluatorConfig(scorer_label="toxicity", threshold="high", operator="gte")


class TestGalileoLunaClient:
    """Tests for the GalileoLunaClient HTTP contract."""

    def test_scorer_invoke_request_matches_api_schema_shape(self) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeInputs, ScorerInvokeRequest

        # Given: a scorer request with scorer config
        request = ScorerInvokeRequest(
            scorer_label="toxicity",
            scorer_id="scorer-123",
            scorer_version_id="version-123",
            inputs=ScorerInvokeInputs(query={"messages": [{"role": "user", "content": "hello"}]}),
            config={"top_k": 1},
        )

        # Then: the serialized payload uses the API-owned scorer invoke fields
        assert request.to_dict() == {
            "scorer_label": "toxicity",
            "scorer_id": "scorer-123",
            "scorer_version_id": "version-123",
            "inputs": {
                "query": {"messages": [{"role": "user", "content": "hello"}]},
                "response": "",
            },
            "config": {"top_k": 1},
        }

    @pytest.mark.parametrize("empty_value", ["", " ", {}, []])
    def test_scorer_invoke_request_requires_input_or_output(self, empty_value: object) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeRequest

        # Given/When/Then: the request mirrors API validation
        with pytest.raises(
            ValidationError, match="Either inputs.query or inputs.response must be set"
        ):
            ScorerInvokeRequest(
                scorer_label="toxicity",
                inputs={"query": empty_value, "response": empty_value},
            )

    def test_scorer_invoke_response_matches_api_schema_shape(self) -> None:
        from agent_control_evaluator_galileo.luna import ScorerInvokeResponse

        # Given: an API scorer invoke response
        response = ScorerInvokeResponse.from_dict(
            {
                "scorer_label": "toxicity",
                "score": 0.82,
                "status": "success",
                "execution_time": 0.12,
                "error_message": None,
            }
        )

        # Then: the model exposes the API response fields
        assert response.model_dump() == {
            "scorer_label": "toxicity",
            "score": 0.82,
            "status": "success",
            "execution_time": 0.12,
            "error_message": None,
        }
        assert response.scorer_label == "toxicity"
        assert response.raw_response["scorer_label"] == "toxicity"

    def test_client_uses_protect_api_url_derivation(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: the same console URL shape used by Protect
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}):
            client = GalileoLunaClient(console_url="https://console.demo-v2.galileocloud.io")

        # Then: the API URL is derived the same way
        assert client.api_base == "https://api.demo-v2.galileocloud.io"

    def test_client_uses_galileo_api_url_when_set(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: an explicit devstack API URL
        with patch.dict(
            os.environ,
            {
                "GALILEO_API_KEY": "test-key",
                "GALILEO_API_URL": "https://api-test-luna.gcp-dev.galileo.ai/",
            },
        ):
            client = GalileoLunaClient(console_url="https://console-test-luna.gcp-dev.galileo.ai")

        # Then: the explicit API URL wins over console URL derivation
        assert client.api_base == "https://api-test-luna.gcp-dev.galileo.ai"

    def test_client_derives_api_url_from_console_dash_hostname(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: a console-<stack> devstack hostname
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}, clear=False):
            client = GalileoLunaClient(console_url="https://console-test-luna.gcp-dev.galileo.ai")

        # Then: the matching api-<stack> hostname is used
        assert client.api_base == "https://api-test-luna.gcp-dev.galileo.ai"

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
                    "scorer_label": "toxicity",
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
                scorer_label="toxicity",
                input="user prompt",
                output="model answer",
                config={"top_k": 1},
            )
        finally:
            await client.close()

        # Then: the direct scorer endpoint and body are used
        assert response.score == 0.82
        assert captured["url"] == "https://api.demo-v2.galileocloud.io/scorers/invoke"
        assert captured["body"] == {
            "scorer_label": "toxicity",
            "inputs": {"query": "user prompt", "response": "model answer"},
            "config": {"top_k": 1},
        }
        assert "stage_name" not in captured["body"]
        assert "prioritized_rulesets" not in captured["body"]
        headers = captured["headers"]
        assert isinstance(headers, dict)
        assert headers["galileo-api-key"] == "test-key"

    @pytest.mark.asyncio
    async def test_client_uses_internal_jwt_when_api_secret_is_set(self) -> None:
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

        # Given: a Luna client configured with the Galileo API internal secret
        with patch.dict(os.environ, {"GALILEO_API_SECRET_KEY": "test-secret"}, clear=True):
            client = GalileoLunaClient(api_url="https://api.default.svc.cluster.local:8088")
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        try:
            # When: invoking a scorer with internal JWT auth
            response = await client.invoke(scorer_label="toxicity", output="model answer")
        finally:
            await client.close()

        # Then: the internal scorer endpoint is called with an internal JWT
        assert response.score == 0.82
        assert (
            captured["url"] == "https://api.default.svc.cluster.local:8088/internal/scorers/invoke"
        )
        assert captured["body"] == {
            "scorer_label": "toxicity",
            "inputs": {"query": "", "response": "model answer"},
        }
        headers = captured["headers"]
        assert isinstance(headers, dict)
        assert "galileo-api-key" not in headers
        auth_header = headers["authorization"]
        assert isinstance(auth_header, str)
        assert auth_header.startswith("Bearer ")
        token_payload = _decode_jwt_payload(auth_header.removeprefix("Bearer "))
        assert token_payload["internal"] is True
        assert token_payload["scope"] == "scorers.invoke"

    @pytest.mark.asyncio
    async def test_client_uses_internal_jwt_without_api_key(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: a Luna client configured with internal JWT auth
        with patch.dict(os.environ, {"GALILEO_API_SECRET_KEY": "test-secret"}, clear=True):
            client = GalileoLunaClient(api_url="https://api.default.svc.cluster.local:8088")

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json={"scorer_label": "toxicity", "score": 0.82, "status": "success"},
            )

        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            # When: invoking without project context
            response = await client.invoke(scorer_label="toxicity", output="model answer")
        finally:
            await client.close()

        # Then: internal JWT auth still works
        assert response.score == 0.82
        headers = captured["headers"]
        assert isinstance(headers, dict)
        auth_header = headers["authorization"]
        assert isinstance(auth_header, str)
        token_payload = _decode_jwt_payload(auth_header.removeprefix("Bearer "))
        assert token_payload["internal"] is True
        assert token_payload["scope"] == "scorers.invoke"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("empty_value", ["", " ", {}, []])
    async def test_client_rejects_missing_input_and_output_values(
        self, empty_value: object
    ) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: a Luna client and scorer input values that API treats as missing
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}, clear=True):
            client = GalileoLunaClient(api_url="https://api.default.svc.cluster.local:8088")

        # When/Then: the client rejects the request before calling API
        with pytest.raises(ValueError, match="At least one of input or output must be provided"):
            await client.invoke(scorer_label="toxicity", input=empty_value, output=empty_value)


class TestLunaEvaluator:
    """Tests for direct Luna evaluator behavior."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    def test_evaluator_metadata(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        assert LunaEvaluator.metadata.name == "galileo.luna"
        assert LunaEvaluator.metadata.requires_api_key is True

    @patch.dict(os.environ, {}, clear=True)
    def test_evaluator_init_without_auth_raises(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        with pytest.raises(ValueError, match="GALILEO_API_SECRET_KEY or GALILEO_API_KEY"):
            LunaEvaluator.from_dict({"scorer_label": "toxicity", "threshold": 0.5})

    @patch.dict(os.environ, {"GALILEO_API_SECRET_KEY": "test-secret"}, clear=True)
    def test_evaluator_init_accepts_api_secret(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict(
            {
                "scorer_label": "toxicity",
                "threshold": 0.5,
            }
        )

        assert evaluator.config.scorer_label == "toxicity"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    async def test_evaluator_applies_threshold_locally_to_raw_score(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        # Given: a direct Luna evaluator and a raw successful scorer response
        evaluator = LunaEvaluator.from_dict(
            {
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
            "scorer_label": "toxicity",
            "score": 0.82,
            "threshold": 0.7,
            "operator": "gte",
            "status": "success",
            "execution_time_seconds": 0.1,
            "error_message": None,
        }
        mock_invoke.assert_awaited_once_with(
            scorer_label="toxicity",
            input="user prompt",
            output="model answer",
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
            {"scorer_label": "toxicity", "threshold": 0.7, "operator": "gte"}
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = ScorerInvokeResponse(
                scorer_label="toxicity",
                score=0.2,
                status="success",
            )

            # When: evaluating selected scalar data
            result = await evaluator.evaluate("hello")

        # Then: the control does not match
        assert result.matched is False
        assert result.confidence == 0.2
        mock_invoke.assert_awaited_once_with(
            scorer_label="toxicity",
            input="hello",
            output=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", ["", "   "])
    async def test_evaluator_does_not_call_api_for_empty_data(self, data: str) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        # Given: an evaluator and empty selected data
        evaluator = LunaEvaluator.from_dict({"scorer_label": "toxicity", "threshold": 0.5})

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            # When: evaluating empty data
            result = await evaluator.evaluate(data)

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

        # Given: fixed fail-open behavior for scorer errors
        evaluator = LunaEvaluator.from_dict({"scorer_label": "toxicity", "threshold": 0.5})

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = RuntimeError("service unavailable")

            # When: the scorer call fails
            result = await evaluator.evaluate("hello")

        # Then: the evaluator reports an infrastructure error without matching
        assert result.matched is False
        assert result.error == "service unavailable"
        assert result.metadata is not None
        assert "error" not in result.metadata
        assert result.metadata["error_type"] == "RuntimeError"
        assert "fallback_action" not in result.metadata
