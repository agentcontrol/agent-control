"""
ATR (Agent Threat Rules) evaluator for Agent Control.

Rewritten per @lan17's 2026-04-26 PR #170 architectural review:

  * Preserves ATR field / scan-target / condition logic in typed rule
    models (see :mod:`.models`).
  * Adapts Agent Control selector output into a typed :class:`ATREvent`
    so each condition only runs against its intended field, instead of
    matching every regex against a flattened string.
  * Bounds per-rule regex evaluation time with a configurable budget so a
    catastrophic-backtracking pattern cannot block the whole evaluator
    pipeline.
  * Never surfaces raw matched values: every match is run through
    :func:`.redact.redact_matched_value` before it lands in
    ``EvaluatorResult.metadata``.

The on-disk rule file (``rules.json``) carries per-condition ``field``,
``operator``, ``value`` and the rule-level ``condition`` expression
(``any`` / ``all``). Legacy rules that only have a flat ``patterns`` list
are auto-upgraded at load time: each pattern becomes one condition
targeting the category's default field per
:data:`.models.ATR_CATEGORY_DEFAULT_FIELD`. This keeps the existing
``rules.json`` working without a wholesale regeneration.
"""
from __future__ import annotations

import json
import logging
import signal
import time
from pathlib import Path
from typing import Any, Optional

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .config import ATRConfig
from .models import (
    ATR_CATEGORY_DEFAULT_FIELD,
    ATR_FIELDS,
    ATRCondition,
    ATREvent,
    ATRRule,
    RuleMatch,
    severity_rank,
)
from .redact import redact_matched_value

logger = logging.getLogger(__name__)


_RULES_PATH = Path(__file__).parent / "rules.json"


# -----------------------------------------------------------------------------
# Rule loader
# -----------------------------------------------------------------------------
def _normalise_rule(raw: dict[str, Any]) -> ATRRule | None:
    """
    Build a typed :class:`ATRRule` from a raw dict.

    Two on-disk shapes are accepted:

    1. Modern ``conditions`` array form — already field-aware. Each entry has
       ``field`` / ``operator`` / ``value`` (matches upstream ATR YAML
       semantics).
    2. Legacy ``patterns`` array form — flat regex list. Each pattern is
       upgraded to a condition targeting the category's default field, so
       every legacy rule still has explicit field semantics in memory.
    """
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        return None

    category = (raw.get("category") or "").lower()
    severity = (raw.get("severity") or "medium").lower()
    title = raw.get("title") or rule_id
    description = raw.get("description") or ""
    condition_expr = (raw.get("condition") or "any").lower()
    if condition_expr not in {"any", "all", "or", "and"}:
        condition_expr = "any"

    scan_target = raw.get("scan_target") or "runtime"

    conditions: list[ATRCondition] = []

    raw_conds = raw.get("conditions")
    if isinstance(raw_conds, list) and raw_conds:
        for entry in raw_conds:
            if not isinstance(entry, dict):
                continue
            field_name = (entry.get("field") or "content").lower()
            if field_name not in ATR_FIELDS:
                field_name = "content"
            operator = (entry.get("operator") or "regex").lower()
            value = entry.get("value")
            if not isinstance(value, str) or not value:
                continue
            conditions.append(
                ATRCondition(
                    field=field_name,
                    operator=operator,
                    value=value,
                    description=entry.get("description") or "",
                )
            )

    if not conditions:
        default_field = ATR_CATEGORY_DEFAULT_FIELD.get(category, "content")
        for entry in raw.get("patterns") or []:
            if not isinstance(entry, dict):
                continue
            value = entry.get("pattern")
            if not isinstance(value, str) or not value:
                continue
            conditions.append(
                ATRCondition(
                    field=default_field,
                    operator="regex",
                    value=value,
                    description=entry.get("description") or "",
                )
            )

    if not conditions:
        return None

    return ATRRule(
        id=rule_id,
        title=title,
        severity=severity,
        category=category,
        conditions=tuple(conditions),
        condition_expr=condition_expr,
        description=description,
        scan_target=scan_target,
    )


def _load_rules(path: Path = _RULES_PATH) -> list[ATRRule]:
    """Load the bundled rule file and normalise every entry."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected list of rules in {path}, got {type(data).__name__}")
    return [r for r in (_normalise_rule(raw) for raw in data) if r is not None]


# -----------------------------------------------------------------------------
# Regex runtime budget (per condition)
# -----------------------------------------------------------------------------
class _BudgetExceeded(Exception):
    """Raised internally when a condition's regex evaluation exceeds the budget."""


def _is_main_thread() -> bool:
    try:
        import threading

        return threading.current_thread() is threading.main_thread()
    except Exception:
        return False


def _wall_clock_search(condition: ATRCondition, value: str, budget_ms: int) -> Optional[str]:
    """
    Run ``condition`` against ``value`` and return the matched substring,
    or ``None`` if no match (or if the budget was exceeded).

    ``signal.SIGALRM``-based budget is used on POSIX main thread. Worker
    threads / Windows fall back to a soft wall-clock check.
    """
    compiled = condition.compiled()
    if compiled is None:
        return None

    has_sigalrm = hasattr(signal, "SIGALRM") and _is_main_thread()
    if not has_sigalrm:
        start = time.monotonic()
        m = compiled.search(value)
        elapsed_ms = (time.monotonic() - start) * 1000.0
        if elapsed_ms > budget_ms * 4:
            logger.warning(
                "atr.threat_rules condition exceeded soft budget %.1fms > %dms (no SIGALRM)",
                elapsed_ms,
                budget_ms,
            )
        return m.group(0) if m else None

    def _alarm_handler(signum: int, frame: object) -> None:  # noqa: ARG001
        raise _BudgetExceeded()

    prev_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    try:
        signal.setitimer(signal.ITIMER_REAL, budget_ms / 1000.0)
        try:
            m = compiled.search(value)
        except _BudgetExceeded:
            logger.warning(
                "atr.threat_rules condition exceeded budget %dms; skipping condition",
                budget_ms,
            )
            return None
        return m.group(0) if m else None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prev_handler)


# -----------------------------------------------------------------------------
# Rule evaluation
# -----------------------------------------------------------------------------
def _evaluate_rule(rule: ATRRule, event: ATREvent, condition_budget_ms: int) -> RuleMatch | None:
    """
    Run one rule's conditions against the typed event with per-field dispatch.

    Returns a :class:`RuleMatch` if the rule's condition expression is
    satisfied, or ``None`` otherwise. Raw matched substring is never
    returned — it is redacted before being placed in the match object.
    """
    matched: list[tuple[ATRCondition, str]] = []
    is_any = rule.condition_expr in {"any", "or"}

    for condition in rule.conditions:
        field_value = event.get_field(condition.field)
        if not field_value:
            continue
        match_text = _wall_clock_search(condition, field_value, condition_budget_ms)
        if match_text is None:
            continue
        matched.append((condition, match_text))
        if is_any:
            break

    if not matched:
        return None
    if not is_any and len(matched) < len(rule.conditions):
        return None

    primary_condition, primary_match = matched[0]
    return RuleMatch(
        rule_id=rule.id,
        title=rule.title,
        severity=rule.severity,
        category=rule.category,
        matched_field=primary_condition.field,
        redacted_excerpt=redact_matched_value(primary_match),
        confidence=rule.confidence(),
        pattern_description=primary_condition.description,
    )


# -----------------------------------------------------------------------------
# Evaluator
# -----------------------------------------------------------------------------
@register_evaluator
class ATREvaluator(Evaluator[ATRConfig]):
    """ATR field-aware evaluator. No API keys, no external calls."""

    metadata = EvaluatorMetadata(
        name="atr.threat_rules",
        version="0.2.0",
        description="Field-aware regex detection for AI-agent threats using the open ATR ruleset",
        requires_api_key=False,
        timeout_ms=5000,
    )

    config_model = ATRConfig

    _DEFAULT_CONDITION_BUDGET_MS = 50

    @classmethod
    def is_available(cls) -> bool:
        return _RULES_PATH.exists()

    def __init__(self, config: ATRConfig) -> None:
        super().__init__(config)
        self.config = config
        self._condition_budget_ms = getattr(
            config, "condition_budget_ms", self._DEFAULT_CONDITION_BUDGET_MS
        )

        raw_rules = _load_rules(_RULES_PATH)

        min_rank = severity_rank(self.config.min_severity)
        allowed_categories = set(self.config.categories) if self.config.categories else None

        rules: list[ATRRule] = []
        for rule in raw_rules:
            if severity_rank(rule.severity) < min_rank:
                continue
            if allowed_categories and rule.category not in allowed_categories:
                continue
            rules.append(rule)
        self._rules: tuple[ATRRule, ...] = tuple(rules)

    @property
    def rules(self) -> tuple[ATRRule, ...]:
        return self._rules

    async def evaluate(self, data: Any) -> EvaluatorResult:  # noqa: D401
        if data is None:
            return EvaluatorResult(matched=False, confidence=1.0, message="No data")

        try:
            event = ATREvent.from_agent_control_data(data)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(f"Failed to adapt input into ATR event: {exc}")

        if not any(event.get_field(name) for name in ATR_FIELDS):
            return EvaluatorResult(matched=False, confidence=1.0, message="Empty event")

        try:
            return self._match_rules(event)
        except Exception as exc:  # noqa: BLE001
            return self._error_result(f"ATR evaluation error: {exc}")

    def _match_rules(self, event: ATREvent) -> EvaluatorResult:
        findings: list[dict[str, Any]] = []
        max_confidence = 0.0

        for rule in self._rules:
            match = _evaluate_rule(rule, event, self._condition_budget_ms)
            if match is None:
                continue
            findings.append(
                {
                    "rule_id": match.rule_id,
                    "title": match.title,
                    "severity": match.severity,
                    "category": match.category,
                    "matched_field": match.matched_field,
                    "redacted_excerpt": match.redacted_excerpt,
                    "pattern_description": match.pattern_description,
                }
            )
            if match.confidence > max_confidence:
                max_confidence = match.confidence

        if not findings:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="ATR: No threats detected",
            )

        primary = findings[0]
        return EvaluatorResult(
            matched=bool(self.config.block_on_match),
            confidence=max_confidence,
            message=f"ATR: {len(findings)} threat(s) detected",
            metadata={
                "findings": findings,
                "count": len(findings),
                "max_severity": primary["severity"],
                # Backwards-compatible single-finding mirrors. NB:
                # ``matched_text`` from v0.1 is intentionally REMOVED and
                # replaced with ``redacted_excerpt`` to prevent the rule
                # from re-exposing the secret it fires on.
                "rule_id": primary["rule_id"],
                "title": primary["title"],
                "severity": primary["severity"],
                "category": primary["category"],
                "matched_field": primary["matched_field"],
                "redacted_excerpt": primary["redacted_excerpt"],
                "pattern_description": primary["pattern_description"],
            },
        )

    def _error_result(self, error_detail: str) -> EvaluatorResult:
        fallback = self.config.on_error
        if fallback == "deny":
            return EvaluatorResult(
                matched=True,
                confidence=0.0,
                message=f"ATR evaluation error (fail-closed): {error_detail}",
                metadata={"error": error_detail, "fallback_action": "deny"},
            )
        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"ATR evaluation error: {error_detail}",
            metadata={"error": error_detail, "fallback_action": "allow"},
            error=error_detail,
        )

    async def aclose(self) -> None:
        """No resources to clean up."""
