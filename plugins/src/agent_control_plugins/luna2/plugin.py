"""Luna-2 plugin implementation."""

import asyncio
import logging
import os
from typing import Any

try:
    from galileo.protect import Payload, Ruleset, ainvoke_protect  # type: ignore
    from galileo_core.schemas.protect.action import PassthroughAction  # type: ignore
    from galileo_core.schemas.protect.rule import Rule  # type: ignore

    LUNA2_AVAILABLE = True
except ImportError:
    LUNA2_AVAILABLE = False
    Payload = None  # type: ignore
    Ruleset = None  # type: ignore
    PassthroughAction = None  # type: ignore
    Rule = None  # type: ignore
    ainvoke_protect = None  # type: ignore

from agent_control_models import (
    EvaluatorResult,
    PluginEvaluator,
    PluginMetadata,
    register_plugin,
)

from .config import Luna2Config

logger = logging.getLogger(__name__)


# Only register if Galileo SDK is available
def _maybe_register(cls: type) -> type:
    """Conditionally register plugin if dependencies available."""
    if LUNA2_AVAILABLE:
        return register_plugin(cls)
    return cls


@_maybe_register
class Luna2Plugin(PluginEvaluator[Luna2Config]):
    """Galileo Luna-2 runtime protection plugin.

    This plugin uses Galileo's Luna-2 enterprise model for real-time
    safety and quality checks on agent inputs and outputs.

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
    """

    metadata = PluginMetadata(
        name="galileo-luna2",
        version="1.0.0",
        description="Galileo Luna-2 enterprise runtime protection",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = Luna2Config

    def __init__(self, config: Luna2Config) -> None:
        """Initialize Luna-2 plugin with configuration.

        Args:
            config: Validated Luna2Config instance

        Raises:
            ImportError: If Galileo SDK not installed
            ValueError: If GALILEO_API_KEY not set
        """
        if not LUNA2_AVAILABLE:
            raise ImportError(
                "Luna-2 plugin requires the Galileo SDK.\n"
                "Install with: pip install agent-control-plugins[luna2]\n"
                "Or: pip install galileo>=1.34.0"
            )

        # Verify API key is configured
        if not os.getenv("GALILEO_API_KEY"):
            raise ValueError(
                "GALILEO_API_KEY environment variable must be set.\n"
                "Get your API key from: https://app.galileo.ai"
            )

        super().__init__(config)

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate data using Galileo Luna-2.

        Args:
            data: The data to evaluate (from selector)

        Returns:
            EvaluatorResult with matched status and metadata
        """
        if self.config.stage_type == "local":
            return await self._evaluate_local_stage(data)
        else:
            return await self._evaluate_central_stage(data)

    def _get_numeric_target_value(self) -> float | int | str | None:
        """Get target_value as numeric if possible (for proper Rule comparison)."""
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
        """Evaluate using a local stage (runtime rulesets)."""
        payload = self._prepare_payload(data)

        # Create Rule with numeric target_value for proper comparison
        rule = Rule(
            metric=self.config.metric,
            operator=self.config.operator,
            target_value=self._get_numeric_target_value(),
        )

        # Create proper Ruleset with PassthroughAction
        ruleset = Ruleset(
            rules=[rule],
            action=PassthroughAction(type="PASSTHROUGH"),
            description=f"Agent-control rule: {self.config.metric}",
        )

        try:
            logger.debug(f"[Luna2] Calling ainvoke_protect")
            logger.debug(f"[Luna2] Payload: {payload}")
            logger.debug(f"[Luna2] Ruleset: {ruleset}")

            response = await ainvoke_protect(
                payload=payload,
                prioritized_rulesets=[ruleset],
                project_name=self.config.galileo_project,
                timeout=self.get_timeout_seconds(),
                metadata=self.config.metadata or {},
            )

            logger.debug(f"[Luna2] Response: {response}")
            if hasattr(response, 'status'):
                logger.debug(f"[Luna2] Status: {response.status}")
            if hasattr(response, 'text'):
                logger.debug(f"[Luna2] Text: {response.text}")

            result = self._parse_response(response)
            logger.debug(f"[Luna2] Parsed: matched={result.matched}, msg={result.message}")
            return result
        except Exception as e:
            logger.error(f"Luna-2 async evaluation error: {e}", exc_info=True)
            return self._handle_error(e)

    async def _evaluate_central_stage(self, data: Any) -> EvaluatorResult:
        """Evaluate using a central stage (pre-defined rulesets)."""
        payload = self._prepare_payload(data)

        try:
            response = await ainvoke_protect(
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

    def _prepare_payload(self, data: Any) -> Any:
        """Prepare the Payload for Galileo protect.

        Payload has 'input' and 'output' fields based on what we're checking.
        Returns a Galileo Payload object.
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

    def _parse_response(self, response: Any) -> EvaluatorResult:
        """Parse Galileo protect response into EvaluatorResult.

        Response is a Pydantic model with attributes:
            - status: ExecutionStatus enum (triggered, success, skipped, paused)
            - text: Response message
            - trace_metadata: TraceMetadata object with id, execution_time, etc.
        """
        if not response:
            return EvaluatorResult(
                matched=False,
                confidence=0.0,
                message="No response from Luna-2",
                metadata={"error": "empty_response"},
            )

        # Handle Pydantic Response model from Galileo SDK
        if hasattr(response, "status"):
            raw_status = response.status
            if hasattr(raw_status, "value"):
                raw_status = raw_status.value
            status = str(raw_status).lower()
        else:
            status_val = response.get("status", "") if isinstance(response, dict) else ""
            status = str(status_val).lower()

        triggered = status == "triggered"

        # Extract text
        if hasattr(response, "text"):
            text = response.text
        else:
            text = response.get("text", "") if isinstance(response, dict) else str(response)

        # Extract trace metadata
        trace_id = None
        execution_time = None
        received_at = None
        response_at = None

        if hasattr(response, "trace_metadata") and response.trace_metadata:
            tm = response.trace_metadata
            trace_id = str(tm.id) if hasattr(tm, "id") else None
            execution_time = tm.execution_time if hasattr(tm, "execution_time") else None
            received_at = tm.received_at if hasattr(tm, "received_at") else None
            response_at = tm.response_at if hasattr(tm, "response_at") else None
        elif isinstance(response, dict):
            trace_metadata = response.get("trace_metadata", {})
            trace_id = trace_metadata.get("id")
            execution_time = trace_metadata.get("execution_time")
            received_at = trace_metadata.get("received_at")
            response_at = trace_metadata.get("response_at")

        return EvaluatorResult(
            matched=triggered,
            confidence=1.0 if triggered else 0.0,
            message=text or f"Luna-2 check: {status}",
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
        """Handle errors from Luna-2 evaluation."""
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
