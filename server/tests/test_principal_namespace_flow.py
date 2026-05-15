"""HTTP-level coverage for principal-derived namespace scoping."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from agent_control_server.auth_framework import (
    Operation,
    Principal,
    set_authorizer,
)
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD


class HeaderNamespaceAuthorizer:
    """Test authorizer that maps a request header to ``Principal.namespace_key``."""

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        del context
        scopes = (
            (Operation.RUNTIME_USE.value,)
            if operation is Operation.RUNTIME_TOKEN_EXCHANGE
            else ()
        )
        return Principal(
            namespace_key=request.headers.get("X-Test-Namespace", "default"),
            is_admin=True,
            scopes=scopes,
        )


def _client(app: FastAPI, namespace_key: str) -> TestClient:
    return TestClient(
        app,
        raise_server_exceptions=True,
        headers={"X-Test-Namespace": namespace_key},
    )


def _agent_payload(agent_name: str) -> dict[str, Any]:
    return {
        "agent": {
            "agent_name": agent_name,
            "agent_description": "test agent",
            "agent_version": "1.0",
        },
        "steps": [],
    }


def _evaluation_payload(agent_name: str) -> dict[str, Any]:
    return {
        "agent_name": agent_name,
        "step": {
            "type": "llm",
            "name": "test-step",
            "input": "x marks the spot",
            "context": {},
        },
        "stage": "pre",
        "target_type": "env",
        "target_id": "prod",
    }


def test_principal_namespace_scopes_management_and_runtime(app: FastAPI) -> None:
    set_authorizer(HeaderNamespaceAuthorizer())

    ns_a = _client(app, "ns-a")
    ns_b = _client(app, "ns-b")
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"

    register_a = ns_a.post("/api/v1/agents/initAgent", json=_agent_payload(agent_name))
    register_b = ns_b.post("/api/v1/agents/initAgent", json=_agent_payload(agent_name))
    assert register_a.status_code == 200, register_a.text
    assert register_b.status_code == 200, register_b.text

    create_control = ns_a.put(
        "/api/v1/controls",
        json={
            "name": f"control-{uuid.uuid4().hex[:12]}",
            "data": VALID_CONTROL_PAYLOAD,
        },
    )
    assert create_control.status_code == 200, create_control.text
    control_id = int(create_control.json()["control_id"])

    policy = ns_a.put(
        "/api/v1/policies",
        json={"name": f"policy-{uuid.uuid4().hex[:12]}"},
    )
    assert policy.status_code == 200, policy.text
    policy_id = int(policy.json()["policy_id"])
    attach_to_policy = ns_a.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert attach_to_policy.status_code == 200, attach_to_policy.text

    binding = ns_a.put(
        "/api/v1/control-bindings",
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
            "enabled": True,
        },
    )
    assert binding.status_code == 200, binding.text

    assert ns_b.get(f"/api/v1/controls/{control_id}").status_code == 404
    assert ns_b.get(f"/api/v1/policies/{policy_id}/controls").status_code == 404
    assert ns_b.get("/api/v1/control-bindings").json()["bindings"] == []

    eval_a = ns_a.post("/api/v1/evaluation", json=_evaluation_payload(agent_name))
    assert eval_a.status_code == 200, eval_a.text
    assert eval_a.json()["is_safe"] is False
    assert eval_a.json()["matches"][0]["control_id"] == control_id

    eval_b = ns_b.post("/api/v1/evaluation", json=_evaluation_payload(agent_name))
    assert eval_b.status_code == 200, eval_b.text
    assert eval_b.json()["is_safe"] is True


def test_principal_namespace_scopes_cross_namespace_writes(app: FastAPI) -> None:
    set_authorizer(HeaderNamespaceAuthorizer())

    ns_a = _client(app, "ns-a")
    ns_b = _client(app, "ns-b")
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"

    assert ns_a.post("/api/v1/agents/initAgent", json=_agent_payload(agent_name)).status_code == 200
    assert ns_b.post("/api/v1/agents/initAgent", json=_agent_payload(agent_name)).status_code == 200

    create_control = ns_a.put(
        "/api/v1/controls",
        json={
            "name": f"control-{uuid.uuid4().hex[:12]}",
            "data": VALID_CONTROL_PAYLOAD,
        },
    )
    assert create_control.status_code == 200, create_control.text
    control_id = int(create_control.json()["control_id"])

    policy = ns_a.put(
        "/api/v1/policies",
        json={"name": f"policy-{uuid.uuid4().hex[:12]}"},
    )
    assert policy.status_code == 200, policy.text
    policy_id = int(policy.json()["policy_id"])

    binding = ns_a.put(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
            "enabled": True,
        },
    )
    assert binding.status_code == 200, binding.text

    assert ns_b.patch(f"/api/v1/controls/{control_id}", json={"enabled": False}).status_code == 404
    assert (
        ns_b.put(
            f"/api/v1/controls/{control_id}/data",
            json={"data": VALID_CONTROL_PAYLOAD},
        ).status_code
        == 404
    )
    assert (
        ns_b.put(
            "/api/v1/control-bindings/by-key",
            json={
                "target_type": "env",
                "target_id": "prod",
                "control_id": control_id,
                "enabled": False,
            },
        ).status_code
        == 404
    )
    delete_binding = ns_b.post(
        "/api/v1/control-bindings/by-key:delete",
        json={
            "target_type": "env",
            "target_id": "prod",
            "control_id": control_id,
        },
    )
    assert delete_binding.status_code == 200, delete_binding.text
    assert delete_binding.json()["deleted"] is False
    assert ns_a.get("/api/v1/control-bindings").json()["bindings"]

    assert ns_b.post(f"/api/v1/agents/{agent_name}/policies/{policy_id}").status_code == 404
    assert ns_b.post(f"/api/v1/agents/{agent_name}/controls/{control_id}").status_code == 404


def test_duplicate_control_names_allowed_across_principal_namespaces(app: FastAPI) -> None:
    set_authorizer(HeaderNamespaceAuthorizer())

    ns_a = _client(app, "ns-a")
    ns_b = _client(app, "ns-b")
    control_name = f"control-{uuid.uuid4().hex[:12]}"
    payload = {"name": control_name, "data": VALID_CONTROL_PAYLOAD}

    assert ns_a.put("/api/v1/controls", json=payload).status_code == 200
    assert ns_b.put("/api/v1/controls", json=payload).status_code == 200


def test_agent_scoped_evaluator_validation_uses_principal_namespace(app: FastAPI) -> None:
    set_authorizer(HeaderNamespaceAuthorizer())

    ns_a = _client(app, "ns-a")
    ns_b = _client(app, "ns-b")
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"

    register_b = ns_b.post(
        "/api/v1/agents/initAgent",
        json={
            **_agent_payload(agent_name),
            "evaluators": [{"name": "custom", "config_schema": {"type": "object"}}],
        },
    )
    assert register_b.status_code == 200, register_b.text

    control_data = deepcopy(VALID_CONTROL_PAYLOAD)
    control_data["condition"]["evaluator"] = {
        "name": f"{agent_name}:custom",
        "config": {},
    }

    resp = ns_a.post("/api/v1/controls/validate", json={"data": control_data})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == f"Agent '{agent_name}' not found"
