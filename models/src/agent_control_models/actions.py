"""Shared control-action types and normalization helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

type ActionDecision = Literal["deny", "steer", "observe"]

_CANONICAL_ACTIONS = frozenset({"deny", "steer", "observe"})
_OBSERVE_ACTION_ALIASES = frozenset({"allow", "observe", "warn", "log"})
_ACTION_QUERY_EXPANSION: dict[ActionDecision, tuple[str, ...]] = {
    "deny": ("deny",),
    "steer": ("steer",),
    "observe": ("observe", "allow", "warn", "log"),
}


def validate_action(action: str) -> ActionDecision:
    """Validate that *action* is one of the canonical action values.

    Use this on public API boundaries (control create/update, query filters)
    where legacy values should be rejected.
    """
    if action in _CANONICAL_ACTIONS:
        return cast(ActionDecision, action)
    raise ValueError(
        f"Invalid action {action!r}. Must be one of: deny, steer, observe."
    )


def validate_action_list(actions: Sequence[str]) -> list[ActionDecision]:
    """Validate a list of actions, preserving order and removing duplicates."""
    validated: list[ActionDecision] = []
    seen: set[ActionDecision] = set()
    for action in actions:
        canonical = validate_action(action)
        if canonical in seen:
            continue
        seen.add(canonical)
        validated.append(canonical)
    return validated


def normalize_action(action: str) -> ActionDecision:
    """Normalize a stored or legacy action name to the canonical action.

    Use this on internal read paths (deserializing DB rows, server responses)
    where historical data may contain legacy values.
    """
    if action in _OBSERVE_ACTION_ALIASES:
        return "observe"
    if action in ("deny", "steer"):
        return cast(ActionDecision, action)
    raise ValueError(
        f"Invalid action {action!r}. Expected one of: deny, steer, observe."
    )


def normalize_action_list(actions: Sequence[str]) -> list[ActionDecision]:
    """Normalize a list of actions while preserving order and removing duplicates."""
    normalized: list[ActionDecision] = []
    seen: set[ActionDecision] = set()
    for action in actions:
        canonical = normalize_action(action)
        if canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(canonical)
    return normalized


def expand_action_filter(actions: Sequence[ActionDecision]) -> list[str]:
    """Expand canonical action filters to include legacy stored event values."""
    expanded: list[str] = []
    seen: set[str] = set()
    for action in actions:
        for candidate in _ACTION_QUERY_EXPANSION[action]:
            if candidate in seen:
                continue
            seen.add(candidate)
            expanded.append(candidate)
    return expanded
