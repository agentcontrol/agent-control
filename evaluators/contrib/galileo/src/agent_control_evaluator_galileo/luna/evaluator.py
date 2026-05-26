"""Direct Galileo Luna evaluator implementation."""

from __future__ import annotations

import json
import logging
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult, JSONValue

from .client import GalileoLunaClient, ScorerInvokeResponse
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
            ValueError: If neither GALILEO_API_SECRET_KEY nor GALILEO_API_KEY is set.
        """
        has_auth = (
            os.getenv("GALILEO_API_SECRET_KEY")
            or os.getenv("GALILEO_API_SECRET")
            or os.getenv("GALILEO_API_KEY")
        )
        if not has_auth:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_KEY environment variable must be set. "
                "Set an API secret for internal auth or a Galileo API key before using "
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
        input_text, output_text = self._prepare_payload(data)
        if not (_has_text(input_text) or _has_text(output_text)):
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No data to score with Luna",
                metadata=self._base_metadata(),
            )

        try:
            scorer_kwargs = self._scorer_kwargs()
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
            logger.error("Luna evaluation error: %s", exc, exc_info=True)
            return self._handle_error(exc)

    def _base_metadata(self) -> dict[str, Any]:
        metadata = {
            "scorer_label": self.config.scorer_label,
            "scorer_id": self.config.scorer_id,
            "scorer_version_id": self.config.scorer_version_id,
        }
        return {key: value for key, value in metadata.items() if value is not None}

    def _scorer_kwargs(self) -> dict[str, Any]:
        kwargs = {
            "scorer_label": self.config.scorer_label,
            "scorer_id": self.config.scorer_id,
            "scorer_version_id": self.config.scorer_version_id,
        }
        return {key: value for key, value in kwargs.items() if value is not None}

    def _metadata(
        self,
        response: ScorerInvokeResponse,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = self._base_metadata()
        metadata.update({
            "scorer_label": response.scorer_label or self.config.scorer_label,
            "score": response.score,
            "threshold": self.config.threshold,
            "operator": self.config.operator,
            "status": response.status,
            "execution_time_seconds": response.execution_time,
            "error_message": response.error_message,
        })
        return metadata

    def _handle_error(
        self,
        error: Exception,
    ) -> EvaluatorResult:
        error_detail = str(error)
        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"Luna evaluation error: {error_detail}",
            metadata={
                "error_type": type(error).__name__,
                "scorer_label": self.config.scorer_label,
                "scorer_id": self.config.scorer_id,
                "scorer_version_id": self.config.scorer_version_id,
            },
            error=error_detail,
        )

    async def aclose(self) -> None:
        """Close the underlying Galileo Luna client."""
        await self._client.close()
