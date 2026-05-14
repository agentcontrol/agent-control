"""Direct HTTP client for Galileo Luna scorer invocation."""

from __future__ import annotations

import logging
import os
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new
from json import dumps
from time import time
from uuid import UUID

import httpx
from agent_control_models import JSONObject, JSONValue
from pydantic import BaseModel, Field, PrivateAttr, model_validator

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
PUBLIC_SCORER_INVOKE_PATH = "/scorers/invoke"
INTERNAL_SCORER_INVOKE_PATH = "/internal/scorers/invoke"


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _internal_auth_token(
    api_secret: str,
    project_id: str | UUID,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
) -> str:
    """Create the internal JWT expected by Galileo API internal routes."""
    now = int(time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "internal": True,
        "project_id": str(project_id),
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
        project_id: Optional Galileo project UUID for project-scoped scorer resolution.
        config: Optional scorer-specific configuration.
    """

    scorer_label: str = Field(min_length=1)
    inputs: ScorerInvokeInputs
    project_id: str | UUID | None = None
    config: JSONObject | None = None

    @model_validator(mode="after")
    def ensure_input_or_output(self) -> ScorerInvokeRequest:
        if not (_has_value(self.inputs.query) or _has_value(self.inputs.response)):
            raise ValueError("Either inputs.query or inputs.response must be set.")
        return self

    def to_dict(self) -> JSONObject:
        """Convert to the Galileo scorer invoke API request shape."""
        return self.model_dump(mode="json", exclude_none=True)


class ScorerInvokeResponse(BaseModel):
    """Response from Galileo Luna scorer invocation.

    Attributes:
        scorer_label: Echoed scorer label.
        score: Raw scorer value.
        status: Invocation status.
        execution_time: Execution time in seconds, when returned.
        error_message: Error detail for non-success statuses.
    """

    scorer_label: str
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
        GALILEO_API_SECRET_KEY or GALILEO_API_SECRET: Galileo API internal JWT signing secret.
        GALILEO_API_KEY: Galileo API key fallback for public scorer invocation.
        GALILEO_CONSOLE_URL: Galileo Console URL (optional, defaults to production).
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        console_url: str | None = None,
        api_url: str | None = None,
    ) -> None:
        """Initialize the Galileo Luna client.

        Args:
            api_key: Galileo API key. If not provided, reads from GALILEO_API_KEY.
            api_secret: Galileo API secret for internal JWT auth. If not provided,
                reads from GALILEO_API_SECRET_KEY or GALILEO_API_SECRET.
            console_url: Galileo Console URL. If not provided, reads from
                GALILEO_CONSOLE_URL or uses the production console URL.
            api_url: Galileo API URL. If not provided, reads from GALILEO_API_URL
                before deriving from the console URL.

        Raises:
            ValueError: If neither API secret nor API key is provided.
        """
        resolved_api_secret = (
            api_secret or os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        )
        resolved_api_key = api_key or os.getenv("GALILEO_API_KEY")
        if not resolved_api_secret and not resolved_api_key:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_KEY is required. "
                "Set one as an environment variable or pass it to the constructor."
            )

        self.api_key = resolved_api_key
        self.api_secret = resolved_api_secret
        self.console_url = (
            console_url or os.getenv("GALILEO_CONSOLE_URL") or "https://console.galileo.ai"
        )
        self.api_base = (api_url or os.getenv("GALILEO_API_URL") or "").rstrip(
            "/"
        ) or self._derive_api_url(self.console_url)
        self._client: httpx.AsyncClient | None = None

    def _derive_api_url(self, console_url: str) -> str:
        """Derive the API URL from a Galileo Console URL."""
        url = console_url.rstrip("/")

        if "console." in url:
            return url.replace("console.", "api.")
        if "console-" in url:
            return url.replace("console-", "api-", 1)

        if url.startswith("https://"):
            return url.replace("https://", "https://api.")
        if url.startswith("http://"):
            return url.replace("http://", "http://api.")

        return url

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json"}
            if self.api_secret is None and self.api_key is not None:
                headers["Galileo-API-Key"] = self.api_key
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECS),
            )
        return self._client

    def _endpoint_and_headers(
        self,
        project_id: str | UUID | None,
        headers: dict[str, str] | None,
    ) -> tuple[str, dict[str, str]]:
        request_headers = dict(headers or {})
        if self.api_secret is None:
            return f"{self.api_base}{PUBLIC_SCORER_INVOKE_PATH}", request_headers

        if project_id is None:
            raise ValueError(
                "project_id is required when using GALILEO_API_SECRET_KEY internal auth."
            )

        request_headers["Authorization"] = (
            f"Bearer {_internal_auth_token(self.api_secret, project_id)}"
        )
        return f"{self.api_base}{INTERNAL_SCORER_INVOKE_PATH}", request_headers

    async def invoke(
        self,
        *,
        scorer_label: str,
        input: JSONValue = None,
        output: JSONValue = None,
        project_id: str | UUID | None = None,
        config: JSONObject | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        headers: dict[str, str] | None = None,
    ) -> ScorerInvokeResponse:
        """Invoke a Galileo Luna scorer.

        Args:
            scorer_label: Preset, registered, or fine-tuned scorer label.
            input: Optional user/system prompt text.
            output: Optional model response text.
            step_type: Runtime step shape used by Galileo scorer input normalization.
            project_id: Optional Galileo project UUID for project-scoped scorer resolution.
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
        if not (_has_value(input) or _has_value(output)):
            raise ValueError("At least one of input or output must be provided.")

        request_body = ScorerInvokeRequest(
            scorer_label=scorer_label,
            inputs=ScorerInvokeInputs(
                query="" if input is None else input, response="" if output is None else output
            ),
            project_id=project_id,
            config=config,
        ).to_dict()
        endpoint, request_headers = self._endpoint_and_headers(project_id, headers)

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
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> GalileoLunaClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Async context manager exit."""
        await self.close()
