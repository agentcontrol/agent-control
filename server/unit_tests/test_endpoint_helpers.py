"""Unit tests for endpoint helpers that don't require the DB test fixture."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_control_models import (
    ControlDefinition,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
    EvaluatorResult,
)
from agent_control_server.endpoints.agents import (
    _find_referencing_controls_for_removed_evaluators,
)
from agent_control_server.endpoints.evaluation import (
    ControlAdapter,
    _emit_observability_events,
)


def test_find_referencing_controls_dedupes_composite_matches() -> None:
    # Given: two leaves in the same control reference the same evaluator
    controls = [
        SimpleNamespace(
            name="composite-ctrl",
            control=ControlDefinition(
                execution="server",
                condition={
                    "and": [
                        {
                            "selector": {"path": "input"},
                            "evaluator": {"name": "agent-123456:custom", "config": {}},
                        },
                        {
                            "selector": {"path": "output"},
                            "evaluator": {"name": "agent-123456:custom", "config": {}},
                        },
                    ]
                },
                action={"decision": "deny"},
            ),
        )
    ]

    # When: scanning for references to the evaluator being removed
    referencing_controls = _find_referencing_controls_for_removed_evaluators(
        controls,
        "agent-123456",
        {"custom"},
    )

    # Then: the same control/evaluator pair is reported only once
    assert referencing_controls == [("composite-ctrl", "custom")]


@pytest.mark.asyncio
async def test_emit_observability_events_uses_representative_leaf_for_composites() -> None:
    # Given: a composite control with two leaves and existing condition metadata
    control = ControlAdapter(
        id=1,
        name="composite-ctrl",
        control=ControlDefinition(
            execution="server",
            condition={
                "and": [
                    {
                        "selector": {"path": "input"},
                        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    },
                    {
                        "selector": {"path": "output"},
                        "evaluator": {"name": "list", "config": {"values": ["done"]}},
                    },
                ]
            },
            action={"decision": "allow"},
        ),
    )
    response = EvaluationResponse(
        is_safe=True,
        confidence=1.0,
        non_matches=[
            ControlMatch(
                control_id=1,
                control_name="composite-ctrl",
                action="allow",
                result=EvaluatorResult(
                    matched=False,
                    confidence=0.9,
                    metadata={"condition_trace": {"kind": "and"}},
                ),
            )
        ],
    )
    request = EvaluationRequest(
        agent_name="agent-000000000001",
        step={"type": "llm", "name": "test-step", "input": "hello"},
        stage="pre",
    )
    ingestor = SimpleNamespace(
        ingest=AsyncMock(return_value=SimpleNamespace(dropped=0, processed=1))
    )

    # When: emitting observability events
    await _emit_observability_events(
        response=response,
        request=request,
        trace_id="trace123",
        span_id="span456",
        agent_name="agent-000000000001",
        applies_to="llm_call",
        control_lookup={1: control},
        total_duration_ms=5.0,
        ingestor=ingestor,
    )

    # Then: the first leaf becomes the event identity and full context is retained
    events = ingestor.ingest.await_args.args[0]
    assert len(events) == 1
    event = events[0]
    assert event.evaluator_name == "regex"
    assert event.selector_path == "input"
    assert event.metadata["condition_trace"] == {"kind": "and"}
    assert event.metadata["primary_evaluator"] == "regex"
    assert event.metadata["primary_selector_path"] == "input"
    assert event.metadata["leaf_count"] == 2
    assert event.metadata["all_evaluators"] == ["regex", "list"]
    assert event.metadata["all_selector_paths"] == ["input", "output"]
