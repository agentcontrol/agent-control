"""System-level endpoints: UI configuration discovery, login, and logout.

These endpoints let the static UI bundle:
 - Discover whether API-key authentication is enabled.
 - Exchange an API key for a signed JWT stored in an HttpOnly cookie.
 - Clear the session cookie on logout.

The JWT cookie is accepted as an alternative credential by the ``require_api_key``
dependency so that browser clients never need to store or transmit raw keys after
the initial login POST.
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Final

import jwt
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from ..auth import AuthLevel, OptionalAPIKey
from ..config import auth_settings, settings
from ..logging_utils import get_logger

router = APIRouter(prefix="", tags=["system"])

_logger = get_logger(__name__)

SESSION_COOKIE_NAME: Final[str] = "agent_control_session"
JWT_ALGORITHM: Final[str] = "HS256"
SESSION_MAX_AGE_SECONDS: Final[int] = 30 * 24 * 60 * 60  # 1 month


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------


class AuthMode(StrEnum):
    """Authentication mode advertised to the UI."""

    NONE = "none"
    API_KEY = "api-key"


class ConfigResponse(BaseModel):
    """Configuration surface exposed to the UI."""

    requires_api_key: bool
    auth_mode: AuthMode
    has_active_session: bool = False


class LoginRequest(BaseModel):
    """Request body for the /login endpoint."""

    api_key: str


class LoginResponse(BaseModel):
    """Response body for the /login endpoint."""

    authenticated: bool
    is_admin: bool


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_session_jwt(*, is_admin: bool) -> str:
    """Mint a signed session JWT. The raw API key is never stored in claims."""
    now = int(time.time())
    payload = {
        "sub": "ac-session",
        "is_admin": is_admin,
        "iat": now,
        "exp": now + SESSION_MAX_AGE_SECONDS,
    }
    return jwt.encode(payload, auth_settings.get_session_secret(), algorithm=JWT_ALGORITHM)


def decode_session_jwt(token: str) -> dict | None:
    """Validate and decode a session JWT. Returns None on any failure."""
    try:
        return jwt.decode(
            token,
            auth_settings.get_session_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat", "is_admin"]},
        )
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/config",
    response_model=ConfigResponse,
    summary="UI configuration",
    response_description="Configuration flags for UI behavior",
)
async def get_config(client: OptionalAPIKey) -> ConfigResponse:
    """Return configuration flags that drive UI behavior.

    If authentication is enabled, this also reports whether the current
    request has an active session (via header or cookie), allowing the UI
    to skip the login prompt on refresh when a valid cookie is present.
    """
    requires = auth_settings.api_key_enabled
    has_session = client is not None and client.auth_level is not AuthLevel.NONE
    return ConfigResponse(
        requires_api_key=requires,
        auth_mode=AuthMode.API_KEY if requires else AuthMode.NONE,
        has_active_session=has_session,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login with API key",
    response_description="Authentication result; sets HttpOnly session cookie on success",
    status_code=status.HTTP_200_OK,
)
async def login(body: LoginRequest, request: Request, response: Response) -> LoginResponse:
    """Validate an API key and issue a signed JWT session cookie.

    The raw API key is transmitted only in this single request and is never
    stored in the cookie.  Subsequent requests authenticate via the JWT.
    """
    # Reject plaintext login unless we're in debug mode or the request is to localhost.
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    scheme = forwarded_proto or request.url.scheme
    hostname = (request.url.hostname or "").lower()
    is_localhost = hostname in ("localhost", "127.0.0.1", "[::1]")
    allow_http = settings.debug or is_localhost

    if scheme == "http" and not allow_http:
        _logger.warning("Login attempt over plain HTTP rejected (non-localhost, non-debug)")
        response.status_code = status.HTTP_403_FORBIDDEN
        return LoginResponse(authenticated=False, is_admin=False)

    api_key = body.api_key.strip()
    if not api_key or not auth_settings.is_valid_api_key(api_key):
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return LoginResponse(authenticated=False, is_admin=False)

    is_admin = auth_settings.is_admin_api_key(api_key)
    token = create_session_jwt(is_admin=is_admin)

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=not allow_http,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE_SECONDS,
    )

    return LoginResponse(authenticated=True, is_admin=is_admin)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout (clear session cookie)",
)
async def logout(request: Request, response: Response) -> None:
    """Clear the session cookie."""
    hostname = (request.url.hostname or "").lower()
    is_localhost = hostname in ("localhost", "127.0.0.1", "[::1]")
    allow_http = settings.debug or is_localhost

    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=not allow_http,
        samesite="lax",
    )
