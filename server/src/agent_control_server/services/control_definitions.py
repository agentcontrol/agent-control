"""Helpers for parsing stored control definitions consistently."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from agent_control_models import ControlDefinition
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from pydantic import ValidationError

from ..errors import APIValidationError
from .validation_paths import format_field_path


def build_control_validation_errors(
    validation_error: ValidationError,
    *,
    field_prefix: str | None = "data",
) -> list[ValidationErrorItem]:
    """Convert ControlDefinition validation errors into API error items."""
    items: list[ValidationErrorItem] = []
    for err in validation_error.errors():
        loc = cast(Sequence[str | int], err.get("loc", ()))
        field_suffix = format_field_path(loc)
        if field_prefix is None:
            field = field_suffix
        elif field_suffix is None:
            field = field_prefix
        else:
            field = f"{field_prefix}.{field_suffix}"

        items.append(
            ValidationErrorItem(
                resource="Control",
                field=field,
                code=err.get("type", "validation_error"),
                message=err.get("msg", "Validation failed"),
            )
        )
    return items


def parse_control_definition_or_api_error(
    data: Any,
    *,
    detail: str,
    hint: str,
    resource_id: str | None = None,
    context: Mapping[str, Any] | None = None,
    field_prefix: str | None = "data",
) -> ControlDefinition:
    """Parse stored control data or raise a structured CORRUPTED_DATA error."""
    try:
        return ControlDefinition.model_validate(data, context=dict(context) if context else None)
    except ValidationError as exc:
        raise APIValidationError(
            error_code=ErrorCode.CORRUPTED_DATA,
            detail=detail,
            resource="Control",
            resource_id=resource_id,
            hint=hint,
            errors=build_control_validation_errors(exc, field_prefix=field_prefix),
        ) from exc
