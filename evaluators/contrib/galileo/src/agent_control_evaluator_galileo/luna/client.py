"""Direct HTTP client for Galileo Luna scorer invocation."""

from __future__ import annotations

import logging
import os
import ssl
from asyncio import Lock
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from hashlib import sha256
from hmac import new as hmac_new
from json import dumps
from time import time
from typing import Literal, cast, get_args
from urllib.parse import urlsplit

import httpx
from agent_control_models import JSONObject, JSONValue, Step
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from .config import ScorerInvokeConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
SERVER_TIMEOUT_RATIO = 0.8
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
DEFAULT_LUNA_SCORER_INVOKE_PATH = "/api/v1/scorers/invoke"
SCORER_GRANT_PATH = "/internal/auth/scorer_grant"
LUNA_INVOKE_URL_ENV = "GALILEO_LUNA_INVOKE_URL"
ORBIT_API_URL_ENV = "GALILEO_API_URL"
GALILEO_API_KEY_ENV = "GALILEO_API_KEY"
GALILEO_API_SECRET_KEY_ENV = "GALILEO_API_SECRET_KEY"
GALILEO_API_SECRET_ENV = "GALILEO_API_SECRET"
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

# These values mirror Orbit's StepType discriminator. Agent Control's generic
# Step remains extensible; only the Galileo transport boundary is constrained.
ScorerInvokeRecordType = Literal[
    "llm",
    "retriever",
    "tool",
    "workflow",
    "agent",
    "control",
    "trace",
    "session",
]
SUPPORTED_SCORER_INVOKE_RECORD_TYPES = frozenset(get_args(ScorerInvokeRecordType))


def _normalize_luna_invoke_url(raw_url: str) -> str:
    """Use full invoke URLs as-is and append the default path to bare service roots."""
    url = raw_url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return url
    return f"{url}{DEFAULT_LUNA_SCORER_INVOKE_PATH}"


def _normalize_orbit_url(raw_url: str) -> str:
    """Normalize the configured Galileo API root used for grant exchange."""
    return raw_url.strip().rstrip("/")


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _internal_auth_token(
    api_secret: str,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
) -> str:
    """Create the legacy internal JWT expected by Luna scorer invoke routes."""
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


def _run_id_from_target(target_type: str | None, target_id: str | None) -> str:
    """Resolve the Orbit run ID from Agent Control's opaque evaluation target."""
    if target_type is None or target_id is None:
        raise ValueError("target_type and target_id must be supplied together for scorer grants.")
    if target_type != "log_stream":
        raise ValueError("Galileo scorer grants require target_type='log_stream'.")
    resolved_target_id = target_id.strip()
    if not resolved_target_id:
        raise ValueError("target_id must be a non-empty log-stream ID for scorer grants.")
    return resolved_target_id


class _ScorerGrant(BaseModel):
    """Orbit-issued grant and its expiration time."""

    token: str
    expires_at: datetime


_scorer_grant_cache: dict[tuple[str, str, str, str], _ScorerGrant] = {}
_scorer_grant_cache_lock = Lock()


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


def _effective_scorer_timeout(
    config: ScorerInvokeConfig,
    *,
    http_timeout_seconds: float,
) -> ScorerInvokeConfig:
    """Resolve an Orbit execution timeout that expires before the HTTP request.

    The server execution budget defaults to 80% of the caller's HTTP deadline,
    leaving time for Orbit to serialize and return the result. Explicit caller
    overrides are preserved only when they maintain the same ordering.

    Args:
        config: Caller-provided scorer-invoke configuration.
        http_timeout_seconds: Agent Control's HTTP request deadline in seconds.

    Returns:
        A scorer-invoke configuration with an effective execution timeout.

    Raises:
        ValueError: If either deadline is invalid or the explicit server timeout
            is not shorter than the HTTP deadline.
    """
    if http_timeout_seconds <= 0:
        raise ValueError("HTTP timeout must be greater than 0 seconds.")

    server_timeout = config.request_timeout_seconds
    if server_timeout is None:
        server_timeout = http_timeout_seconds * SERVER_TIMEOUT_RATIO
    elif server_timeout >= http_timeout_seconds:
        raise ValueError(
            "config.request_timeout_seconds must be shorter than the HTTP "
            f"timeout ({http_timeout_seconds:g} seconds)."
        )

    return config.model_copy(update={"request_timeout_seconds": server_timeout})


class ScorerInvokeInputs(BaseModel):
    """Input values sent to the Luna scorer invoke endpoint."""

    query: JSONValue = ""
    response: JSONValue = ""
    ground_truth: JSONValue = None
    tools: list[JSONObject] | None = None


class ScorerInvokeRecord(BaseModel):
    """Caller-controlled subset of Orbit's partial runtime-record contract.

    Identity, ownership, persistence, and execution IDs are intentionally not
    represented here. Orbit hydrates those fields from trusted server context.
    """

    type: ScorerInvokeRecordType
    name: str | None = None
    input: JSONValue = None
    output: JSONValue = None
    context: JSONObject | None = None
    tools: list[JSONObject] | None = None
    dataset_output: JSONValue = None


class ScorerInvokeRequest(BaseModel):
    """Request payload for Luna scorer invocation.

    Attributes:
        scorer_id: Required scorer identifier.
        scorer_version_id: Deprecated optional compatibility identifier. Orbit
            currently invokes the scorer's current default version.
        scorer_label: Optional display/metadata label.
        inputs: Selected scorer input values.
        record: Optional Orbit-compatible structured runtime record.
        config: Scorer-specific configuration, always emitted.
    """

    scorer_id: str = Field(min_length=1)
    scorer_version_id: str | None = Field(default=None, min_length=1)
    scorer_label: str | None = Field(default=None, min_length=1)
    inputs: ScorerInvokeInputs
    record: ScorerInvokeRecord | None = None
    config: ScorerInvokeConfig = Field(default_factory=ScorerInvokeConfig)

    @model_validator(mode="after")
    def ensure_required_values(self) -> ScorerInvokeRequest:
        if not (_has_value(self.inputs.query) or _has_value(self.inputs.response)):
            raise ValueError("Either inputs.query or inputs.response must be set.")
        return self

    def to_dict(self) -> JSONObject:
        """Convert to the Luna scorer invoke request shape."""
        return self.model_dump(mode="json", exclude_none=True)


def _orbit_record_from_step(
    step: Step | None,
    *,
    selected_input: JSONValue,
    selected_output: JSONValue,
) -> ScorerInvokeRecord | None:
    """Translate a generic Agent Control step into Orbit's record contract.

    Selector-selected values remain the primary scorer input. When a selector
    supplies one side, that value is written to both the legacy and structured
    representations so Orbit's conflict validation cannot observe two meanings.
    The complete step supplies the unselected side and additional record context.

    Unknown Agent Control step types intentionally fall back to the legacy
    ``inputs`` contract. This keeps the open-source Step model extensible without
    sending an invalid discriminator to Orbit.

    Args:
        step: Complete Agent Control step, when contextual evaluation is used.
        selected_input: Selector-selected value sent as ``inputs.query``.
        selected_output: Selector-selected value sent as ``inputs.response``.

    Returns:
        An Orbit-compatible record, or ``None`` for absent/unsupported steps.
    """
    if step is None or step.type not in SUPPORTED_SCORER_INVOKE_RECORD_TYPES:
        return None

    # The membership check above narrows the runtime value to Orbit's known
    # discriminator set, but static type checkers cannot infer that relationship.
    record_type = cast(ScorerInvokeRecordType, step.type)
    return ScorerInvokeRecord(
        type=record_type,
        name=step.name,
        input=selected_input if selected_input is not None else step.input,
        output=selected_output if selected_output is not None else step.output,
        context=step.context,
        tools=step.tools,
        dataset_output=step.ground_truth,
    )


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
        GALILEO_API_KEY and GALILEO_API_URL: Application API key and Galileo API
            root for Orbit grant exchange. Both must be configured together.
        GALILEO_API_SECRET_KEY or GALILEO_API_SECRET: Legacy internal JWT secret.
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
        *,
        api_key: str | None = None,
        orbit_url: str | None = None,
    ) -> None:
        """Initialize the Galileo Luna client.

        Args:
            api_key: Galileo application API key. If not provided, reads from
                GALILEO_API_KEY. The key is sent only to Orbit's grant endpoint.
            orbit_url: Galileo API root. If not provided, reads from GALILEO_API_URL.
            api_secret: Legacy internal JWT secret. If not provided, reads from
                GALILEO_API_SECRET_KEY or GALILEO_API_SECRET. New grant credentials
                take precedence when both modes are configured.
            luna_invoke_url: Luna scorer invoke URL or service root. If not provided,
                reads from GALILEO_LUNA_INVOKE_URL.
            luna_invoke_ca_file: Optional CA bundle used to verify Luna invoke TLS. If not
                provided, reads from GALILEO_LUNA_INVOKE_CA_FILE, then
                AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE.

        Raises:
            ValueError: If the grant credentials are incomplete, neither auth mode is
                configured, or the Luna URL, CA bundle, or connection tuning is invalid.
        """
        configured_api_key = api_key if api_key is not None else os.getenv(GALILEO_API_KEY_ENV)
        configured_orbit_url = orbit_url if orbit_url is not None else os.getenv(ORBIT_API_URL_ENV)
        has_api_key = bool(configured_api_key and configured_api_key.strip())
        has_orbit_url = bool(configured_orbit_url and configured_orbit_url.strip())
        if has_api_key != has_orbit_url:
            raise ValueError(
                "GALILEO_API_KEY and GALILEO_API_URL must be configured together "
                "for scorer-grant authentication."
            )

        resolved_api_secret = (
            api_secret
            or os.getenv(GALILEO_API_SECRET_KEY_ENV)
            or os.getenv(GALILEO_API_SECRET_ENV)
        )
        if not has_api_key and not resolved_api_secret:
            raise ValueError(
                "Configure GALILEO_API_KEY with GALILEO_API_URL for scorer-grant "
                "authentication, or set GALILEO_API_SECRET_KEY or GALILEO_API_SECRET "
                "for legacy Luna authentication."
            )

        resolved_luna_invoke_url = luna_invoke_url or os.getenv(LUNA_INVOKE_URL_ENV)
        if resolved_luna_invoke_url is None or resolved_luna_invoke_url.strip() == "":
            raise ValueError(
                "GALILEO_LUNA_INVOKE_URL is required for Luna scorer invocation. "
                "Set it as an environment variable or pass it to the constructor."
            )

        self.api_key = configured_api_key.strip() if configured_api_key else None
        self.api_secret = resolved_api_secret
        self.auth_mode: Literal["scorer_grant", "legacy"] = (
            "scorer_grant" if has_api_key else "legacy"
        )
        self.orbit_url = (
            _normalize_orbit_url(configured_orbit_url) if configured_orbit_url else None
        )
        self.scorer_grant_url = (
            f"{self.orbit_url}{SCORER_GRANT_PATH}" if self.orbit_url is not None else None
        )
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

    async def _get_scorer_grant(self, *, target_type: str, run_id: str) -> str:
        """Exchange the application key for a cached Orbit-issued run grant."""
        if self.auth_mode != "scorer_grant" or self.api_key is None or self.orbit_url is None:
            raise RuntimeError("Scorer-grant exchange is unavailable in legacy Luna auth mode.")
        caller_context = sha256(self.api_key.encode("utf-8")).hexdigest()
        cache_key = (self.orbit_url, target_type, run_id, caller_context)

        async with _scorer_grant_cache_lock:
            cached = _scorer_grant_cache.get(cache_key)
            now = datetime.now(tz=UTC)
            if cached is not None:
                expires_at = cached.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at > now:
                    return cached.token
                _scorer_grant_cache.pop(cache_key, None)

            client = await self._get_client()
            response = await client.post(
                f"{self.orbit_url}{SCORER_GRANT_PATH}",
                json={"target_type": target_type, "run_id": run_id},
                headers={"Galileo-API-Key": self.api_key},
                timeout=DEFAULT_TIMEOUT_SECS,
            )
            response.raise_for_status()
            try:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("response must be a JSON object")
                grant_value = payload.get("grant")
                expires_value = payload.get("expires_at")
                if not isinstance(grant_value, str) or not grant_value.strip():
                    raise ValueError("response field 'grant' must be a non-empty string")
                if not isinstance(expires_value, str):
                    raise ValueError("response field 'expires_at' must be an ISO timestamp")
                expires_at = datetime.fromisoformat(expires_value.replace("Z", "+00:00"))
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at <= datetime.now(tz=UTC):
                    raise ValueError("response grant is already expired")
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"Invalid Orbit scorer grant response: {exc}") from exc

            grant = _ScorerGrant(token=grant_value, expires_at=expires_at)
            _scorer_grant_cache[cache_key] = grant
            return grant.token

    def _endpoint_and_auth_header(self) -> tuple[str, str]:
        """Return the invoke endpoint and legacy bearer token."""
        if self.auth_mode != "legacy" or self.api_secret is None:
            raise RuntimeError("Legacy Luna auth is unavailable in scorer-grant mode.")
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
        step: Step | None = None,
        config: ScorerInvokeConfig | JSONObject | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        headers: dict[str, str] | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> ScorerInvokeResponse:
        """Invoke a Galileo Luna scorer.

        Args:
            scorer_id: Required scorer identifier.
            scorer_version_id: Deprecated optional compatibility identifier. Orbit
                currently invokes the scorer's current default version.
            scorer_label: Optional display/metadata label.
            input: Optional user/system prompt text.
            output: Optional model response text.
            step: Optional complete runtime step used for structured dual-write.
            config: Optional Orbit-supported scorer invocation configuration.
            timeout: Request timeout in seconds.
            headers: Additional request headers.
            target_type: Opaque evaluation target kind. Grant mode supports
                ``log_stream`` and uses ``target_id`` as Orbit's run ID.
            target_id: Opaque evaluation target ID supplied by Agent Control.

        Returns:
            Parsed scorer invocation response.

        Raises:
            ValueError: If neither input nor output is provided, config contains
                a field Orbit does not support, or the timeout ordering is invalid.
            RuntimeError: If the API response is not a JSON object.
            httpx.HTTPStatusError: If the Luna invoke endpoint returns an error status code.
            httpx.RequestError: If the request fails before a response is received.
        """
        if not (_has_value(input) or _has_value(output)):
            raise ValueError("At least one of input or output must be provided.")

        # Accept dictionaries for source compatibility with the original client,
        # but validate them against Orbit's authoritative allowlist locally.
        invoke_config = (
            ScorerInvokeConfig.model_validate(config)
            if config is not None
            else ScorerInvokeConfig()
        )
        invoke_config = _effective_scorer_timeout(
            invoke_config,
            http_timeout_seconds=timeout,
        )
        request_body = ScorerInvokeRequest(
            scorer_id=scorer_id,
            scorer_version_id=scorer_version_id,
            scorer_label=scorer_label,
            inputs=ScorerInvokeInputs(
                query="" if input is None else input,
                response="" if output is None else output,
                ground_truth=step.ground_truth if step is not None else None,
                tools=step.tools if step is not None else None,
            ),
            record=_orbit_record_from_step(
                step,
                selected_input=input,
                selected_output=output,
            ),
            config=invoke_config,
        ).to_dict()

        if self.auth_mode == "scorer_grant":
            resolved_run_id = _run_id_from_target(target_type, target_id)
            assert target_type is not None
            scorer_grant = await self._get_scorer_grant(
                target_type=target_type,
                run_id=resolved_run_id,
            )
            auth_header = f"Bearer {scorer_grant}"
        else:
            _, auth_header = self._endpoint_and_auth_header()
        request_headers = {
            k: v for k, v in (headers or {}).items() if k.lower() not in _BLOCKED_REQUEST_HEADERS
        }
        request_headers["Authorization"] = auth_header

        logger.debug("[GalileoLunaClient] POST %s", self.luna_invoke_url)
        logger.debug("[GalileoLunaClient] Request body: %s", request_body)

        try:
            client = await self._get_client()
            response = await client.post(
                self.luna_invoke_url,
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
