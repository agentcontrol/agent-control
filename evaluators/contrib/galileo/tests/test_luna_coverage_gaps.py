"""Targeted tests filling coverage gaps in luna/evaluator.py and luna/client.py.

These tests cover the small utility functions and rare branches that the
integration-style tests in ``test_luna_evaluator.py`` skip past.
"""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

LUNA_ENV = {
    "GALILEO_API_SECRET_KEY": "test-secret",
    "GALILEO_LUNA_INVOKE_URL": "http://luna-invoke:8090",
}


def _decode_jwt_payload(token: str) -> dict[str, object]:
    payload_segment = token.split(".")[1]
    padded = payload_segment + ("=" * (-len(payload_segment) % 4))
    return json.loads(urlsafe_b64decode(padded.encode()).decode())


# =============================================================================
# luna/evaluator.py: utility helpers
# =============================================================================


class TestCoercePayloadText:
    """``_coerce_payload_text`` normalises arbitrary values to strings."""

    def test_none_returns_none(self):
        from agent_control_evaluator_galileo.luna.evaluator import _coerce_payload_text

        assert _coerce_payload_text(None) is None

    def test_string_passed_through(self):
        from agent_control_evaluator_galileo.luna.evaluator import _coerce_payload_text

        assert _coerce_payload_text("hello") == "hello"

    @pytest.mark.parametrize("value", [42, 3.14, True])
    def test_scalars_stringified(self, value):
        from agent_control_evaluator_galileo.luna.evaluator import _coerce_payload_text

        assert _coerce_payload_text(value) == str(value)

    def test_dict_is_json_serialized(self):
        from agent_control_evaluator_galileo.luna.evaluator import _coerce_payload_text

        result = _coerce_payload_text({"a": 1, "b": 2})

        assert json.loads(result) == {"a": 1, "b": 2}

    def test_unserialisable_falls_back_to_str(self):
        from agent_control_evaluator_galileo.luna.evaluator import _coerce_payload_text

        class CannotJson:
            def __repr__(self):
                return "<CannotJson>"

        cannot = CannotJson()
        result = _coerce_payload_text({"obj": cannot})

        # default=str converts the inner object, so we still get a JSON string.
        assert isinstance(result, str)


class TestExtractDictText:
    """``_extract_dict_text`` returns ``None`` for missing keys."""

    def test_missing_key_returns_none(self):
        from agent_control_evaluator_galileo.luna.evaluator import _extract_dict_text

        assert _extract_dict_text({}, "absent") is None

    def test_present_key_coerced(self):
        from agent_control_evaluator_galileo.luna.evaluator import _extract_dict_text

        assert _extract_dict_text({"x": 7}, "x") == "7"


class TestContains:
    """``_contains`` supports str/list and dict values against a threshold."""

    def test_none_threshold_is_no_match(self):
        from agent_control_evaluator_galileo.luna.evaluator import _contains

        assert _contains("anything", None) is False

    def test_string_contains_substring(self):
        from agent_control_evaluator_galileo.luna.evaluator import _contains

        assert _contains("hello world", "world") is True
        assert _contains("hello world", "absent") is False

    def test_list_contains_value(self):
        from agent_control_evaluator_galileo.luna.evaluator import _contains

        assert _contains(["a", "b", "c"], "b") is True
        assert _contains(["a", "b", "c"], "z") is False

    def test_dict_threshold_does_not_match_key(self):
        from agent_control_evaluator_galileo.luna.evaluator import _contains

        assert _contains({"toxicity": 0.9}, "toxicity") is False

    def test_dict_threshold_matches_value(self):
        from agent_control_evaluator_galileo.luna.evaluator import _contains

        assert _contains({"label": "flagged"}, "flagged") is True

    def test_other_types_return_false(self):
        from agent_control_evaluator_galileo.luna.evaluator import _contains

        assert _contains(42, 42) is False


class TestConfidenceFromScore:
    """``_confidence_from_score`` maps a raw score to [0, 1]."""

    def test_true_bool_maps_to_one(self):
        from agent_control_evaluator_galileo.luna.evaluator import _confidence_from_score

        assert _confidence_from_score(True) == 1.0

    def test_false_bool_maps_to_zero(self):
        from agent_control_evaluator_galileo.luna.evaluator import _confidence_from_score

        assert _confidence_from_score(False) == 0.0

    def test_in_range_number_returned_as_is(self):
        from agent_control_evaluator_galileo.luna.evaluator import _confidence_from_score

        assert _confidence_from_score(0.42) == 0.42

    def test_out_of_range_falls_back_to_one(self):
        from agent_control_evaluator_galileo.luna.evaluator import _confidence_from_score

        assert _confidence_from_score(7.2) == 1.0

    def test_non_numeric_falls_back_to_one(self):
        from agent_control_evaluator_galileo.luna.evaluator import _confidence_from_score

        assert _confidence_from_score("not-a-number") == 1.0


# =============================================================================
# luna/evaluator.py: _score_matches operator branches
# =============================================================================


@pytest.fixture
def luna_evaluator(monkeypatch):
    """A ready-to-use LunaEvaluator instance with auth env wired up."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna import LunaEvaluator

    return LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5, "operator": "gte"})


class TestScoreMatchesOperators:
    """Every operator branch in ``_score_matches`` should evaluate."""

    def _make(self, operator, threshold, monkeypatch):
        for key, value in LUNA_ENV.items():
            monkeypatch.setenv(key, value)
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        return LunaEvaluator.from_dict(
            {"scorer_id": "scorer-123", "threshold": threshold, "operator": operator}
        )

    def test_any_truthy_score_matches(self, monkeypatch):
        evaluator = self._make("any", 0.5, monkeypatch)
        assert evaluator._score_matches(1) is True
        assert evaluator._score_matches(0) is False

    def test_eq_matches_threshold(self, monkeypatch):
        evaluator = self._make("eq", "flagged", monkeypatch)
        assert evaluator._score_matches("flagged") is True
        assert evaluator._score_matches("safe") is False

    def test_ne_matches_when_different(self, monkeypatch):
        evaluator = self._make("ne", "flagged", monkeypatch)
        assert evaluator._score_matches("safe") is True
        assert evaluator._score_matches("flagged") is False

    def test_contains_matches_substring(self, monkeypatch):
        evaluator = self._make("contains", "flag", monkeypatch)
        assert evaluator._score_matches("flagged") is True
        assert evaluator._score_matches("clean") is False

    def test_numeric_operators_all_branches(self, monkeypatch):
        for op, expectations in [
            ("gt", [(0.9, True), (0.5, False)]),
            ("gte", [(0.5, True), (0.4, False)]),
            ("lt", [(0.4, True), (0.5, False)]),
            ("lte", [(0.5, True), (0.6, False)]),
        ]:
            evaluator = self._make(op, 0.5, monkeypatch)
            for score, expected in expectations:
                assert evaluator._score_matches(score) is expected, (op, score)

    def test_numeric_operator_rejects_non_numeric_score(self, monkeypatch):
        evaluator = self._make("gte", 0.5, monkeypatch)
        with pytest.raises(ValueError, match="not numeric"):
            evaluator._score_matches("not-a-number")


# =============================================================================
# luna/evaluator.py: payload preparation + aclose
# =============================================================================


class TestPreparePayload:
    """``_prepare_payload`` routes scalar data using explicit config."""

    def test_scalar_routed_to_input_by_default(self, monkeypatch):
        for key, value in LUNA_ENV.items():
            monkeypatch.setenv(key, value)
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

        input_text, output_text = evaluator._prepare_payload("hello")

        assert input_text == "hello"
        assert output_text is None

    def test_scalar_routed_to_output_when_payload_field_is_output(self, monkeypatch):
        for key, value in LUNA_ENV.items():
            monkeypatch.setenv(key, value)
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict(
            {"scorer_id": "scorer-123", "threshold": 0.5, "payload_field": "output"}
        )

        input_text, output_text = evaluator._prepare_payload("hello")

        assert input_text is None
        assert output_text == "hello"

    def test_structured_payload_uses_input_output_keys_over_payload_field(self, monkeypatch):
        for key, value in LUNA_ENV.items():
            monkeypatch.setenv(key, value)
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict(
            {"scorer_id": "scorer-123", "threshold": 0.5, "payload_field": "output"}
        )

        input_text, output_text = evaluator._prepare_payload(
            {"input": "prompt", "output": "answer"}
        )

        assert input_text == "prompt"
        assert output_text == "answer"


@pytest.mark.asyncio
async def test_evaluator_aclose_closes_underlying_client(monkeypatch):
    """``aclose`` must release the eagerly-created client without clearing it."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna import LunaEvaluator

    evaluator = LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})

    fake = MagicMock()
    fake.close = AsyncMock()
    evaluator._client = fake

    await evaluator.aclose()

    fake.close.assert_awaited_once()
    assert evaluator._client is fake


@pytest.mark.asyncio
async def test_evaluator_handles_non_success_status(monkeypatch):
    """A non-success status from the scorer must surface as an error result."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    evaluator = LunaEvaluator.from_dict(
        {"scorer_id": "scorer-123", "threshold": 0.5, "operator": "gte"}
    )

    with patch.object(GalileoLunaClient, "invoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = ScorerInvokeResponse(
            scorer_label="toxicity",
            score=None,
            status="failed",
            error_message="upstream timeout",
        )

        result = await evaluator.evaluate("hello")

    assert result.matched is False
    assert result.error is not None
    assert "upstream timeout" in result.error


# =============================================================================
# luna/evaluator.py: package version fallback
# =============================================================================


def test_resolve_package_version_falls_back_when_metadata_missing():
    """The dev fallback must trigger when the package isn't installed by metadata."""
    from importlib.metadata import PackageNotFoundError

    from agent_control_evaluator_galileo.luna import evaluator as evaluator_module

    with patch.object(evaluator_module, "version", side_effect=PackageNotFoundError):
        result = evaluator_module._resolve_package_version()

    assert result == "0.0.0.dev"


# =============================================================================
# luna/client.py: small helpers + branches
# =============================================================================


class TestAsFloatOrNone:
    """``_as_float_or_none`` parses scalar values; strings may fail."""

    def test_returns_none_for_bool(self):
        from agent_control_evaluator_galileo.luna.client import _as_float_or_none

        assert _as_float_or_none(True) is None

    def test_returns_none_for_none(self):
        from agent_control_evaluator_galileo.luna.client import _as_float_or_none

        assert _as_float_or_none(None) is None

    def test_returns_float_for_int(self):
        from agent_control_evaluator_galileo.luna.client import _as_float_or_none

        assert _as_float_or_none(7) == 7.0

    def test_returns_float_for_string_number(self):
        from agent_control_evaluator_galileo.luna.client import _as_float_or_none

        assert _as_float_or_none("0.42") == 0.42

    def test_returns_none_for_unparseable_string(self):
        from agent_control_evaluator_galileo.luna.client import _as_float_or_none

        assert _as_float_or_none("not-a-number") is None

    def test_returns_none_for_other_types(self):
        from agent_control_evaluator_galileo.luna.client import _as_float_or_none

        assert _as_float_or_none([1, 2]) is None


class TestHasValue:
    """``_has_value`` is the "is this scorable" predicate."""

    def test_none_is_empty(self):
        from agent_control_evaluator_galileo.luna.client import _has_value

        assert _has_value(None) is False

    def test_empty_string_is_empty(self):
        from agent_control_evaluator_galileo.luna.client import _has_value

        assert _has_value("") is False
        assert _has_value("   ") is False

    def test_non_empty_string_has_value(self):
        from agent_control_evaluator_galileo.luna.client import _has_value

        assert _has_value("hi") is True

    def test_empty_list_or_dict_is_empty(self):
        from agent_control_evaluator_galileo.luna.client import _has_value

        assert _has_value([]) is False
        assert _has_value({}) is False

    def test_non_empty_list_or_dict_has_value(self):
        from agent_control_evaluator_galileo.luna.client import _has_value

        assert _has_value([1]) is True
        assert _has_value({"k": "v"}) is True

    def test_scalar_other_types_have_value(self):
        from agent_control_evaluator_galileo.luna.client import _has_value

        assert _has_value(42) is True
        assert _has_value(0) is True
        assert _has_value(True) is True


class TestScorerInvokeRequestValidation:
    """``ScorerInvokeRequest`` rejects malformed input combos."""

    def test_missing_scorer_id_raises(self):
        from agent_control_evaluator_galileo.luna.client import (
            ScorerInvokeInputs,
            ScorerInvokeRequest,
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="scorer_id"):
            ScorerInvokeRequest(inputs=ScorerInvokeInputs(query="hello"))


def test_client_raises_when_no_api_secret(monkeypatch):
    """The client requires GALILEO_API_SECRET_KEY or GALILEO_API_SECRET."""
    for name in ("GALILEO_API_SECRET_KEY", "GALILEO_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://luna-invoke:8090")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    with pytest.raises(ValueError, match="GALILEO_API_SECRET_KEY or GALILEO_API_SECRET"):
        GalileoLunaClient()


def test_client_raises_when_no_luna_invoke_url(monkeypatch):
    """The client requires GALILEO_LUNA_INVOKE_URL."""
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.delenv("GALILEO_LUNA_INVOKE_URL", raising=False)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    with pytest.raises(ValueError, match="GALILEO_LUNA_INVOKE_URL"):
        GalileoLunaClient()


def test_client_jwt_has_internal_scope(monkeypatch):
    """JWT produced by the client must carry internal=True and scope=scorers.invoke."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()
    _, auth_header = client._endpoint_and_auth_header()

    assert auth_header.startswith("Bearer ")
    payload = _decode_jwt_payload(auth_header.removeprefix("Bearer "))
    assert payload["internal"] is True
    assert payload["scope"] == "scorers.invoke"


def test_client_posts_to_correct_luna_invoke_endpoint(monkeypatch):
    """_endpoint_and_auth_header must return the Luna invoke endpoint path."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()
    endpoint, _ = client._endpoint_and_auth_header()

    assert endpoint == "http://luna-invoke:8090/api/v1/scorers/invoke"


def test_client_does_not_use_old_api_paths(monkeypatch):
    """The client must not reference /scorers/invoke or /internal/scorers/invoke."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()
    endpoint, _ = client._endpoint_and_auth_header()

    assert "/scorers/invoke" in endpoint
    assert endpoint.startswith("http://luna-invoke:8090/api/v1/")
    assert "/internal/scorers/invoke" not in endpoint


@pytest.mark.asyncio
async def test_get_client_does_not_set_galileo_api_key_header(monkeypatch):
    """The HTTP client must never include a Galileo-API-Key header."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()
    http_client = await client._get_client()
    try:
        assert "Galileo-API-Key" not in http_client.headers
        assert "galileo-api-key" not in http_client.headers
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_client_uses_configured_luna_invoke_ca_file(monkeypatch):
    """The HTTP client should verify internal luna invoke endpoint TLS with the configured CA."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_CA_FILE", "/etc/galileo/luna-invoke-ca.crt")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    ssl_context = object()
    with (
        patch.object(GalileoLunaClient, "_load_ssl_context", return_value=ssl_context),
        patch("httpx.AsyncClient") as async_client,
    ):
        client = GalileoLunaClient()
        await client._get_client()

    assert client.luna_invoke_ca_file == "/etc/galileo/luna-invoke-ca.crt"
    assert async_client.call_args.kwargs["verify"] is ssl_context


@pytest.mark.asyncio
async def test_get_client_falls_back_to_agent_control_auth_upstream_ca_file(monkeypatch):
    """Galileo in-cluster Agent Control pods already mount the internal CA for auth upstream."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GALILEO_LUNA_INVOKE_CA_FILE", raising=False)
    monkeypatch.setenv(
        "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE", "/etc/agent-control/auth-upstream-ca/ca.crt"
    )
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    ssl_context = object()
    with (
        patch.object(GalileoLunaClient, "_load_ssl_context", return_value=ssl_context),
        patch("httpx.AsyncClient") as async_client,
    ):
        client = GalileoLunaClient()
        await client._get_client()

    assert client.luna_invoke_ca_file == "/etc/agent-control/auth-upstream-ca/ca.crt"
    assert async_client.call_args.kwargs["verify"] is ssl_context


@pytest.mark.asyncio
async def test_invoke_raises_when_response_is_not_a_json_object(monkeypatch):
    """A non-object JSON body must surface as a clear RuntimeError."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()

    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()
    fake_response.json = MagicMock(return_value=["not", "an", "object"])

    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=fake_response)
    fake_http.is_closed = False
    client._client = fake_http

    try:
        with pytest.raises(RuntimeError, match="not a JSON object"):
            await client.invoke(scorer_id="scorer-123", input="hello")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invoke_propagates_http_status_error(monkeypatch):
    """The client logs and re-raises HTTP status errors."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()

    fake_response = MagicMock(spec=httpx.Response)
    fake_response.status_code = 500
    fake_response.text = "internal error"
    fake_response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "boom", request=MagicMock(spec=httpx.Request), response=fake_response
        )
    )

    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=fake_response)
    fake_http.is_closed = False
    client._client = fake_http

    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.invoke(scorer_id="scorer-123", input="hello")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invoke_propagates_request_error(monkeypatch):
    """RequestError is logged and re-raised so callers can decide policy."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()

    fake_http = AsyncMock()
    fake_http.post = AsyncMock(side_effect=httpx.RequestError("network down"))
    fake_http.is_closed = False
    client._client = fake_http

    try:
        with pytest.raises(httpx.RequestError):
            await client.invoke(scorer_id="scorer-123", input="hello")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_async_context_manager_closes_on_exit(monkeypatch):
    """Entering/exiting the async context manager must close the client."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    async with GalileoLunaClient() as client:
        await client._get_client()
        assert client._client is not None

    assert client._client is None


@pytest.mark.asyncio
async def test_invoke_strips_caller_supplied_galileo_api_key_header(monkeypatch):
    """Regression: a Galileo-API-Key passed via the headers kwarg must be stripped."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"score": 0.9, "status": "success"})

    client = GalileoLunaClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        await client.invoke(
            scorer_id="scorer-123",
            input="hello",
            headers={"Galileo-API-Key": "should-be-stripped", "X-Custom": "keep-me"},
        )
    finally:
        await client.close()

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert "galileo-api-key" not in headers
    assert headers.get("x-custom") == "keep-me"


@pytest.mark.asyncio
async def test_invoke_always_emits_config_field(monkeypatch):
    """Regression: config must always be present in the request body, defaulting to {}."""
    for key, value in LUNA_ENV.items():
        monkeypatch.setenv(key, value)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"score": 0.5, "status": "success"})

    client = GalileoLunaClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    try:
        await client.invoke(scorer_id="scorer-123", input="hello")
    finally:
        await client.close()

    assert "config" in captured["body"]
    assert captured["body"]["config"] == {}
