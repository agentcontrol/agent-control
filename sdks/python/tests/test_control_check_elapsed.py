"""Public SDK contract tests for actual whole-check elapsed timing."""

import asyncio
import json
from collections.abc import Iterator, Sequence
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from agent_control_models import ControlExecutionEvent, EvaluationResult, Step
from agent_control_telemetry import BaseControlEventSink, SinkResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from agent_control import (
    AgentControlClient,
    ControlCheckEvent,
    check_evaluation_with_local,
    control_check,
    evaluation,
    init_observability,
    register_control_event_sink,
    sync_shutdown_observability,
    unregister_control_event_sink,
)
from agent_control.settings import configure_settings, get_settings


class CheckCollector(BaseControlEventSink):
    """Opt-in sink collecting both event types without a server."""

    def __init__(self) -> None:
        self.checks: list[ControlCheckEvent] = []

    def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        return SinkResult(accepted=len(events))

    def write_control_check_events(self, events: Sequence[ControlCheckEvent]) -> SinkResult:
        self.checks.extend(events)
        return SinkResult(accepted=len(events))


@pytest.fixture(autouse=True)
def settings() -> Iterator[None]:
    previous = get_settings().model_dump()
    configure_settings(observability_enabled=False)
    yield
    sync_shutdown_observability()
    configure_settings(**previous)


@pytest.fixture
def collector() -> Iterator[CheckCollector]:
    sink = CheckCollector()
    register_control_event_sink(sink)
    configure_settings(observability_enabled=True, observability_sink_name="registered")
    yield sink
    unregister_control_event_sink(sink)


def control_payload(execution: str, *, deny: bool = False) -> dict[str, Any]:
    return {
        "id": 1 if execution == "sdk" else 2,
        "name": f"{execution}-control",
        "control": {
            "description": "Timing test",
            "execution": execution,
            "scope": {"step_types": ["llm"], "stages": ["pre", "post"]},
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {"name": "regex", "config": {"pattern": "hello"}},
            },
            "action": {"decision": "deny" if deny else "observe"},
        },
    }


def step() -> Step:
    return Step(type="llm", name="chat", input="hello")


@pytest.mark.asyncio
async def test_five_remote_controls_use_measured_batch_not_mean_or_max(monkeypatch) -> None:
    # Given: five control durations and an independently measured HTTP round trip.
    monkeypatch.setattr(control_check.time, "perf_counter_ns", Mock(side_effect=[0, 100_000_000]))
    wall_clock = Mock(side_effect=AssertionError("disabled telemetry must not read epoch clock"))
    monkeypatch.setattr(control_check.time, "time_ns", wall_clock)
    matches = [
        {
            "control_id": number,
            "control_name": f"c{number}",
            "action": "observe",
            "result": {"matched": False, "confidence": 1},
            "execution_duration_ms": number * 10,
        }
        for number in range(1, 6)
    ]
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"is_safe": True, "confidence": 1, "non_matches": matches}
        )
    )

    # When: using the public SDK helper.
    async with AgentControlClient(base_url="https://test.invalid", transport=transport) as client:
        result = await check_evaluation_with_local(
            client, "test-agent", step(), "pre", [control_payload("server")]
        )

    # Then: the batch is measured directly; individual control durations are preserved.
    assert result.control_check_elapsed_ms == 100
    assert result.control_check_id
    assert [item.execution_duration_ms for item in result.non_matches] == [10, 20, 30, 40, 50]
    assert result.control_check_elapsed_ms != 30  # average
    assert result.control_check_elapsed_ms != 50  # maximum
    wall_clock.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["pre", "post"])
async def test_mixed_local_remote_check_has_one_event_and_parent(
    stage, monkeypatch, collector
) -> None:
    # Given: local and remote controls, plus a deterministic whole-check clock.
    monkeypatch.setattr(control_check.time, "perf_counter_ns", Mock(side_effect=[0, 140_000_000]))
    monkeypatch.setattr(control_check.time, "time_ns", lambda: 1_000_000_000)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"is_safe": True, "confidence": 1})
    )

    # When: one stage checks both local and conditional remote controls.
    async with AgentControlClient(base_url="https://test.invalid", transport=transport) as client:
        result = await check_evaluation_with_local(
            client,
            "test-agent",
            step(),
            stage,
            [control_payload("sdk"), control_payload("server")],
            trace_id="a" * 32,
            span_id="b" * 16,
        )

    # Then: one measured event identifies this invocation and preserves local outcomes.
    assert result.control_check_elapsed_ms == 140
    assert result.matches[0].execution_duration_ms is not None
    assert len(collector.checks) == 1
    event = collector.checks[0]
    assert event.control_check_id == result.control_check_id
    assert event.trace_id == "a" * 32
    assert event.span_id == "b" * 16
    assert event.check_stage == stage
    assert event.status == "completed"
    assert event.start_time_unix_nano == 1_000_000_000
    assert event.end_time_unix_nano == 1_140_000_000


@pytest.mark.asyncio
async def test_local_deny_short_circuits_server_but_still_measures(monkeypatch, collector) -> None:
    # Given: a local deny and a server control that must never be contacted.
    monkeypatch.setattr(control_check.time, "perf_counter_ns", Mock(side_effect=[0, 5_000_000]))
    transport = httpx.MockTransport(lambda request: pytest.fail("server called after local deny"))

    # When: evaluating the controls through the public SDK.
    async with AgentControlClient(base_url="https://test.invalid", transport=transport) as client:
        result = await check_evaluation_with_local(
            client,
            "test-agent",
            step(),
            "pre",
            [control_payload("sdk", deny=True), control_payload("server")],
        )

    # Then: a completed unsafe batch has its own elapsed time.
    assert not result.is_safe
    assert result.control_check_elapsed_ms == 5
    assert collector.checks[0].status == "completed"
    assert collector.checks[0].is_safe is False


@pytest.mark.asyncio
async def test_empty_check_and_measured_zero_are_not_unknown(monkeypatch, collector) -> None:
    # Given: no applicable controls and a clock with genuinely equal readings.
    monkeypatch.setattr(control_check.time, "perf_counter_ns", lambda: 5)
    async with AgentControlClient(base_url="https://test.invalid") as client:
        # When: completing an empty check.
        result = await check_evaluation_with_local(client, "test-agent", step(), "post", [])

    # Then: measured zero is retained, while legacy result timing remains unknown.
    assert result.control_check_elapsed_ms == 0
    assert collector.checks[0].elapsed_ms == 0
    assert EvaluationResult(is_safe=True, confidence=1).control_check_elapsed_ms is None


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_error_and_cancellation_propagate_and_emit_status(cancelled, monkeypatch, collector):
    # Given: an actual HTTP transport failure or cancellation during the check.
    error = asyncio.CancelledError() if cancelled else httpx.ConnectError("private detail")
    monkeypatch.setattr(control_check.time, "perf_counter_ns", Mock(side_effect=[0, 8_000_000]))

    async def fail(request: httpx.Request) -> httpx.Response:
        raise error

    # When: calling the public helper.
    async with AgentControlClient(
        base_url="https://test.invalid", transport=httpx.MockTransport(fail)
    ) as client:
        with pytest.raises(type(error)) as caught:
            await check_evaluation_with_local(
                client, "test-agent", step(), "pre", [control_payload("server")]
            )

    # Then: the original failure survives and no sensitive exception text is recorded.
    assert caught.value is error
    assert collector.checks[0].status == ("cancelled" if cancelled else "error")
    assert collector.checks[0].is_safe is None
    assert "private detail" not in collector.checks[0].model_dump_json()


@pytest.mark.asyncio
async def test_telemetry_failure_preserves_completed_result(monkeypatch, collector) -> None:
    # Given: an enabled sink whose check-event export fails.
    monkeypatch.setattr(
        control_check, "write_control_check_events", Mock(side_effect=RuntimeError("sink failed"))
    )
    async with AgentControlClient(base_url="https://test.invalid") as client:
        # When: completing an empty check.
        result = await check_evaluation_with_local(client, "test-agent", step(), "pre", [])

    # Then: the valid business result and measured timing survive.
    assert result.is_safe
    assert result.control_check_elapsed_ms is not None


@pytest.mark.asyncio
async def test_otel_check_uses_existing_provider_and_actual_interval(monkeypatch) -> None:
    # Given: a configured provider/exporter and real interval independent of child events.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    init_observability(
        enabled=True,
        sink_name="otel",
        sink_config={"enabled": True},
        otel_tracer_provider=provider,
    )
    monkeypatch.setattr(control_check.time, "perf_counter_ns", Mock(side_effect=[0, 25_000_000]))
    monkeypatch.setattr(control_check.time, "time_ns", lambda: 2_000_000_000)

    # When: completing a check with no control children.
    async with AgentControlClient(base_url="https://test.invalid") as client:
        result = await check_evaluation_with_local(
            client,
            "test-agent",
            step(),
            "post",
            [],
            trace_id="a" * 32,
            span_id="b" * 16,
        )

    # Then: the genuine batch span is correlated and is not mislabeled as a control.
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "agent_control.control_check"
    assert span.parent.span_id == int("b" * 16, 16)
    assert span.start_time == 2_000_000_000
    assert span.end_time == 2_025_000_000
    assert span.attributes["agent_control.control_check_elapsed_ms"] == 25
    assert span.attributes["agent_control.control_check_id"] == result.control_check_id
    assert "agent_control.control_id" not in span.attributes
    assert "agent_control.action" not in span.attributes
    metadata = json.loads(span.attributes["metadata"])
    assert metadata["check_stage"] == "post"
    assert metadata["control_check_elapsed_ms"] == 25
    provider.shutdown()


def test_result_timing_rejects_invalid_values_and_server_schema_is_unchanged() -> None:
    # Given: malformed elapsed values and a legacy server response.
    for value in [-1, float("inf"), float("nan")]:
        # When: constructing a typed result with invalid timing.
        with pytest.raises(ValidationError):
            EvaluationResult(is_safe=True, confidence=1, control_check_elapsed_ms=value)
    # Then: the server response has no SDK-only fields.
    assert "control_check_elapsed_ms" not in evaluation.EvaluationResponse.model_fields


@pytest.mark.asyncio
async def test_old_control_only_sink_remains_compatible() -> None:
    # Given: a selected sink implementing only the existing event contract.
    class OldSink(BaseControlEventSink):
        def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
            return SinkResult(accepted=len(events))

    sink = OldSink()
    register_control_event_sink(sink)
    configure_settings(observability_enabled=True, observability_sink_name="registered")
    try:
        async with AgentControlClient(base_url="https://test.invalid") as client:
            # When: completing a check with the old sink selected.
            result = await check_evaluation_with_local(client, "test-agent", step(), "pre", [])
        # Then: timing is available without requiring a new sink method or HTTP payload.
        assert result.is_safe
        assert result.control_check_elapsed_ms is not None
    finally:
        unregister_control_event_sink(sink)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_telemetry_failure_preserves_original_exception(cancelled, monkeypatch, collector):
    # Given: a transport failure/cancellation and an independent telemetry failure.
    error = asyncio.CancelledError() if cancelled else httpx.ConnectError("original")
    monkeypatch.setattr(
        control_check, "write_control_check_events", Mock(side_effect=RuntimeError("sink failed"))
    )

    async def fail(request: httpx.Request) -> httpx.Response:
        raise error

    # When: calling the public helper.
    async with AgentControlClient(
        base_url="https://test.invalid", transport=httpx.MockTransport(fail)
    ) as client:
        with pytest.raises(type(error)) as caught:
            await check_evaluation_with_local(
                client, "test-agent", step(), "pre", [control_payload("server")]
            )
    # Then: telemetry cannot replace the original business failure.
    assert caught.value is error


@pytest.mark.asyncio
async def test_decorator_server_fallback_preserves_raw_extensions_and_measures(
    monkeypatch, collector
):
    # Given: an uncached decorator site with a raw server response extension.
    # The internal adapter is needed to force the fallback without global init/server setup.
    from agent_control import control_decorators

    response = httpx.Response(
        200,
        request=httpx.Request("POST", "https://test.invalid/api/v1/evaluation"),
        json={"is_safe": True, "confidence": 1, "extension": {"kept": True}},
    )
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        control_decorators, "_post_evaluation_request", AsyncMock(return_value=response)
    )
    monkeypatch.setattr(control_check.time, "perf_counter_ns", Mock(side_effect=[0, 12_000_000]))
    # When: the decorator takes its server-only fallback.
    result = await control_decorators._evaluate(
        "test-agent",
        step().model_dump(),
        "post",
        "https://test.invalid",
        trace_id="a" * 32,
        span_id="b" * 16,
        controls=None,
    )
    # Then: raw extensions survive and the genuine check interval is captured.
    assert result["extension"] == {"kept": True}
    assert result["control_check_elapsed_ms"] == 12
    assert collector.checks[0].control_check_id == result["control_check_id"]
    assert collector.checks[0].span_id == "b" * 16


@pytest.mark.asyncio
async def test_server_only_helper_returns_measured_result(monkeypatch, collector) -> None:
    # Given: a server response with no duration fields from an older server.
    monkeypatch.setattr(control_check.time, "perf_counter_ns", Mock(side_effect=[0, 20_000_000]))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"is_safe": True, "confidence": 1})
    )
    async with AgentControlClient(base_url="https://test.invalid", transport=transport) as client:
        # When: using the public server-only helper.
        result = await evaluation.check_evaluation(client, "test-agent", step(), "pre")
    # Then: this SDK measures caller elapsed without relying on server timing fields.
    assert result.control_check_elapsed_ms == 20
    assert collector.checks[0].elapsed_ms == 20
