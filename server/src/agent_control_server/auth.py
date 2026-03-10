"""
API key authentication for Agent Control Server.

This module provides flexible authentication dependencies that can be applied
to individual routers or endpoints with different security requirements.

Two credential sources are supported (checked in this order):

1. **X-API-Key header** — used by SDKs and programmatic clients.
2. **Session JWT cookie** — used by the browser UI after ``POST /api/login``.

If the header is present it is used exclusively (succeed or fail).  The cookie
is only checked when no header is provided.

Usage:
    # In a router file:
    from ..auth import require_api_key, require_admin_key

    # Apply to entire router (in main.py)
    app.include_router(router, dependencies=[Depends(require_api_key)])

    # Or apply to specific endpoints
    @router.get("/sensitive", dependencies=[Depends(require_admin_key)])
    async def sensitive_endpoint():
        ...

    # Access the validated key info in endpoint
    @router.get("/whoami")
    async def whoami(client: AuthenticatedClient = Depends(require_api_key)):
        return {"key_prefix": client.key_id}
"""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from agent_control_models.errors import ErrorCode, ErrorReason
from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from .config import auth_settings
from .errors import APIError, AuthenticationError, ForbiddenError
from .logging_utils import get_logger

_logger = get_logger(__name__)


class AuthLevel(Enum):
    """Authentication level for categorizing access."""

    NONE = "none"  # No authentication required (auth disabled)
    API_KEY = "api_key"  # Standard API key required
    ADMIN = "admin"  # Admin API key required


@dataclass
class AuthenticatedClient:
    """
    Represents an authenticated API client.

    This dataclass provides information about the authenticated request,
    useful for logging, auditing, or conditional logic.
    """

    api_key: str
    is_admin: bool
    auth_level: AuthLevel

    @property
    def key_id(self) -> str:
        """Return a safe identifier for the key (first 8 chars + ellipsis)."""
        if len(self.api_key) > 8:
            return self.api_key[:8] + "..."
        return "***"


# Header extractor - doesn't validate, just extracts
_api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,  # Don't auto-raise; we handle errors ourselves
    description="API key for authentication. Required for all protected endpoints.",
)


async def get_api_key_from_header(
    api_key: str | None = Security(_api_key_header),
) -> str | None:
    """
    Extract API key from header without validation.

    Use this when you need the raw key value for custom validation logic.
    """
    return api_key


def _authenticate_via_cookie(request: Request) -> AuthenticatedClient | None:
    """Try to authenticate using the session JWT cookie.

    Returns an ``AuthenticatedClient`` on success or ``None`` when no valid
    cookie is present.  Importing here avoids a circular import with
    ``endpoints.system`` (both share ``config`` but this module must not
    import endpoint code at module level).
    """
    from .endpoints.system import SESSION_COOKIE_NAME, decode_session_jwt

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    claims = decode_session_jwt(token)
    if claims is None:
        _logger.debug("Session cookie present but JWT is invalid or expired")
        return None

    is_admin: bool = claims.get("is_admin", False)
    auth_level = AuthLevel.ADMIN if is_admin else AuthLevel.API_KEY
    _logger.debug("Authenticated request via session cookie (%s)", auth_level.value)
    return AuthenticatedClient(
        api_key="",
        is_admin=is_admin,
        auth_level=auth_level,
    )


async def _validate_api_key(
    api_key: str | None,
    request: Request,
    require_admin: bool = False,
) -> AuthenticatedClient:
    """
    Internal validation logic for API keys.

    Credential precedence:
    1. ``X-API-Key`` header (if present, used exclusively — succeed or fail).
    2. Session JWT cookie (checked only when no header is provided).

    Args:
        api_key: The API key from the request header (may be None)
        request: The incoming request (used to read cookies)
        require_admin: Whether admin privileges are required

    Returns:
        AuthenticatedClient with key details

    Raises:
        AuthenticationError: If authentication fails
        ForbiddenError: If insufficient privileges
        APIError: If authentication is misconfigured (AUTH_MISCONFIGURED)
    """
    # Skip validation if auth is disabled
    if not auth_settings.api_key_enabled:
        _logger.debug("Authentication disabled, allowing request")
        return AuthenticatedClient(
            api_key="",
            is_admin=False,
            auth_level=AuthLevel.NONE,
        )

    # Check that at least one API key is configured
    all_keys = auth_settings.get_api_keys() | auth_settings.get_admin_api_keys()
    if not all_keys:
        _logger.error("API key authentication enabled but no keys configured")
        raise APIError(
            status_code=500,
            error_code=ErrorCode.AUTH_MISCONFIGURED,
            reason=ErrorReason.INTERNAL_ERROR,
            detail="Server authentication misconfigured. Contact administrator.",
            hint="Server operator must configure API keys via environment variables.",
        )

    # --- Path 1: X-API-Key header (takes strict priority) ---
    if api_key is not None:
        if not auth_settings.is_valid_api_key(api_key):
            key_prefix = api_key[:8] if len(api_key) > 8 else "***"
            _logger.warning(f"Invalid API key attempted: {key_prefix}...")
            raise AuthenticationError(
                error_code=ErrorCode.AUTH_INVALID_KEY,
                detail="Invalid API key.",
                hint="Check that your API key is correct and has not expired.",
            )

        is_admin = auth_settings.is_admin_api_key(api_key)
        if require_admin and not is_admin:
            key_prefix = api_key[:8] if len(api_key) > 8 else "***"
            _logger.warning(f"Non-admin key attempted admin operation: {key_prefix}...")
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="This operation requires admin privileges.",
                hint="Use an admin API key for this operation.",
            )

        auth_level = AuthLevel.ADMIN if is_admin else AuthLevel.API_KEY
        _logger.debug(f"Authenticated request with {auth_level.value} key")
        return AuthenticatedClient(api_key=api_key, is_admin=is_admin, auth_level=auth_level)

    # --- Path 2: Session JWT cookie (fallback for browser clients) ---
    client = _authenticate_via_cookie(request)
    if client is not None:
        if require_admin and not client.is_admin:
            _logger.warning("Non-admin session cookie attempted admin operation")
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="This operation requires admin privileges.",
                hint="Log in with an admin API key.",
            )
        return client

    # --- Neither credential present ---
    _logger.warning("Request missing API key and session cookie")
    raise AuthenticationError(
        error_code=ErrorCode.AUTH_MISSING_KEY,
        detail="Missing credentials. Provide 'X-API-Key' header or log in via the UI.",
        hint="Include the 'X-API-Key' header with a valid API key, or log in at /api/login.",
    )


async def require_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> AuthenticatedClient:
    """
    Dependency that requires a valid API key or session cookie.

    Credential precedence: X-API-Key header first, then session JWT cookie.

    Use as a router dependency or endpoint dependency:

        # Apply to router in main.py
        app.include_router(router, dependencies=[Depends(require_api_key)])

        # Or access the client info in endpoint:
        @router.get("/info")
        async def get_info(client: AuthenticatedClient = Depends(require_api_key)):
            print(f"Request from: {client.key_id}")
    """
    return await _validate_api_key(api_key, request, require_admin=False)


async def require_admin_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> AuthenticatedClient:
    """
    Dependency that requires an admin API key or admin session cookie.

    Use for sensitive operations like evaluator management or configuration:

        @router.delete("/dangerous", dependencies=[Depends(require_admin_key)])
        async def dangerous_op():
            ...
    """
    return await _validate_api_key(api_key, request, require_admin=True)


async def optional_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> AuthenticatedClient | None:
    """
    Dependency that accepts optional authentication.

    Returns AuthenticatedClient if valid key or session cookie provided,
    None otherwise.  Does not raise errors for missing/invalid credentials.

    Useful for endpoints that behave differently for authenticated users:

        @router.get("/data")
        async def get_data(client: AuthenticatedClient | None = Depends(optional_api_key)):
            if client and client.is_admin:
                return full_data()
            return limited_data()
    """
    if not auth_settings.api_key_enabled:
        return None

    # Header takes priority
    if api_key is not None:
        if not auth_settings.is_valid_api_key(api_key):
            return None
        is_admin = auth_settings.is_admin_api_key(api_key)
        return AuthenticatedClient(
            api_key=api_key,
            is_admin=is_admin,
            auth_level=AuthLevel.ADMIN if is_admin else AuthLevel.API_KEY,
        )

    # Fallback to cookie
    return _authenticate_via_cookie(request)


# Type aliases for cleaner endpoint signatures
RequireAPIKey = Annotated[AuthenticatedClient, Depends(require_api_key)]
RequireAdminKey = Annotated[AuthenticatedClient, Depends(require_admin_key)]
OptionalAPIKey = Annotated[AuthenticatedClient | None, Depends(optional_api_key)]

