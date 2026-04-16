"""Tests for shared control-action types, validation, and normalization."""

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
from agent_control_models.actions import normalize_action, validate_action
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# validate_action (strict, for API boundaries)
# ---------------------------------------------------------------------------


class TestValidateAction:
    """Tests for the strict validate_action used on public API boundaries."""

    @pytest.mark.parametrize("action", ["deny", "steer", "observe"])
    def test_accepts_canonical_actions(self, action: str) -> None:
        # Given: a canonical action name
        # When: validating the action
        result = validate_action(action)

        # Then: the same canonical value is returned
        assert result == action

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_rejects_legacy_actions(self, legacy: str) -> None:
        # Given: a legacy action name that is no longer accepted at API boundaries
        # When / Then: validation raises ValueError
        with pytest.raises(ValueError, match="Invalid action"):
            validate_action(legacy)

    def test_rejects_unknown_action(self) -> None:
        # Given: a completely unknown action name
        # When / Then: validation raises ValueError
        with pytest.raises(ValueError, match="Invalid action"):
            validate_action("block")


# ---------------------------------------------------------------------------
# normalize_action (lenient, for internal read paths)
# ---------------------------------------------------------------------------


class TestNormalizeAction:
    """Tests for the lenient normalize_action used on read paths."""

    @pytest.mark.parametrize("action", ["deny", "steer", "observe"])
    def test_passes_canonical_actions(self, action: str) -> None:
        # Given: a canonical action name
        # When: normalizing
        result = normalize_action(action)

        # Then: the same value is returned unchanged
        assert result == action

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_normalizes_legacy_to_observe(self, legacy: str) -> None:
        # Given: a legacy advisory action stored in a historical DB row
        # When: normalizing on the read path
        result = normalize_action(legacy)

        # Then: it maps to the canonical "observe" action
        assert result == "observe"

    def test_rejects_unknown_action(self) -> None:
        # Given: a completely unknown action name
        # When / Then: normalization raises ValueError even on the lenient path
        with pytest.raises(ValueError, match="Invalid action"):
            normalize_action("block")


# ---------------------------------------------------------------------------
# ControlAction (API input boundary — strict)
# ---------------------------------------------------------------------------


class TestControlActionValidation:
    """ControlAction.decision uses strict validation (rejects legacy values)."""

    @pytest.mark.parametrize("action", ["deny", "steer", "observe"])
    def test_accepts_canonical_actions(self, action: str) -> None:
        # Given: a control action payload with a canonical decision
        # When: validating via Pydantic
        ca = ControlAction.model_validate({"decision": action})

        # Then: the decision is accepted as-is
        assert ca.decision == action

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_rejects_legacy_actions(self, legacy: str) -> None:
        # Given: a control action payload using a legacy decision value
        # When / Then: Pydantic validation rejects it at the API boundary
        with pytest.raises(ValidationError, match="Invalid action"):
            ControlAction.model_validate({"decision": legacy})

    def test_rejects_unknown_action(self) -> None:
        # Given: a control action payload with an unknown decision
        # When / Then: Pydantic validation rejects it
        with pytest.raises(ValidationError, match="Invalid action"):
            ControlAction.model_validate({"decision": "block"})


# ---------------------------------------------------------------------------
# EventQueryRequest.actions (API input boundary — strict)
# ---------------------------------------------------------------------------


class TestEventQueryRequestValidation:
    """EventQueryRequest.actions uses strict validation."""

    def test_accepts_canonical_actions(self) -> None:
        # Given: a query filter with all three canonical action values
        # When: constructing the query request
        query = EventQueryRequest(actions=["deny", "steer", "observe"])

        # Then: all actions are accepted
        assert query.actions == ["deny", "steer", "observe"]

    def test_deduplicates_actions(self) -> None:
        # Given: a query filter with duplicate action values
        # When: constructing the query request
        query = EventQueryRequest(actions=["deny", "deny", "observe"])

        # Then: duplicates are removed while preserving order
        assert query.actions == ["deny", "observe"]

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_rejects_legacy_actions(self, legacy: str) -> None:
        # Given: a query filter using a legacy action value
        # When / Then: Pydantic validation rejects it at the API boundary
        with pytest.raises(ValidationError, match="Invalid action"):
            EventQueryRequest(actions=[legacy])

    def test_rejects_unknown_action(self) -> None:
        # Given: a query filter with an unknown action
        # When / Then: Pydantic validation rejects it
        with pytest.raises(ValidationError, match="Invalid action"):
            EventQueryRequest(actions=["block"])


# ---------------------------------------------------------------------------
# ControlMatch / ControlExecutionEvent (read path — lenient normalization)
# ---------------------------------------------------------------------------


class TestReadPathNormalization:
    """Internal read-path models normalize legacy values from DB rows."""

    @pytest.mark.parametrize("legacy,expected", [
        ("allow", "observe"),
        ("warn", "observe"),
        ("log", "observe"),
        ("observe", "observe"),
        ("deny", "deny"),
        ("steer", "steer"),
    ])
    def test_control_match_normalizes_legacy(self, legacy: str, expected: str) -> None:
        # Given: a ControlMatch deserialized from a DB row with a legacy action
        # When: constructing the model
        match = ControlMatch(
            control_id=1,
            control_name="test",
            action=legacy,
            result=EvaluatorResult(matched=True, confidence=0.9),
        )

        # Then: the action is normalized to the canonical value
        assert match.action == expected

    @pytest.mark.parametrize("legacy,expected", [
        ("allow", "observe"),
        ("warn", "observe"),
        ("log", "observe"),
        ("observe", "observe"),
        ("deny", "deny"),
        ("steer", "steer"),
    ])
    def test_control_execution_event_normalizes_legacy(
        self, legacy: str, expected: str
    ) -> None:
        # Given: a ControlExecutionEvent deserialized from a historical event row
        # When: constructing the model
        event = ControlExecutionEvent(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
            agent_name="test-agent",
            control_id=1,
            control_name="test",
            check_stage="pre",
            applies_to="llm_call",
            action=legacy,
            matched=True,
            confidence=0.9,
        )

        # Then: the action is normalized to the canonical value
        assert event.action == expected

    def test_control_match_rejects_unknown(self) -> None:
        # Given: a ControlMatch with a completely unknown action
        # When / Then: validation rejects it even on the lenient read path
        with pytest.raises(ValidationError, match="Invalid action"):
            ControlMatch(
                control_id=1,
                control_name="test",
                action="block",
                result=EvaluatorResult(matched=True, confidence=0.9),
            )


# ---------------------------------------------------------------------------
# expand_action_filter (internal query expansion)
# ---------------------------------------------------------------------------


class TestExpandActionFilter:
    """expand_action_filter expands canonical actions for SQL queries against historical data."""

    def test_observe_expands_to_include_legacy(self) -> None:
        # Given: a canonical "observe" filter
        # When: expanding for SQL WHERE clause against historical events
        expanded = expand_action_filter(["observe"])

        # Then: it includes all legacy advisory action values stored in old rows
        assert expanded == ["observe", "allow", "warn", "log"]

    def test_deny_and_steer_do_not_expand(self) -> None:
        # Given: deny and steer filters (no legacy aliases)
        # When: expanding
        # Then: they map only to themselves
        assert expand_action_filter(["deny"]) == ["deny"]
        assert expand_action_filter(["steer"]) == ["steer"]

    def test_full_expansion(self) -> None:
        # Given: all three canonical actions
        # When: expanding
        expanded = expand_action_filter(["deny", "steer", "observe"])

        # Then: deny and steer are unchanged, observe expands to include legacy
        assert expanded == ["deny", "steer", "observe", "allow", "warn", "log"]
