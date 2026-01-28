"""
Standardized error models for Agent Control API.

This module implements a unified error response format that combines:
- RFC 7807 (Problem Details for HTTP APIs)
- Kubernetes-style error structure
- GitHub-style validation error arrays
- OPA-style semantic error codes

Example error response:
{
    "type": "https://agent-control.dev/errors/not-found",
    "title": "Resource Not Found",
    "status": 404,
    "detail": "Agent with ID '550e8400-e29b-41d4-a716-446655440000' not found",
    "instance": "/api/v1/agents/550e8400-e29b-41d4-a716-446655440000",
    "error_code": "AGENT_NOT_FOUND",
    "kind": "Status",
    "api_version": "v1",
    "reason": "NotFound",
    "metadata": {
        "request_id": "req-abc123",
        "timestamp": "2025-01-15T10:30:00Z"
    },
    "errors": [
        {
            "resource": "Agent",
            "field": "agent_id",
            "code": "not_found",
            "message": "Agent with ID '550e8400-e29b-41d4-a716-446655440000' does not exist"
        }
    ]
}
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import Field

from .base import BaseModel


class ErrorCode(str, Enum):
    """
    Standardized error codes following OPA-style semantic naming.

    Error codes follow the pattern: RESOURCE_ACTION or CATEGORY_DESCRIPTION
    """

    # Authentication & Authorization (1xx pattern in code)
    AUTH_MISSING_KEY = "AUTH_MISSING_KEY"
    AUTH_INVALID_KEY = "AUTH_INVALID_KEY"
    AUTH_INSUFFICIENT_PRIVILEGES = "AUTH_INSUFFICIENT_PRIVILEGES"
    AUTH_MISCONFIGURED = "AUTH_MISCONFIGURED"

    # Resource Not Found (2xx pattern)
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"  # Generic fallback
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
    CONTROL_NOT_FOUND = "CONTROL_NOT_FOUND"
    EVALUATOR_NOT_FOUND = "EVALUATOR_NOT_FOUND"
    EVALUATOR_CONFIG_NOT_FOUND = "EVALUATOR_CONFIG_NOT_FOUND"

    # Conflict Errors (3xx pattern)
    AGENT_NAME_CONFLICT = "AGENT_NAME_CONFLICT"
    AGENT_UUID_CONFLICT = "AGENT_UUID_CONFLICT"
    POLICY_NAME_CONFLICT = "POLICY_NAME_CONFLICT"
    CONTROL_NAME_CONFLICT = "CONTROL_NAME_CONFLICT"
    EVALUATOR_NAME_CONFLICT = "EVALUATOR_NAME_CONFLICT"
    EVALUATOR_CONFIG_NAME_CONFLICT = "EVALUATOR_CONFIG_NAME_CONFLICT"
    CONTROL_IN_USE = "CONTROL_IN_USE"
    EVALUATOR_IN_USE = "EVALUATOR_IN_USE"
    SCHEMA_INCOMPATIBLE = "SCHEMA_INCOMPATIBLE"

    # Validation Errors (4xx pattern)
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_CONFIG = "INVALID_CONFIG"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    CORRUPTED_DATA = "CORRUPTED_DATA"
    POLICY_CONTROL_INCOMPATIBLE = "POLICY_CONTROL_INCOMPATIBLE"

    # Server Errors (5xx pattern)
    DATABASE_ERROR = "DATABASE_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    EVALUATION_FAILED = "EVALUATION_FAILED"


class ErrorReason(str, Enum):
    """
    Kubernetes-style reason codes for error categorization.

    These provide a machine-readable, stable identifier for the error type.
    """

    # Client errors
    NOT_FOUND = "NotFound"
    ALREADY_EXISTS = "AlreadyExists"
    CONFLICT = "Conflict"
    INVALID = "Invalid"
    FORBIDDEN = "Forbidden"
    UNAUTHORIZED = "Unauthorized"
    BAD_REQUEST = "BadRequest"
    UNPROCESSABLE_ENTITY = "UnprocessableEntity"

    # Server errors
    INTERNAL_ERROR = "InternalError"
    SERVICE_UNAVAILABLE = "ServiceUnavailable"
    UNKNOWN = "Unknown"


class ValidationErrorItem(BaseModel):
    """
    GitHub-style validation error item.

    Represents a single validation error with field-level detail.
    """

    resource: str = Field(
        ...,
        description="The resource type where the error occurred (e.g., 'Agent', 'Control')",
    )
    field: str | None = Field(
        default=None,
        description="The field that caused the error (e.g., 'name', 'config.threshold')",
    )
    code: str = Field(
        ...,
        description="Machine-readable error code for this specific validation (e.g., 'required', "
        "'invalid_format', 'too_long')",
    )
    message: str = Field(
        ...,
        description="Human-readable description of what went wrong",
    )
    value: Any | None = Field(
        default=None,
        description="The invalid value that was provided (omitted for sensitive data)",
    )


class ErrorMetadata(BaseModel):
    """
    Metadata about the error occurrence.

    Contains contextual information useful for debugging and tracing.
    """

    request_id: str | None = Field(
        default=None,
        description="Unique identifier for the request (for log correlation)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp when the error occurred",
    )
    retry_after: int | None = Field(
        default=None,
        description="Suggested seconds to wait before retrying (for rate limits)",
    )


class ErrorDetails(BaseModel):
    """
    Additional structured details about the error.

    Kubernetes-style details object containing resource-specific information.
    """

    name: str | None = Field(
        default=None,
        description="Name of the resource that caused the error",
    )
    kind: str | None = Field(
        default=None,
        description="Kind/type of the resource (e.g., 'Agent', 'Policy', 'Control')",
    )
    causes: list[ValidationErrorItem] | None = Field(
        default=None,
        description="List of underlying causes for this error",
    )
    retry_after_seconds: int | None = Field(
        default=None,
        description="Suggested retry interval in seconds",
    )


class ProblemDetail(BaseModel):
    """
    RFC 7807 Problem Details with Kubernetes and GitHub extensions.

    This is the standardized error response format for all API errors.
    All error responses conform to this schema for consistency.

    Combines:
    - RFC 7807 core fields (type, title, status, detail, instance)
    - Kubernetes fields (kind, apiVersion, reason, metadata)
    - GitHub validation (errors array)
    - OPA semantic codes (error_code)
    """

    # RFC 7807 core fields
    type: str = Field(
        default="about:blank",
        description="A URI reference that identifies the problem type. "
        "When dereferenced, should provide human-readable documentation.",
    )
    title: str = Field(
        ...,
        description="A short, human-readable summary of the problem type. "
        "Should not change between occurrences.",
    )
    status: int = Field(
        ...,
        description="The HTTP status code for this occurrence of the problem.",
    )
    detail: str = Field(
        ...,
        description="A human-readable explanation specific to this occurrence of the problem.",
    )
    instance: str | None = Field(
        default=None,
        description="A URI reference that identifies the specific occurrence of the problem. "
        "Typically the request path.",
    )

    # OPA-style semantic error code
    error_code: ErrorCode = Field(
        ...,
        description="Machine-readable error code following OPA-style semantic naming.",
    )

    # Kubernetes-style fields
    kind: str = Field(
        default="Status",
        description="Kubernetes-style kind identifier. Always 'Status' for errors.",
    )
    api_version: str = Field(
        default="v1",
        description="API version that generated this error.",
    )
    reason: ErrorReason = Field(
        ...,
        description="Kubernetes-style reason code for error categorization.",
    )
    metadata: ErrorMetadata | None = Field(
        default=None,
        description="Metadata about this error occurrence.",
    )

    # GitHub-style validation errors
    errors: list[ValidationErrorItem] | None = Field(
        default=None,
        description="Array of validation errors (GitHub-style). "
        "Populated for validation failures with field-level details.",
    )

    # Additional context
    details: ErrorDetails | None = Field(
        default=None,
        description="Kubernetes-style additional details about the error.",
    )

    # Hint for resolution
    hint: str | None = Field(
        default=None,
        description="Actionable suggestion for resolving the error.",
    )

    # Documentation link
    documentation_url: str | None = Field(
        default=None,
        description="URL to relevant documentation for this error type.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "type": "https://agent-control.dev/errors/not-found",
                    "title": "Resource Not Found",
                    "status": 404,
                    "detail": "Agent with ID '550e8400-e29b-41d4-a716-446655440000' not found",
                    "instance": "/api/v1/agents/550e8400-e29b-41d4-a716-446655440000",
                    "error_code": "AGENT_NOT_FOUND",
                    "kind": "Status",
                    "api_version": "v1",
                    "reason": "NotFound",
                    "metadata": {
                        "request_id": "req-abc123",
                        "timestamp": "2025-01-15T10:30:00Z",
                    },
                    "errors": None,
                    "hint": "Verify the agent ID is correct and the agent has been registered.",
                },
                {
                    "type": "https://agent-control.dev/errors/validation-error",
                    "title": "Validation Error",
                    "status": 422,
                    "detail": "Request validation failed with 2 errors",
                    "instance": "/api/v1/controls/42/data",
                    "error_code": "VALIDATION_ERROR",
                    "kind": "Status",
                    "api_version": "v1",
                    "reason": "Invalid",
                    "metadata": {
                        "timestamp": "2025-01-15T10:30:00Z",
                    },
                    "errors": [
                        {
                            "resource": "Control",
                            "field": "data.evaluator.config.threshold",
                            "code": "type_error",
                            "message": "Expected number, got string",
                            "value": "high",
                        },
                        {
                            "resource": "Control",
                            "field": "data.evaluator.name",
                            "code": "not_found",
                            "message": "Evaluator 'nonexistent' not registered",
                        },
                    ],
                    "hint": "Check the evaluator configuration against the schema.",
                },
            ]
        }
    }


# Error type URI base
ERROR_TYPE_BASE = "https://agentcontrol.dev/errors"


def make_error_type(error_code: ErrorCode) -> str:
    """Generate a standardized error type URI from an error code."""
    # Convert AGENT_NOT_FOUND to agent-not-found
    slug = error_code.value.lower().replace("_", "-")
    return f"{ERROR_TYPE_BASE}/{slug}"


# Pre-defined error titles for common error codes
ERROR_TITLES: dict[ErrorCode, str] = {
    # Auth errors
    ErrorCode.AUTH_MISSING_KEY: "Authentication Required",
    ErrorCode.AUTH_INVALID_KEY: "Invalid API Key",
    ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES: "Insufficient Privileges",
    ErrorCode.AUTH_MISCONFIGURED: "Authentication Misconfigured",
    # Not found errors
    ErrorCode.RESOURCE_NOT_FOUND: "Resource Not Found",
    ErrorCode.AGENT_NOT_FOUND: "Agent Not Found",
    ErrorCode.POLICY_NOT_FOUND: "Policy Not Found",
    ErrorCode.CONTROL_NOT_FOUND: "Control Not Found",
    ErrorCode.EVALUATOR_NOT_FOUND: "Evaluator Not Found",
    ErrorCode.EVALUATOR_CONFIG_NOT_FOUND: "Evaluator Config Not Found",
    # Conflict errors
    ErrorCode.AGENT_NAME_CONFLICT: "Agent Name Already Exists",
    ErrorCode.AGENT_UUID_CONFLICT: "Agent UUID Conflict",
    ErrorCode.POLICY_NAME_CONFLICT: "Policy Name Already Exists",
    ErrorCode.CONTROL_NAME_CONFLICT: "Control Name Already Exists",
    ErrorCode.EVALUATOR_NAME_CONFLICT: "Evaluator Name Conflict",
    ErrorCode.EVALUATOR_CONFIG_NAME_CONFLICT: "Evaluator Config Name Conflict",
    ErrorCode.CONTROL_IN_USE: "Control In Use",
    ErrorCode.EVALUATOR_IN_USE: "Evaluator In Use",
    ErrorCode.SCHEMA_INCOMPATIBLE: "Schema Incompatible",
    # Validation errors
    ErrorCode.VALIDATION_ERROR: "Validation Error",
    ErrorCode.INVALID_CONFIG: "Invalid Configuration",
    ErrorCode.INVALID_SCHEMA: "Invalid Schema",
    ErrorCode.CORRUPTED_DATA: "Corrupted Data",
    ErrorCode.POLICY_CONTROL_INCOMPATIBLE: "Policy Control Incompatible",
    # Server errors
    ErrorCode.DATABASE_ERROR: "Database Error",
    ErrorCode.INTERNAL_ERROR: "Internal Server Error",
    ErrorCode.EVALUATION_FAILED: "Evaluation Failed",
}


def get_error_title(error_code: ErrorCode) -> str:
    """Get the standard title for an error code."""
    return ERROR_TITLES.get(error_code, "Error")
