"""HTTP upstream provider.

Forwards the caller's credentials (API key, JWT, cookie — whatever the
upstream system accepts) to a configurable HTTP endpoint and uses the
upstream's allow/deny response to decide. Agent Control does not parse
credentials itself; it treats every relevant header and cookie as opaque
and hands them to the upstream unchanged.

The upstream endpoint receives a JSON body describing the operation and
its context. It authenticates the forwarded credential, authorizes the
action, and responds with either a principal or a deny code. AC maps the
upstream's deny codes onto HTTP statuses:

- ``AUTHN_FAILED`` → 401
- ``INSUFFICIENT_PERMISSIONS`` → 403
- ``TARGET_NOT_FOUND`` → 404
- anything else → 500

An unreachable upstream or a 5xx from the upstream is treated as fail-closed
and surfaces as 503 to the client.

The upstream URL, the endpoint path, and the service-to-service identity
header are all configurable. No upstream-specific nouns are baked in; any
HTTP service that speaks this contract can be an upstream.
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException, Request

from ...logging_utils import get_logger
from ..base import ManagementOperation, ManagementPrincipal

_logger = get_logger(__name__)

# Credential-bearing request headers that should be forwarded verbatim to the
# upstream. These are the common HTTP auth carriers; specific upstreams that
# use different headers can add to this via ``extra_forwarded_headers``.
_DEFAULT_FORWARDED_HEADERS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "x-galileo-api-key",
    "x-api-key",
)


class HttpUpstreamManagementAuthorizer:
    """Calls an upstream HTTP endpoint to authn+authz each management request.

    Configuration:

    - ``upstream_url`` — base URL of the upstream (e.g. ``http://api:8088``).
    - ``check_path`` — path on the upstream to POST (default
      ``/internal/auth/check_management_access``).
    - ``service_token`` — optional service-to-service token AC presents to
      the upstream in a configured header. Separate from the caller's
      credential, which is forwarded in its own headers/cookies.
    - ``service_token_header`` — header name for the service token
      (default ``X-Agent-Control-Service-Token``).
    - ``extra_forwarded_headers`` — additional credential headers to
      forward besides the defaults.
    - ``timeout_seconds`` — per-request timeout. Failures or timeouts
      fail closed (503).
    """

    def __init__(
        self,
        *,
        upstream_url: str,
        check_path: str = "/internal/auth/check_management_access",
        service_token: str | None = None,
        service_token_header: str = "X-Agent-Control-Service-Token",
        extra_forwarded_headers: tuple[str, ...] = (),
        timeout_seconds: float = 5.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._upstream_url = upstream_url.rstrip("/")
        self._check_path = check_path if check_path.startswith("/") else f"/{check_path}"
        self._service_token = service_token
        self._service_token_header = service_token_header
        forwarded = set(h.lower() for h in _DEFAULT_FORWARDED_HEADERS)
        forwarded.update(h.lower() for h in extra_forwarded_headers)
        self._forwarded_headers = frozenset(forwarded)
        self._timeout_seconds = timeout_seconds
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def authorize(
        self,
        request: Request,
        *,
        operation: ManagementOperation,
        context: dict[str, object],
    ) -> ManagementPrincipal:
        outbound_headers = self._build_outbound_headers(request)
        body: dict[str, object] = {"operation": operation.value}
        body["context"] = context or None

        try:
            response = await self._client.post(
                f"{self._upstream_url}{self._check_path}",
                headers=outbound_headers,
                json=body,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            _logger.warning(
                "Management authz upstream unreachable: %s",
                exc,
                extra={"operation": operation.value, "upstream_url": self._upstream_url},
            )
            raise HTTPException(
                status_code=503,
                detail="Management authorization service is unavailable.",
            ) from exc

        if 500 <= response.status_code < 600:
            _logger.warning(
                "Management authz upstream returned server error",
                extra={
                    "operation": operation.value,
                    "status_code": response.status_code,
                    "upstream_url": self._upstream_url,
                },
            )
            raise HTTPException(
                status_code=503,
                detail="Management authorization service is unavailable.",
            )

        if response.status_code == 401:
            raise HTTPException(status_code=401, detail="Authentication failed.")
        if response.status_code == 403:
            raise HTTPException(status_code=403, detail="Permission denied.")
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Target not found.")
        if response.status_code == 400:
            # Shape/validation problem on the upstream — surface as-is.
            try:
                payload = response.json()
                detail = str(payload.get("detail") or payload.get("reason") or "Bad request.")
            except ValueError:
                detail = "Bad request."
            raise HTTPException(status_code=400, detail=detail)

        if response.status_code != 200:
            _logger.warning(
                "Management authz upstream returned unexpected status",
                extra={
                    "operation": operation.value,
                    "status_code": response.status_code,
                    "upstream_url": self._upstream_url,
                },
            )
            raise HTTPException(
                status_code=502,
                detail="Management authorization service returned an unexpected response.",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Management authorization service returned an invalid response.",
            ) from exc

        if not payload.get("allowed", False):
            # Allowed is the 200 contract, but guard against upstream mis-use.
            raise HTTPException(status_code=403, detail="Permission denied.")

        principal_payload = payload.get("principal") or {}
        tenant_id = principal_payload.get("tenant_id")
        if not tenant_id:
            raise HTTPException(
                status_code=502,
                detail="Management authorization service returned an incomplete principal.",
            )
        subject_id = principal_payload.get("subject_id")
        return ManagementPrincipal(
            tenant_id=str(tenant_id),
            subject_id=str(subject_id) if subject_id else None,
        )

    def _build_outbound_headers(self, request: Request) -> dict[str, str]:
        outbound: dict[str, str] = {"Content-Type": "application/json"}
        for name, value in request.headers.items():
            if name.lower() in self._forwarded_headers:
                outbound[name] = value
        if self._service_token:
            outbound[self._service_token_header] = self._service_token
        return outbound

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()
