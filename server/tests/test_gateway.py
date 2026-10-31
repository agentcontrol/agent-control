"""Gateway routing tests through existing bound controls and evaluators."""

from __future__ import annotations

from typing import Any

import pytest
from agent_control_evaluator_budget.budget.evaluator import clear_budget_stores
from agent_control_models import ControlMatch, EvaluationResponse, EvaluatorResult
from agent_control_server.auth_framework import Operation, Principal, set_authorizer
from agent_control_server.endpoints.gateway import _find_gateway_route
from fastapi.testclient import TestClient


def _routing_config(agent_name: str) -> dict[str, Any]:
    if agent_name == "claude-code":
        provider = protocol = "anthropic"
        economy_model, premium_model = "claude-haiku-4-5", "claude-sonnet-4-5"
    else:
        provider = protocol = "openai"
        economy_model, premium_model = "gpt-4.1-mini", "gpt-4.1"
    return {
        "limits": [{"limit": 100, "limit_unit": "tokens"}],
        "budget_id": f"gateway-demo:{agent_name}",
        "gateway_routing": {
            "tiers": {
                "economy": {
                    "models": [
                        {"provider": provider, "model": economy_model, "protocol": protocol}
                    ]
                },
                "premium": {
                    "models": [
                        {"provider": provider, "model": premium_model, "protocol": protocol}
                    ]
                },
            },
            "task_tiers": {
                "default": "economy",
                "classification": "economy",
                "analysis": "premium",
                "code-review": "premium",
            },
            "threshold": 0.8,
            "threshold_tier": "economy",
        },
    }


def _create_control(client: TestClient, name: str, data: dict[str, Any]) -> int:
    response = client.put("/api/v1/controls", json={"name": name, "data": data})
    assert response.status_code == 200, response.text
    return int(response.json()["control_id"])


def _bind_control(client: TestClient, agent_name: str, control_id: int) -> None:
    response = client.put(
        "/api/v1/control-bindings",
        json={"target_type": "agent", "target_id": agent_name, "control_id": control_id},
    )
    assert response.status_code == 200, response.text


def _create_route_control(client: TestClient, agent_name: str) -> int:
    data = {
        "description": "Task-sensitive gateway model routing and token budget",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "condition": {
            "selector": {"path": "input"},
            "evaluator": {"name": "budget", "config": _routing_config(agent_name)},
        },
        "action": {"decision": "route"},
        "tags": ["gateway"],
    }
    return _create_control(client, f"{agent_name}-gateway-routing", data)


class _AgentRuntimeAuthorizer:
    """Test authorizer that returns a target-bound runtime identity."""

    def __init__(self, authenticated_agent: str) -> None:
        self.authenticated_agent = authenticated_agent

    async def authorize(self, request, operation, context=None):
        assert operation is Operation.RUNTIME_USE
        assert context == {
            "target_type": "agent",
            "target_id": request.path_params["agent_name"],
        }
        return Principal(
            namespace_key="default",
            target_type="agent",
            target_id=self.authenticated_agent,
            scopes=(Operation.RUNTIME_USE.value,),
        )


def _register_agent(client: TestClient, agent_name: str) -> None:
    response = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert response.status_code == 200, response.text
    _bind_control(client, agent_name, _create_route_control(client, agent_name))


def _candidates(agent_name: str) -> list[dict[str, str]]:
    if agent_name == "claude-code":
        return [
            {"provider": "anthropic", "model": "claude-haiku-4-5", "protocol": "anthropic"},
            {"provider": "anthropic", "model": "claude-sonnet-4-5", "protocol": "anthropic"},
            {"provider": "openai", "model": "gpt-4.1", "protocol": "openai"},
        ]
    return [
        {"provider": "openai", "model": "gpt-4.1-mini", "protocol": "openai"},
        {"provider": "openai", "model": "gpt-4.1", "protocol": "openai"},
        {"provider": "anthropic", "model": "claude-sonnet-4-5", "protocol": "anthropic"},
    ]


def _route(client: TestClient, agent_name: str, task_type: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/gateway/agents/{agent_name}/route-decision",
        json={"task_type": task_type, "candidate_models": _candidates(agent_name)},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(autouse=True)
def reset_gateway_budgets() -> None:
    clear_budget_stores()
    yield
    clear_budget_stores()


def test_bound_budget_control_selects_task_tier_and_threshold_route(client: TestClient) -> None:
    agent_name = "customer-success-agent"
    _register_agent(client, agent_name)
    set_authorizer(_AgentRuntimeAuthorizer(agent_name), operation=Operation.RUNTIME_USE)

    premium = _route(client, agent_name, "analysis")
    settlement = client.post(
        f"/api/v1/gateway/agents/{agent_name}/usage-settlement",
        json={"model": "gpt-4.1", "input_tokens": 50, "output_tokens": 30},
    )
    threshold = _route(client, agent_name, "analysis")

    assert premium["decision"] == "route"
    assert premium["action"] == "route"
    assert premium["model"] == "gpt-4.1"
    assert premium["policy"] == f"{agent_name}-gateway-routing"
    assert settlement.status_code == 200, settlement.text
    assert settlement.json()["budget"]["used_tokens"] == 80
    assert threshold["model"] == "gpt-4.1-mini"
    assert threshold["budget"]["threshold_reached"] is True


def test_budget_exhaustion_returns_deny_without_a_usable_route(client: TestClient) -> None:
    agent_name = "customer-success-agent"
    _register_agent(client, agent_name)
    set_authorizer(_AgentRuntimeAuthorizer(agent_name), operation=Operation.RUNTIME_USE)
    client.post(
        f"/api/v1/gateway/agents/{agent_name}/usage-settlement",
        json={"model": "gpt-4.1", "input_tokens": 60, "output_tokens": 40},
    )

    result = _route(client, agent_name, "classification")

    assert result["decision"] == "deny"
    assert result["allowed"] is False
    assert result["provider"] is None
    assert result["model"] is None
    assert result["protocol"] is None
    assert result["budget"]["over_limit"] is True


def test_controls_keep_separate_agent_budgets_and_claude_stays_anthropic(
    client: TestClient,
) -> None:
    for name in ("customer-success-agent", "claude-code"):
        _register_agent(client, name)

    set_authorizer(
        _AgentRuntimeAuthorizer("customer-success-agent"), operation=Operation.RUNTIME_USE
    )
    customer = _route(client, "customer-success-agent", "analysis")
    customer_settlement = client.post(
        "/api/v1/gateway/agents/customer-success-agent/usage-settlement",
        json={"model": "gpt-4.1", "input_tokens": 31, "output_tokens": 9},
    )
    set_authorizer(_AgentRuntimeAuthorizer("claude-code"), operation=Operation.RUNTIME_USE)
    claude = _route(client, "claude-code", "code-review")
    claude_after_customer_usage = _route(client, "claude-code", "code-review")
    claude_openai_only = client.post(
        "/api/v1/gateway/agents/claude-code/route-decision",
        json={
            "task_type": "code-review",
            "candidate_models": [
                {"provider": "openai", "model": "gpt-4.1", "protocol": "openai"}
            ],
        },
    )

    assert customer["model"] == "gpt-4.1"
    assert claude["provider"] == "anthropic"
    assert claude["protocol"] == "anthropic"
    assert claude["model"] == "claude-sonnet-4-5"
    assert claude["budget"]["used_tokens"] == 0
    assert customer_settlement.status_code == 200
    assert customer_settlement.json()["budget"]["used_tokens"] == 40
    assert claude_after_customer_usage["budget"]["used_tokens"] == 0
    assert claude_openai_only.status_code == 200
    assert claude_openai_only.json()["decision"] == "deny"
    assert claude_openai_only.json()["model"] is None


def test_bound_deny_control_blocks_gateway_route(client: TestClient) -> None:
    agent_name = "customer-success-agent"
    _register_agent(client, agent_name)
    deny_data = {
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "condition": {
            "selector": {"path": "input.task_type"},
            "evaluator": {"name": "regex", "config": {"pattern": "blocked"}},
        },
        "action": {"decision": "deny"},
    }
    _bind_control(client, agent_name, _create_control(client, "gateway-block", deny_data))
    set_authorizer(_AgentRuntimeAuthorizer(agent_name), operation=Operation.RUNTIME_USE)

    result = _route(client, agent_name, "blocked")

    assert result["decision"] == "deny"
    assert result["action"] == "deny"
    assert result["provider"] is None
    assert result["model"] is None
    assert "denied" in result["reason"].lower()


def test_gateway_rejects_identity_mismatch(client: TestClient) -> None:
    set_authorizer(_AgentRuntimeAuthorizer("claude-code"), operation=Operation.RUNTIME_USE)
    response = client.post(
        "/api/v1/gateway/agents/customer-success-agent/route-decision",
        json={
            "task_type": "classification",
            "candidate_models": _candidates("customer-success-agent"),
        },
    )
    assert response.status_code == 403


def test_non_matching_routing_evaluator_cannot_authorize_a_route() -> None:
    non_match = ControlMatch(
        control_id=1,
        control_name="stale-route-result",
        action="route",
        result=EvaluatorResult(
            matched=False,
            confidence=1.0,
            metadata={
                "gateway_route": {
                    "allowed": True,
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "protocol": "openai",
                }
            },
        ),
    )
    evaluation = EvaluationResponse(is_safe=True, confidence=1.0, non_matches=[non_match])

    assert _find_gateway_route(evaluation) is None
