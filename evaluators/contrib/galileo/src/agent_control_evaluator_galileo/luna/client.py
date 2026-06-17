"""Direct HTTP client for Galileo Luna scorer invocation via runners-api."""

from __future__ import annotations

import logging
import os
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new
from json import dumps
from time import time

import httpx
from agent_control_models import JSONObject, JSONValue
from pydantic import BaseModel, Field, PrivateAttr, model_validator

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
RUNNERS_SCORER_INVOKE_PATH = "/api/v1/scorers/invoke"
RUNNERS_API_URL_ENV = "GALILEO_RUNNERS_API_URL"
RUNNERS_API_CA_FILE_ENV = "GALILEO_RUNNERS_API_CA_FILE"
AUTH_UPSTREAM_CA_FILE_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE"

# Headers that must never be forwarded to runners-api (checked case-insensitively).
_BLOCKED_REQUEST_HEADERS = frozenset({"galileo-api-key"})


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _internal_auth_token(
    api_secret: str,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
) -> str:
    """Create the internal JWT expected by runners-api scorer invoke routes."""
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
    """Input values sent to the runners-api scorer invoke endpoint."""

    query: JSONValue = ""
    response: JSONValue = ""
    ground_truth: JSONValue = None
    tools: JSONValue = None


class ScorerInvokeRequest(BaseModel):
    """Request payload for runners-api scorer invocation.

    Attributes:
        scorer_id: Required scorer identifier.
        scorer_version_id: Optional pinned scorer version identifier.
        scorer_label: Optional display/metadata label.
        inputs: Selected scorer input values.
        config: Optional scorer-specific configuration.
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
        """Convert to the runners-api scorer invoke request shape."""
        return self.model_dump(mode="json", exclude_none=True)


class ScorerInvokeResponse(BaseModel):
    """Response from runners-api scorer invocation.

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
        """Create a response model from the runners-api JSON object."""
        response = cls.model_validate(
            data | {"execution_time": _as_float_or_none(data.get("execution_time"))}
        )
        response._raw_response = data
        return response


class GalileoLunaClient:
    """Thin HTTP client for Galileo Luna scorer invocation via runners-api.

    Environment Variables:
        GALILEO_API_SECRET_KEY or GALILEO_API_SECRET: JWT signing secret for runners-api auth.
        GALILEO_RUNNERS_API_URL: runners-api base URL (required).
    """

    def __init__(
        self,
        api_secret: str | None = None,
        runners_api_url: str | None = None,
        runners_api_ca_file: str | None = None,
    ) -> None:
        """Initialize the Galileo Luna client.

        Args:
            api_secret: Internal JWT signing secret. If not provided, reads from
                GALILEO_API_SECRET_KEY or GALILEO_API_SECRET.
            runners_api_url: runners-api base URL. If not provided, reads from
                GALILEO_RUNNERS_API_URL.
            runners_api_ca_file: Optional CA bundle used to verify runners-api
                TLS. If not provided, reads from GALILEO_RUNNERS_API_CA_FILE,
                then AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE for Galileo in-cluster
                deployments that already mount the internal CA.

        Raises:
            ValueError: If the API secret or runners-api URL is not configured.
        """
        resolved_api_secret = (
            api_secret or os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        )
        if not resolved_api_secret:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for Luna "
                "runners-api invocation. Set one as an environment variable or pass it "
                "to the constructor."
            )

        resolved_runners_url = runners_api_url or os.getenv(RUNNERS_API_URL_ENV)
        if not resolved_runners_url:
            raise ValueError(
                "GALILEO_RUNNERS_API_URL is required for Luna runners-api invocation. "
                "Set it as an environment variable or pass it to the constructor."
            )

        self.api_secret = resolved_api_secret
        self.runners_api_base = resolved_runners_url.rstrip("/")
        self.runners_api_ca_file = (
            runners_api_ca_file
            or os.getenv(RUNNERS_API_CA_FILE_ENV)
            or os.getenv(AUTH_UPSTREAM_CA_FILE_ENV)
            or None
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            verify: str | bool = self.runners_api_ca_file or True
            self._client = httpx.AsyncClient(
                headers={"Content-Type": "application/json"},
                timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECS),
                verify=verify,
            )
        return self._client

    def _endpoint_and_auth_header(self) -> tuple[str, str]:
        token = _internal_auth_token(self.api_secret)
        endpoint = f"{self.runners_api_base}{RUNNERS_SCORER_INVOKE_PATH}"
        return endpoint, f"Bearer {token}"

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
        """Invoke a Galileo Luna scorer via runners-api.

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
            httpx.HTTPStatusError: If runners-api returns an error status code.
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
            k: v
            for k, v in (headers or {}).items()
            if k.lower() not in _BLOCKED_REQUEST_HEADERS
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
