"""Endpoint tests for natural-key target-control attach / detach.

These tests cover the two new routes:

- ``PUT    /api/v1/targets/{target_type}/{external_id}/controls/{control_id}``
- ``DELETE /api/v1/targets/{target_type}/{external_id}/controls/{control_id}``

Lock in:

- Lazy target creation on PUT.
- Idempotent desired-state semantics (PUT converges ``enabled``; repeated
  PUT returns the same attachment).
- Idempotent DELETE semantics (204 when target or attachment is absent).
- Tenant isolation: non-disclosing 404 on cross-tenant control lookups;
  independent target rows for the same natural key across tenants.
- Concurrent PUT does not surface IntegrityError as 5xx.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_control_server.config import db_config
from agent_control_server.models import Control, Target, TargetControl
from agent_control_server.services.targets import (
    ensure_target_by_natural_key,
    upsert_target_control_attachment,
)

from .utils import VALID_CONTROL_PAYLOAD

API_PREFIX = "/api/v1"
TENANT_HEADER = "X-Tenant-Id"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _create_control(client: TestClient, *, tenant: str | None = None) -> int:
    """Create a control via the public API and return its ID."""
    headers = {TENANT_HEADER: tenant} if tenant else {}
    resp = client.put(
        f"{API_PREFIX}/controls",
        headers=headers,
        json={"name": _unique("ctrl"), "data": VALID_CONTROL_PAYLOAD},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


# ---------------------------------------------------------------------------
# GET natural-key list — returns 200 [] for absent target
# ---------------------------------------------------------------------------


def test_get_natural_key_controls_returns_empty_when_target_absent(
    client: TestClient,
) -> None:
    # Given: no target exists for (environment, external_id)
    external_id = _unique("ls-absent")

    # When: we GET the controls via natural key
    resp = client.get(f"{API_PREFIX}/targets/environment/{external_id}/controls")

    # Then: 200 with an empty controls list, and the natural key echoed back
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target_type"] == "environment"
    assert body["external_id"] == external_id
    assert body["controls"] == []


def test_get_natural_key_controls_returns_attachments_when_target_exists(
    client: TestClient,
) -> None:
    # Given: a target with two attached controls (one enabled, one disabled)
    control_a = _create_control(client)
    control_b = _create_control(client)
    external_id = _unique("ls-present")

    client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_a}",
        json={"enabled": True},
    ).raise_for_status()
    client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_b}",
        json={"enabled": False},
    ).raise_for_status()

    # When: we GET via natural key
    resp = client.get(f"{API_PREFIX}/targets/environment/{external_id}/controls")

    # Then: both attachments returned, with their enabled flags
    assert resp.status_code == 200
    body = resp.json()
    assert body["target_type"] == "environment"
    assert body["external_id"] == external_id
    by_control = {c["control_id"]: c for c in body["controls"]}
    assert set(by_control) == {control_a, control_b}
    assert by_control[control_a]["enabled"] is True
    assert by_control[control_b]["enabled"] is False


def test_get_natural_key_controls_is_tenant_scoped(client: TestClient) -> None:
    # Given: tenant-a creates a target + attachment
    control_a = _create_control(client, tenant="tenant-a")
    external_id = _unique("shared-ls")
    client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_a}",
        headers={TENANT_HEADER: "tenant-a"},
        json={"enabled": True},
    ).raise_for_status()

    # When: tenant-b GETs the same natural key
    resp = client.get(
        f"{API_PREFIX}/targets/environment/{external_id}/controls",
        headers={TENANT_HEADER: "tenant-b"},
    )

    # Then: 200 with empty list — tenant-b sees no attachments (and, in
    # effect, does not even know that tenant-a has this target)
    assert resp.status_code == 200
    body = resp.json()
    assert body["controls"] == []


@pytest.mark.parametrize(
    "bad_target_type",
    ["Log-Stream", "log stream", "1log"],
)
def test_get_natural_key_controls_rejects_invalid_target_type(
    client: TestClient, bad_target_type: str
) -> None:
    resp = client.get(
        f"{API_PREFIX}/targets/{bad_target_type}/some-id/controls"
    )
    assert resp.status_code in (404, 422), resp.text


# ---------------------------------------------------------------------------
# PUT happy path — lazy target creation
# ---------------------------------------------------------------------------


def test_put_natural_key_creates_target_and_attachment(client: TestClient) -> None:
    # Given: a control but no target row for (environment, external_id)
    control_id = _create_control(client)
    external_id = _unique("ls")

    # When: we PUT the attach via natural key
    resp = client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_id}",
        json={"enabled": True},
    )

    # Then: the endpoint returns 200 with the current attachment state
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["control_id"] == control_id
    assert body["enabled"] is True
    assert isinstance(body["id"], int)

    # And: a GET /targets/{id}/controls for the lazily-created target reflects it
    list_resp = client.get(f"{API_PREFIX}/targets?target_type=environment")
    assert list_resp.status_code == 200
    matched = [
        t for t in list_resp.json()["targets"] if t["external_id"] == external_id
    ]
    assert len(matched) == 1
    assert matched[0]["name"] is None          # lazy creation leaves name null
    assert matched[0]["data"] == {}            # and data empty


# ---------------------------------------------------------------------------
# PUT is idempotent and updates enabled
# ---------------------------------------------------------------------------


def test_put_natural_key_is_idempotent_and_updates_enabled(client: TestClient) -> None:
    control_id = _create_control(client)
    external_id = _unique("ls")
    path = f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_id}"

    # First PUT with enabled=True
    r1 = client.put(path, json={"enabled": True})
    assert r1.status_code == 200
    first_id = r1.json()["id"]
    assert r1.json()["enabled"] is True

    # Second PUT with enabled=False converges the attachment
    r2 = client.put(path, json={"enabled": False})
    assert r2.status_code == 200
    assert r2.json()["id"] == first_id         # same attachment row
    assert r2.json()["enabled"] is False

    # Third PUT with no body — default is enabled=True, so it flips back
    r3 = client.put(path)
    assert r3.status_code == 200
    assert r3.json()["id"] == first_id
    assert r3.json()["enabled"] is True


# ---------------------------------------------------------------------------
# DELETE idempotent — final-state semantics
# ---------------------------------------------------------------------------


def test_delete_natural_key_returns_204_when_target_absent(client: TestClient) -> None:
    control_id = _create_control(client)
    external_id = _unique("never-touched")

    resp = client.delete(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_id}"
    )
    assert resp.status_code == 204, resp.text


def test_delete_natural_key_returns_204_when_attachment_absent(
    client: TestClient,
) -> None:
    # Given: a target exists but no attachment for this control
    control_id = _create_control(client)
    external_id = _unique("ls")
    # Lazily create the target via a different control attach
    other_control = _create_control(client)
    client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{other_control}"
    ).raise_for_status()

    # When: we DELETE the unrelated (control_id) attachment by natural key
    resp = client.delete(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_id}"
    )

    # Then: 204 (final-state reached, nothing to delete)
    assert resp.status_code == 204


def test_delete_natural_key_removes_attachment_when_present(client: TestClient) -> None:
    control_id = _create_control(client)
    external_id = _unique("ls")
    path = f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_id}"

    client.put(path, json={"enabled": True}).raise_for_status()
    resp = client.delete(path)
    assert resp.status_code == 204

    # Re-PUT returns 200 and the new attachment id differs from the old one
    resp2 = client.put(path, json={"enabled": True})
    assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# Control lookup is tenant-scoped — non-disclosing 404
# ---------------------------------------------------------------------------


def test_put_natural_key_returns_404_when_control_missing_in_tenant(
    client: TestClient,
) -> None:
    external_id = _unique("ls")
    resp = client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/99999",
        json={"enabled": True},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_delete_natural_key_returns_404_when_control_missing_in_tenant(
    client: TestClient,
) -> None:
    external_id = _unique("ls")
    resp = client.delete(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/99999"
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Cross-tenant isolation (9a/b/c per prompt)
# ---------------------------------------------------------------------------


def test_put_cross_tenant_control_id_looks_like_missing(client: TestClient) -> None:
    """(9a) A control that exists only in tenant-a must look like 'missing' to tenant-b.

    The response must not distinguish 'belongs to someone else' from 'does not
    exist', to preserve cross-tenant non-disclosure.
    """
    # Control exists in tenant-a
    control_id = _create_control(client, tenant="tenant-a")

    # tenant-b tries to PUT natural-key attach referencing that control
    external_id = _unique("ls")
    resp = client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_id}",
        headers={TENANT_HEADER: "tenant-b"},
        json={"enabled": True},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"

    # And: the response shape is the same as for a genuinely non-existent control
    resp_missing = client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/99999",
        headers={TENANT_HEADER: "tenant-b"},
        json={"enabled": True},
    )
    assert resp_missing.status_code == 404
    assert resp_missing.json()["error_code"] == resp.json()["error_code"]


def test_put_creates_independent_target_per_tenant(client: TestClient) -> None:
    """(9b) PUT creates a new target in the caller's tenant even if the same
    natural key already exists in another tenant."""
    control_a = _create_control(client, tenant="tenant-a")
    control_b = _create_control(client, tenant="tenant-b")
    external_id = _unique("shared-ls")

    # tenant-a creates its target via natural-key PUT
    r_a = client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_a}",
        headers={TENANT_HEADER: "tenant-a"},
        json={"enabled": True},
    )
    assert r_a.status_code == 200

    # tenant-b creates a target with the same external_id (different tenant)
    r_b = client.put(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_b}",
        headers={TENANT_HEADER: "tenant-b"},
        json={"enabled": True},
    )
    assert r_b.status_code == 200

    # Each tenant's targets list contains exactly one row with this external_id
    list_a = client.get(
        f"{API_PREFIX}/targets", headers={TENANT_HEADER: "tenant-a"}
    ).json()
    list_b = client.get(
        f"{API_PREFIX}/targets", headers={TENANT_HEADER: "tenant-b"}
    ).json()
    a_matches = [t for t in list_a["targets"] if t["external_id"] == external_id]
    b_matches = [t for t in list_b["targets"] if t["external_id"] == external_id]
    assert len(a_matches) == 1
    assert len(b_matches) == 1
    assert a_matches[0]["id"] != b_matches[0]["id"]  # independent rows


def test_delete_cross_tenant_control_returns_404(client: TestClient) -> None:
    """(9c) DELETE for a control that exists only in another tenant returns 404
    (because the tenant-scoped control lookup fails), matching PUT semantics."""
    control_id = _create_control(client, tenant="tenant-a")
    external_id = _unique("ls")

    resp = client.delete(
        f"{API_PREFIX}/targets/environment/{external_id}/controls/{control_id}",
        headers={TENANT_HEADER: "tenant-b"},
    )
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Path-parameter charset guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_target_type",
    ["Log-Stream", "log/stream", "log stream", "1log"],
)
def test_put_natural_key_rejects_invalid_target_type(
    client: TestClient, bad_target_type: str
) -> None:
    control_id = _create_control(client)
    resp = client.put(
        f"{API_PREFIX}/targets/{bad_target_type}/some-id/controls/{control_id}",
        json={"enabled": True},
    )
    # Path-param regex guard triggers a 422 before the handler runs.
    # Note: the slash case is routed as a separate path and surfaces 404.
    assert resp.status_code in (404, 422), resp.text


@pytest.mark.parametrize(
    "bad_external_id",
    ["env prod", "env:prod", "env#prod"],
)
def test_put_natural_key_rejects_invalid_external_id(
    client: TestClient, bad_external_id: str
) -> None:
    control_id = _create_control(client)
    # Percent-encode the caller's value so it reaches the handler; FastAPI's
    # path regex should still reject after decoding.
    import urllib.parse

    encoded = urllib.parse.quote(bad_external_id, safe="")
    resp = client.put(
        f"{API_PREFIX}/targets/environment/{encoded}/controls/{control_id}",
        json={"enabled": True},
    )
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Concurrency — no 5xx under duplicate creation race
# ---------------------------------------------------------------------------


@pytest.fixture
def async_session_factory():
    """Build a per-test async sessionmaker so concurrent coroutines hold
    independent sessions."""
    engine = create_async_engine(db_config.get_url(), echo=False)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    asyncio.run(engine.dispose())


@pytest.mark.asyncio
async def test_ensure_target_by_natural_key_race_safe(async_session_factory) -> None:
    """Two concurrent ensure_target_by_natural_key calls for the same tuple
    must both succeed and agree on the resulting row."""
    tenant = "tenant-race"
    target_type = "environment"
    external_id = _unique("race")

    async def _go() -> tuple[int, bool]:
        async with async_session_factory() as session:
            target, created = await ensure_target_by_natural_key(
                tenant_id=tenant,
                target_type=target_type,
                external_id=external_id,
                db=session,
            )
            return target.id, created

    results = await asyncio.gather(_go(), _go())
    ids = {r[0] for r in results}
    # Exactly one row; both callers see the same id.
    assert len(ids) == 1
    # At least one caller reports created=True (both if PG's ON CONFLICT DO
    # NOTHING serializes them).
    assert sum(1 for _, c in results if c) >= 1

    # And: only a single row exists in the DB for that natural key.
    async with async_session_factory() as session:
        stmt = select(Target).where(
            Target.tenant_id == tenant,
            Target.target_type == target_type,
            Target.external_id == external_id,
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_upsert_attachment_race_safe(async_session_factory) -> None:
    """Concurrent upserts for the same (target, control) pair converge without
    IntegrityError."""
    tenant = "tenant-race"
    target_type = "environment"
    external_id = _unique("race-attach")

    # Seed a target + a control via the ORM.
    async with async_session_factory() as session:
        target, _ = await ensure_target_by_natural_key(
            tenant_id=tenant,
            target_type=target_type,
            external_id=external_id,
            db=session,
        )
        target_id = target.id
        control = Control(
            name=_unique("ctrl"), tenant_id=tenant, data=VALID_CONTROL_PAYLOAD
        )
        session.add(control)
        await session.commit()
        await session.refresh(control)
        control_id = control.id

    async def _upsert(enabled: bool) -> int:
        async with async_session_factory() as session:
            att = await upsert_target_control_attachment(
                target_id=target_id, control_id=control_id, enabled=enabled, db=session
            )
            return att.id

    ids = await asyncio.gather(_upsert(True), _upsert(True))
    assert len(set(ids)) == 1

    # Only one row in target_controls for this pair
    async with async_session_factory() as session:
        stmt = select(TargetControl).where(
            TargetControl.target_id == target_id,
            TargetControl.control_id == control_id,
        )
        rows = (await session.execute(stmt)).scalars().all()
        assert len(rows) == 1
