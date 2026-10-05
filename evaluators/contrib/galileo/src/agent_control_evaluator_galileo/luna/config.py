"""Configuration for Galileo Luna scorer evaluator."""

from agent_control_evaluator_galileo._shared.config import (
    BaseScorerEvaluatorConfig,
    ScorerInvokeConfig,
    coerce_number,
)

# Public aliases kept for backwards compatibility.
LunaOperator = BaseScorerEvaluatorConfig.model_fields["operator"].annotation
LunaPayloadField = BaseScorerEvaluatorConfig.model_fields["payload_field"].annotation


class LunaEvaluatorConfig(BaseScorerEvaluatorConfig):
    """Configuration for direct Luna scorer evaluation."""


__all__ = [
    "LunaEvaluatorConfig",
    "LunaOperator",
    "LunaPayloadField",
    "ScorerInvokeConfig",
    "coerce_number",
]
