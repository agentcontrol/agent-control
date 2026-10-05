"""Configuration for Galileo LLM-as-judge scorer evaluator."""

from agent_control_evaluator_galileo._shared.config import (
    BaseScorerEvaluatorConfig,
    ScorerInvokeConfig,
    coerce_number,
)

# Public aliases kept for consistency with luna naming convention.
LlmOperator = BaseScorerEvaluatorConfig.model_fields["operator"].annotation
LlmPayloadField = BaseScorerEvaluatorConfig.model_fields["payload_field"].annotation


class LlmEvaluatorConfig(BaseScorerEvaluatorConfig):
    """Configuration for direct LLM-as-judge scorer evaluation."""


__all__ = [
    "LlmEvaluatorConfig",
    "LlmOperator",
    "LlmPayloadField",
    "ScorerInvokeConfig",
    "coerce_number",
]
