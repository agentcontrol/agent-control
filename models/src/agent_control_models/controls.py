"""Control definition models for agent protection."""

from typing import Any, Literal, Self
from uuid import uuid4

import re2
from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import BaseModel


class ControlSelector(BaseModel):
    """Selects data from a Step payload.

    - path: which slice of the Step to feed into the evaluator. Optional, defaults to "*"
      meaning the entire Step object.
    """

    path: str | None = Field(
        default="*",
        description=(
            "Path to data using dot notation. "
            "Examples: 'input', 'output', 'context.user_id', 'name', 'type', '*'"
        ),
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str | None) -> str:
        """Validate path; None becomes '*', empty string raises."""
        if v is None:
            return "*"
        if v == "":
            raise ValueError(
                "Path cannot be empty string. Use '*' for root or omit the field."
            )

        # Valid root fields
        valid_roots = {"input", "output", "name", "type", "context", "*"}
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
                {"path": "context.user_id"},
                {"path": "input"},
                {"path": "*"},
                {"path": "name"},
                {"path": "output"},
            ]
        }
    }


class ControlScope(BaseModel):
    """Defines when a control applies to a Step."""

    step_types: list[str] | None = Field(
        default=None,
        description=(
            "Step types this control applies to (omit to apply to all types). "
            "Built-in types are 'tool' and 'llm'."
        ),
    )
    step_names: list[str] | None = Field(
        default=None,
        description="Exact step names this control applies to",
    )
    step_name_regex: str | None = Field(
        default=None,
        description="RE2 pattern matched with search() against step name",
    )
    stages: list[Literal["pre", "post"]] | None = Field(
        default=None,
        description="Evaluation stages this control applies to",
    )

    @field_validator("step_types")
    @classmethod
    def validate_step_types(
        cls, v: list[str] | None
    ) -> list[str] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError(
                "step_types cannot be an empty list. Use None/omit the field to apply to all types."
            )
        if any((not isinstance(x, str) or not x) for x in v):
            raise ValueError("step_types must be a list of non-empty strings")
        return v

    @field_validator("step_names")
    @classmethod
    def validate_step_names(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError(
                "step_names cannot be an empty list. Use None/omit the field to apply to all steps."
            )
        if any((not isinstance(x, str) or not x) for x in v):
            raise ValueError("step_names must be a list of non-empty strings")
        return v

    @field_validator("step_name_regex")
    @classmethod
    def validate_step_name_regex(
        cls, v: str | None, info: ValidationInfo
    ) -> str | None:
        if v is None:
            return v
        if info.context and info.context.get("allow_invalid_step_name_regex"):
            return v
        try:
            re2.compile(v)
        except re2.error as e:
            raise ValueError(f"Invalid step_name_regex: {e}") from e
        return v

    @field_validator("stages")
    @classmethod
    def validate_stages(
        cls, v: list[Literal["pre", "post"]] | None
    ) -> list[Literal["pre", "post"]] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError(
                "stages cannot be an empty list. Use None/omit the field to apply to all stages."
            )
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"step_types": ["tool"], "stages": ["pre"]},
                {"step_names": ["search_db", "fetch_user"]},
                {"step_name_regex": "^db_.*"},
                {"step_types": ["llm"], "stages": ["post"]},
            ]
        }
    }


# =============================================================================
# Unified Evaluator Spec (used in API)
# =============================================================================


class EvaluatorSpec(BaseModel):
    """Evaluator specification. See GET /evaluators for available evaluators and schemas.

    Evaluator reference formats:
    - Built-in: "regex", "list", "json", "sql"
    - External: "galileo.luna2" (requires agent-control-evaluators[galileo])
    - Agent-scoped: "my-agent:my-evaluator" (validated in endpoint, not here)
    """

    name: str = Field(
        ...,
        description="Evaluator name or agent-scoped reference (agent:evaluator)",
        examples=["regex", "list", "my-agent:pii-detector"],
    )
    config: dict[str, Any] = Field(
        ...,
        description="Evaluator-specific configuration",
        examples=[
            {"pattern": r"\d{3}-\d{2}-\d{4}"},
            {"values": ["admin"], "logic": "any"},
        ],
    )

    @model_validator(mode="after")
    def validate_evaluator_config(self) -> Self:
        """Validate config against evaluator's schema if evaluator is registered.

        Agent-scoped evaluators (format: agent:evaluator) are validated in the
        endpoint where we have database access to look up the agent's schema.
        """
        # Agent-scoped evaluators: defer validation to endpoint (needs DB access)
        if ":" in self.name:
            return self

        # Built-in evaluators: validate config against evaluator's config_model
        # This import is optional - evaluators package may not be installed
        try:
            from agent_control_evaluators import ensure_evaluators_discovered, get_evaluator

            # Ensure entry points are loaded before looking up evaluator
            ensure_evaluators_discovered()
            evaluator_cls = get_evaluator(self.name)
            if evaluator_cls:
                evaluator_cls.config_model(**self.config)
        except ImportError:
            # Evaluators package not installed - skip validation
            pass

        # If evaluator not found, allow it (might be a server-side registered evaluator)
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
    execution: Literal["server", "sdk"] = Field(
        ..., description="Where this control executes"
    )

    # When to apply
    scope: ControlScope = Field(
        default_factory=ControlScope,
        description="Which steps and stages this control applies to",
    )

    # What to check
    selector: ControlSelector = Field(..., description="What data to select from the payload")

    # How to check (unified evaluator-based system)
    evaluator: EvaluatorSpec = Field(..., description="How to evaluate the selected data")

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
                    "execution": "server",
                    "scope": {"step_types": ["llm"], "stages": ["post"]},
                    "selector": {"path": "output"},
                    "evaluator": {
                        "name": "regex",
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
    """Result from a control evaluator.

    The `error` field indicates evaluator failures, NOT validation failures:
    - Set `error` for: evaluator crashes, timeouts, missing dependencies, external service errors
    - Do NOT set `error` for: invalid input, syntax errors, schema violations, constraint failures

    When `error` is set, `matched` must be False (fail-open on evaluator errors).
    When `error` is None, `matched` reflects the actual validation result.

    This distinction allows:
    - Clients to distinguish "data violated rules" from "evaluator is broken"
    - Observability systems to monitor evaluator health separately from validation outcomes
    """

    matched: bool = Field(..., description="Whether the pattern matched")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in the evaluation"
    )
    message: str | None = Field(default=None, description="Explanation of the result")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional result metadata")
    error: str | None = Field(
        default=None,
        description=(
            "Error message if evaluation failed internally. "
            "When set, matched=False is due to error, not actual evaluation."
        ),
    )

    @model_validator(mode="after")
    def error_implies_not_matched(self) -> Self:
        """Ensure matched=False when error is set (fail-open on errors)."""
        if self.error is not None and self.matched:
            raise ValueError("matched must be False when error is set")
        return self


class ControlMatch(BaseModel):
    """Represents a control evaluation result (match, non-match, or error)."""

    control_execution_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique ID for this control execution (generated by engine)",
    )
    control_id: int = Field(..., description="Database ID of the control")
    control_name: str = Field(..., description="Name of the control")
    action: Literal["allow", "deny", "warn", "log"] = Field(
        ..., description="Action configured for this control"
    )
    result: EvaluatorResult = Field(
        ..., description="Evaluator result (confidence, message, metadata)"
    )
