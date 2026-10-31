"""Tests for the typed inference-gateway contracts."""

from __future__ import annotations

import pytest
from agent_control_models import GatewayModelCandidate, GatewayModelTier, GatewayPreflightRequest
from pydantic import ValidationError


def test_gateway_preflight_request_normalizes_legacy_agent_and_accepts_candidate() -> None:
    request = GatewayPreflightRequest.model_validate(
        {
            "agent_name": " Customer-Success-Agent ",
            "task_type": "analysis",
            "candidate_models": [
                {"provider": "openai", "model": "gpt-small", "protocol": "openai"}
            ],
        }
    )

    assert request.agent_name == "customer-success-agent"
    assert request.candidate_models[0].model == "gpt-small"


def test_gateway_preflight_request_requires_a_candidate_or_legacy_model() -> None:
    with pytest.raises(ValidationError, match="Provide candidate_models or the legacy model"):
        GatewayPreflightRequest()


def test_gateway_model_candidate_rejects_unknown_protocol_and_empty_tier() -> None:
    with pytest.raises(ValidationError):
        GatewayModelCandidate(provider="openai", model="gpt-small", protocol="custom")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        GatewayModelTier(models=[])
