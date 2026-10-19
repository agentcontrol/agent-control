"""Tests for the Galileo Jev evaluator and Runners client."""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest
from hmac import new as hmac_new
from importlib import reload
from importlib.metadata import PackageNotFoundError
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from agent_control_evaluator_galileo.jev import (
    GalileoJevClient,
    JevEvaluator,
    JevEvaluatorConfig,
    JevInvokeInputs,
    JevInvokeRequest,
    JevInvokeResponse,
)
from agent_control_evaluator_galileo.jev import evaluator as jev_evaluator_module
from agent_control_evaluator_galileo.jev.client import _normalize_invoke_url
from agent_control_evaluator_galileo.jev.evaluator import _contains
from agent_control_evaluator_galileo.luna.client import (
    GalileoExecutionContext,
    ScorerInvokeInputs,
    ScorerInvokeRequest,
)
from agent_control_models import Step
from pydantic import ValidationError

EXTENSIONS = {
    "namespace_key": "org-1",
    "caller_id": "user-7",
    "target_type": "log_stream",
    "target_id": "run-9",
    "metadata": {"project_id": "project-3"},
}


def _decode_jwt_segment(segment: str) -> dict[str, Any]:
    padded = segment + ("=" * (-len(segment) % 4))
    return json.loads(urlsafe_b64decode(padded.encode()).decode())


def _evaluator(monkeypatch: pytest.MonkeyPatch, **config: Any) -> JevEvaluator:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://runners:8090")
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME", "enabled")
    evaluator = JevEvaluator(
        JevEvaluatorConfig(scorer_id="scorer-a", scorer_version_id="version-a", **config)
    )
    return evaluator


def test_jev_registration_and_required_configuration() -> None:
    # Given: the separate Jev entry point and required pinned scorer config
    # Then: Jev is registered independently and both scorer identifiers are required
    from agent_control_evaluators import get_evaluator

    assert get_evaluator("galileo.jev") is JevEvaluator
    with pytest.raises(ValidationError, match="scorer_id"):
        JevEvaluatorConfig(scorer_version_id="version-a")  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="scorer_version_id"):
        JevEvaluatorConfig(scorer_id="scorer-a")  # type: ignore[call-arg]


def test_missing_distribution_metadata_uses_development_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_distribution(_: str) -> str:
        raise PackageNotFoundError

    from agent_control_evaluators import clear_evaluators, get_all_evaluators, register_evaluator

    registered_evaluators = get_all_evaluators()
    monkeypatch.setattr(jev_evaluator_module, "version", missing_distribution)
    try:
        clear_evaluators()
        reloaded_module = reload(jev_evaluator_module)
        assert reloaded_module.JevEvaluator.metadata.version == "0.0.0.dev"
    finally:
        clear_evaluators()
        for evaluator_class in registered_evaluators.values():
            register_evaluator(evaluator_class)


@pytest.mark.parametrize(
    ("value", "threshold", "expected"),
    [
        ("unsafe answer", "unsafe", True),
        ({"label": "unsafe"}, "unsafe", True),
        ({"label": "safe"}, "unsafe", False),
        (42, "unsafe", False),
    ],
)
def test_contains_comparison_handles_supported_and_unsupported_values(
    value: Any, threshold: Any, expected: bool
) -> None:
    assert _contains(value, threshold) is expected


def test_config_rejects_non_numeric_or_missing_thresholds() -> None:
    with pytest.raises(ValidationError, match="requires a numeric threshold"):
        JevEvaluatorConfig(
            scorer_id="scorer-a",
            scorer_version_id="version-a",
            operator="gt",
            threshold=True,
        )
    with pytest.raises(ValidationError, match="threshold is required"):
        JevEvaluatorConfig(
            scorer_id="scorer-a",
            scorer_version_id="version-a",
            operator="eq",
            threshold=None,
        )


def test_config_allows_missing_threshold_for_any_operator() -> None:
    config = JevEvaluatorConfig(
        scorer_id="scorer-a",
        scorer_version_id="version-a",
        operator="any",
        threshold=None,
    )

    assert config.threshold is None


@pytest.mark.asyncio
async def test_client_url_resolution_prefers_explicit_url_then_luna_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://luna:8090")

    explicit_client = GalileoJevClient(invoke_url="http://explicit:8090")
    environment_client = GalileoJevClient()

    expected_path = "/api/v1/scorers/invoke"
    assert explicit_client.invoke_url == f"http://explicit:8090{expected_path}"
    assert environment_client.invoke_url == f"http://luna:8090{expected_path}"
    await explicit_client.close()
    await environment_client.close()


def test_client_requires_luna_invoke_url_when_no_explicit_url_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.delenv("GALILEO_LUNA_INVOKE_URL", raising=False)

    with pytest.raises(ValueError, match="GALILEO_LUNA_INVOKE_URL"):
        GalileoJevClient()


def test_invoke_request_requires_execution_context_and_serializes_nested_record() -> None:
    context = GalileoExecutionContext(
        organization_id="org-1", user_id="user-7", project_id="project-3", run_id="run-9"
    )
    record = {
        "type": "trace",
        "input": "",
        "output": "",
        "spans": [{"type": "llm", "input": [{"role": "user", "content": "q"}]}],
    }
    request = JevInvokeRequest(
        scorer_id="scorer-a",
        scorer_version_id="version-a",
        execution_context=context,
        record=record,
        inputs=JevInvokeInputs(),
        config={"request_timeout_seconds": 8.0},
    )

    payload = request.to_dict()
    assert payload["execution_context"] == {
        "organization_id": "org-1",
        "user_id": "user-7",
        "project_id": "project-3",
        "run_id": "run-9",
    }
    assert payload["record"] == record
    assert payload["scorer_version_id"] == "version-a"
    assert payload["inputs"] == {"query": "", "response": ""}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "threshold", "operator", "expected"),
    [
        (0.82, 0.5, "gte", True),
        ("unsafe", "unsafe", "eq", True),
        (3, 2, "gte", True),
        ("safe", "safe", "ne", False),
        (["unsafe"], "unsafe", "contains", True),
    ],
)
async def test_jev_applies_local_comparison(
    monkeypatch: pytest.MonkeyPatch,
    score: Any,
    threshold: Any,
    operator: str,
    expected: bool,
) -> None:
    evaluator = _evaluator(monkeypatch, threshold=threshold, operator=operator)
    evaluator._client.invoke = AsyncMock(
        return_value=JevInvokeResponse(score=score, status="success")
    )
    result = await evaluator.evaluate_with_extensions(
        "",
        Step(
            type="trace",
            name="root",
            input="",
            children=[Step(type="llm", name="answer", input="")],
        ),
        EXTENSIONS,
    )
    assert result.matched is expected
    await evaluator.aclose()


@pytest.mark.asyncio
async def test_child_only_trace_keeps_nested_span_and_execution_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(monkeypatch)
    invoke = AsyncMock(return_value=JevInvokeResponse(score=0.82, status="success"))
    evaluator._client.invoke = invoke
    step = Step(
        type="trace",
        name="root",
        input="",
        output="",
        children=[
            Step(
                type="tool",
                name="search",
                input={"query": "question"},
                children=[Step(type="retriever", name="docs", input="question", output=["doc"])],
            ),
            Step(type="llm", name="answer", input="question", output="answer"),
        ],
    )

    result = await evaluator.evaluate_with_extensions("", step, EXTENSIONS)

    assert result.matched is True
    call = invoke.await_args.kwargs
    assert call["scorer_version_id"] == "version-a"
    assert call["execution_context"].user_id == "user-7"
    record = call["step"]
    assert record.children[0].children[0].type == "retriever"
    assert call["inputs"].query == ""
    await evaluator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("record_type", ["llm", "tool", "retriever", "trace", "session"])
async def test_supported_record_types_are_built_from_step_children(
    monkeypatch: pytest.MonkeyPatch, record_type: str
) -> None:
    evaluator = _evaluator(monkeypatch)
    invoke = AsyncMock(return_value=JevInvokeResponse(score="yes", status="success"))
    evaluator._client.invoke = invoke
    if record_type == "session":
        step = Step(
            type="session",
            name="session",
            input="",
            children=[
                Step(
                    type="trace",
                    name="trace",
                    input="",
                    children=[Step(type="llm", name="llm", input="")],
                )
            ],
        )
    elif record_type == "trace":
        step = Step(
            type="trace", name="trace", input="", children=[Step(type="llm", name="llm", input="")]
        )
    elif record_type in {"tool", "retriever"}:
        step = Step(
            type=record_type,
            name=record_type,
            input={"query": "question"} if record_type == "tool" else "question",
            children=[Step(type="llm", name="llm", input="")],
        )
    else:
        step = Step(type="llm", name="llm", input="")
    await evaluator.evaluate_with_extensions("input", step, EXTENSIONS)
    assert invoke.await_args.kwargs["step"].type == record_type
    await evaluator.aclose()


@pytest.mark.asyncio
async def test_runtime_disabled_and_missing_context_return_errors_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(monkeypatch)
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME", "disabled")
    invoke = AsyncMock()
    evaluator._client.invoke = invoke

    result = await evaluator.evaluate_with_extensions(
        "question", Step(type="llm", name="answer", input="question"), EXTENSIONS
    )

    assert result.matched is False
    assert "runtime is disabled" in (result.error or "")
    assert invoke.await_count == 0
    direct_result = await evaluator.evaluate("question")
    assert "runtime is disabled" in (direct_result.error or "")
    missing_context = await evaluator.evaluate_with_extensions(
        "question", Step(type="llm", name="answer", input=""), None
    )
    assert missing_context.matched is False
    assert "execution_context" in (missing_context.error or "")
    await evaluator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError("deadline"), RuntimeError("provider failed")])
async def test_timeout_and_provider_errors_are_non_matching(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    evaluator = _evaluator(monkeypatch)
    evaluator._client.invoke = AsyncMock(side_effect=error)
    result = await evaluator.evaluate_with_extensions(
        "input", Step(type="llm", name="answer", input="input"), EXTENSIONS
    )
    assert result.matched is False
    assert result.error == str(error)
    assert result.metadata["error_type"] == type(error).__name__
    await evaluator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("record_type", ["trace", "session", "llm", "tool", "retriever"])
async def test_client_serializes_full_record_context_and_uses_timeout(
    monkeypatch: pytest.MonkeyPatch, record_type: str
) -> None:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://runners:8090")
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME", "enabled")
    client = GalileoJevClient()
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = request.read().decode()
        seen["timeout"] = request.extensions.get("timeout")
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json={"score": 0.9, "status": "success"})

    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = Step(
        type="llm",
        name="answer",
        input=[{"role": "user", "content": "question"}],
        output={"role": "assistant", "content": "answer"},
        tools=[{"name": "lookup", "description": "search"}],
    )
    if record_type == "trace":
        step = Step(
            type="trace",
            name="trace",
            input="",
            children=[
                llm,
                Step(
                    type="tool",
                    name="lookup",
                    input={"query": "question"},
                    output={"found": True},
                    children=[
                        Step(
                            type="retriever",
                            name="docs",
                            input="question",
                            output=[{"text": "document", "metadata": {"source": "kb"}}],
                        )
                    ],
                ),
            ],
        )
    elif record_type == "session":
        step = Step(
            type="session",
            name="session",
            input="",
            children=[Step(type="trace", name="trace", input="question", children=[llm])],
        )
    elif record_type == "tool":
        step = Step(
            type="tool",
            name="lookup",
            input={"query": "question"},
            output={"found": True},
        )
    elif record_type == "retriever":
        step = Step(
            type="retriever",
            name="docs",
            input="question",
            output=[{"text": "document", "metadata": {"source": "kb"}}],
        )
    else:
        step = llm
    response = await client.invoke(
        scorer_id="scorer-a",
        scorer_version_id="version-a",
        scorer_label=None,
        step=step,
        execution_context=GalileoExecutionContext(organization_id="org-1", user_id="user-7"),
        inputs=JevInvokeInputs(),
        timeout=5.0,
    )
    assert response.score == 0.9
    assert seen["url"] == "http://runners:8090/api/v1/scorers/invoke"
    payload = json.loads(seen["payload"])
    assert payload["scorer_version_id"] == "version-a"
    assert payload["execution_context"]["user_id"] == "user-7"
    assert payload["record"]["type"] == record_type
    record = payload["record"]
    assert record["name"] == step.name
    assert record["user_metadata"] == {}
    assert "created_at" in record
    if record_type == "llm":
        assert record["input"] == [{"content": "question", "role": "user"}]
        assert record["output"] == {"content": "answer", "role": "assistant"}
        assert record["tools"] == [{"name": "lookup", "description": "search"}]
    elif record_type == "tool":
        assert record["input"] == '{"query": "question"}'
        assert record["output"] == '{"found": true}'
    elif record_type == "retriever":
        assert record["input"] == "question"
        assert record["output"] == [
            {
                "content": '{"text": "document", "metadata": {"source": "kb"}}',
                "metadata": {},
            }
        ]
    if record_type == "session":
        trace = record["traces"][0]
        assert trace["type"] == "trace"
        assert trace["name"] == "trace"
        assert trace["input"] == "question"
        assert trace["user_metadata"] == {}
        assert trace["spans"][0]["input"] == [{"content": "question", "role": "user"}]
        assert trace["spans"][0]["output"] == {"content": "answer", "role": "assistant"}
        assert trace["spans"][0]["tools"] == [{"name": "lookup", "description": "search"}]
    elif record_type == "trace":
        llm_span, tool_span = record["spans"]
        assert llm_span["type"] == "llm"
        assert llm_span["name"] == "answer"
        assert llm_span["input"] == [{"content": "question", "role": "user"}]
        assert llm_span["output"] == {"content": "answer", "role": "assistant"}
        assert llm_span["tools"] == [{"name": "lookup", "description": "search"}]
        assert tool_span["type"] == "tool"
        assert tool_span["name"] == "lookup"
        assert tool_span["input"] == '{"query": "question"}'
        assert tool_span["output"] == '{"found": true}'
        retriever_span = tool_span["spans"][0]
        assert retriever_span["type"] == "retriever"
        assert retriever_span["name"] == "docs"
        assert retriever_span["input"] == "question"
        assert retriever_span["output"] == [
            {
                "content": '{"text": "document", "metadata": {"source": "kb"}}',
                "metadata": {},
            }
        ]
    token_parts = seen["authorization"].removeprefix("Bearer ").split(".")
    assert len(token_parts) == 3
    header = _decode_jwt_segment(token_parts[0])
    claims = _decode_jwt_segment(token_parts[1])
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert claims["internal"] is True
    assert claims["scope"] == "scorers.invoke"
    assert claims["exp"] - claims["iat"] == 3600
    signing_input = ".".join(token_parts[:2]).encode("ascii")
    expected_signature = (
        urlsafe_b64encode(hmac_new(b"test-secret", signing_input, sha256).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert compare_digest(token_parts[2], expected_signature)
    assert payload["config"]["request_timeout_seconds"] == 4.0
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector_case", "step_type", "data", "payload_field"),
    [
        (
            "input selector",
            "llm",
            [{"role": "user", "content": "selected input"}],
            "input",
        ),
        ("output selector", "llm", "selected output", "output"),
        ("input.query selector", "tool", "selected query", "input"),
        (
            "wildcard selector",
            "trace",
            {
                "type": "trace",
                "name": "trace",
                "input": "selected trace input",
                "output": "selected trace output",
                "children": [{"type": "llm", "name": "child answer"}],
            },
            "input",
        ),
        (
            "wildcard session selector",
            "session",
            {
                "type": "session",
                "name": "session",
                "input": "selected session input",
                "output": "selected session output",
                "children": [{"type": "trace", "name": "trace"}],
            },
            "input",
        ),
    ],
)
async def test_selector_values_update_structured_record_and_preserve_children(
    monkeypatch: pytest.MonkeyPatch,
    selector_case: str,
    step_type: str,
    data: Any,
    payload_field: str,
) -> None:
    evaluator = _evaluator(monkeypatch, payload_field=payload_field)
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(200, json={"score": 0.9, "status": "success"})

    await evaluator._client._client.aclose()
    evaluator._client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm_child = Step(type="llm", name="child answer", input="child question", output="child")
    if step_type == "tool":
        step = Step(
            type="tool",
            name="lookup",
            input={"query": "original query"},
            output="tool result",
            children=[llm_child],
        )
    elif step_type == "trace":
        step = Step(
            type="trace",
            name="trace",
            input="original trace input",
            output="original trace output",
            children=[llm_child],
        )
    elif step_type == "session":
        step = Step(
            type="session",
            name="session",
            input="original session input",
            output="original session output",
            children=[Step(type="trace", name="trace", input="child trace", children=[llm_child])],
        )
    else:
        step = Step(
            type="llm",
            name="root answer",
            input=[{"role": "user", "content": "original input"}],
            output="original output",
        )

    result = await evaluator.evaluate_with_extensions(data, step, EXTENSIONS)

    assert result.matched is True, selector_case
    record = seen["payload"]["record"]
    if selector_case == "input selector":
        assert record["input"] == [{"role": "user", "content": "selected input"}]
        assert record["output"]["content"] == "original output"
    elif selector_case == "output selector":
        assert record["input"] == [{"role": "user", "content": "original input"}]
        assert record["output"]["content"] == "selected output"
    elif selector_case == "input.query selector":
        assert record["input"] == "selected query"
        assert record["output"] == "tool result"
        assert record["spans"][0]["name"] == "child answer"
    elif selector_case == "wildcard selector":
        assert record["input"] == "selected trace input"
        assert record["output"] == "selected trace output"
        assert record["spans"][0]["name"] == "child answer"
    else:
        assert record["input"] == "selected session input"
        assert record["output"] == "selected session output"
        assert record["traces"][0]["spans"][0]["name"] == "child answer"
    await evaluator.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "threshold", "expected"),
    [(0, 0, True), (False, False, True)],
)
async def test_successful_zero_and_false_scores_are_valid(
    monkeypatch: pytest.MonkeyPatch,
    score: Any,
    threshold: Any,
    expected: bool,
) -> None:
    evaluator = _evaluator(monkeypatch, threshold=threshold, operator="eq")
    evaluator._client.invoke = AsyncMock(
        return_value=JevInvokeResponse(score=score, status="success")
    )
    result = await evaluator.evaluate_with_extensions(
        "input", Step(type="llm", name="answer", input="input"), EXTENSIONS
    )
    assert result.matched is expected
    await evaluator.aclose()


@pytest.mark.asyncio
async def test_successful_response_without_score_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(monkeypatch)
    evaluator._client.invoke = AsyncMock(
        return_value=JevInvokeResponse(status="success", score=None)
    )
    result = await evaluator.evaluate_with_extensions(
        "input", Step(type="llm", name="answer", input="input"), EXTENSIONS
    )
    assert result.matched is False
    assert result.error == "Jev scorer response did not include a score"
    await evaluator.aclose()


@pytest.mark.asyncio
async def test_non_success_response_without_score_uses_provider_status_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(monkeypatch)
    evaluator._client.invoke = AsyncMock(
        return_value=JevInvokeResponse(
            status="error", score=None, error_message="provider rejected request"
        )
    )
    result = await evaluator.evaluate_with_extensions(
        "input", Step(type="llm", name="answer", input="input"), EXTENSIONS
    )
    assert result.matched is False
    assert result.error == "provider rejected request"
    await evaluator.aclose()


@pytest.mark.asyncio
async def test_direct_evaluation_and_context_method_report_missing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(monkeypatch)
    step = Step(type="llm", name="answer", input="question")

    direct_result = await evaluator.evaluate("question")
    context_result = await evaluator.evaluate_with_context("question", step)

    assert "requires Step context" in (direct_result.error or "")
    assert "requires execution_context" in (context_result.error or "")
    await evaluator.aclose()


@pytest.mark.asyncio
async def test_extensions_without_organization_id_return_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(monkeypatch)
    extensions = {"caller_id": "user-7", "target_type": "log_stream"}

    result = await evaluator.evaluate_with_extensions(
        "question", Step(type="llm", name="answer", input="question"), extensions
    )

    assert result.matched is False
    assert "missing organization_id" in (result.error or "")
    await evaluator.aclose()


@pytest.mark.parametrize(
    ("score", "threshold", "operator", "expected"),
    [("yes", None, "any", True), ("", None, "any", False)],
)
def test_any_operator_uses_score_truthiness(
    monkeypatch: pytest.MonkeyPatch,
    score: Any,
    threshold: Any,
    operator: str,
    expected: bool,
) -> None:
    evaluator = _evaluator(monkeypatch, threshold=threshold, operator=operator)

    assert evaluator._matches(score) is expected


def test_numeric_comparison_rejects_non_numeric_threshold_from_unvalidated_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://runners:8090")
    config = JevEvaluatorConfig.model_construct(
        scorer_id="scorer-a",
        scorer_version_id="version-a",
        threshold="not numeric",
        operator="gte",
    )
    evaluator = JevEvaluator(config)

    with pytest.raises(ValueError, match="threshold .* is not numeric"):
        evaluator._matches(0.8)


def test_http_status_errors_include_status_code_in_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evaluator = _evaluator(monkeypatch)
    response = httpx.Response(401, request=httpx.Request("POST", "http://runners"))
    error = httpx.HTTPStatusError("unauthorized", request=response.request, response=response)

    result = evaluator._error(error)

    assert result.metadata["http_status_code"] == 401


def test_invoke_url_with_existing_path_is_preserved() -> None:
    url = "https://runners.example/custom?tenant=one#invoke"

    assert _normalize_invoke_url(url) == url


def test_client_falls_back_to_legacy_api_secret_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GALILEO_API_SECRET_KEY", raising=False)
    monkeypatch.setenv("GALILEO_API_SECRET", "legacy-secret")

    client = GalileoJevClient(invoke_url="http://runners:8090")

    assert client.api_secret == "legacy-secret"


def test_client_requires_api_secret_when_environment_variables_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GALILEO_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("GALILEO_API_SECRET", raising=False)

    with pytest.raises(ValueError, match="GALILEO_API_SECRET_KEY or GALILEO_API_SECRET"):
        GalileoJevClient(invoke_url="http://runners:8090")


@pytest.mark.asyncio
async def test_client_rejects_invoke_when_runtime_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME", "disabled")
    client = GalileoJevClient(invoke_url="http://runners:8090")

    with pytest.raises(RuntimeError, match="runtime is disabled"):
        await client.invoke(
            scorer_id="scorer-a",
            scorer_version_id="version-a",
            scorer_label=None,
            step=Step(type="llm", name="answer", input="question"),
            execution_context=GalileoExecutionContext(organization_id="org-1"),
            inputs=JevInvokeInputs(),
            timeout=5.0,
        )

    await client.close()


@pytest.mark.asyncio
async def test_client_rejects_non_object_invoke_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME", "enabled")
    client = GalileoJevClient(invoke_url="http://runners:8090")

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"score": 0.9}])

    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="expected a JSON object"):
        await client.invoke(
            scorer_id="scorer-a",
            scorer_version_id="version-a",
            scorer_label=None,
            step=Step(type="llm", name="answer", input="question"),
            execution_context=GalileoExecutionContext(organization_id="org-1"),
            inputs=JevInvokeInputs(),
            timeout=5.0,
        )

    await client.close()


def test_luna_and_jev_request_shape_parity() -> None:
    context = GalileoExecutionContext(organization_id="org-1", user_id="user-7")
    luna = ScorerInvokeRequest(
        scorer_id="scorer-a",
        scorer_version_id="version-a",
        inputs=ScorerInvokeInputs(query="q", response="a"),
        record={"type": "llm", "input": "q", "output": "a"},
        execution_context=context,
    ).to_dict()
    jev = JevInvokeRequest(
        scorer_id="scorer-a",
        scorer_version_id="version-a",
        inputs=JevInvokeInputs(query="q", response="a"),
        record={"type": "llm", "input": "q", "output": "a"},
        execution_context=context,
    ).to_dict()
    assert set(luna) == set(jev)
    assert set(luna["inputs"]) == set(jev["inputs"])
    assert luna["execution_context"] == jev["execution_context"]
