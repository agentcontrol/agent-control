"""Direct HTTP client for Galileo LLM-as-judge scorer invocation.

Extends the Luna wire contract by embedding caller identity (user_id,
organization_id) in the internal JWT so runners-api can resolve the
caller's LLM provider credentials and build a trusted ExecutionContext.
"""

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
from typing import Literal, cast, get_args
from urllib.parse import urlsplit

import httpx
from agent_control_models import JSONObject, JSONValue, Step
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from agent_control_evaluator_galileo._shared.config import ScorerInvokeConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
SERVER_TIMEOUT_RATIO = 0.8
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
DEFAULT_SCORER_INVOKE_PATH = "/api/v1/scorers/invoke"
SCORER_INVOKE_URL_ENV = "GALILEO_LUNA_INVOKE_URL"
SCORER_INVOKE_CA_FILE_ENV = "GALILEO_LUNA_INVOKE_CA_FILE"
AUTH_UPSTREAM_CA_FILE_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE"

_BLOCKED_REQUEST_HEADERS = frozenset({"galileo-api-key"})

DEFAULT_KEEPALIVE_EXPIRY_SECS = 1.0
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_CLIENT_POOL_SIZE = 1
KEEPALIVE_EXPIRY_ENV = "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS"
MAX_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_CONNECTIONS"
MAX_KEEPALIVE_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS"
CLIENT_POOL_SIZE_ENV = "GALILEO_LUNA_CLIENT_POOL_SIZE"

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


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _internal_auth_token(
    api_secret: str,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
    *,
    user_id: str | None = None,
    organization_id: str | None = None,
) -> str:
    """Create the internal JWT for LLM scorer invoke routes.

    Embeds ``user_id`` and ``organization_id`` as claims so runners-api can
    resolve the caller's LLM provider credentials and build a trusted
    ``ExecutionContext`` without a separate identity lookup.
    """
    now = int(time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, object] = {
        "internal": True,
        "scope": "scorers.invoke",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if user_id is not None:
        payload["user_id"] = user_id
    if organization_id is not None:
        payload["organization_id"] = organization_id
    signing_input = ".".join(
        [
            _b64url(dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac_new(api_secret.encode("utf-8"), signing_input.encode("ascii"), sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _normalize_invoke_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return url
    return f"{url}{DEFAULT_SCORER_INVOKE_PATH}"


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
            f"{KEEPALIVE_EXPIRY_ENV}={keepalive_expiry_seconds} "
            "must be greater than or equal to 0."
        )
    if max_connections <= 0:
        raise ValueError(f"{MAX_CONNECTIONS_ENV}={max_connections} must be greater than 0.")
    if max_keepalive_connections < 0:
        raise ValueError(
            f"{MAX_KEEPALIVE_CONNECTIONS_ENV}={max_keepalive_connections} "
            "must be greater than or equal to 0."
        )
    if max_keepalive_connections > max_connections:
        raise ValueError(
            f"{MAX_KEEPALIVE_CONNECTIONS_ENV}={max_keepalive_connections} "
            f"must be less than or equal to {MAX_CONNECTIONS_ENV}={max_connections}."
        )
    if client_pool_size <= 0:
        raise ValueError(f"{CLIENT_POOL_SIZE_ENV}={client_pool_size} must be greater than 0.")


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
    query: JSONValue = ""
    response: JSONValue = ""
    ground_truth: JSONValue = None
    tools: list[JSONObject] | None = None


class ScorerInvokeRecord(BaseModel):
    type: ScorerInvokeRecordType
    name: str | None = None
    input: JSONValue = None
    output: JSONValue = None
    context: JSONObject | None = None
    tools: list[JSONObject] | None = None
    dataset_output: JSONValue = None


class ScorerInvokeRequest(BaseModel):
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
        return self.model_dump(mode="json", exclude_none=True)


def _orbit_record_from_step(
    step: Step | None,
    *,
    selected_input: JSONValue,
    selected_output: JSONValue,
) -> ScorerInvokeRecord | None:
    if step is None or step.type not in SUPPORTED_SCORER_INVOKE_RECORD_TYPES:
        return None
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
        response = cls.model_validate(
            data | {"execution_time": _as_float_or_none(data.get("execution_time"))}
        )
        response._raw_response = data
        return response


class GalileoLLMClient:
    """Thin HTTP client for Galileo LLM-as-judge scorer invocation.

    Extends the Luna wire contract by embedding caller identity claims
    (``user_id``, ``organization_id``) in the internal JWT so runners-api
    can resolve LLM provider credentials for the calling user.

    Environment Variables:
        GALILEO_API_SECRET_KEY or GALILEO_API_SECRET: JWT signing secret.
        GALILEO_LUNA_INVOKE_URL: Scorer invoke URL or service root (required).
        GALILEO_LUNA_INVOKE_CA_FILE: CA bundle for TLS verification.
        AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE: Shared internal CA fallback.
        GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS: HTTP pooled connection expiry.
        GALILEO_LUNA_MAX_CONNECTIONS: Maximum outbound HTTP connections.
        GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS: Maximum idle pooled connections.
        GALILEO_LUNA_CLIENT_POOL_SIZE: Number of HTTP clients to rotate across.
    """

    def __init__(
        self,
        api_secret: str | None = None,
        invoke_url: str | None = None,
        invoke_ca_file: str | None = None,
    ) -> None:
        resolved_api_secret = (
            api_secret or os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        )
        if not resolved_api_secret:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for LLM "
                "scorer invocation. Set one as an environment variable or pass it "
                "to the constructor."
            )

        resolved_invoke_url = invoke_url or os.getenv(SCORER_INVOKE_URL_ENV)
        if resolved_invoke_url is None or resolved_invoke_url.strip() == "":
            raise ValueError(
                "GALILEO_LUNA_INVOKE_URL is required for LLM scorer invocation. "
                "Set it as an environment variable or pass it to the constructor."
            )

        self.api_secret = resolved_api_secret
        self.invoke_url = _normalize_invoke_url(resolved_invoke_url)
        self.invoke_ca_file = (
            invoke_ca_file
            or os.getenv(SCORER_INVOKE_CA_FILE_ENV)
            or os.getenv(AUTH_UPSTREAM_CA_FILE_ENV)
            or ""
        ).strip() or None
        self._ssl_context = self._load_ssl_context(self.invoke_ca_file)
        self.keepalive_expiry_seconds = _load_float_env(
            KEEPALIVE_EXPIRY_ENV, DEFAULT_KEEPALIVE_EXPIRY_SECS
        )
        self.max_connections = _load_int_env(MAX_CONNECTIONS_ENV, DEFAULT_MAX_CONNECTIONS)
        self.max_keepalive_connections = _load_int_env(
            MAX_KEEPALIVE_CONNECTIONS_ENV, DEFAULT_MAX_KEEPALIVE_CONNECTIONS
        )
        self.client_pool_size = _load_int_env(CLIENT_POOL_SIZE_ENV, DEFAULT_CLIENT_POOL_SIZE)
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
        if ca_file is None:
            return None
        try:
            return ssl.create_default_context(cafile=ca_file)
        except (OSError, ssl.SSLError) as exc:
            raise ValueError(f"Failed to load CA bundle from {ca_file!r}: {exc}") from exc

    def _create_client(self) -> httpx.AsyncClient:
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
        client = self._clients[self._next_client_index % len(self._clients)]
        self._next_client_index = (self._next_client_index + 1) % len(self._clients)
        return client

    async def _get_client(self) -> httpx.AsyncClient:
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

    def _endpoint_and_auth_header(
        self,
        *,
        user_id: str | None,
        organization_id: str | None,
    ) -> tuple[str, str]:
        token = _internal_auth_token(
            self.api_secret,
            user_id=user_id,
            organization_id=organization_id,
        )
        return self.invoke_url, f"Bearer {token}"

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
        user_id: str | None = None,
        organization_id: str | None = None,
    ) -> ScorerInvokeResponse:
        """Invoke a Galileo LLM-as-judge scorer.

        Args:
            scorer_id: Required scorer identifier.
            scorer_version_id: Optional pinned scorer version identifier.
            scorer_label: Optional display/metadata label.
            input: Optional user/system prompt text.
            output: Optional model response text.
            step: Optional complete runtime step for structured dual-write.
            config: Optional Orbit-supported scorer invocation configuration.
            timeout: Request timeout in seconds.
            headers: Additional request headers.
            user_id: Caller's Galileo user UUID. Embedded in the JWT so
                runners-api can resolve LLM provider credentials.
            organization_id: Caller's Galileo organisation UUID. Embedded
                for org-scoped authorization checks in runners-api.
        """
        if not (_has_value(input) or _has_value(output)):
            raise ValueError("At least one of input or output must be provided.")

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

        endpoint, auth_header = self._endpoint_and_auth_header(
            user_id=user_id,
            organization_id=organization_id,
        )
        request_headers = {
            k: v for k, v in (headers or {}).items() if k.lower() not in _BLOCKED_REQUEST_HEADERS
        }
        request_headers["Authorization"] = auth_header

        logger.debug("[GalileoLLMClient] POST %s", endpoint)
        logger.debug("[GalileoLLMClient] Request body: %s", request_body)

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
            logger.debug("[GalileoLLMClient] Response: %s", parsed.raw_response)
            return parsed
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[GalileoLLMClient] API error: %s - %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        except httpx.RequestError as exc:
            logger.error("[GalileoLLMClient] Request failed: %s", exc)
            raise

    async def close(self) -> None:
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

    async def __aenter__(self) -> GalileoLLMClient:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()
