"""Direct HTTP client for Galileo Protect API.

This module provides a lightweight HTTP client that calls the Galileo Protect API
directly, without requiring the full galileo-sdk package.

Reference: https://v2docs.galileo.ai/sdk-api/python/reference/protect
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default timeout for API calls (seconds)
DEFAULT_TIMEOUT_SECS = 10.0


@dataclass
class Payload:
    """Payload for Galileo Protect API requests.

    Attributes:
        input: The input text to evaluate (for input metrics like input_toxicity).
        output: The output text to evaluate (for output metrics like output_toxicity).
    """

    input: str = ""
    output: str = ""

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for API request."""
        return {"input": self.input, "output": self.output}


@dataclass
class Rule:
    """Rule definition for local stage evaluation.

    Attributes:
        metric: The metric to evaluate (e.g., "input_toxicity", "prompt_injection").
        operator: Comparison operator ("gt", "lt", "gte", "lte", "eq", "contains", "any").
        target_value: The threshold value for comparison.
    """

    metric: str
    operator: str
    target_value: float | int | str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request."""
        return {
            "metric": self.metric,
            "operator": self.operator,
            "target_value": self.target_value,
        }


@dataclass
class PassthroughAction:
    """Passthrough action for rulesets.

    When a rule is triggered, a passthrough action allows the request to continue
    while recording the evaluation result.
    """

    type: str = "PASSTHROUGH"

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for API request."""
        return {"type": self.type}


@dataclass
class Ruleset:
    """Ruleset containing rules and an action.

    Attributes:
        rules: List of rules to evaluate.
        action: Action to take when rules are triggered.
        description: Human-readable description of the ruleset.
    """

    rules: list[Rule]
    action: PassthroughAction
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request."""
        return {
            "rules": [rule.to_dict() for rule in self.rules],
            "action": self.action.to_dict(),
            "description": self.description,
        }


@dataclass
class TraceMetadata:
    """Trace metadata from Galileo Protect response.

    Attributes:
        id: Unique trace identifier.
        execution_time: Time taken for evaluation in milliseconds.
        received_at: Timestamp when request was received.
        response_at: Timestamp when response was sent.
    """

    id: str | None = None
    execution_time: float | None = None
    received_at: str | None = None
    response_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TraceMetadata":
        """Create from API response dictionary."""
        if not data:
            return cls()
        return cls(
            id=data.get("id"),
            execution_time=data.get("execution_time"),
            received_at=data.get("received_at"),
            response_at=data.get("response_at"),
        )


@dataclass
class ProtectResponse:
    """Response from Galileo Protect API.

    Attributes:
        status: Execution status ("triggered", "success", "skipped", "paused").
        text: Response message or explanation.
        trace_metadata: Tracing information for the request.
        metric_results: Detailed results for each evaluated metric.
        raw_response: The full raw API response for debugging.
    """

    status: str = "unknown"
    text: str = ""
    trace_metadata: TraceMetadata = field(default_factory=TraceMetadata)
    metric_results: dict[str, Any] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProtectResponse":
        """Create from API response dictionary."""
        return cls(
            status=data.get("status", "unknown"),
            text=data.get("text", ""),
            trace_metadata=TraceMetadata.from_dict(data.get("trace_metadata")),
            metric_results=data.get("metric_results", {}),
            raw_response=data,
        )


class GalileoProtectClient:
    """Direct HTTP client for Galileo Protect API.

    This client provides a lightweight way to call the Galileo Protect API
    without requiring the full galileo-sdk package. It supports both local
    stages (runtime rules) and central stages (pre-defined on server).

    Example:
        ```python
        client = GalileoProtectClient()

        # Local stage evaluation
        response = await client.invoke_protect(
            payload=Payload(input="test message"),
            project_name="my-project",
            prioritized_rulesets=[
                Ruleset(
                    rules=[Rule(metric="input_toxicity", operator="gt", target_value=0.5)],
                    action=PassthroughAction(),
                )
            ],
        )

        # Central stage evaluation
        response = await client.invoke_protect(
            payload=Payload(input="test message"),
            project_name="my-project",
            stage_name="production-guard",
        )
        ```

    Environment Variables:
        GALILEO_API_KEY: Your Galileo API key (required).
        GALILEO_CONSOLE_URL: Galileo Console URL (optional, defaults to production).
    """

    def __init__(
        self,
        api_key: str | None = None,
        console_url: str | None = None,
    ) -> None:
        """Initialize the Galileo Protect client.

        Args:
            api_key: Galileo API key. If not provided, reads from GALILEO_API_KEY env var.
            console_url: Galileo Console URL. If not provided, reads from
                GALILEO_CONSOLE_URL env var or uses default.

        Raises:
            ValueError: If no API key is provided or found in environment.
        """
        self.api_key = api_key or os.getenv("GALILEO_API_KEY")
        self.console_url = (
            console_url or os.getenv("GALILEO_CONSOLE_URL") or "https://console.galileo.ai"
        )

        if not self.api_key:
            raise ValueError(
                "GALILEO_API_KEY is required. "
                "Set it as an environment variable or pass it to the constructor."
            )

        # Derive API base URL from console URL
        # console.galileo.ai -> api.galileo.ai
        # console.demo-v2.galileocloud.io -> api.demo-v2.galileocloud.io
        self.api_base = self._derive_api_url(self.console_url)

        self._client: httpx.AsyncClient | None = None

    def _derive_api_url(self, console_url: str) -> str:
        """Derive the API URL from the console URL.

        Args:
            console_url: The Galileo Console URL.

        Returns:
            The corresponding API URL.
        """
        # Remove trailing slash
        url = console_url.rstrip("/")

        # Replace 'console.' with 'api.' in the hostname
        if "console." in url:
            return url.replace("console.", "api.")

        # If no 'console.' prefix, try to construct API URL
        # e.g., https://galileo.ai -> https://api.galileo.ai
        if url.startswith("https://"):
            return url.replace("https://", "https://api.")
        elif url.startswith("http://"):
            return url.replace("http://", "http://api.")

        return url

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Returns:
            The async HTTP client instance.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "Galileo-API-Key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECS),
            )
        return self._client

    async def invoke_protect(
        self,
        payload: Payload,
        project_name: str | None = None,
        project_id: str | None = None,
        stage_name: str | None = None,
        stage_id: str | None = None,
        stage_version: int | None = None,
        prioritized_rulesets: list[Ruleset] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        metadata: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> ProtectResponse:
        """Invoke the Galileo Protect API.

        This method sends a request to the Galileo Protect API for evaluation.
        It supports both local stages (with runtime rulesets) and central stages
        (with pre-defined server-side rulesets).

        Args:
            payload: The payload containing input/output text to evaluate.
            project_name: Name of the Galileo project.
            project_id: UUID of the Galileo project (alternative to project_name).
            stage_name: Name of the stage (for central stages).
            stage_id: UUID of the stage (alternative to stage_name).
            stage_version: Specific version of the stage to use.
            prioritized_rulesets: Rulesets for local stage evaluation.
            timeout: Request timeout in seconds.
            metadata: Additional metadata to include in the request.
            headers: Additional headers to include in the request.

        Returns:
            ProtectResponse containing the evaluation results.

        Raises:
            httpx.HTTPStatusError: If the API returns an error status code.
            httpx.RequestError: If there's a network error.
        """
        client = await self._get_client()

        # Build request body
        request_body: dict[str, Any] = {
            "payload": payload.to_dict(),
        }

        # Add project identification
        if project_id:
            request_body["project_id"] = project_id
        if project_name:
            request_body["project_name"] = project_name

        # Add stage identification (for central stages)
        if stage_id:
            request_body["stage_id"] = stage_id
        if stage_name:
            request_body["stage_name"] = stage_name
        if stage_version is not None:
            request_body["stage_version"] = stage_version

        # Add rulesets (for local stages)
        if prioritized_rulesets:
            request_body["prioritized_rulesets"] = [rs.to_dict() for rs in prioritized_rulesets]

        # Add metadata
        if metadata:
            request_body["metadata"] = metadata

        # Build request headers
        request_headers = {}
        if headers:
            request_headers.update(headers)

        # Construct the API endpoint
        endpoint = f"{self.api_base}/v1/protect/invoke"

        logger.debug(f"[GalileoProtectClient] POST {endpoint}")
        logger.debug(f"[GalileoProtectClient] Request body: {request_body}")

        try:
            response = await client.post(
                endpoint,
                json=request_body,
                headers=request_headers,
                timeout=timeout,
            )
            response.raise_for_status()

            response_data = response.json()
            logger.debug(f"[GalileoProtectClient] Response: {response_data}")

            return ProtectResponse.from_dict(response_data)

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[GalileoProtectClient] API error: {e.response.status_code} - {e.response.text}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"[GalileoProtectClient] Request failed: {e}")
            raise

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "GalileoProtectClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
