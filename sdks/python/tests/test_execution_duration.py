"""Per-control duration survives SDK response parsing and event reconstruction."""

from collections.abc import Iterator, Sequence
from functools import partial
from typing import Any, Literal
from unittest.mock import MagicMock, patch

import httpx
import pytest
from agent_control_models import ControlExecutionEvent, Step
from agent_control_telemetry import REGISTERED_CONTROL_EVENT_SINK_NAME
from agent_control_telemetry.sinks import BaseControlEventSink, SinkResult

from agent_control import (
    AgentControlClient,
    control,
    register_control_event_sink,
    unregister_control_event_sink,
)
from agent_control._state import state
from agent_control.evaluation import check_evaluation, check_evaluation_with_local
from agent_control.otel_sink import control_event_to_otel_span
from agent_control.settings import configure_settings, get_settings

ResultCategory = Literal["matches", "errors", "non_matches"]


class RecordingSink(BaseControlEventSink):
    """Capture the events delivered through the public sink API."""

    def __init__(self) -> None:
        self.events: list[ControlExecutionEvent] = []

    def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
        self.events.extend(events)
        return SinkResult(accepted=len(events), dropped=0)


@pytest.fixture
def recording_sink(monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingSink]:
    # Given: an isolated SDK session exporting to a registered event sink.
    previous_settings = get_settings().model_dump()
    for name in ("current_agent", "target_type", "target_id", "server_controls"):
        monkeypatch.setattr(state, name, None)
    sink = RecordingSink()
    register_control_event_sink(sink)
    configure_settings(
        observability_enabled=True,
        observability_sink_name=REGISTERED_CONTROL_EVENT_SINK_NAME,
    )
    try:
        yield sink
    finally:
        unregister_control_event_sink(sink)
        configure_settings(**previous_settings)


def _server_response(category: ResultCategory, duration: float | None) -> dict[str, Any]:
    match: dict[str, Any] = {
        "control_id": 2,
        "control_name": "server-control",
        "control_execution_id": "server-execution",
        "action": "observe",
        "result": {
            "matched": category == "matches",
            "confidence": 1.0,
            "error": "Evaluator failed" if category == "errors" else None,
        },
    }
    if duration is not None:
        match["execution_duration_ms"] = duration
    return {"is_safe": category != "errors", "confidence": 1.0, category: [match]}


def _control_payload(control_id: int, execution: str) -> dict[str, Any]:
    return {
        "id": control_id,
        "name": f"{execution}-control",
        "control": {
            "execution": execution,
            "scope": {"stages": ["pre"]},
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {"name": "regex", "config": {"pattern": "hello"}},
            },
            "action": {"decision": "observe"},
        },
    }


@pytest.mark.parametrize("category", ["matches", "errors", "non_matches"])
@pytest.mark.parametrize("duration", [12.5, 0.0, None])
async def test_server_duration_reaches_events_and_otel(
    recording_sink: RecordingSink,
    category: ResultCategory,
    duration: float | None,
) -> None:
    # Given: a real SDK client receiving a timed or legacy server response.
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_server_response(category, duration))
    )

    # When: evaluating through the public server-only SDK helper.
    async with AgentControlClient(base_url="https://server.test", transport=transport) as client:
        result = await check_evaluation(
            client,
            agent_name="agent-000000000001",
            step=Step(type="llm", name="chat", input="hello"),
            stage="pre",
        )

    # Then: the typed result and exported event retain the exact per-control value.
    matches = getattr(result, category)
    assert matches is not None
    assert matches[0].execution_duration_ms == duration
    assert len(recording_sink.events) == 1
    event = recording_sink.events[0]
    assert event.execution_duration_ms == duration
    assert "execution_duration_ms" not in event.metadata
    span = control_event_to_otel_span(event)
    if duration is None:
        assert "agent_control.execution_duration_ms" not in span.attributes
    else:
        assert span.attributes["agent_control.execution_duration_ms"] == duration
        assert span.end_time_unix_nano - span.start_time_unix_nano == int(duration * 1_000_000)


async def test_mixed_local_and_server_events_keep_their_own_durations(
    recording_sink: RecordingSink,
) -> None:
    # Given: a real local regex control and a server control with a distinct duration.
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_server_response("non_matches", 27.5))
    )
    controls = [_control_payload(1, "sdk"), _control_payload(2, "server")]

    # When: evaluating both controls through the public local-first SDK helper.
    async with AgentControlClient(base_url="https://server.test", transport=transport) as client:
        result = await check_evaluation_with_local(
            client,
            agent_name="agent-000000000001",
            step=Step(type="llm", name="chat", input="hello"),
            stage="pre",
            controls=controls,
            trace_id="a" * 32,
            span_id="b" * 16,
        )

    # Then: local engine timing and server timing each reach the corresponding event.
    assert result.matches is not None
    assert result.non_matches is not None
    local_duration = result.matches[0].execution_duration_ms
    assert local_duration is not None
    assert local_duration >= 0
    assert len(recording_sink.events) == 2
    durations = {event.control_id: event.execution_duration_ms for event in recording_sink.events}
    assert durations == {1: local_duration, 2: 27.5}


@pytest.mark.parametrize("category", ["matches", "errors", "non_matches"])
@pytest.mark.parametrize("duration", [12.5, 0.0, None])
async def test_decorator_preserves_duration_in_events_and_debug_logs(
    recording_sink: RecordingSink,
    category: ResultCategory,
    duration: float | None,
) -> None:
    # Given: a decorated control site using cached controls and a mock HTTP server.
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=_server_response(category, duration))
    )
    agent = MagicMock(agent_name="agent-000000000001")

    @control()
    async def chat(message: str) -> str:
        return message

    # When: calling the public decorator through its real evaluation and reconstruction paths.
    with (
        patch("agent_control.current_agent", return_value=agent),
        patch("agent_control.get_server_controls", return_value=[_control_payload(2, "server")]),
        patch(
            "agent_control.control_decorators.AgentControlClient",
            partial(AgentControlClient, transport=transport),
        ),
        patch("agent_control.control_decorators.log_control_evaluation") as log_evaluation,
    ):
        if category == "errors":
            with pytest.raises(RuntimeError, match="Control evaluation failed on server"):
                await chat("hello")
        else:
            assert await chat("hello") == "hello"

    # Then: reconstruction retains duration for every category, including zero and missing values.
    assert len(recording_sink.events) == 1
    assert recording_sink.events[0].execution_duration_ms == duration
    log_evaluation.assert_called_once()
    assert log_evaluation.call_args.kwargs["duration_ms"] == duration
