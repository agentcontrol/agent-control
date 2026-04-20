"""Tests for tenant-aware write paths.

Covers:

- Agent / control / policy creation picks up the resolved tenant from the
  ``X-Tenant-Id`` header (header-based default resolver).
- Association inserts (agent_policies, agent_controls) record a tenant_id
  consistent with the agent's tenant_id.
- A pluggable ``TenantResolver`` override is picked up by the dependency.
- Callers without any header continue to land in the default tenant.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from agent_control_server.models import DEFAULT_TENANT_ID
from agent_control_server.tenancy import (
    HeaderTenantResolver,
    TenantResolver,
    get_active_resolver,
    set_tenant_resolver,
)

from .utils import VALID_CONTROL_PAYLOAD

API_PREFIX = "/api/v1"
TENANT_HEADER = "X-Tenant-Id"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _create_control(
    client: TestClient, *, tenant: str | None = None
) -> tuple[int, str]:
    name = _unique("ctrl")
    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.put(
        f"{API_PREFIX}/controls",
        headers=headers,
        json={"name": name, "data": VALID_CONTROL_PAYLOAD},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"]), name


def _create_policy(
    client: TestClient, *, tenant: str | None = None
) -> tuple[int, str]:
    name = _unique("pol")
    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.put(
        f"{API_PREFIX}/policies", headers=headers, json={"name": name}
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["policy_id"]), name


def _init_agent(
    client: TestClient, *, tenant: str | None = None, agent_name: str | None = None
) -> str:
    name = agent_name or f"agent-{uuid.uuid4().hex[:12]}"
    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.post(
        f"{API_PREFIX}/agents/initAgent",
        headers=headers,
        json={"agent": {"agent_name": name}, "steps": []},
    )
    assert resp.status_code == 200, resp.text
    return name


def _tenant_of(db_engine, table: str, where_sql: str, params: dict) -> str:
    with db_engine.begin() as conn:
        row = conn.execute(
            text(f"SELECT tenant_id FROM {table} WHERE {where_sql}"),
            params,
        ).first()
    assert row is not None, f"expected row in {table} matching {params}"
    return str(row[0])


# ---------------------------------------------------------------------------
# Default resolver (header-based) behavior
# ---------------------------------------------------------------------------


def test_control_create_without_header_lands_in_default_tenant(
    client: TestClient, db_engine
) -> None:
    _, name = _create_control(client)
    assert _tenant_of(
        db_engine, "controls", "name = :name", {"name": name}
    ) == DEFAULT_TENANT_ID


def test_control_create_with_header_lands_in_resolved_tenant(
    client: TestClient, db_engine
) -> None:
    _, name = _create_control(client, tenant="acme-corp")
    assert _tenant_of(
        db_engine, "controls", "name = :name", {"name": name}
    ) == "acme-corp"


def test_policy_create_with_header_lands_in_resolved_tenant(
    client: TestClient, db_engine
) -> None:
    _, name = _create_policy(client, tenant="acme-corp")
    assert _tenant_of(
        db_engine, "policies", "name = :name", {"name": name}
    ) == "acme-corp"


def test_agent_create_with_header_lands_in_resolved_tenant(
    client: TestClient, db_engine
) -> None:
    name = _init_agent(client, tenant="acme-corp")
    assert _tenant_of(
        db_engine, "agents", "name = :name", {"name": name}
    ) == "acme-corp"


def test_agent_policy_association_inherits_agent_tenant(
    client: TestClient, db_engine
) -> None:
    """Association rows must record the agent's tenant, not the request-scoped one."""
    agent_name = _init_agent(client, tenant="agent-tenant")
    policy_id, _ = _create_policy(client, tenant="policy-tenant")

    # Attach without a header. The association must still pick up the agent's tenant
    # rather than falling through to DEFAULT_TENANT_ID.
    attach = client.post(f"{API_PREFIX}/agents/{agent_name}/policies/{policy_id}")
    assert attach.status_code == 200, attach.text

    recorded = _tenant_of(
        db_engine,
        "agent_policies",
        "agent_name = :name AND policy_id = :policy_id",
        {"name": agent_name, "policy_id": policy_id},
    )
    assert recorded == "agent-tenant"


def test_agent_control_association_inherits_agent_tenant(
    client: TestClient, db_engine
) -> None:
    agent_name = _init_agent(client, tenant="agent-tenant")
    control_id, _ = _create_control(client, tenant="other-tenant")

    attach = client.post(
        f"{API_PREFIX}/agents/{agent_name}/controls/{control_id}"
    )
    assert attach.status_code == 200, attach.text

    recorded = _tenant_of(
        db_engine,
        "agent_controls",
        "agent_name = :name AND control_id = :control_id",
        {"name": agent_name, "control_id": control_id},
    )
    assert recorded == "agent-tenant"


def test_whitespace_header_falls_back_to_default_tenant(
    client: TestClient, db_engine
) -> None:
    _, name = _create_control(client, tenant="   ")
    assert _tenant_of(
        db_engine, "controls", "name = :name", {"name": name}
    ) == DEFAULT_TENANT_ID


# ---------------------------------------------------------------------------
# Pluggable resolver
# ---------------------------------------------------------------------------


class _ConstantTenantResolver:
    """Test resolver that always returns a preconfigured tenant id."""

    def __init__(self, tenant: str) -> None:
        self._tenant = tenant

    def resolve(self, x_tenant_id: str | None) -> str:
        del x_tenant_id  # ignored by this resolver
        return self._tenant


@pytest.fixture
def swap_resolver() -> Iterator[None]:
    previous = get_active_resolver()
    try:
        yield None
    finally:
        set_tenant_resolver(previous)


def test_tenant_resolver_protocol_is_runtime_checkable() -> None:
    assert isinstance(_ConstantTenantResolver("enterprise"), TenantResolver)
    assert isinstance(HeaderTenantResolver(), TenantResolver)


def test_installed_resolver_overrides_request_header(
    client: TestClient, db_engine, swap_resolver: None
) -> None:
    del swap_resolver
    set_tenant_resolver(_ConstantTenantResolver("enterprise-default"))

    # Even though the client sends a header, the enterprise resolver ignores
    # it and returns its own tenant. This mimics how an auth-driven resolver
    # would override request-supplied identity.
    _, name = _create_control(client, tenant="client-supplied-ignored")
    assert _tenant_of(
        db_engine, "controls", "name = :name", {"name": name}
    ) == "enterprise-default"
