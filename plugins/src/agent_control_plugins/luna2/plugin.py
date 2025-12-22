"""Luna-2 plugin implementation using direct API calls.

This plugin calls the Galileo Protect API directly via HTTP, without requiring
the full galileo-sdk package. Only httpx is needed as a dependency.
"""

import logging
import os
from typing import Any

from agent_control_models import (
    EvaluatorResult,
    PluginEvaluator,
    PluginMetadata,
    register_plugin,
)

from .config import Luna2Config

logger = logging.getLogger(__name__)

# Check if httpx is available
try:
    import httpx

    from .client import (
        GalileoProtectClient,
        PassthroughAction,
        Payload,
        ProtectResponse,
        Rule,
        Ruleset,
    )

    LUNA2_AVAILABLE = True
except ImportError:
    LUNA2_AVAILABLE = False
    httpx = None  # type: ignore
    GalileoProtectClient = None  # type: ignore
    PassthroughAction = None  # type: ignore
    Payload = None  # type: ignore
    ProtectResponse = None  # type: ignore
    Rule = None  # type: ignore
    Ruleset = None  # type: ignore


# Only register if dependencies are available
def _maybe_register(cls: type) -> type:
    """Conditionally register plugin if dependencies available."""
    if LUNA2_AVAILABLE:
        return register_plugin(cls)
    return cls


@_maybe_register
class Luna2Plugin(PluginEvaluator[Luna2Config]):
    """Galileo Luna-2 runtime protection plugin.

    This plugin uses Galileo's Luna-2 enterprise model for real-time
    safety and quality checks on agent inputs and outputs. It calls
    the Galileo Protect API directly via HTTP.

    Supported Metrics:
        - input_toxicity, output_toxicity
        - input_sexism, output_sexism
        - prompt_injection
        - pii_detection
        - hallucination
        - tone
        - custom metrics (if configured in Galileo)

    Stage Types:
        - local: Define rules at runtime (full control)
        - central: Reference pre-defined stages managed in Galileo

    Example:
        ```python
        from agent_control_plugins.luna2 import Luna2Plugin, Luna2Config

        config = Luna2Config(
            stage_type="local",
            metric="input_toxicity",
            operator="gt",
            target_value=0.8,
            galileo_project="my-project",
        )

        plugin = Luna2Plugin(config)
        result = await plugin.evaluate("some text")
        ```

    Environment Variables:
        GALILEO_API_KEY: Your Galileo API key (required).
        GALILEO_CONSOLE_URL: Galileo Console URL (optional).
    """

    metadata = PluginMetadata(
        name="galileo-luna2",
        version="2.0.0",
        description="Galileo Luna-2 enterprise runtime protection (direct API)",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = Luna2Config

    def __init__(self, config: Luna2Config) -> None:
        """Initialize Luna-2 plugin with configuration.

        Args:
            config: Validated Luna2Config instance.

        Raises:
            ImportError: If httpx is not installed.
            ValueError: If GALILEO_API_KEY is not set.
        """
        if not LUNA2_AVAILABLE:
            raise ImportError(
                "Luna-2 plugin requires httpx.\n"
                "Install with: pip install agent-control-plugins[luna2]\n"
                "Or: pip install httpx>=0.24.0"
            )

        # Verify API key is configured
        if not os.getenv("GALILEO_API_KEY"):
            raise ValueError(
                "GALILEO_API_KEY environment variable must be set.\n"
                "Get your API key from: https://app.galileo.ai"
            )

        super().__init__(config)

        # Initialize the HTTP client
        self._client: GalileoProtectClient | None = None

    def _get_client(self) -> GalileoProtectClient:
        """Get or create the Galileo Protect client.

        Returns:
            The GalileoProtectClient instance.
        """
        if self._client is None:
            self._client = GalileoProtectClient()
        return self._client

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate data using Galileo Luna-2.

        Args:
            data: The data to evaluate (from selector).

        Returns:
            EvaluatorResult with matched status and metadata.
        """
        if self.config.stage_type == "local":
            return await self._evaluate_local_stage(data)
        else:
            return await self._evaluate_central_stage(data)

    def _get_numeric_target_value(self) -> float | int | str | None:
        """Get target_value as numeric if possible (for proper Rule comparison).

        Returns:
            The target value as a numeric type if possible, otherwise as-is.
        """
        target_val = self.config.target_value
        if isinstance(target_val, (int, float)):
            return target_val
        if isinstance(target_val, str):
            try:
                return float(target_val)
            except (ValueError, TypeError):
                return target_val  # Keep as string for non-numeric operators
        return target_val

    async def _evaluate_local_stage(self, data: Any) -> EvaluatorResult:
        """Evaluate using a local stage (runtime rulesets).

        Args:
            data: The data to evaluate.

        Returns:
            EvaluatorResult with evaluation results.
        """
        payload = self._prepare_payload(data)

        # Create Rule with numeric target_value for proper comparison
        rule = Rule(
            metric=self.config.metric or "",
            operator=self.config.operator or "",
            target_value=self._get_numeric_target_value() or 0,
        )

        # Create proper Ruleset with PassthroughAction
        ruleset = Ruleset(
            rules=[rule],
            action=PassthroughAction(type="PASSTHROUGH"),
            description=f"Agent-control rule: {self.config.metric}",
        )

        try:
            logger.debug("[Luna2] Calling Galileo Protect API (local stage)")
            logger.debug(f"[Luna2] Payload: {payload}")
            logger.debug(f"[Luna2] Ruleset: {ruleset}")

            client = self._get_client()
            response = await client.invoke_protect(
                payload=payload,
                prioritized_rulesets=[ruleset],
                project_name=self.config.galileo_project,
                timeout=self.get_timeout_seconds(),
                metadata=self.config.metadata or {},
            )

            # Check for None response before accessing attributes
            if response is None:
                return self._parse_response(None)

            logger.debug(f"[Luna2] Response status: {response.status}")
            logger.debug(f"[Luna2] Response text: {response.text}")

            result = self._parse_response(response)
            logger.debug(f"[Luna2] Parsed: matched={result.matched}, msg={result.message}")
            return result

        except Exception as e:
            logger.error(f"Luna-2 async evaluation error: {e}", exc_info=True)
            return self._handle_error(e)

    async def _evaluate_central_stage(self, data: Any) -> EvaluatorResult:
        """Evaluate using a central stage (pre-defined rulesets).

        Args:
            data: The data to evaluate.

        Returns:
            EvaluatorResult with evaluation results.
        """
        payload = self._prepare_payload(data)

        try:
            logger.debug("[Luna2] Calling Galileo Protect API (central stage)")
            logger.debug(f"[Luna2] Stage: {self.config.stage_name}")

            client = self._get_client()
            response = await client.invoke_protect(
                payload=payload,
                project_name=self.config.galileo_project,
                stage_name=self.config.stage_name,
                stage_version=self.config.stage_version,
                timeout=self.get_timeout_seconds(),
                metadata=self.config.metadata or {},
            )

            return self._parse_response(response)

        except Exception as e:
            logger.error(f"Luna-2 async central stage error: {e}", exc_info=True)
            return self._handle_error(e)

    def _prepare_payload(self, data: Any) -> Payload:
        """Prepare the Payload for Galileo Protect.

        Payload has 'input' and 'output' fields based on what we're checking.

        Args:
            data: The raw data to prepare.

        Returns:
            A Payload object ready for the API call.
        """
        data_str = str(data) if data is not None else ""

        # Check explicit payload_field config
        payload_field = self.config.payload_field
        if payload_field == "output":
            return Payload(input="", output=data_str)
        elif payload_field == "input":
            return Payload(input=data_str, output="")

        # Determine from metric name if provided
        metric = self.config.metric or ""
        is_output_metric = "output" in metric

        if is_output_metric:
            return Payload(input="", output=data_str)
        else:
            # Default to input for central stages or input metrics
            return Payload(input=data_str, output="")

    def _parse_response(self, response: ProtectResponse | None) -> EvaluatorResult:
        """Parse Galileo Protect response into EvaluatorResult.

        Args:
            response: The ProtectResponse from the API, or None if no response.

        Returns:
            EvaluatorResult with matched status and metadata.
        """
        if response is None:
            return EvaluatorResult(
                matched=False,
                confidence=0.0,
                message="No response from Luna-2",
                metadata={"error": "empty_response"},
            )

        status = response.status.lower() if response.status else "unknown"
        triggered = status == "triggered"

        # Extract trace metadata
        trace_id = response.trace_metadata.id if response.trace_metadata else None
        execution_time = response.trace_metadata.execution_time if response.trace_metadata else None
        received_at = response.trace_metadata.received_at if response.trace_metadata else None
        response_at = response.trace_metadata.response_at if response.trace_metadata else None

        return EvaluatorResult(
            matched=triggered,
            confidence=1.0 if triggered else 0.0,
            message=response.text or f"Luna-2 check: {status}",
            metadata={
                "status": status,
                "metric": self.config.metric or "unknown",
                "trace_id": trace_id,
                "execution_time_ms": execution_time,
                "received_at": received_at,
                "response_at": response_at,
            },
        )

    def _handle_error(self, error: Exception) -> EvaluatorResult:
        """Handle errors from Luna-2 evaluation.

        Args:
            error: The exception that occurred.

        Returns:
            EvaluatorResult indicating error state.
        """
        error_action = self.config.on_error

        return EvaluatorResult(
            matched=(error_action == "deny"),  # Fail closed if configured
            confidence=0.0,
            message=f"Luna-2 evaluation error: {str(error)}",
            metadata={
                "error": str(error),
                "error_type": type(error).__name__,
                "metric": self.config.metric,
                "fallback_action": error_action,
            },
        )
