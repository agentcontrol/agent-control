"""Galileo Luna direct scorer evaluator."""

# ruff: noqa: F401
from importlib.metadata import PackageNotFoundError, version

from agent_control_evaluators import EvaluatorMetadata, register_evaluator

from agent_control_evaluator_galileo._shared.evaluator import (
    BaseGalileoScorerEvaluator,
    _coerce_payload_text,
    _confidence_from_score,
    _contains,
    _extract_dict_text,
    _has_text,
    _http_status_error_metadata,
    _truncated_http_response_body,
)
from agent_control_evaluator_galileo.luna.client import GalileoLunaClient
from agent_control_evaluator_galileo.luna.config import LunaEvaluatorConfig

LUNA_AVAILABLE = True


def _resolve_package_version() -> str:
    """Return the installed package version, or a dev fallback during local imports."""
    try:
        return version("agent-control-evaluator-galileo")
    except PackageNotFoundError:
        return "0.0.0.dev"


@register_evaluator
class LunaEvaluator(BaseGalileoScorerEvaluator):
    """Galileo Luna evaluator using the direct scorer invocation API."""

    metadata = EvaluatorMetadata(
        name="galileo.luna",
        version=_resolve_package_version(),
        description="Galileo Luna direct scorer evaluation",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = LunaEvaluatorConfig
    _display_name = "Luna"

    def _get_client(self) -> GalileoLunaClient:
        return self._client  # type: ignore[return-value]
