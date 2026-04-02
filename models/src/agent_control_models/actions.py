"""Shared control-action types and normalization helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast

type ActionDecision = Literal["deny", "steer", "observe"]

_OBSERVE_ACTION_ALIASES = frozenset({"allow", "observe", "warn", "log"})
_ACTION_QUERY_EXPANSION: dict[ActionDecision, tuple[str, ...]] = {
    "deny": ("deny",),
    "steer": ("steer",),
    "observe": ("observe", "allow", "warn", "log"),
}


def normalize_action(action: str) -> ActionDecision:
    """Normalize a public or legacy action name to the canonical action."""
    if action in _OBSERVE_ACTION_ALIASES:
        return "observe"
    if action in ("deny", "steer"):
        return cast(ActionDecision, action)
    raise ValueError(
        "Invalid action. Expected one of: deny, steer, observe "
        "(legacy aliases allow/warn/log are also accepted temporarily)."
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
