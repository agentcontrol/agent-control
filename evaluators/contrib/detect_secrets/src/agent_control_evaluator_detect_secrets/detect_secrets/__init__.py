"""detect-secrets evaluator exports."""

from agent_control_evaluator_detect_secrets.detect_secrets.config import (
    DetectSecretsEvaluatorConfig,
)
from agent_control_evaluator_detect_secrets.detect_secrets.evaluator import (
    DetectSecretsEvaluator,
)

__all__ = [
    "DetectSecretsEvaluator",
    "DetectSecretsEvaluatorConfig",
]
