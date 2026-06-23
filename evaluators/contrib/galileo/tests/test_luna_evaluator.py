"""Tests for the direct Galileo Luna evaluator and client."""

from __future__ import annotations

import asyncio
import json
import os
from base64 import urlsafe_b64decode
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent_control_models import EvaluatorResult
from pydantic import ValidationError

LUNA_ENV = {
    "GALILEO_API_SECRET_KEY": "test-secret",
    "GALILEO_LUNA_INVOKE_URL": "http://luna-invoke:8090",
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

    def test_client_normalizes_luna_invoke_service_root(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        with patch.dict(
            os.environ,
            LUNA_ENV | {"GALILEO_LUNA_INVOKE_URL": "  http://luna-invoke:8090/  "},
            clear=True,
        ):
            client = GalileoLunaClient()

        assert client.luna_invoke_url == "http://luna-invoke:8090/api/v1/scorers/invoke"

    def test_client_uses_full_luna_invoke_url_as_configured(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        with patch.dict(
            os.environ,
            LUNA_ENV
            | {"GALILEO_LUNA_INVOKE_URL": "  http://luna-invoke:8090/luna/scorers/invoke/  "},
            clear=True,
        ):
            client = GalileoLunaClient()

        assert client.luna_invoke_url == "http://luna-invoke:8090/luna/scorers/invoke"

    def test_client_rejects_unreadable_luna_invoke_ca_bundle(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        with patch.dict(
            os.environ,
            LUNA_ENV | {"GALILEO_LUNA_INVOKE_CA_FILE": "/nonexistent/ca.pem"},
            clear=True,
        ):
            with pytest.raises(ValueError, match="Failed to load CA bundle"):
                GalileoLunaClient()

    @pytest.mark.asyncio
    async def test_client_applies_ca_bundle_and_connection_limits(self) -> None:
        import ssl

        from agent_control_evaluator_galileo.luna import GalileoLunaClient
        from agent_control_evaluator_galileo.luna.client import (
            DEFAULT_KEEPALIVE_EXPIRY_SECS,
            DEFAULT_MAX_CONNECTIONS,
            DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
        )

        captured: dict[str, object] = {}
        real_async_client = httpx.AsyncClient

        def recording_client(**kwargs: object) -> httpx.AsyncClient:
            captured.update(kwargs)
            return real_async_client(**kwargs)

        ssl_context = ssl.create_default_context()
        with (
            patch.dict(os.environ, LUNA_ENV, clear=True),
            patch.object(GalileoLunaClient, "_load_ssl_context", return_value=ssl_context),
        ):
            client = GalileoLunaClient(luna_invoke_ca_file="/etc/luna-invoke-ca.pem")

        with patch(
            "agent_control_evaluator_galileo.luna.client.httpx.AsyncClient", recording_client
        ):
            try:
                await client._get_client()
            finally:
                await client.close()

        assert captured["verify"] is client._ssl_context
        limits = captured["limits"]
        assert isinstance(limits, httpx.Limits)
        assert limits.keepalive_expiry == DEFAULT_KEEPALIVE_EXPIRY_SECS
        assert limits.max_connections == DEFAULT_MAX_CONNECTIONS
        assert limits.max_keepalive_connections == DEFAULT_MAX_KEEPALIVE_CONNECTIONS

    @pytest.mark.asyncio
    async def test_client_applies_connection_tuning_env(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        captured: dict[str, object] = {}
        real_async_client = httpx.AsyncClient

        def recording_client(**kwargs: object) -> httpx.AsyncClient:
            captured.update(kwargs)
            return real_async_client(**kwargs)

        with patch.dict(
            os.environ,
            {
                "GALILEO_API_SECRET_KEY": "test-secret",
                "GALILEO_LUNA_INVOKE_URL": "http://luna-invoke:8090",
                "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS": "0.25",
                "GALILEO_LUNA_MAX_CONNECTIONS": "17",
                "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS": "4",
            },
            clear=True,
        ):
            client = GalileoLunaClient()

        with patch(
            "agent_control_evaluator_galileo.luna.client.httpx.AsyncClient", recording_client
        ):
            try:
                await client._get_client()
            finally:
                await client.close()

        assert client.keepalive_expiry_seconds == 0.25
        assert client.max_connections == 17
        assert client.max_keepalive_connections == 4
        limits = captured["limits"]
        assert isinstance(limits, httpx.Limits)
        assert limits.keepalive_expiry == 0.25
        assert limits.max_connections == 17
        assert limits.max_keepalive_connections == 4

    def test_client_ignores_empty_connection_tuning_env(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient
        from agent_control_evaluator_galileo.luna.client import (
            DEFAULT_CLIENT_POOL_SIZE,
            DEFAULT_KEEPALIVE_EXPIRY_SECS,
            DEFAULT_MAX_CONNECTIONS,
            DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
        )

        with patch.dict(
            os.environ,
            {
                "GALILEO_API_SECRET_KEY": "test-secret",
                "GALILEO_LUNA_INVOKE_URL": "http://luna-invoke:8090",
                "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS": "",
                "GALILEO_LUNA_MAX_CONNECTIONS": " ",
                "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS": "",
                "GALILEO_LUNA_CLIENT_POOL_SIZE": " ",
            },
            clear=True,
        ):
            client = GalileoLunaClient()

        assert client.keepalive_expiry_seconds == DEFAULT_KEEPALIVE_EXPIRY_SECS
        assert client.max_connections == DEFAULT_MAX_CONNECTIONS
        assert client.max_keepalive_connections == DEFAULT_MAX_KEEPALIVE_CONNECTIONS
        assert client.client_pool_size == DEFAULT_CLIENT_POOL_SIZE

    @pytest.mark.asyncio
    async def test_client_pool_size_rotates_across_http_clients(self) -> None:
        import agent_control_evaluator_galileo.luna.client as luna_client_module
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        class FakeAsyncClient:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                self.is_closed = False

            async def aclose(self) -> None:
                self.is_closed = True

        created: list[FakeAsyncClient] = []

        def recording_client(**kwargs: object) -> FakeAsyncClient:
            client = FakeAsyncClient(**kwargs)
            created.append(client)
            return client

        with patch.dict(
            os.environ,
            {
                "GALILEO_API_SECRET_KEY": "test-secret",
                "GALILEO_LUNA_INVOKE_URL": "http://luna-invoke:8090",
                "GALILEO_LUNA_CLIENT_POOL_SIZE": "3",
            },
            clear=True,
        ):
            client = GalileoLunaClient()

        with patch.object(luna_client_module.httpx, "AsyncClient", recording_client):
            try:
                selected = [await client._get_client() for _ in range(5)]
            finally:
                await client.close()

        assert client.client_pool_size == 3
        assert len(created) == 3
        assert selected == [created[0], created[1], created[2], created[0], created[1]]
        assert all(created_client.is_closed for created_client in created)

    @pytest.mark.asyncio
    async def test_pooled_client_selection_waits_for_client_lock(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        class FakeAsyncClient:
            is_closed = False

            async def aclose(self) -> None:
                self.is_closed = True

        with patch.dict(
            os.environ,
            {
                "GALILEO_API_SECRET_KEY": "test-secret",
                "GALILEO_LUNA_INVOKE_URL": "http://luna-invoke:8090",
                "GALILEO_LUNA_CLIENT_POOL_SIZE": "2",
            },
            clear=True,
        ):
            client = GalileoLunaClient()

        first_client = FakeAsyncClient()
        second_client = FakeAsyncClient()
        client._clients = [first_client, second_client]  # type: ignore[list-item]

        await client._client_lock.acquire()
        try:
            pending_selection = asyncio.create_task(client._get_client())
            await asyncio.sleep(0)

            assert not pending_selection.done()
        finally:
            client._client_lock.release()

        try:
            assert await pending_selection is first_client
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_close_waits_for_client_lock_before_resetting_state(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        class FakeAsyncClient:
            is_closed = False

            async def aclose(self) -> None:
                self.is_closed = True

        with patch.dict(os.environ, LUNA_ENV, clear=True):
            client = GalileoLunaClient()

        http_client = FakeAsyncClient()
        client._client = http_client  # type: ignore[assignment]
        client._clients = [http_client]  # type: ignore[list-item]

        await client._client_lock.acquire()
        try:
            pending_close = asyncio.create_task(client.close())
            await asyncio.sleep(0)

            assert not pending_close.done()
            assert client._client is http_client
            assert not http_client.is_closed
        finally:
            client._client_lock.release()

        await pending_close

        assert client._client is None
        assert client._clients == []
        assert client._next_client_index == 0
        assert http_client.is_closed

    @pytest.mark.parametrize(
        "env_values, expected",
        [
            ({"GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS": "soon"}, "not a number"),
            ({"GALILEO_LUNA_MAX_CONNECTIONS": "many"}, "not an integer"),
            ({"GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS": "some"}, "not an integer"),
            (
                {"GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS": "-0.1"},
                "greater than or equal to 0",
            ),
            ({"GALILEO_LUNA_MAX_CONNECTIONS": "0"}, "greater than 0"),
            (
                {"GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS": "-1"},
                "greater than or equal to 0",
            ),
            (
                {
                    "GALILEO_LUNA_MAX_CONNECTIONS": "2",
                    "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS": "3",
                },
                "less than or equal",
            ),
            ({"GALILEO_LUNA_CLIENT_POOL_SIZE": "many"}, "not an integer"),
            ({"GALILEO_LUNA_CLIENT_POOL_SIZE": "0"}, "greater than 0"),
        ],
    )
    def test_client_reports_invalid_connection_tuning_env(
        self, env_values: dict[str, str], expected: str
    ) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        env = LUNA_ENV | env_values
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError) as exc_info:
                GalileoLunaClient()

        assert expected in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_client_posts_to_luna_invoke_scorer_invoke(self) -> None:
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

        # Given: a Luna client pointing at luna invoke endpoint
        with patch.dict(os.environ, LUNA_ENV, clear=True):
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

        # Then: posts to luna invoke endpoint /api/v1/scorers/invoke with JWT, no Galileo-API-Key
        assert response.score == 0.82
        assert captured["url"] == "http://luna-invoke:8090/api/v1/scorers/invoke"
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
            return httpx.Response(200, json={"score": 0.5, "status": "success"})

        with patch.dict(os.environ, LUNA_ENV, clear=True):
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

        env = {**LUNA_ENV, "GALILEO_API_KEY": "should-not-be-sent"}
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

        with patch.dict(os.environ, LUNA_ENV, clear=True):
            client = GalileoLunaClient()

        with pytest.raises(ValueError, match="At least one of input or output must be provided"):
            await client.invoke(scorer_id="scorer-123", input=empty_value, output=empty_value)


class TestLunaEvaluator:
    """Tests for direct Luna evaluator behavior."""

    @patch.dict(os.environ, LUNA_ENV)
    def test_evaluator_metadata(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        assert LunaEvaluator.metadata.name == "galileo.luna"
        assert LunaEvaluator.metadata.requires_api_key is True

    @patch.dict(os.environ, {}, clear=True)
    def test_evaluator_init_without_auth_raises(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        with pytest.raises(ValueError, match="GALILEO_API_SECRET_KEY or GALILEO_API_SECRET"):
            LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

    @patch.dict(os.environ, LUNA_ENV, clear=True)
    def test_evaluator_init_accepts_api_secret(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

        assert evaluator.config.scorer_id == "scorer-123"

    @patch.dict(os.environ, LUNA_ENV)
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

    @patch.dict(os.environ, LUNA_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_forwards_configured_scorer_version_id(self) -> None:
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
            scorer_version_id="version-456",
            input="hello",
            output=None,
            config=None,
            timeout=10.0,
        )

    @patch.dict(os.environ, LUNA_ENV)
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

    @patch.dict(os.environ, LUNA_ENV)
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

    @patch.dict(os.environ, LUNA_ENV)
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

    @patch.dict(os.environ, LUNA_ENV)
    @pytest.mark.asyncio
    async def test_evaluator_error_metadata_includes_http_status_context(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        evaluator = LunaEvaluator.from_dict(
            {"scorer_id": "scorer-123", "scorer_label": "toxicity", "threshold": 0.5}
        )
        request = httpx.Request(
            "POST",
            "http://luna-invoke:8090/api/v1/scorers/invoke?token=secret",
        )
        response = httpx.Response(
            503,
            headers={"content-type": "application/json"},
            text='{"detail":"busy"}',
            request=request,
        )

        with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
            mock_invoke.side_effect = httpx.HTTPStatusError(
                "service unavailable",
                request=request,
                response=response,
            )

            result = await evaluator.evaluate("hello")

        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["error_type"] == "HTTPStatusError"
        assert result.metadata["http_status_code"] == 503
        assert result.metadata["http_method"] == "POST"
        assert result.metadata["http_endpoint_path"] == "/api/v1/scorers/invoke"
        assert result.metadata["http_response_content_type"] == "application/json"
        assert result.metadata["http_response_body"] == '{"detail":"busy"}'
        assert result.metadata["http_response_body_truncated"] is False
        assert "token=secret" not in str(result.metadata)
