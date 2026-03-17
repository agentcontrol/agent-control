"""Configuration for list evaluator."""

from typing import Literal

from pydantic import Field, field_validator

from agent_control_evaluators._base import EvaluatorConfig


class ListEvaluatorConfig(EvaluatorConfig):
    """Configuration for list evaluator."""

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

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: list[str | int | float]) -> list[str | int | float]:
        """Reject blank string entries that would compile into pathological regexes."""
        if any(isinstance(value, str) and value.strip() == "" for value in values):
            raise ValueError("values must not contain empty or whitespace-only strings")
        return values
