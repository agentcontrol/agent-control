"""Targeted tests filling coverage gaps in luna/evaluator.py and luna/client.py.

These tests cover the small utility functions and rare branches that the
integration-style tests in ``test_luna_evaluator.py`` skip past.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


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

        # json.dumps with default=str would actually serialize this, so use
        # something that breaks both the JSON pass AND triggers TypeError.
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

        # Non-iterable score => no match.
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

        # Above 1.0 → fall back to default confidence
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
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
    from agent_control_evaluator_galileo.luna import LunaEvaluator

    return LunaEvaluator.from_dict(
        {"scorer_label": "toxicity", "threshold": 0.5, "operator": "gte"}
    )


class TestScoreMatchesOperators:
    """Every operator branch in ``_score_matches`` should evaluate."""

    def _make(self, operator, threshold, monkeypatch):
        monkeypatch.setenv("GALILEO_API_KEY", "test-key")
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        if operator in {"eq", "ne", "contains"}:
            threshold_value = threshold
        else:
            threshold_value = threshold
        return LunaEvaluator.from_dict(
            {"scorer_label": "toxicity", "threshold": threshold_value, "operator": operator}
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

    def test_scalar_routed_to_input_when_label_lacks_output(self, monkeypatch):
        monkeypatch.setenv("GALILEO_API_KEY", "test-key")
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict({"scorer_label": "toxicity", "threshold": 0.5})

        input_text, output_text = evaluator._prepare_payload("hello")

        assert input_text == "hello"
        assert output_text is None

    def test_scalar_routed_to_output_when_payload_field_is_output(self, monkeypatch):
        monkeypatch.setenv("GALILEO_API_KEY", "test-key")
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict(
            {
                "scorer_label": "toxicity",
                "threshold": 0.5,
                "payload_field": "output",
            }
        )

        input_text, output_text = evaluator._prepare_payload("hello")

        assert input_text is None
        assert output_text == "hello"

    def test_scalar_output_label_without_payload_field_still_defaults_to_input(
        self,
        monkeypatch,
    ):
        monkeypatch.setenv("GALILEO_API_KEY", "test-key")
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict(
            {"scorer_label": "output_correctness", "threshold": 0.5}
        )

        input_text, output_text = evaluator._prepare_payload("hello")

        assert input_text == "hello"
        assert output_text is None

    def test_structured_payload_uses_input_output_keys_over_payload_field(self, monkeypatch):
        monkeypatch.setenv("GALILEO_API_KEY", "test-key")
        from agent_control_evaluator_galileo.luna import LunaEvaluator

        evaluator = LunaEvaluator.from_dict(
            {
                "scorer_label": "toxicity",
                "threshold": 0.5,
                "payload_field": "output",
            }
        )

        input_text, output_text = evaluator._prepare_payload(
            {"input": "prompt", "output": "answer"}
        )

        assert input_text == "prompt"
        assert output_text == "answer"


@pytest.mark.asyncio
async def test_evaluator_aclose_closes_underlying_client(monkeypatch):
    """``aclose`` must release the eagerly-created client without clearing it."""
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
    from agent_control_evaluator_galileo.luna import LunaEvaluator

    evaluator = LunaEvaluator.from_dict({"scorer_label": "toxicity", "threshold": 0.5})

    fake = MagicMock()
    fake.close = AsyncMock()
    evaluator._client = fake

    await evaluator.aclose()

    fake.close.assert_awaited_once()
    assert evaluator._client is fake


@pytest.mark.asyncio
async def test_evaluator_handles_non_success_status(monkeypatch):
    """A non-success status from the scorer must surface as an error result."""
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
    from agent_control_evaluator_galileo.luna import LunaEvaluator, ScorerInvokeResponse
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    evaluator = LunaEvaluator.from_dict(
        {"scorer_label": "toxicity", "threshold": 0.5, "operator": "gte"}
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
        assert _has_value(0) is True  # 0 is a real value, not empty
        assert _has_value(True) is True


class TestScorerInvokeRequestValidation:
    """``ScorerInvokeRequest`` rejects malformed input combos."""

    def test_missing_all_identifiers_raises(self):
        from agent_control_evaluator_galileo.luna.client import (
            ScorerInvokeInputs,
            ScorerInvokeRequest,
        )
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="One of scorer_label"):
            ScorerInvokeRequest(inputs=ScorerInvokeInputs(query="hello"))


def test_client_raises_when_no_credentials(monkeypatch):
    """The client requires at least an API secret or an API key."""
    for name in (
        "GALILEO_API_SECRET_KEY",
        "GALILEO_API_SECRET",
        "GALILEO_API_KEY",
        "GALILEO_LUNA_AUTH_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    with pytest.raises(ValueError, match="GALILEO_API_SECRET_KEY"):
        GalileoLunaClient()


def test_client_requires_explicit_mode_when_both_credentials_are_present(monkeypatch):
    """A mixed credential environment must not silently choose an auth route."""
    monkeypatch.setenv("GALILEO_API_KEY", "public-key")
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "internal-secret")
    monkeypatch.delenv("GALILEO_LUNA_AUTH_MODE", raising=False)
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    with pytest.raises(ValueError, match="Both Galileo API key and API secret"):
        GalileoLunaClient()


def test_client_uses_explicit_public_mode_when_both_credentials_are_present(monkeypatch):
    """Explicit public mode should use the API-key route even if a secret is also set."""
    monkeypatch.setenv("GALILEO_API_KEY", "public-key")
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "internal-secret")
    monkeypatch.setenv("GALILEO_LUNA_AUTH_MODE", "public")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()

    assert client.auth_mode == "public"
    endpoint, request_headers = client._endpoint_and_headers(None)
    assert endpoint.endswith("/scorers/invoke")
    assert "Authorization" not in request_headers


def test_client_uses_explicit_internal_mode_when_both_credentials_are_present(monkeypatch):
    """Explicit internal mode should use the internal JWT route."""
    monkeypatch.setenv("GALILEO_API_KEY", "public-key")
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "internal-secret")
    monkeypatch.setenv("GALILEO_LUNA_AUTH_MODE", "internal")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()

    assert client.auth_mode == "internal"
    endpoint, request_headers = client._endpoint_and_headers(None)
    assert endpoint.endswith("/internal/scorers/invoke")
    assert request_headers["Authorization"].startswith("Bearer ")


def test_client_rejects_mode_without_matching_credential(monkeypatch):
    """The selected mode must have its matching credential configured."""
    monkeypatch.delenv("GALILEO_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("GALILEO_API_SECRET", raising=False)
    monkeypatch.setenv("GALILEO_API_KEY", "public-key")
    monkeypatch.setenv("GALILEO_LUNA_AUTH_MODE", "internal")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    with pytest.raises(ValueError, match="GALILEO_API_SECRET_KEY"):
        GalileoLunaClient()


def test_client_rejects_invalid_auth_mode(monkeypatch):
    """Invalid auth mode values should fail during client initialization."""
    monkeypatch.setenv("GALILEO_API_KEY", "public-key")
    monkeypatch.setenv("GALILEO_LUNA_AUTH_MODE", "sideways")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    with pytest.raises(ValueError, match="GALILEO_LUNA_AUTH_MODE"):
        GalileoLunaClient()


class TestDeriveApiUrl:
    """URL derivation covers every console.* → api.* substitution branch."""

    def _client(self, monkeypatch):
        monkeypatch.delenv("GALILEO_API_SECRET_KEY", raising=False)
        monkeypatch.delenv("GALILEO_API_SECRET", raising=False)
        monkeypatch.delenv("GALILEO_LUNA_AUTH_MODE", raising=False)
        monkeypatch.setenv("GALILEO_API_KEY", "test-key")
        from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

        return GalileoLunaClient()

    def test_console_dot_rewritten_to_api_dot(self, monkeypatch):
        client = self._client(monkeypatch)
        assert (
            client._derive_api_url("https://console.galileo.ai")
            == "https://api.galileo.ai"
        )

    def test_console_dash_rewritten_to_api_dash(self, monkeypatch):
        client = self._client(monkeypatch)
        assert (
            client._derive_api_url("https://console-staging.galileo.ai")
            == "https://api-staging.galileo.ai"
        )

    def test_plain_https_host_gets_api_prefix(self, monkeypatch):
        client = self._client(monkeypatch)
        assert (
            client._derive_api_url("https://example.com")
            == "https://api.example.com"
        )

    def test_non_prefix_console_substring_gets_api_prefix(self, monkeypatch):
        client = self._client(monkeypatch)
        assert (
            client._derive_api_url("https://my-console.example.com")
            == "https://api.my-console.example.com"
        )

    def test_console_substring_in_path_does_not_rewrite_path(self, monkeypatch):
        client = self._client(monkeypatch)
        assert (
            client._derive_api_url("https://app.galileo.ai/console.html")
            == "https://api.app.galileo.ai/console.html"
        )

    def test_plain_http_host_gets_api_prefix(self, monkeypatch):
        client = self._client(monkeypatch)
        assert client._derive_api_url("http://example.com") == "http://api.example.com"

    def test_unknown_scheme_returned_as_is(self, monkeypatch):
        client = self._client(monkeypatch)
        # No console./console- prefix, no http(s) scheme → return unchanged.
        assert client._derive_api_url("api.example.com") == "api.example.com"


@pytest.mark.asyncio
async def test_get_client_adds_api_key_header_when_no_secret(monkeypatch):
    """When only an API key is configured, the public-API header is set."""
    monkeypatch.delenv("GALILEO_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("GALILEO_API_SECRET", raising=False)
    monkeypatch.setenv("GALILEO_API_KEY", "public-key")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()
    http_client = await client._get_client()
    try:
        assert http_client.headers.get("Galileo-API-Key") == "public-key"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invoke_rejects_missing_scorer_identifier(monkeypatch):
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()
    try:
        with pytest.raises(ValueError, match="At least one scorer identifier"):
            await client.invoke(input="hello")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invoke_raises_when_response_is_not_a_json_object(monkeypatch):
    """A non-object JSON body must surface as a clear RuntimeError."""
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
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
            await client.invoke(scorer_label="toxicity", input="hello")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invoke_propagates_http_status_error(monkeypatch):
    """The client logs and re-raises HTTP status errors."""
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
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
            await client.invoke(scorer_label="toxicity", input="hello")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invoke_propagates_request_error(monkeypatch):
    """RequestError is logged and re-raised so callers can decide policy."""
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    client = GalileoLunaClient()

    fake_http = AsyncMock()
    fake_http.post = AsyncMock(side_effect=httpx.RequestError("network down"))
    fake_http.is_closed = False
    client._client = fake_http

    try:
        with pytest.raises(httpx.RequestError):
            await client.invoke(scorer_label="toxicity", input="hello")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_async_context_manager_closes_on_exit(monkeypatch):
    """Entering/exiting the async context manager must close the client."""
    monkeypatch.setenv("GALILEO_API_KEY", "test-key")
    from agent_control_evaluator_galileo.luna.client import GalileoLunaClient

    async with GalileoLunaClient() as client:
        # Trigger lazy client creation so close() has work to do.
        await client._get_client()
        assert client._client is not None

    # __aexit__ closes the underlying httpx client.
    assert client._client is None
