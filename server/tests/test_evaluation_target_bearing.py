"""End-to-end coverage for evaluation requests with target context.

The evaluation endpoint resolves the same merged effective set as
``initAgent`` and ``GET /agents/{name}/controls``: the de-duplicated
union of the agent's direct controls, policy-derived controls, and (when
``target_type`` and ``target_id`` are both supplied) controls bound to
that target via enabled bindings in the same namespace.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD, canonicalize_control_payload


def _agent_payload(agent_name: str) -> dict[str, Any]:
    return {
        "agent": {
            "agent_name": agent_name,
            "agent_description": "test agent",
            "agent_version": "1.0",
        },
        "steps": [],
    }


def _register_agent(client: TestClient, agent_name: str) -> None:
    resp = client.post("/api/v1/agents/initAgent", json=_agent_payload(agent_name))
    assert resp.status_code == 200, resp.text


def _create_control(client: TestClient) -> int:
    payload = canonicalize_control_payload(deepcopy(VALID_CONTROL_PAYLOAD))
    resp = client.put(
        "/api/v1/controls",
        json={"name": f"control-{uuid.uuid4().hex[:12]}", "data": payload},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


def _create_binding(
    client: TestClient,
    *,
    control_id: int,
    target_type: str = "env",
    target_id: str = "prod",
    enabled: bool = True,
) -> int:
    body: dict[str, Any] = {
        "target_type": target_type,
        "target_id": target_id,
        "control_id": control_id,
        "enabled": enabled,
    }
    resp = client.put("/api/v1/control-bindings", json=body)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["binding_id"])


def _evaluate(
    client: TestClient,
    *,
    agent_name: str,
    target_type: str | None = None,
    target_id: str | None = None,
    input_text: str = "x marks the spot",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "agent_name": agent_name,
        "step": {
            "type": "llm",
            "name": "test-step",
            "input": input_text,
            "context": {},
        },
        "stage": "pre",
    }
    if target_type is not None:
        body["target_type"] = target_type
    if target_id is not None:
        body["target_id"] = target_id
    resp = client.post("/api/v1/evaluation", json=body)
    return {"status": resp.status_code, "body": resp.json()}


def test_target_binding_runs_through_evaluation(client: TestClient) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id)

    result = _evaluate(client, agent_name=agent_name, target_type="env", target_id="prod")
    assert result["status"] == 200
    body = result["body"]
    # The control denies on regex 'x' which appears in the default input.
    assert body["is_safe"] is False
    assert body["matches"] and body["matches"][0]["control_id"] == control_id


def test_unmatched_target_returns_safe(client: TestClient) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    # No binding exists for this target.
    result = _evaluate(client, agent_name=agent_name, target_type="env", target_id="dev")
    assert result["status"] == 200
    assert result["body"]["is_safe"] is True


def test_disabled_binding_excludes_control_at_runtime(client: TestClient) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id, enabled=False)

    result = _evaluate(client, agent_name=agent_name, target_type="env", target_id="prod")
    assert result["status"] == 200
    assert result["body"]["is_safe"] is True


def test_partial_target_pair_rejected(client: TestClient) -> None:
    body = {
        "agent_name": "mytestagent01",
        "step": {"type": "llm", "name": "s", "input": "hi"},
        "stage": "pre",
        "target_type": "env",
    }
    resp = client.post("/api/v1/evaluation", json=body)
    assert resp.status_code == 422


def test_evaluation_without_registered_agent_returns_404(client: TestClient) -> None:
    result = _evaluate(
        client,
        agent_name="never-registered-agent",
        target_type="env",
        target_id="prod",
    )
    assert result["status"] == 404


def test_target_evaluation_includes_direct_attachments(client: TestClient) -> None:
    """Even on the target-bearing path, agent's direct controls still apply."""
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    direct_control_id = _create_control(client)
    target_control_id = _create_control(client)

    attach = client.post(
        f"/api/v1/agents/{agent_name}/controls/{direct_control_id}",
    )
    assert attach.status_code == 200, attach.text

    _create_binding(client, control_id=target_control_id)

    result = _evaluate(
        client, agent_name=agent_name, target_type="env", target_id="prod"
    )
    assert result["status"] == 200
    body = result["body"]
    matched_ids = {m["control_id"] for m in (body.get("matches") or [])}
    # Both direct and target controls fire on the same input.
    assert direct_control_id in matched_ids
    assert target_control_id in matched_ids
