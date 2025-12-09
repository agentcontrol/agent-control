"""Control definition models for agent protection."""

from typing import Any, Literal, Self

import re2
from pydantic import Field, field_validator, model_validator

from .base import BaseModel


class ControlSelector(BaseModel):
    """Selects data from payload using a path."""

    path: str = Field(
        ...,
        description=(
            "Path to data using dot notation. "
            "Examples: 'input', 'output', 'arguments.query', 'context.user_id', 'tool_name', '*'"
        ),
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate path and warn about common typos."""
        if not v:
            raise ValueError("Path cannot be empty")

        # Valid root fields
        valid_roots = {"input", "output", "arguments", "tool_name", "context", "*"}
        root = v.split(".")[0]

        if root not in valid_roots:
            raise ValueError(
                f"Invalid path root '{root}'. "
                f"Must be one of: {', '.join(sorted(valid_roots))}"
            )

        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"path": "output"},
                {"path": "arguments.query"},
                {"path": "context.user_id"},
                {"path": "input"},
                {"path": "*"},
            ]
        }
    }


# =============================================================================
# Plugin Config Models (used by plugin implementations)
# =============================================================================


class RegexConfig(BaseModel):
    """Configuration for regex plugin."""

    pattern: str = Field(..., description="Regular expression pattern")
    flags: list[str] | None = Field(default=None, description="Regex flags")

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """Validate that the pattern is a valid regex."""
        try:
            re2.compile(v)
        except re2.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")
        return v


class ListConfig(BaseModel):
    """Configuration for list plugin."""

    values: list[str | int | float] = Field(
        ..., description="List of values to match against"
    )
    logic: Literal["any", "all"] = Field(
        "any", description="Matching logic: any item matches vs all items match"
    )
    match_on: Literal["match", "no_match"] = Field(
        "match", description="Trigger rule on match or no match"
    )
    match_mode: Literal["exact", "contains"] = Field(
        "exact",
        description="'exact' for full string match, 'contains' for keyword/substring match",
    )
    case_sensitive: bool = Field(False, description="Whether matching is case sensitive")


# =============================================================================
# Unified Evaluator Config (used in API)
# =============================================================================


class EvaluatorConfig(BaseModel):
    """Evaluator configuration. See GET /plugins for available plugins and schemas.

    All evaluators are plugins - built-in (regex, list) or external (galileo-luna2).
    """

    plugin: str = Field(
        ...,
        description="Plugin name",
        examples=["regex", "list", "galileo-luna2", "custom-code"],
    )
    config: dict[str, Any] = Field(
        ...,
        description="Plugin-specific configuration",
        examples=[
            {"pattern": r"\d{3}-\d{2}-\d{4}"},
            {"values": ["admin"], "logic": "any"},
        ],
    )

    @model_validator(mode="after")
    def validate_plugin_config(self) -> Self:
        """Validate config against plugin's schema if plugin is registered."""
        # Import here to avoid circular imports
        from .plugin import get_plugin

        plugin_cls = get_plugin(self.plugin)
        if plugin_cls:
            # Validate config against plugin's config_model
            plugin_cls.config_model(**self.config)
        # If plugin not found, allow it (might be registered later)
        return self


class ControlAction(BaseModel):
    """What to do when control matches."""

    decision: Literal["allow", "deny", "warn", "log"] = Field(
        ..., description="Action to take when control is triggered"
    )


class ControlDefinition(BaseModel):
    """A control definition to evaluate agent interactions.

    This model contains only the logic and configuration.
    Identity fields (id, name) are managed by the database.
    """

    description: str | None = Field(None, description="Detailed description of the control")
    enabled: bool = Field(True, description="Whether this control is active")

    # When to apply
    applies_to: Literal["llm_call", "tool_call"] = Field(
        ..., description="Which type of interaction this control applies to"
    )
    check_stage: Literal["pre", "post"] = Field(
        ..., description="When to execute this control"
    )

    # What to check
    selector: ControlSelector = Field(..., description="What data to select from the payload")

    # How to check (unified plugin-based evaluator)
    evaluator: EvaluatorConfig = Field(..., description="How to evaluate the selected data")

    # What to do
    action: ControlAction = Field(..., description="What action to take when control matches")

    # Metadata
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Block outputs containing US Social Security Numbers",
                    "enabled": True,
                    "applies_to": "llm_call",
                    "check_stage": "post",
                    "selector": {"path": "output"},
                    "evaluator": {
                        "plugin": "regex",
                        "config": {
                            "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
                        },
                    },
                    "action": {
                        "decision": "deny",
                    },
                    "tags": ["pii", "compliance"],
                }
            ]
        }
    }


class EvaluatorResult(BaseModel):
    """Result from a control evaluator."""

    matched: bool = Field(..., description="Whether the pattern matched")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in the evaluation"
    )
    message: str | None = Field(default=None, description="Explanation of the result")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional result metadata")


class ControlMatch(BaseModel):
    """Represents a control match (could be allow, deny, warn, or log)."""

    control_id: int = Field(..., description="Database ID of the control that matched")
    control_name: str = Field(..., description="Name of the control that matched")
    action: Literal["allow", "deny", "warn", "log"] = Field(
        ..., description="Action to take for this match"
    )
    result: EvaluatorResult = Field(
        ..., description="Evaluator result (confidence, message, metadata)"
    )


