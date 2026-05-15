"""End-to-end coverage for the merged effective-controls contract.

``initAgent``, ``GET /agents/{name}/controls`` and ``POST /evaluation``
all return the same de-duplicated union of:

- the agent's direct controls,
- policy-derived controls,
- and (when target context is supplied) controls bound to that target via
  enabled bindings in the same namespace.

These tests pin that all three surfaces agree on the same set for the
same inputs.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

import pytest
from agent_control_server.auth_framework import Operation, Principal, set_authorizer
from fastapi import Request
from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD, canonicalize_control_payload


class RecordingAuthorizer:
    """Authorizer that records operation/context pairs for endpoint contract tests."""

    def __init__(self, *, target_namespace_key: str = "default") -> None:
        self.calls: list[tuple[Operation, dict[str, Any] | None]] = []
        self.target_namespace_key = target_namespace_key

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        del request
        self.calls.append((operation, context))
        namespace_key = (
            self.target_namespace_key
            if operation is Operation.CONTROL_BINDINGS_READ and context is not None
            else "default"
        )
        return Principal(namespace_key=namespace_key, is_admin=True)


def _agent_payload(
    agent_name: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "agent": {
            "agent_name": agent_name,
            "agent_description": "",
            "agent_version": "1.0",
        },
        "steps": [],
    }
    if target_type is not None:
        payload["target_type"] = target_type
    if target_id is not None:
        payload["target_id"] = target_id
    return payload


def _register_agent(
    client: TestClient,
    agent_name: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    resp = client.post(
        "/api/v1/agents/initAgent",
        json=_agent_payload(agent_name, target_type=target_type, target_id=target_id),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_control(client: TestClient, *, name: str | None = None) -> int:
    payload = canonicalize_control_payload(deepcopy(VALID_CONTROL_PAYLOAD))
    resp = client.put(
        "/api/v1/controls",
        json={"name": name or f"control-{uuid.uuid4().hex[:12]}", "data": payload},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


def _bind(
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


def _attach_direct(client: TestClient, agent_name: str, control_id: int) -> None:
    resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert resp.status_code == 200, resp.text


def _list_effective_via_get(
    client: TestClient,
    agent_name: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
) -> list[int]:
    params: dict[str, Any] = {}
    if target_type is not None:
        params["target_type"] = target_type
    if target_id is not None:
        params["target_id"] = target_id
    resp = client.get(f"/api/v1/agents/{agent_name}/controls", params=params or None)
    assert resp.status_code == 200, resp.text
    return [c["id"] for c in resp.json()["controls"]]


# ---------------------------------------------------------------------------
# initAgent contract.
# ---------------------------------------------------------------------------


def test_init_agent_with_target_merges_direct_and_target_controls(
    client: TestClient,
) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    direct_id = _create_control(client)
    target_id_ctrl = _create_control(client)

    # Pre-existing binding before the agent is registered.
    _bind(client, control_id=target_id_ctrl)

    # Agent registers with target context.
    _register_agent(client, agent_name)
    _attach_direct(client, agent_name, direct_id)

    body = _register_agent(client, agent_name, target_type="env", target_id="prod")
    returned_ids = {c["id"] for c in body["controls"]}
    assert returned_ids == {direct_id, target_id_ctrl}


def test_init_agent_newly_created_with_target_picks_up_pre_existing_bindings(
    client: TestClient,
) -> None:
    """Bindings can pre-exist the agent row.

    A binding for ``(env, prod)`` is created first; when the agent
    registers for the first time with that target context, the response
    must already include the bound control rather than the empty list
    that the create branch used to short-circuit to.
    """
    pre_existing = _create_control(client)
    _bind(client, control_id=pre_existing)

    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    body = _register_agent(client, agent_name, target_type="env", target_id="prod")
    assert body["created"] is True
    returned_ids = [c["id"] for c in body["controls"]]
    assert returned_ids == [pre_existing]


def test_init_agent_partial_target_pair_rejected(client: TestClient) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    payload = _agent_payload(agent_name)
    payload["target_type"] = "env"  # target_id omitted
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 422


def test_init_agent_with_target_requires_target_read_authorization(
    client: TestClient,
) -> None:
    authorizer = RecordingAuthorizer()
    set_authorizer(authorizer)
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"

    body = _register_agent(client, agent_name, target_type="env", target_id="prod")

    assert body["created"] is True
    assert (
        Operation.CONTROL_BINDINGS_READ,
        {"target_type": "env", "target_id": "prod"},
    ) in authorizer.calls


# ---------------------------------------------------------------------------
# GET /agents/{name}/controls contract.
# ---------------------------------------------------------------------------


def test_get_agent_controls_with_target_matches_init_agent_response(
    client: TestClient,
) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    direct_id = _create_control(client)
    target_id_ctrl = _create_control(client)
    _attach_direct(client, agent_name, direct_id)
    _bind(client, control_id=target_id_ctrl)

    init_body = _register_agent(client, agent_name, target_type="env", target_id="prod")
    init_ids = sorted(c["id"] for c in init_body["controls"])

    get_ids = sorted(
        _list_effective_via_get(client, agent_name, target_type="env", target_id="prod")
    )
    assert init_ids == get_ids == sorted([direct_id, target_id_ctrl])


def test_get_agent_controls_partial_target_pair_returns_400(
    client: TestClient,
) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    resp = client.get(
        f"/api/v1/agents/{agent_name}/controls",
        params={"target_type": "env"},  # target_id missing
    )
    assert resp.status_code == 400


def test_get_agent_controls_with_target_requires_target_read_authorization(
    client: TestClient,
) -> None:
    authorizer = RecordingAuthorizer()
    set_authorizer(authorizer)
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)
    authorizer.calls.clear()

    ids = _list_effective_via_get(
        client,
        agent_name,
        target_type="env",
        target_id="prod",
    )

    assert ids == []
    assert (Operation.AGENTS_READ, None) in authorizer.calls
    assert (
        Operation.CONTROL_BINDINGS_READ,
        {"target_type": "env", "target_id": "prod"},
    ) in authorizer.calls


def test_get_agent_controls_rejects_target_namespace_mismatch(
    client: TestClient,
) -> None:
    set_authorizer(RecordingAuthorizer(target_namespace_key="other-ns"))
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    resp = client.get(
        f"/api/v1/agents/{agent_name}/controls",
        params={"target_type": "env", "target_id": "prod"},
    )

    assert resp.status_code == 403, resp.text


def test_get_agent_controls_no_target_omits_target_bindings(
    client: TestClient,
) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    direct_id = _create_control(client)
    target_only = _create_control(client)
    _attach_direct(client, agent_name, direct_id)
    _bind(client, control_id=target_only)

    ids = _list_effective_via_get(client, agent_name)  # no target params
    assert ids == [direct_id]


def test_target_binding_de_duplicated_against_direct_attachment(
    client: TestClient,
) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    shared = _create_control(client)
    _attach_direct(client, agent_name, shared)
    _bind(client, control_id=shared)

    ids = _list_effective_via_get(client, agent_name, target_type="env", target_id="prod")
    assert ids == [shared]


async def _insert_agent_in_namespace(async_db, *, name: str, namespace_key: str) -> None:
    """Insert an Agent row directly so the test can simulate a foreign namespace.

    The default test authorizer returns the default namespace; this helper
    sidesteps the authorizer to seed an agent that the request-time code
    path should not be able to reach.
    """
    from agent_control_server.models import Agent

    async_db.add(Agent(name=name, namespace_key=namespace_key, data={}))
    await async_db.flush()
    await async_db.commit()


@pytest.mark.asyncio
async def test_get_agent_controls_cross_namespace_returns_404(
    client: TestClient, async_db
) -> None:
    """Agent existing only in another namespace must not surface here.

    The merged-resolver contract is namespace-scoped end-to-end; if the
    request-time path resolves the agent only by name it can return 200
    with the wrong/empty control set instead of 404 once duplicate names
    exist across namespaces.
    """
    agent_name = f"foreign-agent-{uuid.uuid4().hex[:12]}"
    await _insert_agent_in_namespace(async_db, name=agent_name, namespace_key="other-ns")

    resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_agent_association_endpoints_reject_cross_namespace_agent(
    client: TestClient, async_db
) -> None:
    """Agent association endpoints must not act on a cross-namespace agent.

    Even when the FK constraints would prevent a successful write, a
    name-only lookup leaks existence and lets the caller probe foreign
    namespaces. The agent association routes must surface 404 in that
    situation, just like the effective-controls route.
    """
    agent_name = f"foreign-agent-{uuid.uuid4().hex[:12]}"
    await _insert_agent_in_namespace(async_db, name=agent_name, namespace_key="other-ns")

    # Both read and write association routes should 404, not 200.
    list_resp = client.get(f"/api/v1/agents/{agent_name}/policies")
    assert list_resp.status_code == 404, list_resp.text

    delete_resp = client.delete(f"/api/v1/agents/{agent_name}/policies")
    assert delete_resp.status_code == 404, delete_resp.text


def test_disabled_binding_excluded_via_get_endpoint(client: TestClient) -> None:
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _register_agent(client, agent_name)

    bound = _create_control(client)
    _bind(client, control_id=bound, enabled=False)

    ids = _list_effective_via_get(client, agent_name, target_type="env", target_id="prod")
    assert ids == []
