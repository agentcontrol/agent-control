"""Forwards authorization decisions to a configurable upstream HTTP service.

Used by deployments that already have an authorization service of
record (Cerbos behind an internal API, an in-house RBAC, etc.). The
provider is generic: it speaks a small JSON protocol to a single
configurable URL, forwards the caller's credentials so the upstream
can identify them, and maps the upstream's HTTP status onto the
matching error.

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

Statuses other than 200 / 401 / 403 / 404 / 5xx fail closed (503).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from agent_control_models.errors import ErrorCode, ErrorReason
from fastapi import Request

from ...errors import APIError, AuthenticationError, ForbiddenError, NotFoundError
from ...logging_utils import get_logger
from ..core import Operation, Principal, RequestAuthorizer

_logger = get_logger(__name__)

_FORWARDED_HEADERS = ("X-API-Key", "Authorization", "Cookie")


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
        self._client = client or httpx.AsyncClient(timeout=config.timeout_seconds)

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

        return self._handle_response(response, operation)

    def _forward_headers(self, request: Request) -> dict[str, str]:
        headers: dict[str, str] = {}
        for name in _FORWARDED_HEADERS:
            value = request.headers.get(name)
            if value is not None:
                headers[name] = value
        if self._config.service_token is not None:
            headers[self._config.service_token_header] = self._config.service_token
        return headers

    def _handle_response(
        self, response: httpx.Response, operation: Operation
    ) -> Principal:
        status = response.status_code
        if status == 200:
            return self._parse_principal(response)
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
            detail="Authorization service returned an unexpected response.",
            hint="Retry the request; if the failure persists, contact the operator.",
        )

    def _parse_principal(self, response: httpx.Response) -> Principal:
        try:
            payload = response.json()
        except ValueError as exc:
            _logger.error("Auth upstream returned non-JSON payload: %s", exc)
            raise APIError(
                status_code=502,
                error_code=ErrorCode.AUTH_MISCONFIGURED,
                reason=ErrorReason.INTERNAL_ERROR,
                detail="Authorization service returned an invalid response.",
                hint="Contact the operator.",
            ) from exc

        namespace_key = payload.get("namespace_key")
        if not isinstance(namespace_key, str) or not namespace_key:
            _logger.error(
                "Auth upstream payload missing or empty 'namespace_key': %r", payload
            )
            raise APIError(
                status_code=502,
                error_code=ErrorCode.AUTH_MISCONFIGURED,
                reason=ErrorReason.INTERNAL_ERROR,
                detail="Authorization service returned a malformed principal.",
                hint="Contact the operator.",
            )

        is_admin = bool(payload.get("is_admin", False))
        caller_id = payload.get("caller_id")
        if caller_id is not None and not isinstance(caller_id, str):
            caller_id = None

        return Principal(
            namespace_key=namespace_key,
            is_admin=is_admin,
            caller_id=caller_id,
        )
