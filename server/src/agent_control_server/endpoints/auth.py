"""Auth endpoints (runtime token exchange).

The runtime auth flow is two-phase: this endpoint is phase one. The
caller presents a long-lived credential plus ``(target_type,
target_id)``; the configured authorization provider authenticates the
credential and authorizes the implied
``runtime.token_exchange`` operation. On success, this endpoint
mints a short-lived local runtime token bound to the supplied target
and returns it. Subsequent target-bearing runtime calls present the
returned token, which is verified locally by
the runtime JWT provider.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from agent_control_models.errors import ErrorCode, ErrorReason
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..auth_framework import Operation, Principal, require_operation
from ..auth_framework.config import runtime_auth_config
from ..auth_framework.runtime_token import (
    RuntimeTokenError,
    UpstreamGrantExpiredError,
    mint_runtime_token,
)
from ..errors import APIError, BadRequestError
from ..logging_utils import get_logger

router = APIRouter(prefix="/auth", tags=["auth"])
_logger = get_logger(__name__)


def _log_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class RuntimeTokenExchangeRequest(BaseModel):
    """Body for the runtime token exchange endpoint."""

    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(
        ..., description="Opaque target kind (e.g., ``session``).", min_length=1
    )
    target_id: str = Field(..., description="Opaque target identifier.", min_length=1)


class RuntimeTokenExchangeResponse(BaseModel):
    """Issued runtime token plus its expiry."""

    token: str = Field(..., description="Short-lived runtime token (HS256 JWT).")
    expires_at: datetime = Field(..., description="UTC timestamp at which the token expires.")
    target_type: str = Field(..., description="Target the token is bound to.")
    target_id: str = Field(..., description="Target the token is bound to.")
    scopes: list[str] = Field(
        ..., description="Granted runtime scopes; always includes ``runtime.use``."
    )


async def _exchange_context(request: Request) -> dict[str, Any]:
    """Surface target identifiers to the authorization context.

    Reads the request body once. FastAPI caches the parsed body, so the
    endpoint's own Pydantic body model still binds normally.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001  malformed JSON, defer to endpoint validation
        return {}
    if not isinstance(body, dict):
        return {}
    return {
        "target_type": body.get("target_type"),
        "target_id": body.get("target_id"),
    }


@router.post(
    "/runtime-token-exchange",
    response_model=RuntimeTokenExchangeResponse,
    summary="Exchange a credential for a runtime token bound to a target",
)
async def runtime_token_exchange(
    body: RuntimeTokenExchangeRequest,
    principal: Principal = Depends(
        require_operation(
            Operation.RUNTIME_TOKEN_EXCHANGE,
            context_builder=_exchange_context,
        )
    ),
) -> RuntimeTokenExchangeResponse:
    """Mint a short-lived runtime token for the requested target.

    The caller's credential is authenticated and authorized before the
    resolved principal supplies the actor identity, grant scopes, and
    expiry. This endpoint then mints a local HS256 token whose lifetime
    cannot outlive the grant.

    Runtime auth must be enabled via
    ``AGENT_CONTROL_RUNTIME_TOKEN_SECRET``; otherwise the endpoint
    returns 503.
    """
    config = runtime_auth_config()
    if config is None:
        raise APIError(
            status_code=503,
            error_code=ErrorCode.AUTH_MISCONFIGURED,
            reason=ErrorReason.SERVICE_UNAVAILABLE,
            detail=(
                "Runtime auth is not enabled on this server "
                "(AGENT_CONTROL_RUNTIME_TOKEN_SECRET is not set)."
            ),
            hint="Configure the runtime token secret to enable this endpoint.",
        )

    # When the provider returns its own target binding (e.g., upstream
    # validated the target), require it to match the request body.
    if principal.target_type is not None and principal.target_type != body.target_type:
        raise BadRequestError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail=("Authorized target_type does not match the requested target_type."),
            hint="Ensure the credential is scoped to the requested target.",
        )
    if principal.target_id is not None and principal.target_id != body.target_id:
        raise BadRequestError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail=("Authorized target_id does not match the requested target_id."),
            hint="Ensure the credential is scoped to the requested target.",
        )

    actor_id = principal.caller_id or "anonymous"
    # The exchange endpoint requires the authorizer to explicitly grant
    # runtime.use. Local providers supply a normalized grant for
    # ``RUNTIME_TOKEN_EXCHANGE``;
    # upstream providers that return an explicit empty scopes array fail
    # closed here rather than escalating to runtime.use.
    if Operation.RUNTIME_USE.value not in principal.scopes:
        raise BadRequestError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail=("Authorizer grant does not include runtime.use; cannot mint a runtime token."),
            hint=("The credential is not authorized for runtime use on this target."),
        )
    scopes = principal.scopes

    try:
        token, claims = mint_runtime_token(
            namespace_key=principal.namespace_key,
            actor_id=actor_id,
            target_type=body.target_type,
            target_id=body.target_id,
            scopes=scopes,
            secret=config.secret,
            ttl_seconds=config.ttl_seconds,
            upstream_expires_at=principal.grant_expires_at,
        )
    except UpstreamGrantExpiredError as exc:
        # Upstream returned a grant whose ``expires_at`` is already in
        # the past - minting would hand the caller a token that's dead
        # on arrival. Distinguished from the misconfigured case so the
        # error code and status reflect "upstream returned bad data."
        raise APIError(
            status_code=502,
            error_code=ErrorCode.AUTH_MISCONFIGURED,
            reason=ErrorReason.INTERNAL_ERROR,
            detail="Authorization service returned an already-expired grant.",
            hint=(
                "Retry the request to obtain a fresh grant; "
                "if the failure persists, contact the operator."
            ),
        ) from exc
    except RuntimeTokenError as exc:
        raise APIError(
            status_code=503,
            error_code=ErrorCode.AUTH_MISCONFIGURED,
            reason=ErrorReason.SERVICE_UNAVAILABLE,
            detail=str(exc),
            hint="Check the runtime token configuration.",
        ) from exc

    _logger.info(
        "Runtime token exchanged",
        extra={
            "namespace_key": claims.namespace_key,
            "actor_id_hash": _log_hash(claims.actor_id),
            "target_type": claims.target_type,
            "target_id": claims.target_id,
            "scopes": list(claims.scopes),
            "expires_at": claims.expires_at.isoformat(),
            "jti": claims.jti,
        },
    )

    return RuntimeTokenExchangeResponse(
        token=token,
        expires_at=claims.expires_at,
        target_type=claims.target_type,
        target_id=claims.target_id,
        scopes=list(claims.scopes),
    )
