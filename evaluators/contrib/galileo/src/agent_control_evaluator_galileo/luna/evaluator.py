"""Direct Galileo Luna evaluator implementation."""

from __future__ import annotations

import json
import logging
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult, JSONObject, JSONValue, Step

from .client import GalileoExecutionContext, GalileoLunaClient, ScorerInvokeResponse
from .config import LunaEvaluatorConfig, coerce_number

logger = logging.getLogger(__name__)


def _resolve_package_version() -> str:
    """Return the installed package version, or a dev fallback during local imports."""
    try:
        return version("agent-control-evaluator-galileo")
    except PackageNotFoundError:
        return "0.0.0.dev"


_PACKAGE_VERSION = _resolve_package_version()
LUNA_AVAILABLE = True
_HTTP_ERROR_BODY_LIMIT = 500


def _coerce_payload_text(value: Any) -> str | None:
    """Coerce selected data into scorer text without losing structured values."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _has_text(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def _extract_dict_text(data: dict[str, Any], key: str) -> str | None:
    if key not in data:
        return None
    return _coerce_payload_text(data.get(key))


def _contains(score: JSONValue, threshold: JSONValue) -> bool:
    if threshold is None:
        return False
    if isinstance(score, str):
        return str(threshold) in score
    if isinstance(score, list):
        return threshold in score
    if isinstance(score, dict):
        return threshold in score.values()
    return False


def _confidence_from_score(score: JSONValue) -> float:
    if isinstance(score, bool):
        return 1.0 if score else 0.0
    number = coerce_number(score)
    if number is not None and 0.0 <= number <= 1.0:
        return number
    return 1.0


def _truncated_http_response_body(body: str) -> tuple[str, bool]:
    if len(body) <= _HTTP_ERROR_BODY_LIMIT:
        return body, False
    return body[:_HTTP_ERROR_BODY_LIMIT], True


def _http_status_error_metadata(error: httpx.HTTPStatusError) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    request = error.request
    metadata["http_method"] = request.method
    metadata["http_endpoint_path"] = request.url.path

    response = error.response
    metadata["http_status_code"] = response.status_code
    metadata["http_response_content_type"] = response.headers.get("content-type")

    body = response.text
    if body:
        metadata["http_response_body"], metadata["http_response_body_truncated"] = (
            _truncated_http_response_body(body)
        )

    return {key: value for key, value in metadata.items() if value is not None}


@register_evaluator
class LunaEvaluator(Evaluator[LunaEvaluatorConfig]):
    """Galileo Luna evaluator using the direct scorer invocation API."""

    metadata = EvaluatorMetadata(
        name="galileo.luna",
        version=_PACKAGE_VERSION,
        description="Galileo Luna direct scorer evaluation",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = LunaEvaluatorConfig

    @classmethod
    def is_available(cls) -> bool:
        """Check whether required runtime dependencies are available."""
        return LUNA_AVAILABLE

    def __init__(self, config: LunaEvaluatorConfig) -> None:
        """Initialize the direct Luna evaluator.

        Args:
            config: Validated LunaEvaluatorConfig instance.

        Raises:
            ValueError: If neither GALILEO_API_SECRET_KEY nor GALILEO_API_SECRET is set.
        """
        has_secret = os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        if not has_secret:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for Luna "
                "scorer invocation. Set one as an environment variable before using "
                "galileo.luna."
            )

        super().__init__(config)
        self._client = GalileoLunaClient()

    def _get_client(self) -> GalileoLunaClient:
        """Get the Galileo Luna client."""
        return self._client

    def _prepare_payload(self, data: Any) -> tuple[str | None, str | None]:
        """Prepare scorer input/output fields from selected data."""
        if isinstance(data, dict):
            input_text = _extract_dict_text(data, "input")
            output_text = _extract_dict_text(data, "output")
            if _has_text(input_text) or _has_text(output_text):
                return input_text, output_text

        text = _coerce_payload_text(data)
        if self.config.payload_field == "output":
            return None, text
        return text, None

    def _score_matches(self, score: JSONValue) -> bool:
        """Apply the configured local threshold comparison to a raw Luna score."""
        operator = self.config.operator
        threshold = self.config.threshold

        if operator == "any":
            return bool(score)
        if operator == "eq":
            return score == threshold
        if operator == "ne":
            return score != threshold
        if operator == "contains":
            return _contains(score, threshold)

        score_number = coerce_number(score)
        threshold_number = coerce_number(threshold)
        if score_number is None:
            raise ValueError(f"Luna score {score!r} is not numeric")
        if threshold_number is None:
            raise ValueError(f"Luna threshold {threshold!r} is not numeric")

        if operator == "gt":
            return score_number > threshold_number
        if operator == "gte":
            return score_number >= threshold_number
        if operator == "lt":
            return score_number < threshold_number
        if operator == "lte":
            return score_number <= threshold_number

        raise ValueError(f"Unsupported Luna operator: {operator}")

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate selected data with Galileo Luna direct scorer invocation.

        Args:
            data: The data selected from the runtime step.

        Returns:
            EvaluatorResult with local threshold decision and scorer metadata.
        """
        return await self._evaluate(data, step=None)

    async def evaluate_with_context(self, data: Any, step: Step) -> EvaluatorResult:
        """Evaluate selected data while dual-writing the complete runtime step.

        Args:
            data: Data selected by the configured control selector.
            step: Complete runtime step for structured scorer context.

        Returns:
            EvaluatorResult with local threshold decision and scorer metadata.
        """
        return await self._evaluate(data, step=step)

    async def evaluate_with_extensions(
        self,
        data: Any,
        step: Step,
        extensions: JSONObject | None,
    ) -> EvaluatorResult:
        """Evaluate using opaque authenticated metadata supplied by Agent Control."""
        return await self._evaluate(
            data,
            step=step,
            extensions=extensions,
        )

    @staticmethod
    def _execution_context_from_extensions(
        extensions: JSONObject | None,
    ) -> GalileoExecutionContext | None:
        """Translate trusted opaque auth metadata into Galileo's request context."""
        if extensions is None:
            return None

        metadata = extensions.get("metadata")
        metadata_obj = metadata if isinstance(metadata, dict) else {}
        organization_id = extensions.get("namespace_key")
        # The runtime envelope's caller_id is supplied by the authenticated
        # principal and is the caller identity Galileo associates with this run.
        user_id = extensions.get("caller_id")
        project_id = metadata_obj.get("project_id")
        target_type = extensions.get("target_type")
        target_id = extensions.get("target_id")
        run_id = (
            target_id
            if target_type in ("log_stream", "agent_stream")
            and isinstance(target_id, str)
            and target_id
            else None
        )
        if not isinstance(organization_id, str) or not organization_id:
            raise ValueError("Authenticated execution metadata is missing organization_id")

        resolved_user_id = user_id if isinstance(user_id, str) and user_id else None
        resolved_project_id = project_id if isinstance(project_id, str) and project_id else None
        raw_api_key = os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET") or ""
        api_key_hint = f"...{raw_api_key[-4:]}" if len(raw_api_key) >= 4 else "***"
        logger.info(
            "[execution_context] caller_id=%r → user_id=%r org=%r project=%r run=%r api_key=%s",
            user_id,
            resolved_user_id,
            organization_id,
            resolved_project_id,
            run_id,
            api_key_hint,
        )
        return GalileoExecutionContext(
            organization_id=organization_id,
            user_id=resolved_user_id,
            project_id=resolved_project_id,
            run_id=run_id,
        )

    async def _evaluate(
        self,
        data: Any,
        *,
        step: Step | None,
        extensions: JSONObject | None = None,
    ) -> EvaluatorResult:
        """Run a Luna evaluation with optional structured runtime context."""
        display = self.__class__.__name__
        scorer_id = self.config.scorer_id
        logger.info("[%s] Dispatching scorer evaluation: scorer_id=%s", display, scorer_id)
        input_text, output_text = self._prepare_payload(data)
        if not (_has_text(input_text) or _has_text(output_text)):
            logger.info("[%s] Skipping scorer invocation: no data to score", display)
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No data to score with Luna",
                metadata=self._base_metadata(),
            )

        try:
            execution_context = self._execution_context_from_extensions(extensions)
            scorer_kwargs = self._scorer_kwargs()
            if step is not None:
                scorer_kwargs["step"] = step
                scorer_kwargs["selected_data"] = data
                scorer_kwargs["selected_data_payload_field"] = self.config.payload_field
            if execution_context is not None:
                scorer_kwargs["execution_context"] = execution_context
            logger.info(
                "[%s] Invoking scorer: scorer_id=%s timeout=%.1fs",
                display,
                scorer_id,
                self.get_timeout_seconds(),
            )
            response = await self._get_client().invoke(
                **scorer_kwargs,
                input=input_text if _has_text(input_text) else None,
                output=output_text if _has_text(output_text) else None,
                config=self.config.scorer_config,
                timeout=self.get_timeout_seconds(),
            )

            if response.status.lower() != "success":
                message = response.error_message or f"Luna scorer status: {response.status}"
                raise RuntimeError(message)

            matched = self._score_matches(response.score)
            metadata = self._metadata(response)
            operator = self.config.operator
            threshold = self.config.threshold
            state = "triggered" if matched else "not triggered"
            logger.info(
                "[%s] Scorer result: scorer_id=%s score=%r %s threshold=%r → %s",
                display,
                scorer_id,
                response.score,
                operator,
                threshold,
                state,
            )
            return EvaluatorResult(
                matched=matched,
                confidence=_confidence_from_score(response.score),
                message=(
                    f"Luna score {response.score!r} {operator} threshold "
                    f"{threshold!r}: control {state}."
                ),
                metadata=metadata,
            )
        except Exception as exc:
            logger.error(
                "[%s] Scorer evaluation error: scorer_id=%s error=%s",
                display,
                scorer_id,
                exc,
                exc_info=True,
            )
            return self._handle_error(exc)

    def _base_metadata(self) -> dict[str, Any]:
        """Build result metadata without implying a requested version executed."""
        metadata: dict[str, Any] = {"scorer_id": self.config.scorer_id}
        if self.config.scorer_version_id is not None:
            metadata["requested_scorer_version_id"] = self.config.scorer_version_id
        if self.config.scorer_label is not None:
            metadata["scorer_label"] = self.config.scorer_label
        return metadata

    def _scorer_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"scorer_id": self.config.scorer_id}
        if self.config.scorer_version_id is not None:
            kwargs["scorer_version_id"] = self.config.scorer_version_id
        if self.config.scorer_label is not None:
            kwargs["scorer_label"] = self.config.scorer_label
        return kwargs

    def _metadata(
        self,
        response: ScorerInvokeResponse,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = self._base_metadata()
        echoed_label = response.scorer_label or self.config.scorer_label
        if echoed_label is not None:
            metadata["scorer_label"] = echoed_label
        metadata.update(
            {
                "score": response.score,
                "threshold": self.config.threshold,
                "operator": self.config.operator,
                "status": response.status,
                "execution_time_seconds": response.execution_time,
                "error_message": response.error_message,
            }
        )
        return metadata

    def _handle_error(
        self,
        error: Exception,
    ) -> EvaluatorResult:
        error_detail = str(error)
        metadata: dict[str, Any] = {
            **self._base_metadata(),
            "error_type": type(error).__name__,
        }
        if isinstance(error, httpx.HTTPStatusError):
            metadata.update(_http_status_error_metadata(error))

        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"Luna evaluation error: {error_detail}",
            metadata=metadata,
            error=error_detail,
        )

    async def aclose(self) -> None:
        """Close the underlying Galileo Luna client."""
        await self._client.close()
