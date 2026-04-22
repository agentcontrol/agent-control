"""Configuration for the detect-secrets evaluator."""

from __future__ import annotations

from typing import Literal

import re2
from agent_control_evaluators import EvaluatorConfig
from detect_secrets_async import get_runtime_info
from pydantic import Field, field_validator

DEFAULT_TIMEOUT_MS = 10_000
DEFAULT_MAX_BYTES = 1_048_576


class DetectSecretsEvaluatorConfig(EvaluatorConfig):
    """Typed configuration for the detect-secrets evaluator."""

    timeout_ms: int = Field(
        default=DEFAULT_TIMEOUT_MS,
        gt=0,
        description="End-to-end timeout in milliseconds for queue wait and scan execution.",
    )
    on_error: Literal["allow", "deny"] = Field(
        default="allow",
        description="Whether evaluator failures should fail open or fail closed.",
    )
    max_bytes: int = Field(
        default=DEFAULT_MAX_BYTES,
        gt=0,
        description="Maximum UTF-8 payload size after normalization and line filtering.",
    )
    enabled_plugins: list[str] | None = Field(
        default=None,
        description="Optional explicit upstream detect-secrets plugin class names.",
    )
    exclude_lines_regex: list[str] = Field(
        default_factory=list,
        description="RE2 patterns for lines that should be blanked before scanning.",
    )

    @field_validator("enabled_plugins")
    @classmethod
    def validate_enabled_plugins(cls, value: list[str] | None) -> list[str] | None:
        """Validate explicit upstream plugin names against detect-secrets-async introspection."""
        if value is None:
            return None

        available = set(get_runtime_info().available_plugin_names)
        normalized: list[str] = []
        seen: set[str] = set()

        for plugin_name in value:
            candidate = plugin_name.strip()
            if not candidate:
                raise ValueError("enabled_plugins entries must be non-empty")
            if candidate not in available:
                raise ValueError(f"Unknown detect-secrets plugin: {candidate}")
            if candidate not in seen:
                normalized.append(candidate)
                seen.add(candidate)

        return normalized

    @field_validator("exclude_lines_regex")
    @classmethod
    def validate_exclude_lines_regex(cls, value: list[str]) -> list[str]:
        """Validate each configured exclude pattern as a RE2 regex."""
        for pattern in value:
            if pattern == "":
                raise ValueError("exclude_lines_regex entries must be non-empty")
            try:
                re2.compile(pattern)
            except re2.error as exc:
                raise ValueError(f"Invalid RE2 pattern '{pattern}': {exc}") from exc
        return value
