from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .config import ATRConfig

_SEVERITY_ORDER: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

_SEVERITY_CONFIDENCE: dict[str, float] = {
    "low": 0.6,
    "medium": 0.75,
    "high": 0.9,
    "critical": 0.99,
}

_RULES_PATH = Path(__file__).parent / "rules.json"


def _load_rules(path: Path) -> list[dict[str, Any]]:
    """Load ATR rules from the bundled JSON file."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected list of rules, got {type(data).__name__}")
    return data


def _coerce_to_string(data: Any) -> str:
    """Convert arbitrary input data to a string for pattern matching."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        # Try common content fields first
        for key in ("content", "input", "output", "text", "message"):
            if key in data and data[key] is not None:
                return str(data[key])
        # Fall back to JSON serialization
        try:
            return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return str(data)
    if isinstance(data, (int, float, bool)):
        return str(data)
    if isinstance(data, (list, tuple)):
        try:
            return json.dumps(data, ensure_ascii=False, default=str)
        except TypeError:
            return str(data)
    return str(data)


@register_evaluator
class ATREvaluator(Evaluator[ATRConfig]):
    """ATR (Agent Threat Rules) evaluator.

    Regex-based AI agent threat detection using community rules.
    No external API calls or keys required.
    """

    metadata = EvaluatorMetadata(
        name="atr.threat_rules",
        version="0.1.0",
        description="Regex-based AI agent threat detection using ATR community rules",
        requires_api_key=False,
        timeout_ms=5000,
    )

    config_model = ATRConfig

    @classmethod
    def is_available(cls) -> bool:
        """Always available -- no optional dependencies."""
        return _RULES_PATH.exists()

    def __init__(self, config: ATRConfig) -> None:
        self.config = config

        # Load and filter rules eagerly
        raw_rules = _load_rules(_RULES_PATH)

        min_level = _SEVERITY_ORDER.get(self.config.min_severity, 1)
        allowed_categories = set(self.config.categories) if self.config.categories else None

        self._compiled_rules: list[dict[str, Any]] = []
        for rule in raw_rules:
            severity = rule.get("severity", "medium").lower()
            if _SEVERITY_ORDER.get(severity, 0) < min_level:
                continue

            category = rule.get("category", "")
            if allowed_categories and category not in allowed_categories:
                continue

            compiled_patterns: list[dict[str, Any]] = []
            for p in rule.get("patterns", []):
                try:
                    compiled_patterns.append({
                        "regex": re.compile(p["pattern"], re.IGNORECASE),
                        "description": p.get("description", ""),
                    })
                except re.error:
                    # Skip invalid patterns rather than failing entirely
                    continue

            if compiled_patterns:
                self._compiled_rules.append({
                    "id": rule.get("id", "unknown"),
                    "title": rule.get("title", ""),
                    "severity": severity,
                    "category": category,
                    "confidence": _SEVERITY_CONFIDENCE.get(severity, 0.75),
                    "patterns": compiled_patterns,
                })

    async def evaluate(self, data: Any) -> EvaluatorResult:  # noqa: D401
        """Evaluate input data against ATR threat rules."""
        if data is None:
            return EvaluatorResult(matched=False, confidence=1.0, message="No data")

        try:
            text = _coerce_to_string(data)
        except Exception as e:  # noqa: BLE001
            return self._error_result(f"Failed to coerce input: {e}")

        if not text:
            return EvaluatorResult(matched=False, confidence=1.0, message="Empty input")

        try:
            return self._match_rules(text)
        except Exception as e:  # noqa: BLE001
            return self._error_result(f"ATR evaluation error: {e}")

    def _match_rules(self, text: str) -> EvaluatorResult:
        """Run all compiled rules against the text and return the first match."""
        for rule in self._compiled_rules:
            for pattern_entry in rule["patterns"]:
                regex: re.Pattern[str] = pattern_entry["regex"]
                match = regex.search(text)
                if match:
                    matched = self.config.block_on_match
                    return EvaluatorResult(
                        matched=matched,
                        confidence=rule["confidence"],
                        message=(
                            f"ATR threat detected: {rule['title']} "
                            f"[{rule['id']}] (severity: {rule['severity']})"
                        ),
                        metadata={
                            "rule_id": rule["id"],
                            "title": rule["title"],
                            "severity": rule["severity"],
                            "category": rule["category"],
                            "matched_text": match.group()[:200],
                            "pattern_description": pattern_entry["description"],
                        },
                    )

        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="No ATR threats detected",
        )

    def _error_result(self, error_detail: str) -> EvaluatorResult:
        """Build an error result respecting the on_error policy."""
        fallback = self.config.on_error
        if fallback == "deny":
            # fail-closed: matched=True, error=None (to satisfy model validator)
            return EvaluatorResult(
                matched=True,
                confidence=0.0,
                message=f"ATR evaluation error (fail-closed): {error_detail}",
                metadata={"error": error_detail, "fallback_action": "deny"},
            )
        # fail-open: matched=False, error set
        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"ATR evaluation error: {error_detail}",
            metadata={"error": error_detail, "fallback_action": "allow"},
            error=error_detail,
        )

    async def aclose(self) -> None:
        """No resources to clean up."""
