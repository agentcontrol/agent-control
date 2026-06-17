"""Tests for the direct Galileo Luna evaluator and client."""

from __future__ import annotations

import asyncio
import json
import logging
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
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}, clear=True):
            client = GalileoLunaClient(console_url="https://console.demo-v2.galileocloud.io")

        # Then: the API URL is derived the same way
        assert client.api_base == "https://api.demo-v2.galileocloud.io"

    def test_client_uses_galileo_api_url_when_set(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: an explicit custom-environment API URL
        with patch.dict(
            os.environ,
            {
                "GALILEO_API_KEY": "test-key",
                "GALILEO_API_URL": "https://api-test-luna.example.com/",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console-test-luna.example.com")

        # Then: the explicit API URL wins over console URL derivation
        assert client.api_base == "https://api-test-luna.example.com"

    def test_client_uses_luna_api_url_when_set(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: a Luna-specific API URL and a general API URL are both configured
        with patch.dict(
            os.environ,
            {
                "GALILEO_API_KEY": "test-key",
                "GALILEO_LUNA_API_URL": "https://luna-api.example.com/",
                "GALILEO_API_URL": "https://api.example.com",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console.example.com")

        # Then: the Luna-specific URL wins without changing the general API URL contract
        assert client.api_base == "https://luna-api.example.com"

    def test_client_uses_luna_api_url_for_internal_auth(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: internal auth and both Luna-specific and general API URLs are configured
        with patch.dict(
            os.environ,
            {
                "GALILEO_API_SECRET_KEY": "test-secret",
                "GALILEO_LUNA_API_URL": "https://internal-api.example.com",
                "GALILEO_API_URL": "https://api-public.example.com",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console.example.com")

        # Then: internal scorer invocation uses the Luna-specific API base
        assert client.api_base == "https://internal-api.example.com"

    def test_client_derives_api_url_from_console_dash_hostname(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: a console-<environment> hostname
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}, clear=True):
            client = GalileoLunaClient(console_url="https://console-test-luna.example.com")

        # Then: the matching api-<environment> hostname is used
        assert client.api_base == "https://api-test-luna.example.com"

    def test_client_strips_whitespace_from_env_url(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: a URL override padded with whitespace and a trailing slash
        with patch.dict(
            os.environ,
            {
                "GALILEO_API_KEY": "test-key",
                "GALILEO_LUNA_API_URL": "  https://luna-api.example.com/  ",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console.example.com")

        # Then: the resolved base URL is trimmed and slash-free
        assert client.api_base == "https://luna-api.example.com"

    def test_client_warns_when_deprecated_auth_mode_env_is_set(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: the deprecated auth-mode environment variable
        caplog.set_level(logging.WARNING)
        with patch.dict(
            os.environ,
            {"GALILEO_API_KEY": "test-key", "GALILEO_LUNA_AUTH_MODE": "public"},
            clear=True,
        ):
            # When/Then: construction still works but emits a deprecation warning
            with pytest.warns(DeprecationWarning, match="GALILEO_LUNA_AUTH_MODE is deprecated"):
                client = GalileoLunaClient(console_url="https://console.example.com")

        assert client.auth_mode == "public"
        assert "GALILEO_LUNA_AUTH_MODE is deprecated" in caplog.text

    def test_client_rejects_unreadable_ca_bundle(self) -> None:
        from agent_control_evaluator_galileo.luna import GalileoLunaClient

        # Given: a CA bundle path that does not exist
        with patch.dict(
            os.environ,
            {
                "GALILEO_API_SECRET_KEY": "test-secret",
                "GALILEO_LUNA_CA_FILE": "/nonexistent/ca.pem",
            },
            clear=True,
        ):
            # When/Then: client construction fails fast instead of at first request
            with pytest.raises(ValueError, match="Failed to load CA bundle"):
                GalileoLunaClient(console_url="https://console.example.com")

    @pytest.mark.asyncio
    async def test_client_applies_ca_bundle_and_connection_limits(self) -> None:
        import certifi
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

        # Given: internal auth with a CA bundle configured
        with patch.dict(os.environ, {"GALILEO_API_SECRET_KEY": "test-secret"}, clear=True):
            client = GalileoLunaClient(
                console_url="https://console.example.com", ca_file=certifi.where()
            )

        with patch(
            "agent_control_evaluator_galileo.luna.client.httpx.AsyncClient", recording_client
        ):
            try:
                await client._get_client()
            finally:
                await client.close()

        # Then: TLS verification uses the configured CA bundle and pooled
        # connections expire quickly so closed server sockets are not reused
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
                "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS": "0.25",
                "GALILEO_LUNA_MAX_CONNECTIONS": "17",
                "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS": "4",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console.example.com")

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
                "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS": "",
                "GALILEO_LUNA_MAX_CONNECTIONS": " ",
                "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS": "",
                "GALILEO_LUNA_CLIENT_POOL_SIZE": " ",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console.example.com")

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
                "GALILEO_LUNA_CLIENT_POOL_SIZE": "3",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console.example.com")

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
                "GALILEO_LUNA_CLIENT_POOL_SIZE": "2",
            },
            clear=True,
        ):
            client = GalileoLunaClient(console_url="https://console.example.com")

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

        with patch.dict(os.environ, {"GALILEO_API_SECRET_KEY": "test-secret"}, clear=True):
            client = GalileoLunaClient(console_url="https://console.example.com")

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

        env = {"GALILEO_API_SECRET_KEY": "test-secret"} | env_values
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError) as exc_info:
                GalileoLunaClient(console_url="https://console.example.com")

        assert expected in str(exc_info.value)

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
        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}, clear=True):
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

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @pytest.mark.asyncio
    async def test_evaluator_error_metadata_includes_http_status_context(self) -> None:
        from agent_control_evaluator_galileo.luna import LunaEvaluator
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        evaluator = LunaEvaluator.from_dict({"scorer_label": "toxicity", "threshold": 0.5})
        request = httpx.Request(
            "POST",
            "https://api.example.test/internal/scorers/invoke?token=secret",
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
        assert result.metadata["http_endpoint_path"] == "/internal/scorers/invoke"
        assert result.metadata["http_response_content_type"] == "application/json"
        assert result.metadata["http_response_body"] == '{"detail":"busy"}'
        assert result.metadata["http_response_body_truncated"] is False
        assert "token=secret" not in str(result.metadata)
