"""Base HTTP client for Agent Control server communication."""

import hashlib
import logging
import os
from collections.abc import Generator
from types import TracebackType
from typing import Any, cast

import httpx

from . import __version__ as sdk_version
from .runtime_auth import (
    RuntimeAuthMode,
    RuntimeTokenCache,
    normalize_runtime_auth_mode,
    parse_runtime_token_exchange_response,
)

_logger = logging.getLogger(__name__)

_RUNTIME_AUTH_MODE_ENV_VAR = "AGENT_CONTROL_RUNTIME_AUTH_MODE"
_DEFAULT_RUNTIME_TOKEN_REFRESH_MARGIN_SECONDS = 30
_AUTO_RUNTIME_TOKEN_FALLBACK_STATUSES = {404, 500, 502, 503, 504}
_GLOBAL_RUNTIME_TOKEN_FALLBACK_STATUSES = {404}


def _runtime_cache_identity(api_key: str | None, api_key_header: str) -> str:
    """Return a stable cache identity without storing the raw credential."""
    normalized_header = api_key_header.lower()
    if not api_key:
        return f"api_key:{normalized_header}:anonymous"
    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    return f"api_key:{normalized_header}:{digest}"


class _AgentControlAuth(httpx.Auth):
    """Attach local API-key credentials unless a request already has Bearer auth."""

    def __init__(self, api_key: str | None, header_name: str = "X-API-Key") -> None:
        self._api_key = api_key
        self._header_name = header_name

    def auth_flow(
        self,
        request: httpx.Request,
    ) -> Generator[httpx.Request, httpx.Response, None]:
        if self._api_key and "Authorization" not in request.headers:
            if self._header_name not in request.headers:
                request.headers[self._header_name] = self._api_key
        yield request


class AgentControlClient:
    """
    Async HTTP client for Agent Control server.

    This is the base client that provides the HTTP connection management.
    Specific operations are organized into separate modules:
    agents, policies, controls, evaluation.

    Authentication:
        The client supports API key authentication. By default the key is
        sent on the ``X-API-Key`` header; set ``api_key_header`` (or the
        ``AGENT_CONTROL_API_KEY_HEADER`` environment variable) to override.
        API key can be provided:
        1. Directly via the `api_key` parameter
        2. Via the AGENT_CONTROL_API_KEY environment variable

    Usage:
        # Explicit API key
        async with AgentControlClient(api_key="my-secret-key") as client:
            await client.health_check()

        # From environment variable
        os.environ["AGENT_CONTROL_API_KEY"] = "my-secret-key"
        async with AgentControlClient() as client:
            await client.health_check()

        # Custom header name (e.g., when the upstream auth expects something
        # other than X-API-Key). The header name applies to every request
        # this client sends.
        async with AgentControlClient(
            api_key="my-secret-key", api_key_header="X-Custom-API-Key"
        ) as client:
            await client.health_check()
    """

    # Environment variable name for API key
    API_KEY_ENV_VAR = "AGENT_CONTROL_API_KEY"
    API_KEY_HEADER_ENV_VAR = "AGENT_CONTROL_API_KEY_HEADER"
    DEFAULT_API_KEY_HEADER = "X-API-Key"
    BASE_URL_ENV_VAR = "AGENT_CONTROL_URL"

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        api_key: str | None = None,
        api_key_header: str | None = None,
        runtime_auth_mode: RuntimeAuthMode | str | None = None,
        runtime_token_cache: RuntimeTokenCache | None = None,
        runtime_token_refresh_margin_seconds: int = (_DEFAULT_RUNTIME_TOKEN_REFRESH_MARGIN_SECONDS),
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the Agent Control server. If not provided,
                AGENT_CONTROL_URL is used, falling back to http://localhost:8000.
            timeout: Request timeout in seconds
            api_key: API key for authentication. If not provided, will attempt
                     to read from AGENT_CONTROL_API_KEY environment variable.
            api_key_header: HTTP header name to send the API key on. Defaults
                     to ``X-API-Key``; the AGENT_CONTROL_API_KEY_HEADER
                     environment variable overrides the default. Useful when
                     the configured upstream auth expects a different header.
            runtime_auth_mode: Runtime auth mode for evaluation requests. ``auto``
                attempts target-bound JWT exchange and falls back to normal
                request auth when the exchange endpoint is unavailable. ``jwt``
                requires a successful exchange. ``api_key`` and ``none`` keep
                evaluation requests on the normal request-auth path.
            runtime_token_cache: Optional cache shared across client instances.
            runtime_token_refresh_margin_seconds: Refresh cached runtime tokens
                before this many seconds of validity remain.
            transport: Optional httpx transport, primarily for tests.
        """
        resolved_base_url = base_url or os.environ.get(
            self.BASE_URL_ENV_VAR, "http://localhost:8000"
        )
        self.base_url = resolved_base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key or os.environ.get(self.API_KEY_ENV_VAR)
        self._api_key_header = (
            api_key_header
            or os.environ.get(self.API_KEY_HEADER_ENV_VAR)
            or self.DEFAULT_API_KEY_HEADER
        )
        self._runtime_cache_identity = _runtime_cache_identity(self._api_key, self._api_key_header)
        configured_runtime_mode = runtime_auth_mode or os.environ.get(_RUNTIME_AUTH_MODE_ENV_VAR)
        self._runtime_auth_mode = normalize_runtime_auth_mode(configured_runtime_mode)
        if runtime_token_refresh_margin_seconds < 0:
            raise ValueError("runtime_token_refresh_margin_seconds must be >= 0.")
        self._runtime_token_refresh_margin_seconds = runtime_token_refresh_margin_seconds
        self._runtime_token_cache = runtime_token_cache or RuntimeTokenCache()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._server_version_warning_emitted = False

    @property
    def api_key(self) -> str | None:
        """Get the configured API key (read-only)."""
        return self._api_key

    @property
    def api_key_header(self) -> str:
        """Get the header name the API key is sent on (read-only)."""
        return self._api_key_header

    @property
    def runtime_auth_mode(self) -> RuntimeAuthMode:
        """Get the configured runtime auth mode (read-only)."""
        return self._runtime_auth_mode

    def _get_headers(self) -> dict[str, str]:
        """Build base SDK metadata headers."""
        return {
            "X-Agent-Control-SDK": "python",
            "X-Agent-Control-SDK-Version": sdk_version,
        }

    async def _check_server_version(self, response: httpx.Response) -> None:
        """Warn once when the server major version differs from the SDK major."""
        if self._server_version_warning_emitted:
            return

        server_version = response.headers.get("X-Agent-Control-Server-Version")
        if not server_version:
            return

        sdk_major = sdk_version.split(".", 1)[0]
        server_major = server_version.split(".", 1)[0]
        if sdk_major == server_major:
            return

        _logger.warning(
            "Agent Control SDK major version %s is talking to server major version %s. "
            "Upgrade the SDK and server together to avoid control-schema mismatches.",
            sdk_version,
            server_version,
        )
        self._server_version_warning_emitted = True

    async def __aenter__(self) -> "AgentControlClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._get_headers(),
            auth=_AgentControlAuth(self._api_key, self._api_key_header),
            transport=self._transport,
            event_hooks={"response": [self._check_server_version]},
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    async def health_check(self) -> dict[str, str]:
        """
        Check server health.

        Returns:
            Dictionary with health status

        Raises:
            httpx.HTTPError: If request fails
        """
        if self._client is None:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")
        response = await self._client.get("/health")
        response.raise_for_status()
        from typing import cast

        return cast(dict[str, str], response.json())

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get the underlying HTTP client."""
        if self._client is None:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")
        return self._client

    async def post_runtime_evaluation(
        self,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> httpx.Response:
        """POST an evaluation request with runtime auth when configured."""
        runtime_authorization = await self._runtime_authorization(
            target_type=target_type,
            target_id=target_id,
        )
        request_headers = self._merge_runtime_headers(headers, runtime_authorization)
        response = await self.http_client.post(
            "/api/v1/evaluation",
            json=json,
            headers=request_headers,
        )

        if _should_refresh_runtime_token(response) and runtime_authorization is not None:
            await response.aread()
            if target_type is not None and target_id is not None:
                self._runtime_token_cache.remove(
                    self.base_url,
                    target_type,
                    target_id,
                    cache_identity=self._runtime_cache_identity,
                )
            runtime_authorization = await self._runtime_authorization(
                target_type=target_type,
                target_id=target_id,
                force_refresh=True,
                allow_auto_fallback=False,
            )
            request_headers = self._merge_runtime_headers(headers, runtime_authorization)
            response = await self.http_client.post(
                "/api/v1/evaluation",
                json=json,
                headers=request_headers,
            )
            if (
                _should_refresh_runtime_token(response)
                and target_type is not None
                and target_id is not None
            ):
                await response.aread()
                self._runtime_token_cache.remove(
                    self.base_url,
                    target_type,
                    target_id,
                    cache_identity=self._runtime_cache_identity,
                )

        return response

    def _merge_runtime_headers(
        self,
        headers: dict[str, str] | None,
        runtime_authorization: str | None,
    ) -> dict[str, str] | None:
        """Merge caller headers with an optional Bearer token."""
        if headers is None and runtime_authorization is None:
            return None

        merged = dict(headers or {})
        if runtime_authorization is not None:
            merged["Authorization"] = runtime_authorization
        return merged

    async def _runtime_authorization(
        self,
        *,
        target_type: str | None,
        target_id: str | None,
        force_refresh: bool = False,
        allow_auto_fallback: bool = True,
    ) -> str | None:
        """Return an Authorization header value for runtime evaluation."""
        if self._runtime_auth_mode in {"none", "api_key"}:
            return None

        if target_type is None or target_id is None:
            if self._runtime_auth_mode == "jwt":
                raise RuntimeError(
                    "runtime_auth_mode='jwt' requires target_type and target_id "
                    "for evaluation requests."
                )
            return None

        if (
            self._runtime_auth_mode == "auto"
            and not force_refresh
            and self._runtime_token_cache.is_jwt_unavailable(
                self.base_url,
                target_type,
                target_id,
                cache_identity=self._runtime_cache_identity,
            )
        ):
            return None

        if not force_refresh:
            cached = self._runtime_token_cache.get(
                self.base_url,
                target_type,
                target_id,
                cache_identity=self._runtime_cache_identity,
                refresh_margin_seconds=self._runtime_token_refresh_margin_seconds,
            )
            if cached is not None:
                return f"Bearer {cached.token}"

        exchange_lock = self._runtime_token_cache.exchange_lock(
            self.base_url,
            target_type,
            target_id,
            cache_identity=self._runtime_cache_identity,
        )
        async with exchange_lock:
            if (
                self._runtime_auth_mode == "auto"
                and not force_refresh
                and self._runtime_token_cache.is_jwt_unavailable(
                    self.base_url,
                    target_type,
                    target_id,
                    cache_identity=self._runtime_cache_identity,
                )
            ):
                return None
            if not force_refresh:
                cached = self._runtime_token_cache.get(
                    self.base_url,
                    target_type,
                    target_id,
                    cache_identity=self._runtime_cache_identity,
                    refresh_margin_seconds=self._runtime_token_refresh_margin_seconds,
                )
                if cached is not None:
                    return f"Bearer {cached.token}"

            token = await self._exchange_runtime_token(
                target_type=target_type,
                target_id=target_id,
                allow_auto_fallback=allow_auto_fallback,
            )
        if token is None:
            return None
        return f"Bearer {token}"

    async def _exchange_runtime_token(
        self,
        *,
        target_type: str,
        target_id: str,
        allow_auto_fallback: bool = True,
    ) -> str | None:
        """Exchange the configured credential for a target-bound runtime token."""
        try:
            response = await self.http_client.post(
                "/api/v1/auth/runtime-token-exchange",
                json={"target_type": target_type, "target_id": target_id},
            )
        except httpx.RequestError:
            if self._runtime_auth_mode == "auto" and allow_auto_fallback:
                _logger.debug(
                    "Runtime token exchange request failed; falling back to normal request auth "
                    "for %s/%s.",
                    target_type,
                    target_id,
                )
                self._runtime_token_cache.mark_jwt_unavailable(
                    server_url=self.base_url,
                    target_type=target_type,
                    target_id=target_id,
                    cache_identity=self._runtime_cache_identity,
                )
                return None
            raise

        if (
            self._runtime_auth_mode == "auto"
            and allow_auto_fallback
            and response.status_code in _AUTO_RUNTIME_TOKEN_FALLBACK_STATUSES
        ):
            _logger.debug(
                "Runtime token exchange returned HTTP %s; falling back to normal request auth "
                "for %s/%s.",
                response.status_code,
                target_type,
                target_id,
            )
            self._runtime_token_cache.mark_jwt_unavailable(
                server_url=self.base_url,
                target_type=target_type,
                target_id=target_id,
                cache_identity=self._runtime_cache_identity,
                globally=response.status_code in _GLOBAL_RUNTIME_TOKEN_FALLBACK_STATUSES,
            )
            return None

        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Runtime token exchange response was not an object.")
        token = parse_runtime_token_exchange_response(
            cast(dict[str, object], payload),
            server_url=self.base_url,
        )
        if token.target_type != target_type or token.target_id != target_id:
            raise RuntimeError(
                "Runtime token exchange response target did not match the requested target."
            )
        self._runtime_token_cache.set(token, cache_identity=self._runtime_cache_identity)
        return token.token


def _should_refresh_runtime_token(response: httpx.Response) -> bool:
    if response.status_code == 401:
        return True
    if response.status_code != 403:
        return False
    authenticate = response.headers.get("WWW-Authenticate", "")
    return "invalid_token" in authenticate.lower()
