"""Typed configuration for the DefenseClaw rule-pack evaluator."""

from __future__ import annotations

from typing import Literal, Self

from agent_control_evaluators import EvaluatorConfig
from pydantic import BaseModel, Field, model_validator

from ..common import STRICT_PROVIDER_CONFIG, NonEmptyString, Severity


class RuleConfig(BaseModel):
    """One DefenseClaw rule."""

    model_config = STRICT_PROVIDER_CONFIG

    id: NonEmptyString
    pattern: NonEmptyString
    title: NonEmptyString
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    tags: list[NonEmptyString]


class RulePack(BaseModel):
    """Versioned DefenseClaw rule pack."""

    model_config = STRICT_PROVIDER_CONFIG

    version: Literal[1] = 1
    category: Literal["agent-control"] = "agent-control"
    rules: list[RuleConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_rule_ids(self) -> Self:
        """Reject ambiguous rule packs containing duplicate identifiers."""
        rule_ids = [rule.id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("rule ids must be unique within a rule pack")
        return self


class DefenseClawRulePackConfig(EvaluatorConfig):
    """Configuration envelope for `defenseclaw.rule_pack`."""

    model_config = STRICT_PROVIDER_CONFIG

    schema_version: Literal[1] = 1
    rule_pack: RulePack
