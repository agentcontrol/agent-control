"""
Typed data models for the ATR (Agent Threat Rules) evaluator.

These types preserve the ATR rule format's field / condition / scan-target
semantics through the evaluator pipeline. Per @lan17's 2026-04-26 review
on PR #170: ATR is an event/field-aware rule format, not a flattened regex
scanner. Each condition has an intended target field; the evaluator must
only run it against that field.

The wire format on disk (``rules.json``) carries the same structure so
the evaluator does not have to infer field semantics at load time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

# -----------------------------------------------------------------------------
# Field vocabulary — the surfaces an ATR rule can target
# -----------------------------------------------------------------------------
#
# Mirrors the upstream ATR `agent_source.type` + per-condition `field`
# vocabulary. Additive: unknown fields fall back to ``content``.
#
ATR_FIELDS: frozenset[str] = frozenset(
    {
        "content",
        "user_input",
        "agent_output",
        "tool_name",
        "tool_args",
        "tool_description",
        "tool_response",
        "agent_message",
        "skill_manifest",
    }
)


# Default field per ATR category — used when a rule does not declare an
# explicit per-condition field. Derived from the upstream ATR taxonomy at
# https://github.com/Agent-Threat-Rule/agent-threat-rules .
ATR_CATEGORY_DEFAULT_FIELD: Mapping[str, str] = {
    "prompt-injection": "user_input",
    "agent-manipulation": "content",
    "context-exfiltration": "agent_output",
    "tool-poisoning": "tool_description",
    "privilege-escalation": "tool_args",
    "skill-compromise": "skill_manifest",
    "data-poisoning": "content",
    "excessive-autonomy": "tool_name",
    "model-abuse": "content",
    "model-security": "content",
}


_SEVERITY_ORDER: Mapping[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_SEVERITY_CONFIDENCE: Mapping[str, float] = {
    "low": 0.6,
    "medium": 0.75,
    "high": 0.9,
    "critical": 0.99,
}


def severity_rank(level: str) -> int:
    """Map a severity string to its ordered rank; unknown values rank as 'low'."""
    return _SEVERITY_ORDER.get((level or "").lower(), 0)


def severity_confidence(level: str) -> float:
    """Default match confidence for a given severity, when the rule does not specify."""
    return _SEVERITY_CONFIDENCE.get((level or "").lower(), 0.5)


# -----------------------------------------------------------------------------
# ATREvent — typed view of an Agent Control input
# -----------------------------------------------------------------------------
@dataclass
class ATREvent:
    """
    Per-field view of an Agent Control selector input, adapted into the ATR
    rule format's field vocabulary.

    Empty strings are the conventional "no value" — rules whose target field
    is empty short-circuit without running their regex.

    Construct via :py:meth:`from_agent_control_data` so the mapping from
    Agent Control's raw data shape into ATR fields stays in one place.
    """

    content: str = ""
    user_input: str = ""
    agent_output: str = ""
    tool_name: str = ""
    tool_args: str = ""
    tool_description: str = ""
    tool_response: str = ""
    agent_message: str = ""
    skill_manifest: str = ""

    def get_field(self, field_name: str) -> str:
        """Return the value of a named field, or ``""`` if the field is unknown."""
        return getattr(self, field_name, "") if field_name in ATR_FIELDS else ""

    @classmethod
    def from_agent_control_data(cls, data: Any) -> "ATREvent":
        """
        Map an Agent Control selector output into a typed ATR event.

        Strategy:
          * ``None`` → empty event.
          * ``str`` → entire payload assumed to be ``content`` (the lowest-
            specificity field). Rules targeting other fields will not fire
            unless the caller maps the string into a structured shape first.
          * ``dict`` → keys whose name overlaps the ATR field vocabulary are
            used directly. ``"input"`` / ``"output"`` aliases map to
            ``user_input`` / ``agent_output`` respectively. Any remaining
            keys are JSON-serialised into ``content`` so detection rules
            with broad ``content`` patterns can still fire defensively.
          * Anything else → string-coerced into ``content``.

        Field-aware mapping is the entire purpose of this layer: a rule that
        targets ``tool_args`` will not fire on a benign ``user_input`` that
        happens to share text with the rule pattern.
        """
        if data is None:
            return cls()

        if isinstance(data, str):
            return cls(content=data)

        if isinstance(data, Mapping):
            kwargs: dict[str, str] = {}

            # Direct field assignment for known ATR fields.
            for field_name in ATR_FIELDS:
                value = data.get(field_name)
                if isinstance(value, str) and value:
                    kwargs[field_name] = value

            # Common aliases that Agent Control upstream may emit.
            if "input" in data and "user_input" not in kwargs:
                value = data.get("input")
                if isinstance(value, str):
                    kwargs["user_input"] = value
            if "output" in data and "agent_output" not in kwargs:
                value = data.get("output")
                if isinstance(value, str):
                    kwargs["agent_output"] = value
            if "text" in data and "content" not in kwargs:
                value = data.get("text")
                if isinstance(value, str):
                    kwargs["content"] = value
            if "message" in data and "content" not in kwargs:
                value = data.get("message")
                if isinstance(value, str):
                    kwargs["content"] = value

            # Catch-all: any remaining keys serialised into content for
            # broad-pattern rules. Avoid clobbering an explicit content if
            # one was already set.
            if "content" not in kwargs:
                leftover = {k: v for k, v in data.items() if k not in ATR_FIELDS and k not in ("input", "output", "text", "message")}
                if leftover:
                    import json as _json

                    try:
                        kwargs["content"] = _json.dumps(leftover, ensure_ascii=False, sort_keys=True, default=str)
                    except TypeError:
                        kwargs["content"] = str(leftover)

            return cls(**kwargs)

        # Non-string, non-mapping fallback.
        return cls(content=str(data))


# -----------------------------------------------------------------------------
# ATRCondition + ATRRule — typed rule models
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class ATRCondition:
    """
    A single ATR detection condition: regex pattern targeting one field.

    Compilation lives on the dataclass for caching — :py:meth:`compiled`
    yields the compiled pattern lazily and caches via ``object.__setattr__``
    on this frozen dataclass.
    """

    field: str
    operator: str
    value: str
    description: str = ""
    _compiled: Optional[re.Pattern[str]] = None

    def compiled(self, flags: int = re.IGNORECASE) -> Optional[re.Pattern[str]]:
        """Lazily compile and cache the regex. Returns ``None`` on regex error."""
        if self._compiled is not None:
            return self._compiled
        if self.operator != "regex":
            return None
        try:
            compiled = re.compile(self.value, flags)
        except re.error:
            return None
        object.__setattr__(self, "_compiled", compiled)
        return compiled


@dataclass(frozen=True)
class ATRRule:
    """Typed ATR rule with explicit field/condition semantics."""

    id: str
    title: str
    severity: str
    category: str
    conditions: tuple[ATRCondition, ...]
    condition_expr: str = "any"  # "any" | "all"
    description: str = ""
    scan_target: str = "runtime"  # "skill" | "mcp" | "runtime" | "both"

    def confidence(self) -> float:
        """Default confidence derived from severity if rule does not set one."""
        return severity_confidence(self.severity)


# -----------------------------------------------------------------------------
# RuleMatch — output of evaluating one rule
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class RuleMatch:
    """
    Result of a successful rule evaluation.

    ``matched_field`` records which event field the match came from — useful
    for audit logs and downstream policy decisions. ``redacted_excerpt`` is
    a safe-to-log summary derived from the raw match via
    :func:`agent_control_evaluator_atr.threat_rules.redact.redact_matched_value`;
    the raw matched text is intentionally never surfaced from this layer.
    """

    rule_id: str
    title: str
    severity: str
    category: str
    matched_field: str
    redacted_excerpt: str
    confidence: float
    pattern_description: str = ""
