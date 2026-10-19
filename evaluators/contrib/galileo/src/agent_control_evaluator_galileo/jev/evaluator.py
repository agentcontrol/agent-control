"""Galileo Jev decision-model evaluator."""

from __future__ import annotations

import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult, JSONObject, JSONValue, Step

from ..luna.client import GalileoExecutionContext
from ..luna.config import scorer_invoke_runtime_enabled
from .client import GalileoJevClient, JevInvokeInputs, JevInvokeResponse
from .config import JevEvaluatorConfig

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
class JevEvaluator(Evaluator[JevEvaluatorConfig]):
    """Evaluate data using a pinned Galileo Jev decision scorer."""

    metadata = EvaluatorMetadata(
        name="galileo.jev",
        version=_PACKAGE_VERSION,
        description="Galileo Jev decision scorer evaluation",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = JevEvaluatorConfig

    def __init__(self, config: JevEvaluatorConfig) -> None:
        super().__init__(config)
        self._client = GalileoJevClient()

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Return an actionable error because Jev requires runtime context."""
        if not scorer_invoke_runtime_enabled() or not self._client.runtime_enabled:
            return self._error(
                RuntimeError(
                    "Galileo scorer-invoke runtime is disabled; galileo.jev requires "
                    "GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME=enabled."
                )
            )
        return self._error(RuntimeError("galileo.jev requires Step context and execution_context"))

    async def evaluate_with_context(self, data: Any, step: Step) -> EvaluatorResult:
        """Evaluate a step when an authenticated execution context is supplied by extensions."""
        return await self._evaluate(data, step, None)

    async def evaluate_with_extensions(
        self, data: Any, step: Step, extensions: JSONObject | None
    ) -> EvaluatorResult:
        """Evaluate with execution identity forwarded from trusted runtime extensions."""
        try:
            context = self._execution_context(extensions)
            if context is None:
                raise ValueError("galileo.jev requires execution_context")
            return await self._evaluate(data, step, context)
        except Exception as exc:
            return self._error(exc)

    async def _evaluate(
        self, data: Any, step: Step, execution_context: GalileoExecutionContext | None
    ) -> EvaluatorResult:
        try:
            if not scorer_invoke_runtime_enabled() or not self._client.runtime_enabled:
                raise RuntimeError(
                    "Galileo scorer-invoke runtime is disabled; galileo.jev requires "
                    "GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME=enabled."
                )
            if execution_context is None:
                raise ValueError("galileo.jev requires execution_context")
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
                    response.error_message or f"Jev scorer status: {response.status}"
                )
            if response.score is None:
                raise RuntimeError("Jev scorer response did not include a score")
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
                    f"Jev result {response.score!r} {self.config.operator} "
                    f"threshold {self.config.threshold!r}: control "
                    f"{'triggered' if matched else 'not triggered'}."
                ),
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("Jev evaluation error: %s", exc, exc_info=True)
            return self._error(exc)

    @staticmethod
    def _execution_context(extensions: JSONObject | None) -> GalileoExecutionContext | None:
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
        return GalileoExecutionContext(
            organization_id=organization_id,
            user_id=user_id if isinstance(user_id, str) and user_id else None,
            project_id=project_id if isinstance(project_id, str) else None,
            run_id=run_id if isinstance(run_id, str) and run_id else None,
        )

    @staticmethod
    def _inputs(data: Any, step: Step) -> JevInvokeInputs:
        """Build the legacy inputs without rejecting valid child-only records."""
        if isinstance(data, dict) and ("input" in data or "output" in data):
            query = data.get("input", "")
            response = data.get("output", "")
        elif data is not None and data != "":
            query, response = data, ""
        else:
            query, response = step.input, step.output if step.output is not None else ""
        return JevInvokeInputs(
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
            raise ValueError(f"Jev result {value!r} is not numeric for operator '{operator}'")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise ValueError(f"Jev threshold {threshold!r} is not numeric")
        return {
            "gt": value > threshold,
            "gte": value >= threshold,
            "lt": value < threshold,
            "lte": value <= threshold,
        }[operator]

    def _metadata(self, response: JevInvokeResponse) -> dict[str, Any]:
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
            message=f"Jev evaluation error: {detail}",
            metadata=metadata,
            error=detail,
        )

    async def aclose(self) -> None:
        """Close the Jev HTTP client."""
        await self._client.close()
