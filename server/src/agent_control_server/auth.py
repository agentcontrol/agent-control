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

import hashlib
import hmac
from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from agent_control_models.errors import ErrorCode, ErrorReason
from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader

from .config import auth_settings
from .errors import APIError, AuthenticationError, ForbiddenError
from .logging_utils import get_logger
from .models import DEFAULT_NAMESPACE_KEY
from .services.access import (
    CredentialIdentity,
    authenticate_database_api_key,
    database_has_active_credentials,
    resolve_database_credential,
)

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
    namespace_key: str = DEFAULT_NAMESPACE_KEY
    user_id: str | None = None
    api_key_id: str | None = None
    allowed_control_ids: frozenset[int] | None = None
    credential_source: str = "environment"

    @property
    def key_id(self) -> str:
        """Return a safe identifier for the key (first 8 chars + ellipsis)."""
        if self.api_key_id is not None:
            return self.api_key_id
        if len(self.api_key) > 8:
            return self.api_key[:8] + "..."
        return "***"

    @property
    def credential_fingerprint(self) -> str | None:
        """Return a non-secret fingerprint used to revalidate env-key sessions."""
        if not self.api_key:
            return None
        return _environment_fingerprint(self.api_key)


def _environment_fingerprint(raw_key: str) -> str:
    """Return a session-secret-keyed identifier, not an offline key verifier."""

    return hmac.new(
        auth_settings.get_session_secret().encode("utf-8"),
        raw_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _database_client(raw_key: str, identity: CredentialIdentity) -> AuthenticatedClient:
    return AuthenticatedClient(
        api_key=raw_key,
        is_admin=identity.is_admin,
        auth_level=AuthLevel.ADMIN if identity.is_admin else AuthLevel.API_KEY,
        namespace_key=identity.namespace_key,
        user_id=identity.user_id,
        api_key_id=identity.api_key_id,
        allowed_control_ids=identity.allowed_control_ids,
        credential_source="database",
    )


def _environment_client(raw_key: str) -> AuthenticatedClient:
    is_admin = auth_settings.is_admin_api_key(raw_key)
    return AuthenticatedClient(
        api_key=raw_key,
        is_admin=is_admin,
        auth_level=AuthLevel.ADMIN if is_admin else AuthLevel.API_KEY,
        # Environment keys are accepted only from the admin bootstrap list.
        allowed_control_ids=None,
        credential_source="environment",
    )


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


async def _authenticate_via_cookie(request: Request) -> AuthenticatedClient | None:
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

    source = claims.get("credential_source")
    if source == "database":
        api_key_id = claims.get("api_key_id")
        user_id = claims.get("user_id")
        if not isinstance(api_key_id, str) or not isinstance(user_id, str):
            return None
        identity = await resolve_database_credential(
            api_key_id, expected_user_id=user_id
        )
        if identity is None:
            return None
        return _database_client("", identity)

    if source == "environment":
        fingerprint = claims.get("credential_fingerprint")
        if not isinstance(fingerprint, str):
            return None
        configured_keys = auth_settings.get_admin_api_keys()
        for configured_key in configured_keys:
            configured_fingerprint = _environment_fingerprint(configured_key)
            if hmac.compare_digest(fingerprint, configured_fingerprint):
                return _environment_client(configured_key)
        return None

    return None


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

    # --- Path 1: X-API-Key header (takes strict priority) ---
    if api_key is not None:
        client: AuthenticatedClient | None = None
        if auth_settings.is_admin_api_key(api_key):
            client = _environment_client(api_key)
        else:
            identity = await authenticate_database_api_key(api_key)
            if identity is not None:
                client = _database_client(api_key, identity)

        if client is None:
            key_prefix = api_key[:8] if len(api_key) > 8 else "***"
            _logger.warning(f"Invalid API key attempted: {key_prefix}...")
            raise AuthenticationError(
                error_code=ErrorCode.AUTH_INVALID_KEY,
                detail="Invalid API key.",
                hint="Check that your API key is correct and has not expired.",
            )

        if require_admin and not client.is_admin:
            key_prefix = api_key[:8] if len(api_key) > 8 else "***"
            _logger.warning(f"Non-admin key attempted admin operation: {key_prefix}...")
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="This operation requires admin privileges.",
                hint="Use an admin API key for this operation.",
            )

        _logger.debug(f"Authenticated request with {client.auth_level.value} key")
        return client

    # --- Path 2: Session JWT cookie (fallback for browser clients) ---
    client = await _authenticate_via_cookie(request)
    if client is not None:
        if require_admin and not client.is_admin:
            _logger.warning("Non-admin session cookie attempted admin operation")
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="This operation requires admin privileges.",
                hint="Log in with an admin API key.",
            )
        return client

    # A presented but invalid/revoked cookie is an authentication failure,
    # not a server bootstrap misconfiguration.
    from .endpoints.system import SESSION_COOKIE_NAME

    if request.cookies.get(SESSION_COOKIE_NAME):
        raise AuthenticationError(
            error_code=ErrorCode.AUTH_INVALID_KEY,
            detail="Session is invalid, expired, or revoked.",
            hint="Log in again with an active API key.",
        )

    # Preserve the existing loud failure when auth is enabled without
    # either an environment bootstrap key or an active database key.
    all_environment_keys = auth_settings.get_admin_api_keys()
    if not all_environment_keys and not await database_has_active_credentials():
        _logger.error("API key authentication enabled but no active keys configured")
        raise APIError(
            status_code=500,
            error_code=ErrorCode.AUTH_MISCONFIGURED,
            reason=ErrorReason.INTERNAL_ERROR,
            detail="Server authentication misconfigured. Contact administrator.",
            hint=(
                "Configure an environment admin bootstrap key or create an active "
                "database API key."
            ),
        )

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
        if auth_settings.is_admin_api_key(api_key):
            return _environment_client(api_key)
        identity = await authenticate_database_api_key(api_key)
        return _database_client(api_key, identity) if identity is not None else None

    # Fallback to cookie
    return await _authenticate_via_cookie(request)


# Type aliases for cleaner endpoint signatures
RequireAPIKey = Annotated[AuthenticatedClient, Depends(require_api_key)]
RequireAdminKey = Annotated[AuthenticatedClient, Depends(require_admin_key)]
OptionalAPIKey = Annotated[AuthenticatedClient | None, Depends(optional_api_key)]
