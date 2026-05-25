"""Forwards authorization decisions to a configurable upstream HTTP service.

Used by deployments that already have an authorization service of
record. The provider is generic: it speaks a small JSON protocol to a
single configurable URL, forwards the caller's credentials so the
upstream can identify them, and maps the upstream's HTTP status onto
the matching error.

Wire protocol
-------------

Request (POST to ``upstream_url``):

.. code-block:: json

    {
        "operation": "control_bindings.write",
        "context": { "...optional path params..." }
    }

with the caller's credentials forwarded as request headers (the
provider sets ``X-API-Key``, ``Authorization``, and the ``Cookie``
header from the inbound request) plus an optional service-to-service
token header for upstream→authorization-service trust.

Response (200): JSON object

.. code-block:: json

    {
        "namespace_key": "...",
        "is_admin": false,
        "caller_id": "..."
    }

Statuses other than 200 / 401 / 403 / 404 / 429 fail closed. Unexpected
upstream 4xx responses are reported separately from Agent Control
misconfiguration so operators can distinguish upstream request rejection
from local auth setup failures.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from agent_control_models.errors import ErrorCode, ErrorReason
from fastapi import Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ...errors import APIError, AuthenticationError, ForbiddenError, NotFoundError
from ...logging_utils import get_logger
from ..core import Operation, Principal, RequestAuthorizer

_logger = get_logger(__name__)

_DEFAULT_FORWARDED_HEADERS = ("X-API-Key", "Authorization", "Cookie")


class _UpstreamGrant(BaseModel):
    """Strict schema for the upstream authorization-service response.

    Unknown fields are tolerated (so the upstream can evolve), but every
    *known* field is type-checked. A wrong type on any field - or a
    half-supplied target binding - causes the provider to fail closed
    with a 502.
    """

    model_config = ConfigDict(extra="ignore", strict=True)

    namespace_key: str = Field(min_length=1)
    is_admin: bool = False
    caller_id: str | None = None
    target_type: str | None = Field(default=None, min_length=1)
    target_id: str | None = Field(default=None, min_length=1)
    scopes: tuple[str, ...] = ()
    expires_at: datetime | None = None

    @field_validator("expires_at", mode="after")
    @classmethod
    def _expires_at_must_be_timezone_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        """Reject naive ``expires_at`` values.

        A naive datetime carries no timezone, so comparing it against
        ``datetime.now(UTC)`` during token mint raises ``TypeError`` and
        surfaces as a 500. Fail closed at the parser instead so a
        malformed-but-accepted grant becomes a clean 502 alongside the
        rest of the strict-grant rejections.
        """
        if value is not None and value.tzinfo is None:
            raise ValueError(
                "expires_at must include timezone information (e.g., a UTC offset)"
            )
        return value

    @model_validator(mode="after")
    def _target_must_be_paired(self) -> _UpstreamGrant:
        """Reject a grant that supplies only one half of the target binding.

        A target is meaningful only as a ``(target_type, target_id)``
        pair; allowing one side without the other would let a malformed
        grant pass and the exchange endpoint mint a token for the
        request's value of the missing half - outside the upstream's
        intended authorization.
        """
        if (self.target_type is None) != (self.target_id is None):
            raise ValueError(
                "target_type and target_id must both be supplied or both omitted"
            )
        return self


@dataclass(frozen=True)
class HttpUpstreamConfig:
    """Configuration for :class:`HttpUpstreamAuthProvider`."""

    url: str
    """Full URL the provider POSTs each authorization request to."""

    timeout_seconds: float = 5.0
    """Per-request timeout. Network errors fail closed (503)."""

    service_token: str | None = None
    """Optional service-to-service shared secret. Sent in the
    ``service_token_header`` so the upstream can verify the caller is
    Agent Control. Leave unset if the upstream uses a different trust
    model."""

    service_token_header: str = "X-Agent-Control-Service-Token"

    extra_forward_headers: tuple[str, ...] = ()
    """Additional inbound request headers to forward to the upstream
    on top of the default ``(X-API-Key, Authorization, Cookie)`` set.

    Use this when the upstream authenticates via a header the provider
    does not forward by default (e.g., a deployer-specific API-key
    header). Header lookups against the inbound request are
    case-insensitive; an empty or absent inbound header is silently
    dropped. Names duplicating the default set or each other (after
    case-folding) are deduplicated."""

    ca_file: str | None = None
    """Optional CA bundle path used only when verifying the auth upstream."""

    def __post_init__(self) -> None:
        if self.service_token is None:
            return
        forwarded = {
            name.lower()
            for name in (*_DEFAULT_FORWARDED_HEADERS, *self.extra_forward_headers)
        }
        if self.service_token_header.lower() in forwarded:
            raise ValueError(
                "service_token_header must not match a forwarded caller credential header"
            )


class HttpUpstreamAuthProvider(RequestAuthorizer):
    """Delegates authorization to an upstream HTTP service."""

    def __init__(
        self,
        config: HttpUpstreamConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        if client is not None:
            self._client = client
        elif config.ca_file is not None:
            ssl_context = ssl.create_default_context(cafile=config.ca_file)
            self._client = httpx.AsyncClient(
                timeout=config.timeout_seconds,
                verify=ssl_context,
            )
        else:
            self._client = httpx.AsyncClient(timeout=config.timeout_seconds)

    async def aclose(self) -> None:
        """Release the HTTP client if this provider created it."""
        if self._owns_client:
            await self._client.aclose()

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        headers = self._forward_headers(request)
        payload: dict[str, Any] = {"operation": operation.value}
        if context:
            payload["context"] = context

        try:
            response = await self._client.post(
                self._config.url,
                json=payload,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            _logger.warning(
                "Auth upstream unreachable for operation %s: %s",
                operation.value,
                exc,
            )
            raise APIError(
                status_code=503,
                error_code=ErrorCode.AUTH_MISCONFIGURED,
                reason=ErrorReason.SERVICE_UNAVAILABLE,
                detail="Authorization service unavailable.",
                hint="Retry the request; if the failure persists, contact the operator.",
            ) from exc

        return self._handle_response(response, operation, context)

    def _forward_headers(self, request: Request) -> dict[str, str]:
        headers: dict[str, str] = {}
        seen: set[str] = set()
        for name in (*_DEFAULT_FORWARDED_HEADERS, *self._config.extra_forward_headers):
            lower = name.lower()
            if lower in seen:
                continue
            seen.add(lower)
            value = request.headers.get(name)
            if value is not None:
                headers[name] = value
        if self._config.service_token is not None:
            headers[self._config.service_token_header] = self._config.service_token
        return headers

    def _handle_response(
        self,
        response: httpx.Response,
        operation: Operation,
        context: dict[str, Any] | None,
    ) -> Principal:
        status = response.status_code
        if status == 200:
            principal = self._parse_principal(response)
            _ensure_target_context_matches_grant(context, principal)
            return principal
        if status == 401:
            raise AuthenticationError(
                error_code=ErrorCode.AUTH_INVALID_KEY,
                detail="Authentication failed at the upstream service.",
                hint="Provide a valid credential.",
            )
        if status == 403:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail=f"Not authorized to perform {operation.value!r}.",
                hint="Contact your administrator if you expected access.",
            )
        if status == 404:
            raise NotFoundError(
                error_code=ErrorCode.AUTH_INVALID_KEY,
                detail="Resource not found.",
                resource="Resource",
                hint="Verify the resource exists in the requested namespace.",
            )
        if status == 429:
            # Surface upstream rate limiting distinctly. Folding it into
            # the catch-all 503 hides a transient, retryable signal from
            # operators and clients; a dedicated 503 with a different
            # detail/hint preserves the structured error code while
            # naming the failure mode.
            retry_after = response.headers.get("Retry-After")
            hint = (
                "The authorization service is rate-limiting requests; "
                "back off and retry."
            )
            if retry_after is not None:
                hint = f"{hint} Retry-After: {retry_after}."
            _logger.warning(
                "Upstream returned 429 for operation %s",
                operation.value,
            )
            raise APIError(
                status_code=503,
                error_code=ErrorCode.AUTH_MISCONFIGURED,
                reason=ErrorReason.SERVICE_UNAVAILABLE,
                detail="Authorization service is rate-limiting requests.",
                hint=hint,
            )
        if 400 <= status < 500:
            _logger.warning(
                "Authorization upstream rejected operation %s with status %d",
                operation.value,
                status,
            )
            raise APIError(
                status_code=502,
                error_code=ErrorCode.AUTH_UPSTREAM_REJECTED,
                reason=ErrorReason.INTERNAL_ERROR,
                detail=(
                    "Authorization service rejected the authorization check "
                    f"(status {status})."
                ),
                hint=(
                    "Check that the Agent Control authorization request shape "
                    "matches the upstream authorization service contract."
                ),
            )
        # Fail closed on 5xx and unexpected statuses.
        _logger.warning(
            "Unexpected upstream status %d for operation %s",
            status,
            operation.value,
        )
        raise APIError(
            status_code=503,
            error_code=ErrorCode.AUTH_MISCONFIGURED,
            reason=ErrorReason.SERVICE_UNAVAILABLE,
            detail=f"Authorization service returned an unexpected response (status {status}).",
            hint="Retry the request; if the failure persists, contact the operator.",
        )

    def _parse_principal(self, response: httpx.Response) -> Principal:
        # Validate against the raw JSON bytes so Pydantic's JSON parser
        # accepts ISO datetimes, JSON arrays (for ``scopes``), etc.,
        # while strict mode still rejects type-coercion mistakes like
        # ``"false"`` for ``is_admin`` or non-string entries in
        # ``scopes``. Validating ``response.json()`` output instead
        # would round-trip through Python types and fail on legitimate
        # wire-shape input (datetimes-as-strings, tuples-as-lists).
        try:
            grant = _UpstreamGrant.model_validate_json(response.content)
        except ValidationError as exc:
            _logger.error(
                "Auth upstream returned a malformed grant: %s",
                exc.errors(),
            )
            raise APIError(
                status_code=502,
                error_code=ErrorCode.AUTH_MISCONFIGURED,
                reason=ErrorReason.INTERNAL_ERROR,
                detail="Authorization service returned a malformed principal.",
                hint="Contact the operator.",
            ) from exc

        return Principal(
            namespace_key=grant.namespace_key,
            is_admin=grant.is_admin,
            caller_id=grant.caller_id,
            target_type=grant.target_type,
            target_id=grant.target_id,
            scopes=grant.scopes,
            grant_expires_at=grant.expires_at,
        )


def _ensure_target_context_matches_grant(
    context: dict[str, Any] | None,
    principal: Principal,
) -> None:
    """Reject target-bound grants that do not match the requested target."""
    if principal.target_type is None and principal.target_id is None:
        return
    if context is None:
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="Authorization grant is target-bound but the request target is unavailable.",
            hint=(
                "Use an endpoint that includes target_type and target_id "
                "in the authorization context."
            ),
        )

    expected_type = context.get("target_type")
    expected_id = context.get("target_id")
    if not isinstance(expected_type, str) or not isinstance(expected_id, str):
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="Authorization grant is target-bound but the request target is incomplete.",
            hint="Provide both target_type and target_id for target-bound credentials.",
        )
    if principal.target_type == expected_type and principal.target_id == expected_id:
        return

    raise ForbiddenError(
        error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
        detail="Authorization grant target does not match the requested target.",
        hint="Retry with credentials authorized for the requested target.",
    )
