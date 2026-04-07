"""Tests for telemetry sink contracts."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

from agent_control_models import ControlExecutionEvent
from agent_control_telemetry import (
    BaseAsyncControlEventSink,
    BaseControlEventSink,
    SinkResult,
)


def _make_event(*, control_id: int) -> ControlExecutionEvent:
    return ControlExecutionEvent(
        trace_id="trace-123",
        span_id="span-456",
        agent_name="demo-agent",
        control_id=control_id,
        control_name=f"control-{control_id}",
        check_stage="pre",
        applies_to="tool_call",
        action="observe",
        matched=False,
        confidence=0.0,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_sink_result_success_reflects_accepted_events() -> None:
    # Given: two sink results with and without accepted events
    successful = SinkResult(accepted=1, dropped=0)
    unsuccessful = SinkResult(accepted=0, dropped=2)

    # When/Then: success tracks whether any events were accepted
    assert successful.success is True
    assert unsuccessful.success is False


def test_base_control_event_sink_batches_single_event_writers() -> None:
    # Given: a sink that only implements single-event writes
    class RecordingSink(BaseControlEventSink):
        def __init__(self) -> None:
            self.seen_control_ids: list[int] = []

        def write_event(self, event: ControlExecutionEvent) -> SinkResult:
            self.seen_control_ids.append(event.control_id)
            return SinkResult(accepted=1, dropped=event.control_id % 2)

    sink = RecordingSink()
    events = [_make_event(control_id=1), _make_event(control_id=2)]

    # When: the caller uses the batch contract
    result = sink.write_events(events)

    # Then: the base helper fans out to single-event writes and aggregates results
    assert sink.seen_control_ids == [1, 2]
    assert result == SinkResult(accepted=2, dropped=1)


def test_base_control_event_sink_single_event_delegates_to_batch_writer() -> None:
    # Given: a sink that only implements batch writes
    class RecordingSink(BaseControlEventSink):
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
            self.batch_sizes.append(len(events))
            return SinkResult(accepted=len(events))

    sink = RecordingSink()
    event = _make_event(control_id=7)

    # When: the caller uses the single-event contract
    result = sink.write_event(event)

    # Then: the base helper delegates through the batch implementation
    assert sink.batch_sizes == [1]
    assert result == SinkResult(accepted=1, dropped=0)


def test_base_async_control_event_sink_batches_single_event_writers() -> None:
    # Given: an async sink that only implements single-event writes
    class RecordingAsyncSink(BaseAsyncControlEventSink):
        def __init__(self) -> None:
            self.seen_control_ids: list[int] = []

        async def write_event(self, event: ControlExecutionEvent) -> SinkResult:
            self.seen_control_ids.append(event.control_id)
            return SinkResult(accepted=1, dropped=event.control_id % 2)

    sink = RecordingAsyncSink()
    events = [_make_event(control_id=1), _make_event(control_id=2)]

    # When: the caller uses the async batch contract
    result = asyncio.run(sink.write_events(events))

    # Then: the base helper fans out to single-event writes and aggregates results
    assert sink.seen_control_ids == [1, 2]
    assert result == SinkResult(accepted=2, dropped=1)


def test_base_async_control_event_sink_single_event_delegates_to_batch_writer() -> None:
    # Given: an async sink that only implements batch writes
    class RecordingAsyncSink(BaseAsyncControlEventSink):
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        async def write_events(self, events: Sequence[ControlExecutionEvent]) -> SinkResult:
            self.batch_sizes.append(len(events))
            return SinkResult(accepted=len(events))

    sink = RecordingAsyncSink()
    event = _make_event(control_id=7)

    # When: the caller uses the async single-event contract
    result = asyncio.run(sink.write_event(event))

    # Then: the base helper delegates through the batch implementation
    assert sink.batch_sizes == [1]
    assert result == SinkResult(accepted=1, dropped=0)
