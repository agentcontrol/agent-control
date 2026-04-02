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
        assert validate_action(action) == action

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_rejects_legacy_actions(self, legacy: str) -> None:
        with pytest.raises(ValueError, match="Invalid action"):
            validate_action(legacy)

    def test_rejects_unknown_action(self) -> None:
        with pytest.raises(ValueError, match="Invalid action"):
            validate_action("block")


# ---------------------------------------------------------------------------
# normalize_action (lenient, for internal read paths)
# ---------------------------------------------------------------------------


class TestNormalizeAction:
    """Tests for the lenient normalize_action used on read paths."""

    @pytest.mark.parametrize("action", ["deny", "steer", "observe"])
    def test_passes_canonical_actions(self, action: str) -> None:
        assert normalize_action(action) == action

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_normalizes_legacy_to_observe(self, legacy: str) -> None:
        assert normalize_action(legacy) == "observe"

    def test_rejects_unknown_action(self) -> None:
        with pytest.raises(ValueError, match="Invalid action"):
            normalize_action("block")


# ---------------------------------------------------------------------------
# ControlAction (API input boundary — strict)
# ---------------------------------------------------------------------------


class TestControlActionValidation:
    """ControlAction.decision uses strict validation (rejects legacy values)."""

    @pytest.mark.parametrize("action", ["deny", "steer", "observe"])
    def test_accepts_canonical_actions(self, action: str) -> None:
        ca = ControlAction.model_validate({"decision": action})
        assert ca.decision == action

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_rejects_legacy_actions(self, legacy: str) -> None:
        with pytest.raises(ValidationError, match="Invalid action"):
            ControlAction.model_validate({"decision": legacy})

    def test_rejects_unknown_action(self) -> None:
        with pytest.raises(ValidationError, match="Invalid action"):
            ControlAction.model_validate({"decision": "block"})


# ---------------------------------------------------------------------------
# EventQueryRequest.actions (API input boundary — strict)
# ---------------------------------------------------------------------------


class TestEventQueryRequestValidation:
    """EventQueryRequest.actions uses strict validation."""

    def test_accepts_canonical_actions(self) -> None:
        query = EventQueryRequest(actions=["deny", "steer", "observe"])
        assert query.actions == ["deny", "steer", "observe"]

    def test_deduplicates_actions(self) -> None:
        query = EventQueryRequest(actions=["deny", "deny", "observe"])
        assert query.actions == ["deny", "observe"]

    @pytest.mark.parametrize("legacy", ["allow", "warn", "log"])
    def test_rejects_legacy_actions(self, legacy: str) -> None:
        with pytest.raises(ValidationError, match="Invalid action"):
            EventQueryRequest(actions=[legacy])

    def test_rejects_unknown_action(self) -> None:
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
        match = ControlMatch(
            control_id=1,
            control_name="test",
            action=legacy,
            result=EvaluatorResult(matched=True, confidence=0.9),
        )
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
        assert event.action == expected

    def test_control_match_rejects_unknown(self) -> None:
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
        expanded = expand_action_filter(["observe"])
        assert expanded == ["observe", "allow", "warn", "log"]

    def test_deny_and_steer_do_not_expand(self) -> None:
        assert expand_action_filter(["deny"]) == ["deny"]
        assert expand_action_filter(["steer"]) == ["steer"]

    def test_full_expansion(self) -> None:
        expanded = expand_action_filter(["deny", "steer", "observe"])
        assert expanded == ["deny", "steer", "observe", "allow", "warn", "log"]
