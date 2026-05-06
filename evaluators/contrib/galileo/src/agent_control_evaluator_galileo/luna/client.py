"""Direct HTTP client for Galileo Luna scorer invocation."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from uuid import UUID

import httpx
from agent_control_models import JSONObject, JSONValue

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0


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


@dataclass(frozen=True)
class ScorerInvokeRequest:
    """Request payload for Galileo Luna scorer invocation.

    Attributes:
        metric: Preset, registered, or fine-tuned scorer name.
        input: Optional user/system prompt text.
        output: Optional model response text.
        luna_model: Optional Luna model override.
        project_id: Optional Galileo project UUID for project-scoped scorer resolution.
        config: Optional scorer-specific configuration.
    """

    metric: str
    input: str | None = None
    output: str | None = None
    project_id: str | UUID | None = None
    luna_model: str | None = None
    config: JSONObject | None = None

    def to_dict(self) -> JSONObject:
        """Convert to the public API request shape."""
        body: JSONObject = {"metric": self.metric}
        if self.input is not None:
            body["input"] = self.input
        if self.output is not None:
            body["output"] = self.output
        if self.project_id is not None:
            body["project_id"] = str(self.project_id)
        if self.luna_model is not None:
            body["luna_model"] = self.luna_model
        if self.config is not None:
            body["config"] = self.config
        return body


@dataclass
class ScorerInvokeResponse:
    """Response from Galileo Luna scorer invocation.

    Attributes:
        metric: Echoed scorer metric.
        score: Raw scorer value.
        status: Invocation status.
        execution_time: Execution time in seconds, when returned.
        error_message: Error detail for non-success statuses.
        raw_response: Full response body for diagnostics.
    """

    metric: str
    score: JSONValue
    status: str = "unknown"
    execution_time: float | None = None
    error_message: str | None = None
    raw_response: JSONObject = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: JSONObject) -> ScorerInvokeResponse:
        """Create a response model from the API JSON object."""
        metric_value = data.get("metric", "")
        status_value = data.get("status", "unknown")
        error_value = data.get("error_message")

        return cls(
            metric=str(metric_value) if metric_value is not None else "",
            score=data.get("score"),
            status=str(status_value) if status_value is not None else "unknown",
            execution_time=_as_float_or_none(data.get("execution_time")),
            error_message=str(error_value) if error_value is not None else None,
            raw_response=data,
        )


class GalileoLunaClient:
    """Thin HTTP client for Galileo Luna direct scorer invocation.

    Environment Variables:
        GALILEO_API_KEY: Galileo API key (required).
        GALILEO_CONSOLE_URL: Galileo Console URL (optional, defaults to production).
    """

    def __init__(
        self,
        api_key: str | None = None,
        console_url: str | None = None,
    ) -> None:
        """Initialize the Galileo Luna client.

        Args:
            api_key: Galileo API key. If not provided, reads from GALILEO_API_KEY.
            console_url: Galileo Console URL. If not provided, reads from
                GALILEO_CONSOLE_URL or uses the production console URL.

        Raises:
            ValueError: If no API key is provided or found in the environment.
        """
        resolved_api_key = api_key or os.getenv("GALILEO_API_KEY")
        if not resolved_api_key:
            raise ValueError(
                "GALILEO_API_KEY is required. "
                "Set it as an environment variable or pass it to the constructor."
            )

        self.api_key = resolved_api_key
        self.console_url = (
            console_url or os.getenv("GALILEO_CONSOLE_URL") or "https://console.galileo.ai"
        )
        self.api_base = self._derive_api_url(self.console_url)
        self._client: httpx.AsyncClient | None = None

    def _derive_api_url(self, console_url: str) -> str:
        """Derive the API URL from a Galileo Console URL."""
        url = console_url.rstrip("/")

        if "console." in url:
            return url.replace("console.", "api.")

        if url.startswith("https://"):
            return url.replace("https://", "https://api.")
        if url.startswith("http://"):
            return url.replace("http://", "http://api.")

        return url

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Galileo-API-Key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECS),
            )
        return self._client

    async def invoke(
        self,
        *,
        metric: str,
        input: str | None = None,
        output: str | None = None,
        project_id: str | UUID | None = None,
        luna_model: str | None = None,
        config: JSONObject | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        headers: dict[str, str] | None = None,
    ) -> ScorerInvokeResponse:
        """Invoke a Galileo Luna scorer.

        Args:
            metric: Preset, registered, or fine-tuned scorer name.
            input: Optional user/system prompt text.
            output: Optional model response text.
            project_id: Optional Galileo project UUID for project-scoped scorer resolution.
            luna_model: Optional Luna model override.
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
        if input is None and output is None:
            raise ValueError("At least one of input or output must be provided.")

        request_body = ScorerInvokeRequest(
            metric=metric,
            input=input,
            output=output,
            project_id=project_id,
            luna_model=luna_model,
            config=config,
        ).to_dict()
        request_headers = dict(headers or {})
        endpoint = f"{self.api_base}/scorers/invoke"

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
