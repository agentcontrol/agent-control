"""Helpers for migrating stored controls to condition trees."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from agent_control_models import ControlDefinition
from pydantic import ValidationError

type MigrationStatus = Literal["unchanged", "migrated", "invalid"]


@dataclass(frozen=True)
class ControlMigrationResult:
    """Outcome of migrating a single stored control payload."""

    status: MigrationStatus
    payload: dict[str, Any] | None = None
    reason: str | None = None


def _validation_message(error: ValidationError) -> str:
    first_error = error.errors()[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()))
    message = first_error.get("msg", "Validation failed.")
    if location:
        return f"{location}: {message}"
    return message


def migrate_control_payload(data: object) -> ControlMigrationResult:
    """Migrate a stored control payload to canonical condition-tree shape."""
    if not isinstance(data, dict):
        return ControlMigrationResult(
            status="invalid",
            reason="Stored control data must be a JSON object.",
        )

    has_condition = "condition" in data
    has_selector = "selector" in data
    has_evaluator = "evaluator" in data

    if has_condition and (has_selector or has_evaluator):
        return ControlMigrationResult(
            status="invalid",
            reason=(
                "Stored control data mixes canonical condition fields "
                "with legacy selector/evaluator fields."
            ),
        )

    candidate = deepcopy(data)
    status: MigrationStatus = "unchanged"

    if not has_condition:
        if has_selector != has_evaluator:
            return ControlMigrationResult(
                status="invalid",
                reason="Legacy control data must include both selector and evaluator.",
            )
        if not has_selector:
            return ControlMigrationResult(
                status="invalid",
                reason="Stored control data is missing the condition definition.",
            )

        selector = candidate.pop("selector")
        evaluator = candidate.pop("evaluator")
        candidate["condition"] = {
            "selector": selector,
            "evaluator": evaluator,
        }
        status = "migrated"

    try:
        validated = ControlDefinition.model_validate(candidate)
    except ValidationError as error:
        return ControlMigrationResult(
            status="invalid",
            reason=_validation_message(error),
        )

    return ControlMigrationResult(
        status=status,
        payload=validated.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_unset=True,
        ),
    )
