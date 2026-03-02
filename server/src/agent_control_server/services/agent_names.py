"""Agent name normalization helpers for server endpoints."""

from agent_control_models.agent import normalize_agent_name
from agent_control_models.errors import ErrorCode, ValidationErrorItem

from ..errors import APIValidationError


def normalize_agent_name_or_422(
    agent_name: str,
    *,
    field_name: str = "agent_name",
) -> str:
    """Normalize an agent name or raise a standardized 422 validation error."""
    try:
        return normalize_agent_name(agent_name)
    except ValueError as exc:
        raise APIValidationError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="Invalid agent_name",
            resource="Agent",
            hint=(
                "Agent names must be at least 10 characters and may only contain "
                "letters, digits, ':', '_' or '-'."
            ),
            errors=[
                ValidationErrorItem(
                    resource="Agent",
                    field=field_name,
                    code="invalid_format",
                    message=str(exc),
                    value=agent_name,
                )
            ],
        ) from exc
