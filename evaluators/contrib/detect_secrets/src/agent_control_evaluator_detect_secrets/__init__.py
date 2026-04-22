"""Agent Control evaluator package for detect-secrets."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-evaluator-detect-secrets")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from agent_control_evaluator_detect_secrets.detect_secrets import (
    DetectSecretsEvaluator,
    DetectSecretsEvaluatorConfig,
)

__all__ = [
    "DetectSecretsEvaluator",
    "DetectSecretsEvaluatorConfig",
]
