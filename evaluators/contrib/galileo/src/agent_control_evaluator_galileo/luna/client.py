"""Direct HTTP client for Galileo Luna scorer invocation."""

from __future__ import annotations

import logging
import os
import ssl
import warnings
from asyncio import Lock
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new
from json import dumps
from time import time
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from agent_control_models import JSONObject, JSONValue
from pydantic import BaseModel, Field, PrivateAttr, model_validator

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
# Keep pooled-connection reuse shorter than typical server keepalive/worker
# recycle windows so requests do not pick up sockets the server already closed.
DEFAULT_KEEPALIVE_EXPIRY_SECS = 1.0
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_CLIENT_POOL_SIZE = 1
LUNA_KEEPALIVE_EXPIRY_ENV = "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS"
LUNA_MAX_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_CONNECTIONS"
LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS"
LUNA_CLIENT_POOL_SIZE_ENV = "GALILEO_LUNA_CLIENT_POOL_SIZE"
PUBLIC_SCORER_INVOKE_PATH = "/scorers/invoke"
INTERNAL_SCORER_INVOKE_PATH = "/internal/scorers/invoke"
AuthMode = Literal["public", "internal"]


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _internal_auth_token(
    api_secret: str,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
) -> str:
    """Create the internal JWT expected by Galileo API internal routes."""
    now = int(time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "internal": True,
        "scope": "scorers.invoke",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    signing_input = ".".join(
        [
            _b64url(dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac_new(api_secret.encode("utf-8"), signing_input.encode("ascii"), sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _env_auth_mode() -> AuthMode | None:
    value = os.getenv("GALILEO_LUNA_AUTH_MODE")
    if value is None or value.strip() == "":
        return None
    deprecation_message = (
        "GALILEO_LUNA_AUTH_MODE is deprecated. Configure exactly one credential "
        "(GALILEO_API_KEY for public auth, GALILEO_API_SECRET_KEY for internal "
        "auth) or pass auth_mode to GalileoLunaClient."
    )
    warnings.warn(deprecation_message, DeprecationWarning, stacklevel=2)
    logger.warning(deprecation_message)
    normalized = value.strip().lower()
    if normalized == "public":
        return "public"
    if normalized == "internal":
        return "internal"
    raise ValueError("GALILEO_LUNA_AUTH_MODE must be either 'public' or 'internal'.")


def _load_float_env(env_name: str, default: float) -> float:
    raw = os.getenv(env_name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name}={raw!r} is not a number.") from exc


def _load_int_env(env_name: str, default: int) -> int:
    raw = os.getenv(env_name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name}={raw!r} is not an integer.") from exc


def _validate_connection_config(
    *,
    keepalive_expiry_seconds: float,
    max_connections: int,
    max_keepalive_connections: int,
    client_pool_size: int,
) -> None:
    if keepalive_expiry_seconds < 0:
        raise ValueError(
            f"{LUNA_KEEPALIVE_EXPIRY_ENV}={keepalive_expiry_seconds} "
            "must be greater than or equal to 0."
        )
    if max_connections <= 0:
        raise ValueError(f"{LUNA_MAX_CONNECTIONS_ENV}={max_connections} must be greater than 0.")
    if max_keepalive_connections < 0:
        raise ValueError(
            f"{LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV}={max_keepalive_connections} "
            "must be greater than or equal to 0."
        )
    if max_keepalive_connections > max_connections:
        raise ValueError(
            f"{LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV}={max_keepalive_connections} "
            f"must be less than or equal to {LUNA_MAX_CONNECTIONS_ENV}={max_connections}."
        )
    if client_pool_size <= 0:
        raise ValueError(f"{LUNA_CLIENT_POOL_SIZE_ENV}={client_pool_size} must be greater than 0.")


def _as_float_or_none(value: JSONValue) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _has_value(value: JSONValue) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


class ScorerInvokeInputs(BaseModel):
    """Input values sent to Galileo's scorer invoke API."""

    query: JSONValue = ""
    response: JSONValue = ""
    ground_truth: JSONValue = None
    tools: JSONValue = None


class ScorerInvokeRequest(BaseModel):
    """Request payload for Galileo Luna scorer invocation.

    Attributes:
        inputs: Selected scorer input values.
        scorer_label: Preset, registered, or fine-tuned scorer label.
        scorer_id: Optional Galileo scorer identifier.
        scorer_version_id: Optional Galileo scorer version identifier.
        config: Optional scorer-specific configuration.
    """

    inputs: ScorerInvokeInputs
    scorer_label: str | None = Field(default=None, min_length=1)
    scorer_id: str | None = Field(default=None, min_length=1)
    scorer_version_id: str | None = Field(default=None, min_length=1)
    config: JSONObject | None = None

    @model_validator(mode="after")
    def ensure_required_values(self) -> ScorerInvokeRequest:
        if not (self.scorer_label or self.scorer_id or self.scorer_version_id):
            raise ValueError(
                "One of scorer_label, scorer_id, or scorer_version_id must be set."
            )
        if not (_has_value(self.inputs.query) or _has_value(self.inputs.response)):
            raise ValueError("Either inputs.query or inputs.response must be set.")
        return self

    def to_dict(self) -> JSONObject:
        """Convert to the Galileo scorer invoke API request shape."""
        return self.model_dump(mode="json", exclude_none=True)


class ScorerInvokeResponse(BaseModel):
    """Response from Galileo Luna scorer invocation.

    Attributes:
        scorer_label: Echoed scorer label, when returned.
        score: Raw scorer value.
        status: Invocation status.
        execution_time: Execution time in seconds, when returned.
        error_message: Error detail for non-success statuses.
    """

    scorer_label: str | None = None
    score: JSONValue
    status: str = "unknown"
    execution_time: float | None = None
    error_message: str | None = None
    _raw_response: JSONObject = PrivateAttr(default_factory=dict)

    @property
    def raw_response(self) -> JSONObject:
        return self._raw_response

    @classmethod
    def from_dict(cls, data: JSONObject) -> ScorerInvokeResponse:
        """Create a response model from the API JSON object."""
        response = cls.model_validate(
            data | {"execution_time": _as_float_or_none(data.get("execution_time"))}
        )
        response._raw_response = data
        return response


class GalileoLunaClient:
    """Thin HTTP client for Galileo Luna direct scorer invocation.

    Environment Variables:
        GALILEO_API_SECRET_KEY: Deployment-provided Galileo API internal JWT signing secret.
        GALILEO_API_KEY: Galileo API key fallback for public scorer invocation.
        GALILEO_LUNA_API_URL: Galileo Luna scorer invoke API URL override.
        GALILEO_API_URL: Galileo API URL fallback.
        GALILEO_LUNA_CA_FILE: CA bundle used to verify the scorer API endpoint, for
            deployments whose API serves an internally-issued TLS certificate.
        GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS: HTTP pooled connection expiry.
        GALILEO_LUNA_MAX_CONNECTIONS: Maximum outbound HTTP connections.
        GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS: Maximum idle pooled HTTP connections.
        GALILEO_LUNA_CLIENT_POOL_SIZE: Number of outbound HTTP clients to rotate across.
        GALILEO_CONSOLE_URL: Galileo Console URL (optional, defaults to production).
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        console_url: str | None = None,
        api_url: str | None = None,
        auth_mode: AuthMode | None = None,
        ca_file: str | None = None,
    ) -> None:
        """Initialize the Galileo Luna client.

        Args:
            api_key: Galileo API key. If not provided, reads from GALILEO_API_KEY.
            api_secret: Deployment-provided Galileo API secret for internal JWT auth.
                If not provided, reads from GALILEO_API_SECRET_KEY.
            console_url: Galileo Console URL. If not provided, reads from
                GALILEO_CONSOLE_URL or uses the production console URL.
            api_url: Galileo API URL. If not provided, reads from GALILEO_LUNA_API_URL,
                then GALILEO_API_URL, before deriving from the console URL.
            auth_mode: Auth mode to use. If not provided, inferred from the single
                available credential.
            ca_file: CA bundle path used to verify the scorer API endpoint. If not
                provided, reads from GALILEO_LUNA_CA_FILE. Leave unset for endpoints
                with publicly-trusted certificates.

        Raises:
            ValueError: If credentials are missing, ambiguous, or incompatible with
                the selected auth mode, or if the CA bundle cannot be loaded.
        """
        resolved_api_secret = (
            api_secret or os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        )
        resolved_api_key = api_key or os.getenv("GALILEO_API_KEY")
        resolved_auth_mode = self._resolve_auth_mode(
            auth_mode or _env_auth_mode(),
            api_key=resolved_api_key,
            api_secret=resolved_api_secret,
        )

        self.api_key = resolved_api_key
        self.api_secret = resolved_api_secret
        self.auth_mode = resolved_auth_mode
        self.console_url = (
            console_url or os.getenv("GALILEO_CONSOLE_URL") or "https://console.galileo.ai"
        )
        self.api_base = self._resolve_api_base(api_url)
        self.ca_file = (ca_file or os.getenv("GALILEO_LUNA_CA_FILE") or "").strip() or None
        self._ssl_context = self._load_ssl_context(self.ca_file)
        self.keepalive_expiry_seconds = _load_float_env(
            LUNA_KEEPALIVE_EXPIRY_ENV, DEFAULT_KEEPALIVE_EXPIRY_SECS
        )
        self.max_connections = _load_int_env(LUNA_MAX_CONNECTIONS_ENV, DEFAULT_MAX_CONNECTIONS)
        self.max_keepalive_connections = _load_int_env(
            LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV, DEFAULT_MAX_KEEPALIVE_CONNECTIONS
        )
        self.client_pool_size = _load_int_env(
            LUNA_CLIENT_POOL_SIZE_ENV, DEFAULT_CLIENT_POOL_SIZE
        )
        _validate_connection_config(
            keepalive_expiry_seconds=self.keepalive_expiry_seconds,
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections,
            client_pool_size=self.client_pool_size,
        )
        self._client: httpx.AsyncClient | None = None
        self._clients: list[httpx.AsyncClient] = []
        self._next_client_index = 0
        self._client_lock = Lock()
        logger.info("[GalileoLunaClient] Auth mode selected: %s", self.auth_mode)

    def _resolve_api_base(self, api_url: str | None) -> str:
        """Resolve the scorer invoke API base URL from explicit and environment config."""
        candidates = [api_url, os.getenv("GALILEO_LUNA_API_URL")]
        candidates.append(os.getenv("GALILEO_API_URL"))

        for candidate in candidates:
            if candidate and candidate.strip():
                return candidate.strip().rstrip("/")
        return self._derive_api_url(self.console_url)

    @staticmethod
    def _load_ssl_context(ca_file: str | None) -> ssl.SSLContext | None:
        """Build a TLS verification context from a CA bundle path, if configured."""
        if ca_file is None:
            return None
        try:
            return ssl.create_default_context(cafile=ca_file)
        except (OSError, ssl.SSLError) as exc:
            raise ValueError(f"Failed to load CA bundle from {ca_file!r}: {exc}") from exc

    @staticmethod
    def _resolve_auth_mode(
        auth_mode: AuthMode | None,
        *,
        api_key: str | None,
        api_secret: str | None,
    ) -> AuthMode:
        if auth_mode == "public":
            if not api_key:
                raise ValueError("GALILEO_API_KEY is required for public Luna auth.")
            return "public"

        if auth_mode == "internal":
            if not api_secret:
                raise ValueError(
                    "GALILEO_API_SECRET_KEY is required for internal Luna auth."
                )
            return "internal"

        if api_key and api_secret:
            raise ValueError(
                "Both a Galileo API key and a Galileo API secret are configured. "
                "Unset one credential so the auth mode can be inferred, or pass "
                "auth_mode='public' or auth_mode='internal' explicitly."
            )
        if api_secret:
            return "internal"
        if api_key:
            return "public"
        raise ValueError(
            "GALILEO_API_SECRET_KEY or GALILEO_API_KEY is required. "
            "Set one as an environment variable or pass it to the constructor."
        )

    def _derive_api_url(self, console_url: str) -> str:
        """Derive the API URL from a Galileo Console URL.

        Galileo Console hostnames use ``console.`` or ``console-`` prefixes for
        canonical environments. For other HTTP(S) hosts, preserve the existing
        fallback behavior of prefixing the hostname with ``api.``.
        """
        url = console_url.rstrip("/")
        parts = urlsplit(url)
        host = parts.hostname or ""

        if host.startswith("console."):
            new_host = "api." + host[len("console."):]
        elif host.startswith("console-"):
            new_host = "api-" + host[len("console-"):]
        elif parts.scheme in {"http", "https"} and host:
            new_host = f"api.{host}"
        else:
            return url

        return urlunsplit(
            parts._replace(netloc=parts.netloc.replace(host, new_host, 1))
        )

    def _create_client(self) -> httpx.AsyncClient:
        """Create an HTTP client with the configured auth, TLS, and connection limits."""
        headers = {"Content-Type": "application/json"}
        if self.auth_mode == "public" and self.api_key is not None:
            headers["Galileo-API-Key"] = self.api_key
        verify: ssl.SSLContext | bool = (
            self._ssl_context if self._ssl_context is not None else True
        )
        return httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECS),
            limits=httpx.Limits(
                max_connections=self.max_connections,
                max_keepalive_connections=self.max_keepalive_connections,
                keepalive_expiry=self.keepalive_expiry_seconds,
            ),
            verify=verify,
        )

    def _select_pooled_client(self) -> httpx.AsyncClient:
        """Select the next pooled client while holding the client state lock."""
        client = self._clients[self._next_client_index % len(self._clients)]
        self._next_client_index = (self._next_client_index + 1) % len(self._clients)
        return client

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the next HTTP client."""
        async with self._client_lock:
            self._clients = [client for client in self._clients if not client.is_closed]

            if self.client_pool_size == 1:
                if self._client is not None and not self._client.is_closed:
                    return self._client
                self._client = self._clients[0] if self._clients else self._create_client()
                self._clients = [self._client]
                return self._client

            self._client = None
            while len(self._clients) < self.client_pool_size:
                self._clients.append(self._create_client())

            return self._select_pooled_client()

    def _endpoint_and_headers(
        self,
        headers: dict[str, str] | None,
    ) -> tuple[str, dict[str, str]]:
        request_headers = dict(headers or {})
        if self.auth_mode == "public":
            return f"{self.api_base}{PUBLIC_SCORER_INVOKE_PATH}", request_headers

        if self.api_secret is None:
            raise RuntimeError("Internal Luna auth mode is missing an API secret.")
        request_headers["Authorization"] = f"Bearer {_internal_auth_token(self.api_secret)}"
        return f"{self.api_base}{INTERNAL_SCORER_INVOKE_PATH}", request_headers

    async def invoke(
        self,
        *,
        scorer_label: str | None = None,
        scorer_id: str | None = None,
        scorer_version_id: str | None = None,
        input: JSONValue = None,
        output: JSONValue = None,
        config: JSONObject | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        headers: dict[str, str] | None = None,
    ) -> ScorerInvokeResponse:
        """Invoke a Galileo Luna scorer.

        Args:
            scorer_label: Preset, registered, or fine-tuned scorer label.
            scorer_id: Optional Galileo scorer identifier.
            scorer_version_id: Optional Galileo scorer version identifier.
            input: Optional user/system prompt text.
            output: Optional model response text.
            config: Optional scorer-specific configuration.
            timeout: Request timeout in seconds.
            headers: Additional request headers.

        Returns:
            Parsed scorer invocation response.

        Raises:
            ValueError: If neither input nor output is provided.
            RuntimeError: If the API response is not a JSON object.
            httpx.HTTPStatusError: If the API returns an error status code.
            httpx.RequestError: If the request fails before a response is received.
        """
        if not (scorer_label or scorer_id or scorer_version_id):
            raise ValueError("At least one scorer identifier must be provided.")
        if not (_has_value(input) or _has_value(output)):
            raise ValueError("At least one of input or output must be provided.")

        request_body = ScorerInvokeRequest(
            scorer_label=scorer_label,
            scorer_id=scorer_id,
            scorer_version_id=scorer_version_id,
            inputs=ScorerInvokeInputs(
                query="" if input is None else input, response="" if output is None else output
            ),
            config=config,
        ).to_dict()
        endpoint, request_headers = self._endpoint_and_headers(headers)

        logger.debug("[GalileoLunaClient] POST %s", endpoint)
        logger.debug("[GalileoLunaClient] Request body: %s", request_body)

        try:
            client = await self._get_client()
            response = await client.post(
                endpoint,
                json=request_body,
                headers=request_headers,
                timeout=timeout,
            )
            response.raise_for_status()
            response_data = response.json()
            if not isinstance(response_data, dict):
                raise RuntimeError("Invalid response payload: not a JSON object")

            parsed = ScorerInvokeResponse.from_dict(response_data)
            logger.debug("[GalileoLunaClient] Response: %s", parsed.raw_response)
            return parsed
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[GalileoLunaClient] API error: %s - %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        except httpx.RequestError as exc:
            logger.error("[GalileoLunaClient] Request failed: %s", exc)
            raise

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        async with self._client_lock:
            clients: list[httpx.AsyncClient] = []
            seen_client_ids: set[int] = set()
            if self._client is not None:
                clients.append(self._client)
                seen_client_ids.add(id(self._client))
            self._client = None
            for client in self._clients:
                if id(client) not in seen_client_ids:
                    clients.append(client)
                    seen_client_ids.add(id(client))
            self._clients = []
            self._next_client_index = 0

            for client in clients:
                if not client.is_closed:
                    await client.aclose()

    async def __aenter__(self) -> GalileoLunaClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Async context manager exit."""
        await self.close()
