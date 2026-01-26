"""
Standardized error handling for Agent Control Server.

This module provides exception classes and utilities for generating
RFC 7807 / Kubernetes / GitHub-style error responses.

Usage:
    from .errors import NotFoundError, ConflictError, ValidationError

    # Raise a not found error
    raise NotFoundError(
        error_code=ErrorCode.AGENT_NOT_FOUND,
        detail=f"Agent with ID '{agent_id}' not found",
        resource="Agent",
        resource_id=str(agent_id),
    )

    # Raise a validation error with field-level details
    raise APIValidationError(
        error_code=ErrorCode.VALIDATION_ERROR,
        detail="Request validation failed",
        errors=[
            ValidationErrorItem(
                resource="Control",
                field="data.evaluator.config",
                code="invalid_format",
                message="Config must be an object",
            )
        ],
    )
"""

import logging
import os
import traceback
import uuid
from typing import Any

from agent_control_models.errors import (
    ERROR_TITLES,
    ErrorCode,
    ErrorDetails,
    ErrorMetadata,
    ErrorReason,
    ProblemDetail,
    ValidationErrorItem,
    make_error_type,
)
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .config import settings


class APIError(HTTPException):
    """
    Base exception for all API errors.

    Generates RFC 7807 / Kubernetes / GitHub-style error responses.
    Subclass this for specific error types.
    """

    def __init__(
        self,
        status_code: int,
        error_code: ErrorCode,
        reason: ErrorReason,
        detail: str,
        *,
        errors: list[ValidationErrorItem] | None = None,
        hint: str | None = None,
        resource: str | None = None,
        resource_id: str | None = None,
        request_id: str | None = None,
        documentation_url: str | None = None,
        extra_details: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize an API error.

        Args:
            status_code: HTTP status code
            error_code: OPA-style semantic error code
            reason: Kubernetes-style reason code
            detail: Human-readable error message
            errors: GitHub-style validation error array
            hint: Actionable suggestion for resolution
            resource: Resource type (for error details)
            resource_id: Resource identifier (for error details)
            request_id: Request ID for tracing
            documentation_url: Link to relevant documentation
            extra_details: Additional context to include
        """
        self.error_code = error_code
        self.reason = reason
        self.errors = errors
        self.hint = hint
        self.resource = resource
        self.resource_id = resource_id
        self.request_id = request_id
        self.documentation_url = documentation_url
        self.extra_details = extra_details

        # Build the problem detail model
        super().__init__(status_code=status_code, detail=detail)

    def to_problem_detail(self, instance: str | None = None) -> ProblemDetail:
        """Convert this exception to a ProblemDetail response model."""
        # Build error details if we have resource info
        details: ErrorDetails | None = None
        if self.resource or self.errors:
            causes = self.errors if self.errors else None
            details = ErrorDetails(
                name=self.resource_id,
                kind=self.resource,
                causes=causes,
            )

        return ProblemDetail(
            type=make_error_type(self.error_code),
            title=ERROR_TITLES.get(self.error_code, "Error"),
            status=self.status_code,
            detail=self.detail,
            instance=instance,
            error_code=self.error_code,
            reason=self.reason,
            metadata=ErrorMetadata(request_id=self.request_id),
            errors=self.errors,
            details=details,
            hint=self.hint,
            documentation_url=self.documentation_url,
        )


# =============================================================================
# Specific Error Classes (4xx Client Errors)
# =============================================================================


class NotFoundError(APIError):
    """Resource not found error (404)."""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str,
        *,
        resource: str | None = None,
        resource_id: str | None = None,
        hint: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            status_code=404,
            error_code=error_code,
            reason=ErrorReason.NOT_FOUND,
            detail=detail,
            resource=resource,
            resource_id=resource_id,
            hint=hint,
            **kwargs,
        )


class ConflictError(APIError):
    """Resource conflict error (409)."""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str,
        *,
        resource: str | None = None,
        resource_id: str | None = None,
        hint: str | None = None,
        errors: list[ValidationErrorItem] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            status_code=409,
            error_code=error_code,
            reason=ErrorReason.CONFLICT,
            detail=detail,
            resource=resource,
            resource_id=resource_id,
            hint=hint,
            errors=errors,
            **kwargs,
        )


class APIValidationError(APIError):
    """Validation error (422)."""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str,
        *,
        errors: list[ValidationErrorItem] | None = None,
        resource: str | None = None,
        hint: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            status_code=422,
            error_code=error_code,
            reason=ErrorReason.UNPROCESSABLE_ENTITY,
            detail=detail,
            errors=errors,
            resource=resource,
            hint=hint,
            **kwargs,
        )


class BadRequestError(APIError):
    """Bad request error (400)."""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str,
        *,
        errors: list[ValidationErrorItem] | None = None,
        hint: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            status_code=400,
            error_code=error_code,
            reason=ErrorReason.BAD_REQUEST,
            detail=detail,
            errors=errors,
            hint=hint,
            **kwargs,
        )


class AuthenticationError(APIError):
    """Authentication error (401)."""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str,
        *,
        hint: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            status_code=401,
            error_code=error_code,
            reason=ErrorReason.UNAUTHORIZED,
            detail=detail,
            hint=hint,
            **kwargs,
        )


class ForbiddenError(APIError):
    """Authorization/permission error (403)."""

    def __init__(
        self,
        error_code: ErrorCode,
        detail: str,
        *,
        hint: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            status_code=403,
            error_code=error_code,
            reason=ErrorReason.FORBIDDEN,
            detail=detail,
            hint=hint,
            **kwargs,
        )


# =============================================================================
# Server Error Classes (5xx)
# =============================================================================


class DatabaseError(APIError):
    """Database operation error (500)."""

    def __init__(
        self,
        detail: str,
        *,
        resource: str | None = None,
        operation: str | None = None,
        **kwargs: Any,
    ) -> None:
        hint = "This is a server-side issue. Please try again later or contact support."
        if operation:
            hint = f"Failed during {operation}. {hint}"

        super().__init__(
            status_code=500,
            error_code=ErrorCode.DATABASE_ERROR,
            reason=ErrorReason.INTERNAL_ERROR,
            detail=detail,
            resource=resource,
            hint=hint,
            **kwargs,
        )


class InternalError(APIError):
    """Internal server error (500)."""

    def __init__(
        self,
        detail: str,
        *,
        hint: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            status_code=500,
            error_code=ErrorCode.INTERNAL_ERROR,
            reason=ErrorReason.INTERNAL_ERROR,
            detail=detail,
            hint=hint or "This is an unexpected error. Please try again or contact support.",
            **kwargs,
        )


# =============================================================================
# Exception Handlers
# =============================================================================


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """
    Exception handler for APIError instances.

    Converts APIError exceptions to RFC 7807 JSON responses.
    """
    problem = exc.to_problem_detail(instance=str(request.url.path))

    # Add headers for auth errors
    headers: dict[str, str] | None = None
    if exc.status_code == 401:
        headers = {"WWW-Authenticate": "ApiKey"}

    return JSONResponse(
        status_code=exc.status_code,
        content=problem.model_dump(mode="json", exclude_none=True),
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Exception handler for standard HTTPException.

    Converts generic HTTPException to RFC 7807 format for consistency.
    This handles cases where HTTPException is raised directly (legacy code)
    or from FastAPI internals.
    """
    # Map status codes to error codes and reasons
    status_to_error: dict[int, tuple[ErrorCode, ErrorReason]] = {
        400: (ErrorCode.VALIDATION_ERROR, ErrorReason.BAD_REQUEST),
        401: (ErrorCode.AUTH_INVALID_KEY, ErrorReason.UNAUTHORIZED),
        403: (ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES, ErrorReason.FORBIDDEN),
        404: (ErrorCode.RESOURCE_NOT_FOUND, ErrorReason.NOT_FOUND),
        409: (ErrorCode.CONTROL_NAME_CONFLICT, ErrorReason.CONFLICT),
        422: (ErrorCode.VALIDATION_ERROR, ErrorReason.UNPROCESSABLE_ENTITY),
        500: (ErrorCode.INTERNAL_ERROR, ErrorReason.INTERNAL_ERROR),
    }

    error_code, reason = status_to_error.get(
        exc.status_code, (ErrorCode.INTERNAL_ERROR, ErrorReason.UNKNOWN)
    )

    # Extract detail - handle both string and dict details
    if isinstance(exc.detail, dict):
        detail_str = exc.detail.get("message", str(exc.detail))
    else:
        detail_str = str(exc.detail)

    problem = ProblemDetail(
        type=make_error_type(error_code),
        title=ERROR_TITLES.get(error_code, "Error"),
        status=exc.status_code,
        detail=detail_str,
        instance=str(request.url.path),
        error_code=error_code,
        reason=reason,
        metadata=ErrorMetadata(),
    )

    headers: dict[str, str] | None = None
    if exc.status_code == 401:
        headers = {"WWW-Authenticate": "ApiKey"}

    return JSONResponse(
        status_code=exc.status_code,
        content=problem.model_dump(mode="json", exclude_none=True),
        headers=headers,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Exception handler for unhandled exceptions.

    Converts unexpected exceptions to RFC 7807 format.

    SECURITY NOTE: Stack traces are NEVER exposed to users, even in debug mode.
    Debug information is only logged server-side.
    """
    # Always log the full exception server-side for debugging
    logging.error(f"Unhandled exception: {exc}", exc_info=True)

    # SECURITY: Never expose internal details to users
    # Stack traces and exception messages may contain:
    # - File paths revealing server structure
    # - Database queries or credentials
    # - Internal logic details useful to attackers
    detail = "An unexpected error occurred. Please try again or contact support."

    # Generate a correlation ID for support to look up the full error in logs
    # In production, you'd want to use a proper request ID from middleware
    error_id = str(uuid.uuid4())[:8]
    logging.error(f"Error ID {error_id}: {traceback.format_exc()}")

    problem = ProblemDetail(
        type=make_error_type(ErrorCode.INTERNAL_ERROR),
        title="Internal Server Error",
        status=500,
        detail=detail,
        instance=str(request.url.path),
        error_code=ErrorCode.INTERNAL_ERROR,
        reason=ErrorReason.INTERNAL_ERROR,
        metadata=ErrorMetadata(request_id=error_id),
        hint=f"Reference error ID '{error_id}' when contacting support.",
    )

    # SECURITY: Only in explicitly local development, allow exception type
    # This requires BOTH debug=true AND running on localhost
    is_local_dev = (
        settings.debug
        and os.environ.get("AGENT_CONTROL_EXPOSE_ERRORS", "").lower() == "true"
    )
    if is_local_dev:
        logging.warning(
            "SECURITY: Exposing error details. "
            "Ensure AGENT_CONTROL_EXPOSE_ERRORS is not set in production!"
        )
        # Only expose exception type and message, never full traceback
        problem.detail = f"{type(exc).__name__}: {exc}"

    return JSONResponse(
        status_code=500,
        content=problem.model_dump(mode="json", exclude_none=True),
    )


async def validation_exception_handler(
    request: Request, exc: "RequestValidationError"
) -> JSONResponse:
    """
    Exception handler for Pydantic/FastAPI validation errors.

    Converts validation errors to GitHub-style error arrays within RFC 7807 format.
    """
    # Convert Pydantic errors to our format
    errors: list[ValidationErrorItem] = []

    for error in exc.errors():
        # Build field path from location
        loc = error.get("loc", ())
        # Skip 'body' prefix in location
        field_parts = [str(p) for p in loc if p != "body"]
        field = ".".join(field_parts) if field_parts else None

        # Determine resource from first path component
        resource = "Request"
        if field_parts:
            # Map common prefixes to resources
            prefix_map = {
                "agent": "Agent",
                "steps": "Step",
                "evaluators": "Evaluator",
                "data": "Control",
                "policy": "Policy",
            }
            first_part = field_parts[0].lower()
            resource = prefix_map.get(first_part, resource)

        errors.append(
            ValidationErrorItem(
                resource=resource,
                field=field,
                code=error.get("type", "validation_error"),
                message=error.get("msg", "Validation failed"),
                value=error.get("input"),
            )
        )

    problem = ProblemDetail(
        type=make_error_type(ErrorCode.VALIDATION_ERROR),
        title="Validation Error",
        status=422,
        detail=f"Request validation failed with {len(errors)} error(s)",
        instance=str(request.url.path),
        error_code=ErrorCode.VALIDATION_ERROR,
        reason=ErrorReason.UNPROCESSABLE_ENTITY,
        metadata=ErrorMetadata(),
        errors=errors,
        hint="Check the 'errors' array for field-level validation details.",
    )

    return JSONResponse(
        status_code=422,
        content=problem.model_dump(mode="json", exclude_none=True),
    )


# Type hint import for the handler
from fastapi.exceptions import RequestValidationError  # noqa: E402
