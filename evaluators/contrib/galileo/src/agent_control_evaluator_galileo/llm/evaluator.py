"""Galileo LLM-as-judge direct scorer evaluator."""

from agent_control_evaluators import EvaluatorMetadata, register_evaluator

from agent_control_evaluator_galileo._shared.evaluator import (
    BaseGalileoScorerEvaluator,
    _resolve_package_version,
)
from agent_control_evaluator_galileo.llm.client import GalileoLLMClient
from agent_control_evaluator_galileo.llm.config import LlmEvaluatorConfig

LLM_AVAILABLE = True


@register_evaluator
class LlmEvaluator(BaseGalileoScorerEvaluator):
    """Galileo LLM-as-judge evaluator using the direct scorer invocation API."""

    metadata = EvaluatorMetadata(
        name="galileo.llm",
        version=_resolve_package_version(),
        description="Galileo LLM-as-judge direct scorer evaluation",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = LlmEvaluatorConfig
    _display_name = "LLM scorer"

    def _get_client(self) -> GalileoLLMClient:
        return self._client  # type: ignore[return-value]
