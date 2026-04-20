"""End-to-end tests for target-bearing evaluation resolution."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD

API_PREFIX = "/api/v1"
TENANT_HEADER = "X-Tenant-Id"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _register_agent(client: TestClient, agent_name: str | None = None) -> str:
    name = agent_name or f"agent-{uuid.uuid4().hex[:12]}"
    resp = client.post(
        f"{API_PREFIX}/agents/initAgent",
        json={"agent": {"agent_name": name}, "steps": []},
    )
    assert resp.status_code == 200, resp.text
    return name


def _deny_on_secret_payload() -> dict:
    payload = dict(VALID_CONTROL_PAYLOAD)
    payload["description"] = "Deny when input contains 'secret'"
    payload["condition"] = {
        "selector": {"path": "input"},
        "evaluator": {"name": "regex", "config": {"pattern": "secret"}},
    }
    payload["action"] = {"decision": "deny"}
    return payload


def _create_control(client: TestClient, *, payload: dict | None = None) -> tuple[int, str]:
    data = payload if payload is not None else _deny_on_secret_payload()
    name = _unique("ctrl")
    resp = client.put(f"{API_PREFIX}/controls", json={"name": name, "data": data})
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"]), name


def _create_target(
    client: TestClient, *, tenant: str | None = None
) -> tuple[int, str]:
    external_id = _unique("ext")
    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.post(
        f"{API_PREFIX}/targets",
        headers=headers,
        json={"target_type": "environment", "external_id": external_id},
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["target_id"]), external_id


def _attach_control(
    client: TestClient,
    target_id: int,
    control_id: int,
    *,
    enabled: bool = True,
    tenant: str | None = None,
) -> None:
    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.post(
        f"{API_PREFIX}/targets/{target_id}/controls/{control_id}",
        headers=headers,
        json={"enabled": enabled},
    )
    assert resp.status_code == 200, resp.text


def _evaluate(
    client: TestClient,
    *,
    agent_name: str,
    input_text: str,
    target_type: str | None = None,
    target_external_id: str | None = None,
    tenant: str | None = None,
) -> dict:
    body: dict[str, object] = {
        "agent_name": agent_name,
        "step": {"type": "llm", "name": "test-step", "input": input_text, "output": None},
        "stage": "pre",
    }
    if target_type is not None:
        body["target_type"] = target_type
    if target_external_id is not None:
        body["target_id"] = target_external_id

    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.post(f"{API_PREFIX}/evaluation", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Core merge semantics
# ---------------------------------------------------------------------------


def test_target_control_enabled_contributes_to_effective_set(
    client: TestClient,
) -> None:
    agent_name = _register_agent(client)
    control_id, control_name = _create_control(client)
    target_id, external_id = _create_target(client)
    _attach_control(client, target_id, control_id, enabled=True)

    result = _evaluate(
        client,
        agent_name=agent_name,
        input_text="contains a secret",
        target_type="environment",
        target_external_id=external_id,
    )

    assert result["is_safe"] is False
    assert any(m["control_name"] == control_name for m in result["matches"])


def test_target_control_disabled_is_hidden_from_effective_set(
    client: TestClient,
) -> None:
    agent_name = _register_agent(client)
    control_id, _ = _create_control(client)
    target_id, external_id = _create_target(client)
    _attach_control(client, target_id, control_id, enabled=False)

    result = _evaluate(
        client,
        agent_name=agent_name,
        input_text="contains a secret",
        target_type="environment",
        target_external_id=external_id,
    )

    assert result["is_safe"] is True
    assert not result.get("matches")


def test_no_target_request_ignores_target_controls(client: TestClient) -> None:
    """Regression: OSS no-target evaluation is unchanged by any target_controls."""
    agent_name = _register_agent(client)
    control_id, _ = _create_control(client)
    target_id, _ = _create_target(client)
    _attach_control(client, target_id, control_id, enabled=True)

    result = _evaluate(
        client, agent_name=agent_name, input_text="contains a secret"
    )

    assert result["is_safe"] is True
    assert not result.get("matches")


def test_agent_control_masks_target_disable(client: TestClient) -> None:
    """If a control is attached directly to an agent, target-level disable has no effect."""
    agent_name = _register_agent(client)
    control_id, control_name = _create_control(client)
    # Attach control directly to agent via the existing endpoint.
    direct_resp = client.post(
        f"{API_PREFIX}/agents/{agent_name}/controls/{control_id}"
    )
    assert direct_resp.status_code == 200, direct_resp.text

    target_id, external_id = _create_target(client)
    _attach_control(client, target_id, control_id, enabled=False)

    result = _evaluate(
        client,
        agent_name=agent_name,
        input_text="contains a secret",
        target_type="environment",
        target_external_id=external_id,
    )

    assert result["is_safe"] is False
    assert any(m["control_name"] == control_name for m in result["matches"])


def test_agent_control_and_target_enabled_both_contribute_once(
    client: TestClient,
) -> None:
    """Deduplication: same control via agent_controls and target_controls counts once."""
    agent_name = _register_agent(client)
    control_id, control_name = _create_control(client)
    client.post(f"{API_PREFIX}/agents/{agent_name}/controls/{control_id}")
    target_id, external_id = _create_target(client)
    _attach_control(client, target_id, control_id, enabled=True)

    result = _evaluate(
        client,
        agent_name=agent_name,
        input_text="contains a secret",
        target_type="environment",
        target_external_id=external_id,
    )

    matches = [m for m in result["matches"] if m["control_name"] == control_name]
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# Target resolution edge cases
# ---------------------------------------------------------------------------


def test_target_bearing_request_with_unknown_target_returns_404(
    client: TestClient,
) -> None:
    agent_name = _register_agent(client)
    body = {
        "agent_name": agent_name,
        "step": {"type": "llm", "name": "test-step", "input": "hi", "output": None},
        "stage": "pre",
        "target_type": "environment",
        "target_id": "unknown-external-id",
    }
    resp = client.post(f"{API_PREFIX}/evaluation", json=body)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "TARGET_NOT_FOUND"


def test_target_resolution_is_tenant_scoped(client: TestClient) -> None:
    """Cross-tenant evaluation surfaces the agent boundary first.

    Agent lookup is now tenant-scoped, so a caller in tenant-b that references
    an agent owned by tenant-a gets AGENT_NOT_FOUND before target resolution
    runs. That is the enforcement we want: no cross-tenant access leaks the
    presence of either the agent or the target.
    """
    register_resp = client.post(
        f"{API_PREFIX}/agents/initAgent",
        headers={TENANT_HEADER: "tenant-a"},
        json={
            "agent": {"agent_name": f"agent-{uuid.uuid4().hex[:12]}"},
            "steps": [],
        },
    )
    assert register_resp.status_code == 200, register_resp.text
    agent_name = register_resp.request.headers.get("X-Tenant-Id"), register_resp.json()
    # Re-derive agent_name from request body (initAgent echoes created=true)
    agent_body = {"agent": {"agent_name": f"agent-{uuid.uuid4().hex[:12]}"}, "steps": []}
    tenant_a_register = client.post(
        f"{API_PREFIX}/agents/initAgent",
        headers={TENANT_HEADER: "tenant-a"},
        json=agent_body,
    )
    assert tenant_a_register.status_code == 200
    tenant_a_agent = agent_body["agent"]["agent_name"]

    _, external_id = _create_target(client, tenant="tenant-a")

    body = {
        "agent_name": tenant_a_agent,
        "step": {"type": "llm", "name": "test-step", "input": "hi", "output": None},
        "stage": "pre",
        "target_type": "environment",
        "target_id": external_id,
    }
    resp = client.post(
        f"{API_PREFIX}/evaluation", headers={TENANT_HEADER: "tenant-b"}, json=body
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"


def test_only_target_type_without_target_id_fails_validation(
    client: TestClient,
) -> None:
    agent_name = _register_agent(client)
    body = {
        "agent_name": agent_name,
        "step": {"type": "llm", "name": "test-step", "input": "hi", "output": None},
        "stage": "pre",
        "target_type": "environment",
    }
    resp = client.post(f"{API_PREFIX}/evaluation", json=body)
    assert resp.status_code == 422


def test_only_target_id_without_target_type_fails_validation(
    client: TestClient,
) -> None:
    agent_name = _register_agent(client)
    body = {
        "agent_name": agent_name,
        "step": {"type": "llm", "name": "test-step", "input": "hi", "output": None},
        "stage": "pre",
        "target_id": "some-external-id",
    }
    resp = client.post(f"{API_PREFIX}/evaluation", json=body)
    assert resp.status_code == 422
