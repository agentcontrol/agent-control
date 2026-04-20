"""Cross-tenant enforcement tests.

Every request-scoped lookup of a tenant-owned resource must refuse access
across tenant boundaries. These tests lock that in: for each lookup path,
tenant B sees tenant A's rows as non-existent.

``Agent.name``, ``Control.name``, and ``Policy.name`` are still globally
unique at the schema level, so "same name in two tenants" is not yet a thing
we can test. What we *can* test is that holding a valid ID obtained from
another tenant does not let you read, mutate, or link against it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD

API_PREFIX = "/api/v1"
TENANT_HEADER = "X-Tenant-Id"

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _init_agent(client: TestClient, *, tenant: str, name: str | None = None) -> str:
    agent_name = name or _unique("agent")
    resp = client.post(
        f"{API_PREFIX}/agents/initAgent",
        headers={TENANT_HEADER: tenant},
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert resp.status_code == 200, resp.text
    return agent_name


def _create_control(client: TestClient, *, tenant: str) -> int:
    name = _unique("ctrl")
    resp = client.put(
        f"{API_PREFIX}/controls",
        headers={TENANT_HEADER: tenant},
        json={"name": name, "data": VALID_CONTROL_PAYLOAD},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


def _create_policy(client: TestClient, *, tenant: str) -> int:
    name = _unique("pol")
    resp = client.put(
        f"{API_PREFIX}/policies",
        headers={TENANT_HEADER: tenant},
        json={"name": name},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["policy_id"])


def _create_target(client: TestClient, *, tenant: str) -> tuple[int, str]:
    external_id = _unique("ext")
    resp = client.post(
        f"{API_PREFIX}/targets",
        headers={TENANT_HEADER: tenant},
        json={"target_type": "environment", "external_id": external_id},
    )
    assert resp.status_code == 201, resp.text
    return int(resp.json()["target_id"]), external_id


# ---------------------------------------------------------------------------
# initAgent: cross-tenant name reservation surfaces as 409 non-disclosing
# ---------------------------------------------------------------------------


def test_init_agent_across_tenants_returns_409_non_disclosing(
    client: TestClient,
) -> None:
    """Agent.name is globally unique; tenant B can't bind an existing name."""
    shared_name = _unique("agent")
    _init_agent(client, tenant=TENANT_A, name=shared_name)

    resp = client.post(
        f"{API_PREFIX}/agents/initAgent",
        headers={TENANT_HEADER: TENANT_B},
        json={"agent": {"agent_name": shared_name}, "steps": []},
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "AGENT_NAME_CONFLICT"
    # Response must not disclose which tenant owns the existing name.
    body_text = resp.text.lower()
    assert TENANT_A.lower() not in body_text


# ---------------------------------------------------------------------------
# Agent reads / mutations
# ---------------------------------------------------------------------------


def test_get_agent_cross_tenant_returns_404(client: TestClient) -> None:
    agent_name = _init_agent(client, tenant=TENANT_A)
    resp = client.get(
        f"{API_PREFIX}/agents/{agent_name}",
        headers={TENANT_HEADER: TENANT_B},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"


def test_list_agents_does_not_leak_other_tenants(client: TestClient) -> None:
    _init_agent(client, tenant=TENANT_A)
    _init_agent(client, tenant=TENANT_A)

    resp = client.get(
        f"{API_PREFIX}/agents", headers={TENANT_HEADER: TENANT_B}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agents"] == []
    assert body["pagination"]["total"] == 0


def test_patch_agent_cross_tenant_returns_404(client: TestClient) -> None:
    agent_name = _init_agent(client, tenant=TENANT_A)
    resp = client.patch(
        f"{API_PREFIX}/agents/{agent_name}",
        headers={TENANT_HEADER: TENANT_B},
        json={"remove_steps": [], "remove_evaluators": []},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Agent - Policy association
# ---------------------------------------------------------------------------


def test_add_agent_policy_cross_tenant_agent_returns_404(client: TestClient) -> None:
    """Caller in tenant B cannot attach to tenant A's agent."""
    agent_name = _init_agent(client, tenant=TENANT_A)
    policy_id = _create_policy(client, tenant=TENANT_B)

    resp = client.post(
        f"{API_PREFIX}/agents/{agent_name}/policies/{policy_id}",
        headers={TENANT_HEADER: TENANT_B},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"


def test_add_agent_policy_cross_tenant_policy_returns_404(client: TestClient) -> None:
    """Caller in tenant A cannot attach tenant B's policy to tenant A's agent."""
    agent_name = _init_agent(client, tenant=TENANT_A)
    policy_id = _create_policy(client, tenant=TENANT_B)

    resp = client.post(
        f"{API_PREFIX}/agents/{agent_name}/policies/{policy_id}",
        headers={TENANT_HEADER: TENANT_A},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "POLICY_NOT_FOUND"


# ---------------------------------------------------------------------------
# Agent - Control direct attach
# ---------------------------------------------------------------------------


def test_add_agent_control_cross_tenant_control_returns_404(
    client: TestClient,
) -> None:
    agent_name = _init_agent(client, tenant=TENANT_A)
    control_id = _create_control(client, tenant=TENANT_B)

    resp = client.post(
        f"{API_PREFIX}/agents/{agent_name}/controls/{control_id}",
        headers={TENANT_HEADER: TENANT_A},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Controls: cross-tenant reads/mutations/deletes
# ---------------------------------------------------------------------------


def test_get_control_cross_tenant_returns_404(client: TestClient) -> None:
    control_id = _create_control(client, tenant=TENANT_A)
    resp = client.get(
        f"{API_PREFIX}/controls/{control_id}",
        headers={TENANT_HEADER: TENANT_B},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_list_controls_does_not_leak_other_tenants(client: TestClient) -> None:
    """Tenant B must not see tenant A's controls in the list or in the count."""
    _create_control(client, tenant=TENANT_A)
    _create_control(client, tenant=TENANT_A)

    resp = client.get(
        f"{API_PREFIX}/controls", headers={TENANT_HEADER: TENANT_B}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["controls"] == []
    assert body["pagination"]["total"] == 0


def test_list_controls_same_tenant_returns_own_rows(client: TestClient) -> None:
    _create_control(client, tenant=TENANT_A)
    _create_control(client, tenant=TENANT_A)
    _create_control(client, tenant=TENANT_B)

    resp = client.get(
        f"{API_PREFIX}/controls", headers={TENANT_HEADER: TENANT_A}
    )
    assert resp.status_code == 200
    assert resp.json()["pagination"]["total"] == 2


def test_set_control_data_cross_tenant_returns_404(client: TestClient) -> None:
    control_id = _create_control(client, tenant=TENANT_A)
    resp = client.put(
        f"{API_PREFIX}/controls/{control_id}/data",
        headers={TENANT_HEADER: TENANT_B},
        json={"data": VALID_CONTROL_PAYLOAD},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_patch_control_cross_tenant_returns_404(client: TestClient) -> None:
    control_id = _create_control(client, tenant=TENANT_A)
    resp = client.patch(
        f"{API_PREFIX}/controls/{control_id}",
        headers={TENANT_HEADER: TENANT_B},
        json={"enabled": False},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_delete_control_cross_tenant_returns_404(client: TestClient) -> None:
    control_id = _create_control(client, tenant=TENANT_A)
    resp = client.delete(
        f"{API_PREFIX}/controls/{control_id}",
        headers={TENANT_HEADER: TENANT_B},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Policy - Control association
# ---------------------------------------------------------------------------


def test_add_control_to_policy_cross_tenant_policy_returns_404(
    client: TestClient,
) -> None:
    policy_id = _create_policy(client, tenant=TENANT_A)
    control_id = _create_control(client, tenant=TENANT_B)
    resp = client.post(
        f"{API_PREFIX}/policies/{policy_id}/controls/{control_id}",
        headers={TENANT_HEADER: TENANT_B},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "POLICY_NOT_FOUND"


def test_add_control_to_policy_cross_tenant_control_returns_404(
    client: TestClient,
) -> None:
    policy_id = _create_policy(client, tenant=TENANT_A)
    control_id = _create_control(client, tenant=TENANT_B)
    resp = client.post(
        f"{API_PREFIX}/policies/{policy_id}/controls/{control_id}",
        headers={TENANT_HEADER: TENANT_A},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Target - Control attachment
# ---------------------------------------------------------------------------


def test_attach_target_control_cross_tenant_control_returns_404(
    client: TestClient,
) -> None:
    target_id, _ = _create_target(client, tenant=TENANT_A)
    control_id = _create_control(client, tenant=TENANT_B)
    resp = client.post(
        f"{API_PREFIX}/targets/{target_id}/controls/{control_id}",
        headers={TENANT_HEADER: TENANT_A},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Control definition validation (agent-scoped evaluator references)
# ---------------------------------------------------------------------------


def test_control_referencing_foreign_tenant_agent_evaluator_returns_404(
    client: TestClient,
) -> None:
    """A control in tenant B cannot reference an agent-scoped evaluator from tenant A.

    The foreign agent must look like non-existent so the response does not
    leak either the agent's presence or its evaluator inventory.
    """
    tenant_a_agent = _unique("agent")
    init_resp = client.post(
        f"{API_PREFIX}/agents/initAgent",
        headers={TENANT_HEADER: TENANT_A},
        json={
            "agent": {"agent_name": tenant_a_agent},
            "steps": [],
            "evaluators": [
                {
                    "name": "secret-luna",
                    "config_schema": {"type": "object"},
                    "description": "Tenant A's private evaluator",
                }
            ],
        },
    )
    assert init_resp.status_code == 200, init_resp.text

    control_def = {
        "description": "cross-tenant evaluator probe",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "condition": {
            "selector": {"path": "input"},
            "evaluator": {
                "name": f"{tenant_a_agent}:secret-luna",
                "config": {},
            },
        },
        "action": {"decision": "deny"},
    }
    resp = client.put(
        f"{API_PREFIX}/controls",
        headers={TENANT_HEADER: TENANT_B},
        json={"name": _unique("ctrl"), "data": control_def},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"
    # The response must not expose tenant A's evaluator inventory.
    body_text = resp.text.lower()
    assert "secret-luna" not in body_text


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_evaluate_cross_tenant_agent_returns_404(client: TestClient) -> None:
    agent_name = _init_agent(client, tenant=TENANT_A)
    body = {
        "agent_name": agent_name,
        "step": {"type": "llm", "name": "test-step", "input": "hi", "output": None},
        "stage": "pre",
    }
    resp = client.post(
        f"{API_PREFIX}/evaluation",
        headers={TENANT_HEADER: TENANT_B},
        json=body,
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Positive control: same-tenant operations still succeed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tenant", [TENANT_A, TENANT_B])
def test_same_tenant_operations_still_succeed(client: TestClient, tenant: str) -> None:
    """Sanity: enforcement does not break legitimate same-tenant flows."""
    agent_name = _init_agent(client, tenant=tenant)
    policy_id = _create_policy(client, tenant=tenant)
    control_id = _create_control(client, tenant=tenant)

    resp = client.post(
        f"{API_PREFIX}/agents/{agent_name}/policies/{policy_id}",
        headers={TENANT_HEADER: tenant},
    )
    assert resp.status_code == 200

    resp = client.post(
        f"{API_PREFIX}/agents/{agent_name}/controls/{control_id}",
        headers={TENANT_HEADER: tenant},
    )
    assert resp.status_code == 200

    resp = client.post(
        f"{API_PREFIX}/policies/{policy_id}/controls/{control_id}",
        headers={TENANT_HEADER: tenant},
    )
    assert resp.status_code == 200
