"""HTTP client for Galileo Decision Models scorer invocation."""

from __future__ import annotations

import logging
import os
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
DEFAULT_INVOKE_PATH = "/api/v1/scorers/invoke"
LUNA_INVOKE_URL_ENV = "GALILEO_LUNA_INVOKE_URL"
AUTH_UPSTREAM_CA_FILE_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE"


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
        resolved_url = invoke_url or os.getenv(LUNA_INVOKE_URL_ENV)
        if not resolved_url or not resolved_url.strip():
            raise ValueError(f"{LUNA_INVOKE_URL_ENV} is required for galileo.decision_models")
        self.api_secret = resolved_secret
        self.invoke_url = _normalize_invoke_url(resolved_url)
        self.runtime_enabled = scorer_invoke_runtime_enabled()
        self.timeout = timeout
        self._client = httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
            verify=os.getenv(AUTH_UPSTREAM_CA_FILE_ENV) or True,
        )

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
        response = await self._client.post(
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
        """Close the underlying HTTP client."""
        await self._client.aclose()
