"""Control definition models for agent protection."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal, Self
from uuid import uuid4

import re2
from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .actions import ActionDecision, normalize_action
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
        examples=[["llm"], ["tool"], ["llm", "tool"]],
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
        min_length=1,
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

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        if not normalized:
            raise ValueError("Evaluator name cannot be empty or whitespace-only.")
        return normalized

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


type ConditionLeafParts = tuple[ControlSelector, EvaluatorSpec]


@dataclass(frozen=True)
class ControlObservabilityIdentity:
    """Stable selector/evaluator identity derived from a condition tree."""

    selector_path: str | None
    evaluator_name: str | None
    leaf_count: int
    all_evaluators: list[str]
    all_selector_paths: list[str]


class SteeringContext(BaseModel):
    """Steering context for steer actions.

    This model provides an extensible structure for steering guidance.
    Future fields could include severity, categories, suggested_actions, etc.
    """

    message: str = Field(
        ...,
        description="Guidance message explaining what needs to be corrected and how"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "message": (
                        "This large transfer requires user verification. "
                        "Request 2FA code from user, verify it, then retry "
                        "the transaction with verified_2fa=True."
                    )
                },
                {
                    "message": (
                        "Transfer exceeds daily limit. Steps: "
                        "1) Ask user for business justification, "
                        "2) Request manager approval with amount and justification, "
                        "3) If approved, retry with manager_approved=True and "
                        "justification filled in."
                    )
                }
            ]
        }
    }


class ControlAction(BaseModel):
    """What to do when control matches."""

    decision: ActionDecision = Field(
        ..., description="Action to take when control is triggered"
    )
    steering_context: SteeringContext | None = Field(
        None,
        description=(
            "Steering context object for steer actions. Strongly recommended when "
            "decision='steer' to provide correction suggestions. If not provided, the "
            "evaluator result message will be used as fallback."
        )
    )

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: str) -> ActionDecision:
        return normalize_action(value)


MAX_CONDITION_DEPTH = 6


class ConditionNode(BaseModel):
    """Recursive boolean condition tree for control evaluation."""

    selector: ControlSelector | None = Field(
        default=None,
        description="Leaf selector. Must be provided together with evaluator.",
    )
    evaluator: EvaluatorSpec | None = Field(
        default=None,
        description="Leaf evaluator. Must be provided together with selector.",
    )
    and_: list[ConditionNode] | None = Field(
        default=None,
        alias="and",
        serialization_alias="and",
        description="Logical AND over child conditions.",
    )
    or_: list[ConditionNode] | None = Field(
        default=None,
        alias="or",
        serialization_alias="or",
        description="Logical OR over child conditions.",
    )
    not_: ConditionNode | None = Field(
        default=None,
        alias="not",
        serialization_alias="not",
        description="Logical NOT over a single child condition.",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True,
        validate_assignment=True,
        extra="ignore",
        serialize_by_alias=True,
    )

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        """Ensure each node is exactly one of leaf/and/or/not."""
        has_selector = self.selector is not None
        has_evaluator = self.evaluator is not None
        has_leaf = has_selector and has_evaluator
        if has_selector != has_evaluator:
            raise ValueError("Leaf condition requires both selector and evaluator")

        populated = sum(
            1
            for present in (
                has_leaf,
                self.and_ is not None,
                self.or_ is not None,
                self.not_ is not None,
            )
            if present
        )
        if populated != 1:
            raise ValueError("Condition node must contain exactly one of leaf, and, or, not")

        if self.and_ is not None and len(self.and_) == 0:
            raise ValueError("'and' must contain at least one child condition")
        if self.or_ is not None and len(self.or_) == 0:
            raise ValueError("'or' must contain at least one child condition")

        return self

    def kind(self) -> Literal["leaf", "and", "or", "not"]:
        """Return the logical node type."""
        if self.is_leaf():
            return "leaf"
        if self.and_ is not None:
            return "and"
        if self.or_ is not None:
            return "or"
        return "not"

    def is_leaf(self) -> bool:
        """Return True when this node is a leaf selector/evaluator pair."""
        return self.selector is not None and self.evaluator is not None

    def children_in_order(self) -> list[ConditionNode]:
        """Return child conditions in evaluation order."""
        if self.and_ is not None:
            return self.and_
        if self.or_ is not None:
            return self.or_
        if self.not_ is not None:
            return [self.not_]
        return []

    def iter_leaves(self) -> Iterator[ConditionNode]:
        """Yield leaf nodes in left-to-right traversal order."""
        if self.is_leaf():
            yield self
            return

        for child in self.children_in_order():
            yield from child.iter_leaves()

    def iter_leaf_parts(self) -> Iterator[ConditionLeafParts]:
        """Yield leaf selector/evaluator pairs in left-to-right traversal order."""
        leaf_parts = self.leaf_parts()
        if leaf_parts is not None:
            yield leaf_parts
            return

        for child in self.children_in_order():
            yield from child.iter_leaf_parts()

    def max_depth(self) -> int:
        """Return the maximum nesting depth of this condition tree."""
        children = self.children_in_order()
        if not children:
            return 1
        return 1 + max(child.max_depth() for child in children)

    def leaf_parts(self) -> ConditionLeafParts | None:
        """Return the selector/evaluator pair for leaf nodes."""
        if not self.is_leaf():
            return None
        selector = self.selector
        evaluator = self.evaluator
        if selector is None or evaluator is None:
            return None
        return selector, evaluator

    model_config["json_schema_extra"] = {
        "examples": [
            {
                "selector": {"path": "output"},
                "evaluator": {"name": "regex", "config": {"pattern": r"\d{3}-\d{2}-\d{4}"}},
            },
            {
                "and": [
                    {
                        "selector": {"path": "context.risk_level"},
                        "evaluator": {
                            "name": "list",
                            "config": {"values": ["high", "critical"]},
                        },
                    },
                    {
                        "not": {
                            "selector": {"path": "context.user_role"},
                            "evaluator": {
                                "name": "list",
                                "config": {"values": ["admin", "security"]},
                            },
                        }
                    },
                ]
            },
        ]
    }


ConditionNode.model_rebuild()


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
    condition: ConditionNode = Field(
        ...,
        description=(
            "Recursive boolean condition tree. Leaf nodes contain selector + evaluator; "
            "composite nodes contain and/or/not."
        ),
    )

    # What to do
    action: ControlAction = Field(..., description="What action to take when control matches")

    # Metadata
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")

    @classmethod
    def canonicalize_payload(cls, data: Any) -> Any:
        """Rewrite legacy selector/evaluator payloads into canonical condition shape."""
        if not isinstance(data, dict):
            return data

        has_condition = "condition" in data
        has_selector = "selector" in data
        has_evaluator = "evaluator" in data

        if has_condition and (has_selector or has_evaluator):
            raise ValueError(
                "Control definition mixes canonical condition fields "
                "with legacy selector/evaluator fields."
            )
        if has_selector != has_evaluator:
            raise ValueError(
                "Legacy control definition must include both selector and evaluator."
            )
        if not has_condition and has_selector:
            canonical = dict(data)
            selector = canonical.pop("selector")
            evaluator = canonical.pop("evaluator")
            canonical["condition"] = {
                "selector": selector,
                "evaluator": evaluator,
            }
            return canonical
        return data

    @model_validator(mode="before")
    @classmethod
    def canonicalize_legacy_condition_shape(cls, data: Any) -> Any:
        """Accept legacy flat leaf payloads during condition-tree rollout."""
        return cls.canonicalize_payload(data)

    @model_validator(mode="after")
    def validate_condition_constraints(self) -> Self:
        """Validate cross-field control constraints."""
        if self.condition.max_depth() > MAX_CONDITION_DEPTH:
            raise ValueError(
                f"Condition nesting depth exceeds maximum of {MAX_CONDITION_DEPTH}"
            )

        if (
            self.action.decision == "steer"
            and not self.condition.is_leaf()
            and self.action.steering_context is None
        ):
            raise ValueError(
                "Composite steer controls require action.steering_context"
            )
        return self

    def iter_condition_leaves(self) -> Iterator[ConditionNode]:
        """Yield leaf conditions in evaluation order."""
        yield from self.condition.iter_leaves()

    def iter_condition_leaf_parts(self) -> Iterator[ConditionLeafParts]:
        """Yield leaf selector/evaluator pairs in evaluation order."""
        yield from self.condition.iter_leaf_parts()

    def primary_leaf(self) -> ConditionNode | None:
        """Return the single leaf node when the whole condition is just one leaf."""
        if self.condition.is_leaf():
            return self.condition
        return None

    def observability_identity(self) -> ControlObservabilityIdentity:
        """Return a deterministic representative identity for observability.

        The representative selector/evaluator comes from the first leaf in
        evaluation order so composite trees still populate top-level event
        dimensions. The full ordered, deduped leaf context is also returned.
        """
        all_evaluators: list[str] = []
        all_selector_paths: list[str] = []
        seen_evaluators: set[str] = set()
        seen_selector_paths: set[str] = set()
        leaf_count = 0

        for selector, evaluator in self.iter_condition_leaf_parts():
            leaf_count += 1
            selector_path = selector.path or "*"

            if evaluator.name not in seen_evaluators:
                seen_evaluators.add(evaluator.name)
                all_evaluators.append(evaluator.name)

            if selector_path not in seen_selector_paths:
                seen_selector_paths.add(selector_path)
                all_selector_paths.append(selector_path)

        return ControlObservabilityIdentity(
            selector_path=all_selector_paths[0] if all_selector_paths else None,
            evaluator_name=all_evaluators[0] if all_evaluators else None,
            leaf_count=leaf_count,
            all_evaluators=all_evaluators,
            all_selector_paths=all_selector_paths,
        )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Block outputs containing US Social Security Numbers",
                    "enabled": True,
                    "execution": "server",
                    "scope": {"step_types": ["llm"], "stages": ["post"]},
                    "condition": {
                        "selector": {"path": "output"},
                        "evaluator": {
                            "name": "regex",
                            "config": {
                                "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
                            },
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
    action: ActionDecision = Field(
        ..., description="Action configured for this control"
    )
    result: EvaluatorResult = Field(
        ..., description="Evaluator result (confidence, message, metadata)"
    )
    steering_context: SteeringContext | None = Field(
        None,
        description="Steering context for steer actions if configured"
    )

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action_value(cls, value: str) -> ActionDecision:
        return normalize_action(value)
