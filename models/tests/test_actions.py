"""Tests for shared control-action compatibility behavior."""

from __future__ import annotations

import pytest
from agent_control_models import (
    ControlAction,
    ControlExecutionEvent,
    ControlMatch,
    EventQueryRequest,
    EvaluatorResult,
    expand_action_filter,
)
from pydantic import ValidationError


def test_event_query_actions_normalize_and_expand_for_legacy_observability() -> None:
    # Given: a query that mixes canonical and legacy advisory action names
    query = EventQueryRequest(
        actions=["warn", "observe", "deny", "log", "deny", "steer", "allow", "steer"]
    )

    # When: expanding the normalized public action filter for stored event rows
    expanded = expand_action_filter(query.actions or [])

    # Then: the public filter is canonicalized, deduped, and expanded for legacy rows
    assert query.actions == ["observe", "deny", "steer"]
    assert expanded == ["observe", "allow", "warn", "log", "deny", "steer"]


def test_invalid_action_is_rejected_across_public_model_boundaries() -> None:
    # Given: the same invalid action at each public model boundary
    invalid_action = "block"
    invalid_builders = [
        lambda: ControlAction.model_validate({"decision": invalid_action}),
        lambda: ControlMatch(
            control_id=123,
            control_name="pii-check",
            action=invalid_action,
            result=EvaluatorResult(matched=True, confidence=0.9),
        ),
        lambda: ControlExecutionEvent(
            trace_id="trace-123",
            span_id="span-123",
            agent_name="test-agent",
            control_id=123,
            control_name="pii-check",
            check_stage="pre",
            applies_to="llm_call",
            action=invalid_action,
            matched=True,
            confidence=0.9,
        ),
        lambda: EventQueryRequest(actions=[invalid_action]),
    ]

    for build_invalid_model in invalid_builders:
        # When / Then: validation fails before the invalid action can enter the system
        with pytest.raises(ValidationError, match="Invalid action"):
            build_invalid_model()
