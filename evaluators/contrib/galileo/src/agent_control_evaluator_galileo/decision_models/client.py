"""HTTP client for Galileo Decision Models scorer invocation."""

from __future__ import annotations

import logging
import os
from asyncio import Lock
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new
from json import dumps
from time import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from agent_control_models import JSONObject, JSONValue, Step
from pydantic import BaseModel, Field

from ..records import record_from_step
from .config import DecisionModelsPayloadField, scorer_invoke_runtime_enabled

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
DEFAULT_INVOKE_PATH = "/api/v1/scorers/invoke/runtime"
EXTERNAL_INVOKE_URL_ENV = "GALILEO_EXTERNAL_INVOKE_URL"
AUTH_UPSTREAM_CA_FILE_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE"
DEFAULT_KEEPALIVE_EXPIRY_SECS = 1.0
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_CLIENT_POOL_SIZE = 1
LUNA_KEEPALIVE_EXPIRY_ENV = "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS"
LUNA_MAX_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_CONNECTIONS"
LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS"
LUNA_CLIENT_POOL_SIZE_ENV = "GALILEO_LUNA_CLIENT_POOL_SIZE"


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


class DecisionModelsExecutionContext(BaseModel):
    """Authenticated organization and optional identity fields for scorer invocation."""

    organization_id: str = Field(min_length=1)
    user_id: str | None = Field(default=None, min_length=1)
    project_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decision_models_internal_auth_token(
    api_secret: str,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
) -> str:
    """Create the internal JWT expected by Runners scorer-invoke routes."""
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


def _normalize_invoke_url(raw_url: str) -> str:
    """Append the Runners scorer-invoke path to a service-root URL."""
    url = raw_url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return url
    return f"{url}{DEFAULT_INVOKE_PATH}"


class DecisionModelsInvokeInputs(BaseModel):
    """Legacy inputs accepted alongside the structured Galileo record."""

    query: JSONValue = ""
    response: JSONValue = ""
    ground_truth: JSONValue = None
    tools: list[JSONObject] | None = None


class DecisionModelsInvokeRequest(BaseModel):
    """Structured Runners scorer-invoke request."""

    scorer_id: str = Field(min_length=1)
    scorer_version_id: str = Field(min_length=1)
    scorer_label: str | None = None
    execution_context: DecisionModelsExecutionContext
    record: JSONObject
    inputs: DecisionModelsInvokeInputs
    config: JSONObject = Field(default_factory=dict)

    def to_dict(self) -> JSONObject:
        """Serialize the complete request while preserving nested record data."""
        request = self.model_dump(mode="json", exclude_none=True)
        request["execution_context"] = self.execution_context.model_dump(mode="json")
        return request


class DecisionModelsInvokeResponse(BaseModel):
    """Response returned by the Decision Models scorer-invoke runtime."""

    score: JSONValue | None = None
    status: str = "unknown"
    scorer_label: str | None = None
    execution_time: float | None = None
    error_message: str | None = None


class GalileoDecisionModelsClient:
    """Small HTTP client for the Runners scorer-invoke endpoint."""

    def __init__(
        self,
        api_secret: str | None = None,
        invoke_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECS,
    ) -> None:
        resolved_secret = (
            api_secret or os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        )
        if not resolved_secret:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for "
                "galileo.decision_models"
            )
        resolved_url = invoke_url or os.getenv(EXTERNAL_INVOKE_URL_ENV)
        if not resolved_url or not resolved_url.strip():
            raise ValueError(f"{EXTERNAL_INVOKE_URL_ENV} is required for galileo.decision_models")
        self.api_secret = resolved_secret
        self.invoke_url = _normalize_invoke_url(resolved_url)
        self.runtime_enabled = scorer_invoke_runtime_enabled()
        self.timeout = timeout
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
        self._client = self._create_client()
        self._clients = [self._client]
        self._next_client_index = 0
        self._client_lock = Lock()

    def _create_client(self) -> httpx.AsyncClient:
        """Create an HTTP client with configured connection limits."""
        return httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(self.timeout),
            limits=httpx.Limits(
                max_connections=self.max_connections,
                max_keepalive_connections=self.max_keepalive_connections,
                keepalive_expiry=self.keepalive_expiry_seconds,
            ),
            verify=os.getenv(AUTH_UPSTREAM_CA_FILE_ENV) or True,
        )

    def _select_pooled_client(self) -> httpx.AsyncClient:
        client = self._clients[self._next_client_index % len(self._clients)]
        self._next_client_index = (self._next_client_index + 1) % len(self._clients)
        return client

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the next HTTP client in the configured pool."""
        async with self._client_lock:
            self._clients = [client for client in self._clients if not client.is_closed]
            if self.client_pool_size == 1:
                if self._client.is_closed:
                    self._client = self._create_client()
                self._clients = [self._client]
                return self._client

            while len(self._clients) < self.client_pool_size:
                self._clients.append(self._create_client())
            self._client = self._clients[0]
            return self._select_pooled_client()

    async def invoke(
        self,
        *,
        scorer_id: str,
        scorer_version_id: str,
        scorer_label: str | None,
        step: Step,
        execution_context: DecisionModelsExecutionContext,
        inputs: DecisionModelsInvokeInputs,
        timeout: float,
        selected_data: Any = None,
        payload_field: DecisionModelsPayloadField = "input",
    ) -> DecisionModelsInvokeResponse:
        """Invoke the pinned scorer with the complete Galileo Core record."""
        if not self.runtime_enabled:
            raise RuntimeError(
                "Galileo scorer-invoke runtime is disabled; galileo.decision_models requires "
                "GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME=enabled."
            )
        record = record_from_step(
            step,
            selected_data=selected_data,
            payload_field=payload_field,
        ).model_dump(mode="json", exclude_none=True)
        request = DecisionModelsInvokeRequest(
            scorer_id=scorer_id,
            scorer_version_id=scorer_version_id,
            scorer_label=scorer_label,
            execution_context=execution_context,
            record=record,
            inputs=inputs,
            config={"request_timeout_seconds": timeout * 0.8},
        )
        client = await self._get_client()
        response = await client.post(
            self.invoke_url,
            json=request.to_dict(),
            headers={
                "Authorization": f"Bearer {_decision_models_internal_auth_token(self.api_secret)}"
            },
            timeout=timeout,
        )
        response.raise_for_status()
        body: Any = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Invalid Decision Models scorer response: expected a JSON object")
        return DecisionModelsInvokeResponse.model_validate(body)

    async def close(self) -> None:
        """Close all HTTP clients in the connection pool."""
        for client in self._clients:
            if not client.is_closed:
                await client.aclose()
        self._clients.clear()
