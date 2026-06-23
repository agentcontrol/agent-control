"""Direct HTTP client for Galileo Luna scorer invocation."""

from __future__ import annotations

import logging
import os
import ssl
from asyncio import Lock
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new
from json import dumps
from time import time
from urllib.parse import urlsplit

import httpx
from agent_control_models import JSONObject, JSONValue
from pydantic import BaseModel, Field, PrivateAttr, model_validator

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
DEFAULT_LUNA_SCORER_INVOKE_PATH = "/api/v1/scorers/invoke"
LUNA_INVOKE_URL_ENV = "GALILEO_LUNA_INVOKE_URL"
LUNA_INVOKE_CA_FILE_ENV = "GALILEO_LUNA_INVOKE_CA_FILE"
AUTH_UPSTREAM_CA_FILE_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE"

# Headers that must never be forwarded to the Luna invoke endpoint (checked case-insensitively).
_BLOCKED_REQUEST_HEADERS = frozenset({"galileo-api-key"})

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


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _internal_auth_token(
    api_secret: str,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
) -> str:
    """Create the internal JWT expected by Luna scorer invoke routes."""
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


def _normalize_luna_invoke_url(raw_url: str) -> str:
    """Use full invoke URLs as-is and append the default path to bare service roots."""
    url = raw_url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return url
    return f"{url}{DEFAULT_LUNA_SCORER_INVOKE_PATH}"


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
    """Input values sent to the Luna scorer invoke endpoint."""

    query: JSONValue = ""
    response: JSONValue = ""
    ground_truth: JSONValue = None
    tools: JSONValue = None


class ScorerInvokeRequest(BaseModel):
    """Request payload for Luna scorer invocation.

    Attributes:
        scorer_id: Required scorer identifier.
        scorer_version_id: Optional pinned scorer version identifier.
        scorer_label: Optional display/metadata label.
        inputs: Selected scorer input values.
        config: Scorer-specific configuration, always emitted.
    """

    scorer_id: str = Field(min_length=1)
    scorer_version_id: str | None = Field(default=None, min_length=1)
    scorer_label: str | None = Field(default=None, min_length=1)
    inputs: ScorerInvokeInputs
    config: JSONObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_required_values(self) -> ScorerInvokeRequest:
        if not (_has_value(self.inputs.query) or _has_value(self.inputs.response)):
            raise ValueError("Either inputs.query or inputs.response must be set.")
        return self

    def to_dict(self) -> JSONObject:
        """Convert to the Luna scorer invoke request shape."""
        return self.model_dump(mode="json", exclude_none=True)


class ScorerInvokeResponse(BaseModel):
    """Response from Luna scorer invocation.

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
        """Create a response model from the Luna scorer invoke JSON object."""
        response = cls.model_validate(
            data | {"execution_time": _as_float_or_none(data.get("execution_time"))}
        )
        response._raw_response = data
        return response


class GalileoLunaClient:
    """Thin HTTP client for Galileo Luna scorer invocation.

    Environment Variables:
        GALILEO_API_SECRET_KEY or GALILEO_API_SECRET: JWT signing secret for internal auth.
        GALILEO_LUNA_INVOKE_URL: Luna scorer invoke URL or service root (required).
        GALILEO_LUNA_INVOKE_CA_FILE: CA bundle used to verify Luna invoke TLS.
        AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE: Shared internal CA fallback.
        GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS: HTTP pooled connection expiry.
        GALILEO_LUNA_MAX_CONNECTIONS: Maximum outbound HTTP connections.
        GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS: Maximum idle pooled HTTP connections.
        GALILEO_LUNA_CLIENT_POOL_SIZE: Number of outbound HTTP clients to rotate across.
    """

    def __init__(
        self,
        api_secret: str | None = None,
        luna_invoke_url: str | None = None,
        luna_invoke_ca_file: str | None = None,
    ) -> None:
        """Initialize the Galileo Luna client.

        Args:
            api_secret: Internal JWT signing secret. If not provided, reads from
                GALILEO_API_SECRET_KEY or GALILEO_API_SECRET.
            luna_invoke_url: Luna scorer invoke URL or service root. If not provided,
                reads from GALILEO_LUNA_INVOKE_URL.
            luna_invoke_ca_file: Optional CA bundle used to verify Luna invoke TLS. If not
                provided, reads from GALILEO_LUNA_INVOKE_CA_FILE, then
                AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE.

        Raises:
            ValueError: If the API secret, Luna invoke URL, CA bundle, or connection
                tuning configuration is invalid.
        """
        resolved_api_secret = (
            api_secret or os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        )
        if not resolved_api_secret:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for Luna "
                "scorer invocation. Set one as an environment variable or pass it "
                "to the constructor."
            )

        resolved_luna_invoke_url = luna_invoke_url or os.getenv(LUNA_INVOKE_URL_ENV)
        if resolved_luna_invoke_url is None or resolved_luna_invoke_url.strip() == "":
            raise ValueError(
                "GALILEO_LUNA_INVOKE_URL is required for Luna scorer invocation. "
                "Set it as an environment variable or pass it to the constructor."
            )

        self.api_secret = resolved_api_secret
        self.luna_invoke_url = _normalize_luna_invoke_url(resolved_luna_invoke_url)
        self.luna_invoke_ca_file = (
            luna_invoke_ca_file
            or os.getenv(LUNA_INVOKE_CA_FILE_ENV)
            or os.getenv(AUTH_UPSTREAM_CA_FILE_ENV)
            or ""
        ).strip() or None
        self._ssl_context = self._load_ssl_context(self.luna_invoke_ca_file)
        self.keepalive_expiry_seconds = _load_float_env(
            LUNA_KEEPALIVE_EXPIRY_ENV, DEFAULT_KEEPALIVE_EXPIRY_SECS
        )
        self.max_connections = _load_int_env(LUNA_MAX_CONNECTIONS_ENV, DEFAULT_MAX_CONNECTIONS)
        self.max_keepalive_connections = _load_int_env(
            LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV, DEFAULT_MAX_KEEPALIVE_CONNECTIONS
        )
        self.client_pool_size = _load_int_env(LUNA_CLIENT_POOL_SIZE_ENV, DEFAULT_CLIENT_POOL_SIZE)
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

    @staticmethod
    def _load_ssl_context(ca_file: str | None) -> ssl.SSLContext | None:
        """Build a TLS verification context from a CA bundle path, if configured."""
        if ca_file is None:
            return None
        try:
            return ssl.create_default_context(cafile=ca_file)
        except (OSError, ssl.SSLError) as exc:
            raise ValueError(f"Failed to load CA bundle from {ca_file!r}: {exc}") from exc

    def _create_client(self) -> httpx.AsyncClient:
        """Create an HTTP client with the configured TLS and connection limits."""
        verify: ssl.SSLContext | bool = self._ssl_context if self._ssl_context is not None else True
        return httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
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

    def _endpoint_and_auth_header(self) -> tuple[str, str]:
        token = _internal_auth_token(self.api_secret)
        return self.luna_invoke_url, f"Bearer {token}"

    async def invoke(
        self,
        *,
        scorer_id: str,
        scorer_version_id: str | None = None,
        scorer_label: str | None = None,
        input: JSONValue = None,
        output: JSONValue = None,
        config: JSONObject | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        headers: dict[str, str] | None = None,
    ) -> ScorerInvokeResponse:
        """Invoke a Galileo Luna scorer.

        Args:
            scorer_id: Required scorer identifier.
            scorer_version_id: Optional pinned scorer version identifier.
            scorer_label: Optional display/metadata label.
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
            httpx.HTTPStatusError: If the Luna invoke endpoint returns an error status code.
            httpx.RequestError: If the request fails before a response is received.
        """
        if not (_has_value(input) or _has_value(output)):
            raise ValueError("At least one of input or output must be provided.")

        request_body = ScorerInvokeRequest(
            scorer_id=scorer_id,
            scorer_version_id=scorer_version_id,
            scorer_label=scorer_label,
            inputs=ScorerInvokeInputs(
                query="" if input is None else input, response="" if output is None else output
            ),
            config=config if config is not None else {},
        ).to_dict()

        endpoint, auth_header = self._endpoint_and_auth_header()
        request_headers = {
            k: v for k, v in (headers or {}).items() if k.lower() not in _BLOCKED_REQUEST_HEADERS
        }
        request_headers["Authorization"] = auth_header

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
        """Close HTTP clients and release resources."""
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
