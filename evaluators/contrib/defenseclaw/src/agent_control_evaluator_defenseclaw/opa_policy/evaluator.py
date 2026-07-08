"""DefenseClaw OPA-policy evaluator."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult

from ..common import no_op_result
from .config import DefenseClawOpaPolicyConfig


def _resolve_package_version() -> str:
    try:
        return version("agent-control-evaluator-defenseclaw")
    except PackageNotFoundError:
        return "0.0.0.dev"


@register_evaluator
class DefenseClawOpaPolicyEvaluator(Evaluator[DefenseClawOpaPolicyConfig]):
    """Evaluate selected data with a typed DefenseClaw OPA policy."""

    metadata = EvaluatorMetadata(
        name="defenseclaw.opa_policy",
        version=_resolve_package_version(),
        description="DefenseClaw OPA-policy evaluation",
    )
    config_model = DefenseClawOpaPolicyConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Return the intentional no-op result for all selected data."""
        return no_op_result()
