"""Galileo Decision Models evaluator."""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult, JSONObject, JSONValue, Step

from .client import (
    DecisionModelsExecutionContext,
    DecisionModelsInvokeInputs,
    DecisionModelsInvokeResponse,
    GalileoDecisionModelsClient,
)
from .config import (
    DecisionModelsEvaluatorConfig,
    decision_models_evaluator_enabled,
    scorer_invoke_runtime_enabled,
)

logger = logging.getLogger(__name__)

try:
    _PACKAGE_VERSION = version("agent-control-evaluator-galileo")
except PackageNotFoundError:
    _PACKAGE_VERSION = "0.0.0.dev"


def _contains(value: JSONValue, threshold: JSONValue) -> bool:
    if isinstance(value, str):
        return str(threshold) in value
    if isinstance(value, list):
        return threshold in value
    if isinstance(value, dict):
        return threshold in value.values()
    return False


@register_evaluator
class DecisionModelsEvaluator(Evaluator[DecisionModelsEvaluatorConfig]):
    """Evaluate data using a pinned Galileo Decision Models scorer."""

    metadata = EvaluatorMetadata(
        name="galileo.decision_models",
        version=_PACKAGE_VERSION,
        description="Galileo Decision Models scoring",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = DecisionModelsEvaluatorConfig

    @classmethod
    def is_available(cls) -> bool:
        """Expose Decision Models only when its feature flag and scorer runtime are enabled."""
        return decision_models_evaluator_enabled() and scorer_invoke_runtime_enabled()

    def __init__(self, config: DecisionModelsEvaluatorConfig) -> None:
        super().__init__(config)
        self._client = GalileoDecisionModelsClient()

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Return an actionable error because Decision Models requires runtime context."""
        if not scorer_invoke_runtime_enabled() or not self._client.runtime_enabled:
            return self._error(
                RuntimeError(
                    "Galileo scorer-invoke runtime is disabled; galileo.decision_models requires "
                    "GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME=enabled."
                )
            )
        return self._error(
            RuntimeError(
                "galileo.decision_models requires Step context and authenticated execution "
                "metadata from runtime extensions"
            )
        )

    async def evaluate_with_context(self, data: Any, step: Step) -> EvaluatorResult:
        """Evaluate a step when only step context is available.

        Decision Models also needs authenticated execution metadata, which this method does not
        receive. The explicit error helps callers distinguish missing runtime metadata from a
        missing step.
        """
        return await self._evaluate(data, step, None)

    async def evaluate_with_extensions(
        self, data: Any, step: Step, extensions: JSONObject | None
    ) -> EvaluatorResult:
        """Evaluate with execution identity forwarded from trusted runtime extensions."""
        try:
            context = self._execution_context(extensions)
            if context is None:
                raise ValueError(
                    "galileo.decision_models requires authenticated execution metadata from "
                    "runtime extensions"
                )
            return await self._evaluate(data, step, context)
        except Exception as exc:
            return self._error(exc)

    async def _evaluate(
        self, data: Any, step: Step, execution_context: DecisionModelsExecutionContext | None
    ) -> EvaluatorResult:
        try:
            if not scorer_invoke_runtime_enabled() or not self._client.runtime_enabled:
                raise RuntimeError(
                    "Galileo scorer-invoke runtime is disabled; galileo.decision_models requires "
                    "GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME=enabled."
                )
            if execution_context is None:
                raise ValueError(
                    "galileo.decision_models requires authenticated execution metadata from "
                    "runtime extensions; Step context alone is not sufficient"
                )
            inputs = self._inputs(data, step)
            response = await self._client.invoke(
                scorer_id=self.config.scorer_id,
                scorer_version_id=self.config.scorer_version_id,
                scorer_label=self.config.scorer_label,
                step=step,
                execution_context=execution_context,
                inputs=inputs,
                timeout=self.get_timeout_seconds(),
                selected_data=data,
                payload_field=self.config.payload_field,
            )
            if response.status.lower() != "success":
                raise RuntimeError(
                    response.error_message or f"Decision Models scorer status: {response.status}"
                )
            if response.score is None:
                raise RuntimeError("Decision Models scorer response did not include a score")
            matched = self._matches(response.score)
            metadata = self._metadata(response)
            confidence = (
                response.score
                if isinstance(response.score, float) and 0 <= response.score <= 1
                else 1.0
            )
            return EvaluatorResult(
                matched=matched,
                confidence=confidence,
                message=(
                    f"Decision Models result {response.score!r} {self.config.operator} "
                    f"threshold {self.config.threshold!r}: control "
                    f"{'triggered' if matched else 'not triggered'}."
                ),
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("Decision Models evaluation error: %s", exc, exc_info=True)
            return self._error(exc)

    @staticmethod
    def _execution_context(extensions: JSONObject | None) -> DecisionModelsExecutionContext | None:
        if extensions is None:
            return None
        metadata = extensions.get("metadata")
        metadata_obj = metadata if isinstance(metadata, dict) else {}
        organization_id = extensions.get("namespace_key")
        user_id = extensions.get("caller_id")
        target_type = extensions.get("target_type")
        target_id = extensions.get("target_id")
        run_id = target_id if target_type in ("log_stream", "agent_stream") else None
        project_id = metadata_obj.get("project_id")
        if not isinstance(organization_id, str) or not organization_id:
            raise ValueError("Authenticated execution metadata is missing organization_id")
        return DecisionModelsExecutionContext(
            organization_id=organization_id,
            user_id=user_id if isinstance(user_id, str) and user_id else None,
            project_id=project_id if isinstance(project_id, str) and project_id else None,
            run_id=run_id if isinstance(run_id, str) and run_id else None,
        )

    @staticmethod
    def _inputs(data: Any, step: Step) -> DecisionModelsInvokeInputs:
        """Build the legacy inputs without rejecting valid child-only records."""
        if isinstance(data, dict) and ("input" in data or "output" in data):
            query = data.get("input", "")
            response = data.get("output", "")
        elif data is not None and data != "":
            query, response = data, ""
        else:
            query, response = step.input, step.output if step.output is not None else ""
        return DecisionModelsInvokeInputs(
            query=query,
            response=response,
            ground_truth=step.ground_truth,
            tools=step.tools,
        )

    def _matches(self, value: JSONValue) -> bool:
        operator = self.config.operator
        threshold = self.config.threshold
        if operator == "any":
            return bool(value)
        if operator == "eq":
            return value == threshold
        if operator == "ne":
            return value != threshold
        if operator == "contains":
            return _contains(value, threshold)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"Decision Models result {value!r} is not numeric for operator '{operator}'"
            )
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError(f"Decision Models threshold {threshold!r} is not numeric")
        return {
            "gt": value > threshold,
            "gte": value >= threshold,
            "lt": value < threshold,
            "lte": value <= threshold,
        }[operator]

    def _metadata(self, response: DecisionModelsInvokeResponse) -> dict[str, Any]:
        return {
            "scorer_id": self.config.scorer_id,
            "scorer_version_id": self.config.scorer_version_id,
            "scorer_label": response.scorer_label or self.config.scorer_label,
            "score": response.score,
            "threshold": self.config.threshold,
            "operator": self.config.operator,
            "status": response.status,
            "execution_time_seconds": response.execution_time,
            "error_message": response.error_message,
        }

    def _error(self, error: Exception) -> EvaluatorResult:
        detail = str(error)
        metadata: dict[str, Any] = {
            "scorer_id": self.config.scorer_id,
            "scorer_version_id": self.config.scorer_version_id,
            "error_type": type(error).__name__,
        }
        if isinstance(error, httpx.HTTPStatusError):
            metadata["http_status_code"] = error.response.status_code
        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"Decision Models evaluation error: {detail}",
            metadata=metadata,
            error=detail,
        )

    async def aclose(self) -> None:
        """Close the Decision Models HTTP client."""
        await self._client.close()
