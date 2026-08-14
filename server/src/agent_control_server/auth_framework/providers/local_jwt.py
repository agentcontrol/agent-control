"""Authorizer that verifies a locally-minted runtime token.

Wired to the runtime resolution path. Reads a Bearer token from a
configurable header (``Authorization`` by default), verifies the
signature against the runtime secret, checks the token's scope covers
the requested operation, and returns a :class:`Principal` carrying the
bound target. When a ``context_builder`` on the dependency must surface
matching ``target_type`` / ``target_id`` values for target-bound tokens.

The header the runtime token arrives on is configurable so the server
can sit behind a gateway that reserves ``Authorization`` for its own
downstream identity JWT. When the token rides a dedicated header (e.g.
``X-Agent-Control-Runtime-Token``), the ``Bearer`` scheme prefix is
optional; on ``Authorization`` it stays required for back-compat.
"""

from __future__ import annotations

from typing import Any

from agent_control_models.errors import ErrorCode
from fastapi import Request

from ...errors import AuthenticationError, ForbiddenError
from ..core import Operation, Principal, RequestAuthorizer
from ..runtime_token import RuntimeTokenError, verify_runtime_token

DEFAULT_RUNTIME_TOKEN_HEADER = "Authorization"


class LocalJwtVerifyProvider(RequestAuthorizer):
    """Verifies a runtime Bearer token and emits a target-bound :class:`Principal`."""

    def __init__(
        self,
        *,
        secret: str,
        header_name: str = DEFAULT_RUNTIME_TOKEN_HEADER,
    ) -> None:
        if not secret:
            raise ValueError("LocalJwtVerifyProvider requires a non-empty secret.")
        if not header_name or not header_name.strip():
            raise ValueError("LocalJwtVerifyProvider requires a non-empty header_name.")
        self._secret = secret
        self._header_name = header_name.strip()
        # The Bearer scheme is mandatory on Authorization (existing SDK
        # contract) but optional on a dedicated runtime-token header,
        # where the raw token is the whole value.
        # Mirror of AgentControlClient._runtime_token_use_bearer in the SDK —
        # the verifier's expectation and the send format must stay in sync.
        self._require_bearer = self._header_name.lower() == "authorization"

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        token = self._extract_bearer_token(request)
        try:
            claims = verify_runtime_token(token, self._secret)
        except RuntimeTokenError as exc:
            raise AuthenticationError(
                error_code=ErrorCode.AUTH_INVALID_KEY,
                detail=str(exc),
                hint="Re-exchange a fresh runtime token and retry.",
            ) from exc

        if operation.value not in claims.scopes:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail=(
                    f"Runtime token does not grant {operation.value!r}; "
                    f"granted scopes: {list(claims.scopes)}."
                ),
                hint="Request a token with the required scope.",
            )

        requested_target_type = context.get("target_type") if context is not None else None
        requested_target_id = context.get("target_id") if context is not None else None
        if requested_target_type != claims.target_type:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="Runtime token target_type does not match the request.",
                hint="Re-exchange a token bound to the request target.",
            )
        if requested_target_id != claims.target_id:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="Runtime token target_id does not match the request.",
                hint="Re-exchange a token bound to the request target.",
            )

        return Principal(
            namespace_key=claims.namespace_key,
            caller_id=claims.actor_id,
            target_type=claims.target_type,
            target_id=claims.target_id,
            scopes=claims.scopes,
            grant_expires_at=claims.expires_at,
        )

    def _extract_bearer_token(self, request: Request) -> str:
        header = request.headers.get(self._header_name)
        if not header:
            raise AuthenticationError(
                error_code=ErrorCode.AUTH_MISSING_KEY,
                detail=f"Missing {self._header_name} header.",
                hint="Present a Bearer runtime token.",
            )
        scheme, sep, value = header.partition(" ")
        if sep and scheme.lower() == "bearer":
            token = value.strip()
        elif self._require_bearer:
            raise AuthenticationError(
                error_code=ErrorCode.AUTH_MISSING_KEY,
                detail=f"{self._header_name} header must be a Bearer token.",
                hint=f"Format: ``{self._header_name}: Bearer <token>``.",
            )
        else:
            # Dedicated runtime-token header: accept the raw token.
            token = header.strip()
        if not token:
            raise AuthenticationError(
                error_code=ErrorCode.AUTH_MISSING_KEY,
                detail=f"{self._header_name} header is empty.",
                hint="Present a Bearer runtime token.",
            )
        return token
