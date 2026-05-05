"""Luna-2 evaluator implementation using direct API calls.

This evaluator calls the Galileo Protect API directly via HTTP, without requiring
the full galileo-sdk package. Only httpx is needed as a dependency.
"""

import logging
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult

from agent_control_evaluator_galileo.luna2.config import Luna2EvaluatorConfig

logger = logging.getLogger(__name__)


def _resolve_package_version() -> str:
    """Return the installed package version, or a dev fallback during local imports."""
    try:
        return version("agent-control-evaluator-galileo")
    except PackageNotFoundError:
        return "0.0.0.dev"


_PACKAGE_VERSION = _resolve_package_version()

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


@register_evaluator
class Luna2Evaluator(Evaluator[Luna2EvaluatorConfig]):
    """Galileo Luna-2 runtime protection evaluator.

    This evaluator uses Galileo's Luna-2 enterprise model for real-time
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
        from agent_control_evaluator_galileo.luna2 import Luna2Evaluator, Luna2EvaluatorConfig

        config = Luna2EvaluatorConfig(
            stage_type="local",
            metric="input_toxicity",
            operator="gt",
            target_value=0.8,
            galileo_project="my-project",
        )

        evaluator = Luna2Evaluator(config)
        result = await evaluator.evaluate("some text")
        ```

    Environment Variables:
        GALILEO_API_KEY: Your Galileo API key (required).
        GALILEO_CONSOLE_URL: Galileo Console URL (optional).
    """

    metadata = EvaluatorMetadata(
        name="galileo.luna2",
        version=_PACKAGE_VERSION,
        description="Galileo Luna-2 enterprise runtime protection (direct API)",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = Luna2EvaluatorConfig

    @classmethod
    def is_available(cls) -> bool:
        """Check if httpx dependency is installed."""
        return LUNA2_AVAILABLE

    def __init__(self, config: Luna2EvaluatorConfig) -> None:
        """Initialize Luna-2 evaluator with configuration.

        Args:
            config: Validated Luna2EvaluatorConfig instance.

        Raises:
            ValueError: If GALILEO_API_KEY is not set.
        """
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

        We use PASSTHROUGH action so Protect computes the metric and returns
        metric_results without making a block decision itself — agent-control
        owns that decision via the control's action.decision field.

        Numeric operators (gt, lt, gte, lte, eq): Protect evaluates the rule
        server-side and returns status="triggered" when the condition is met,
        so _parse_response picks it up directly.

        Categorical operators (not_empty, any): the Protect local-stage rule
        engine does not support these operators and always returns
        status="not_triggered", even when the metric value is non-empty.
        _parse_response falls back to _evaluate_metric_results which evaluates
        the condition client-side from the raw metric_results dict.

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
                stage_name=self.config.stage_name,
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
            payload = Payload(input="", output=data_str)
        else:
            # Default to input for central stages or input metrics
            payload = Payload(input=data_str, output="")

        logger.debug(
            "[Luna2] _prepare_payload: metric=%r payload_field_config=%r "
            "→ input=%d chars, output=%d chars",
            self.config.metric,
            self.config.payload_field,
            len(payload.input),
            len(payload.output),
        )
        return payload

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

        # Numeric operators (gt/lt/etc.) are evaluated server-side by Protect and
        # return status="triggered" correctly even with PASSTHROUGH.
        # Categorical operators (not_empty, any) are NOT supported by Protect's
        # local-stage rule engine — it always returns status="not_triggered" for
        # them regardless of the metric value.  Fall back to client-side evaluation
        # from metric_results for those cases.
        if not triggered and response.metric_results:
            triggered = self._evaluate_metric_results(response.metric_results)

        logger.info(
            "[Luna2] response: status=%r triggered=%s metric_results=%s",
            status,
            triggered,
            response.metric_results,
        )

        # Extract trace metadata
        trace_id = response.trace_metadata.id if response.trace_metadata else None
        execution_time = response.trace_metadata.execution_time if response.trace_metadata else None
        received_at = response.trace_metadata.received_at if response.trace_metadata else None
        response_at = response.trace_metadata.response_at if response.trace_metadata else None

        message = self._build_message(triggered, status, response.metric_results)

        return EvaluatorResult(
            matched=triggered,
            confidence=1.0 if triggered else 0.0,
            message=message,
            metadata={
                "status": status,
                "metric": self.config.metric or "unknown",
                "trace_id": trace_id,
                "execution_time_ms": execution_time,
                "received_at": received_at,
                "response_at": response_at,
            },
        )

    def _build_message(self, triggered: bool, status: str, metric_results: dict) -> str:
        """Build a human-readable message from the evaluation result."""
        metric = self.config.metric or "unknown"

        if not triggered:
            return f"Luna-2 {metric} check passed"

        result = (metric_results or {}).get(metric, {})
        value = result.get("value")

        if isinstance(value, list) and value:
            categories = ", ".join(str(v).replace("_", " ") for v in value)
            return f"{metric} detected: {categories}"
        if isinstance(value, (int, float)):
            return f"{metric} score {value:.2f} exceeded threshold"

        return f"Luna-2 {metric} check triggered"

    def _evaluate_metric_results(self, metric_results: dict) -> bool:
        """Evaluate the configured operator/target against raw metric_results.

        Used when the Protect API returns PASSTHROUGH (no server-side trigger)
        but we still need to decide whether the rule condition is met.

        Args:
            metric_results: The metric_results dict from the Protect API response.

        Returns:
            True if the rule condition is satisfied.
        """
        metric = self.config.metric
        if not metric or metric not in metric_results:
            return False

        result = metric_results[metric]
        if result.get("status") != "SUCCESS":
            return False

        value = result.get("value")
        operator = self.config.operator
        target = self.config.target_value

        if operator in ("not_empty", "not_null"):
            return bool(value)
        if operator in ("empty", "is_null"):
            return not bool(value)
        if operator == "any" and isinstance(value, list):
            return target in value if target is not None else bool(value)
        if operator == "contains":
            return target in value if (value and target is not None) else False
        if isinstance(value, (int, float)) and target is not None:
            try:
                t = float(target)
                if operator == "gt":
                    return value > t
                if operator == "gte":
                    return value >= t
                if operator == "lt":
                    return value < t
                if operator == "lte":
                    return value <= t
                if operator == "eq":
                    return value == t
            except (TypeError, ValueError):
                pass

        return False

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
