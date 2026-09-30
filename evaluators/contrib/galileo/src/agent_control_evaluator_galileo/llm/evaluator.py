"""Direct Galileo LLM-as-judge evaluator implementation."""

from __future__ import annotations

import logging
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult, Step

from agent_control_evaluator_galileo.llm.client import GalileoLLMClient, ScorerInvokeResponse
from agent_control_evaluator_galileo._shared.evaluator_helpers import (
    _coerce_payload_text,
    _confidence_from_score,
    _extract_dict_text,
    _has_text,
    _http_status_error_metadata,
    base_metadata,
    full_metadata,
    score_matches,
)

from .config import LlmEvaluatorConfig

LLM_AVAILABLE = True

logger = logging.getLogger(__name__)

# The caller-identity ContextVar is set by the AC server's evaluation endpoint
# before engine.process() runs. It is read here to embed user_id and
# organization_id in the outbound scorer JWT so runners-api can resolve LLM
# provider credentials. The import is deferred to avoid a hard dependency on
# the server package — if the ContextVar is not available (e.g. in tests or
# direct SDK usage) the evaluator falls back to an identity-free JWT.
def _get_caller_context() -> dict[str, str]:
    try:
        from agent_control_server.endpoints.evaluation import _caller_context  # type: ignore[import]
        return _caller_context.get()
    except ImportError:
        return {}


def _resolve_package_version() -> str:
    """Return the installed package version, or a dev fallback during local imports."""
    try:
        return version("agent-control-evaluator-galileo")
    except PackageNotFoundError:
        return "0.0.0.dev"


_PACKAGE_VERSION = _resolve_package_version()


@register_evaluator
class LlmEvaluator(Evaluator[LlmEvaluatorConfig]):
    """Galileo LLM-as-judge evaluator using the direct scorer invocation API."""

    metadata = EvaluatorMetadata(
        name="galileo.llm",
        version=_PACKAGE_VERSION,
        description="Galileo LLM-as-judge direct scorer evaluation",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = LlmEvaluatorConfig

    @classmethod
    def is_available(cls) -> bool:
        """Check whether required runtime dependencies are available."""
        return LLM_AVAILABLE

    def __init__(self, config: LlmEvaluatorConfig) -> None:
        """Initialize the direct LLM-as-judge evaluator.

        Args:
            config: Validated LlmEvaluatorConfig instance.

        Raises:
            ValueError: If neither GALILEO_API_SECRET_KEY nor GALILEO_API_SECRET is set.
        """
        has_secret = os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        if not has_secret:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for LLM "
                "scorer invocation. Set one as an environment variable before using "
                "galileo.llm."
            )

        super().__init__(config)
        self._client = GalileoLLMClient()

    def _get_client(self) -> GalileoLLMClient:
        """Get the Galileo LLM scorer client."""
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

    def _score_matches(self, score: Any) -> bool:
        """Apply the configured local threshold comparison to a raw LLM scorer score."""
        return score_matches(score, operator=self.config.operator, threshold=self.config.threshold)

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate selected data with Galileo LLM-as-judge direct scorer invocation.

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

    async def _evaluate(self, data: Any, *, step: Step | None) -> EvaluatorResult:
        """Run an LLM scorer evaluation with optional structured runtime context."""
        input_text, output_text = self._prepare_payload(data)
        if not (_has_text(input_text) or _has_text(output_text)):
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No data to score with LLM scorer",
                metadata=self._base_metadata(),
            )

        try:
            scorer_kwargs = self._scorer_kwargs()
            if step is not None:
                scorer_kwargs["step"] = step
            caller_ctx = _get_caller_context()
            response = await self._get_client().invoke(
                **scorer_kwargs,
                input=input_text if _has_text(input_text) else None,
                output=output_text if _has_text(output_text) else None,
                config=None,
                timeout=self.get_timeout_seconds(),
                user_id=caller_ctx.get("user_id"),
                organization_id=caller_ctx.get("organization_id"),
            )

            if response.status.lower() != "success":
                message = response.error_message or f"LLM scorer status: {response.status}"
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
                    f"LLM scorer score {response.score!r} {operator} threshold "
                    f"{threshold!r}: control {state}."
                ),
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("LLM scorer evaluation error: %s", exc, exc_info=True)
            return self._handle_error(exc)

    def _base_metadata(self) -> dict[str, Any]:
        return base_metadata(
            self.config.scorer_id,
            scorer_version_id=self.config.scorer_version_id,
            scorer_label=self.config.scorer_label,
        )

    def _scorer_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"scorer_id": self.config.scorer_id}
        if self.config.scorer_version_id is not None:
            kwargs["scorer_version_id"] = self.config.scorer_version_id
        if self.config.scorer_label is not None:
            kwargs["scorer_label"] = self.config.scorer_label
        return kwargs

    def _metadata(self, response: ScorerInvokeResponse) -> dict[str, Any]:
        return full_metadata(
            response,
            scorer_id=self.config.scorer_id,
            scorer_version_id=self.config.scorer_version_id,
            scorer_label=self.config.scorer_label,
            threshold=self.config.threshold,
            operator=self.config.operator,
        )

    def _handle_error(self, error: Exception) -> EvaluatorResult:
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
            message=f"LLM scorer evaluation error: {error_detail}",
            metadata=metadata,
            error=error_detail,
        )

    async def aclose(self) -> None:
        """Close the underlying Galileo scorer client."""
        await self._client.close()
