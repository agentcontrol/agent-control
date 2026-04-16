from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from collections.abc import AsyncGenerator
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from agent_control_server.db import get_async_db
from agent_control_server.models import (
    Control,
    ControlStore,
    ControlVersion,
    Policy,
    control_stores_controls,
    policy_controls,
)
from agent_control_server.services.controls import ControlService

from .conftest import AsyncSessionTest, engine
from .utils import VALID_CONTROL_PAYLOAD


def _make_integrity_error(constraint_name: str) -> IntegrityError:
    diag = SimpleNamespace(constraint_name=constraint_name)
    orig = Exception(f'duplicate key value violates unique constraint "{constraint_name}"')
    setattr(orig, "diag", diag)
    return IntegrityError("statement", {}, orig)


def _unrendered_template_payload() -> dict[str, Any]:
    return {
        "template": {
            "description": "Regex denial template",
            "parameters": {
                "pattern": {
                    "type": "regex_re2",
                    "label": "Pattern",
                },
            },
            "definition_template": {
                "description": "Template-backed control",
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": {"$param": "pattern"}},
                    },
                },
                "action": {"decision": "deny"},
            },
        },
        "template_values": {},
    }


def _ensure_default_store() -> int:
    with Session(engine) as session:
        existing = session.scalar(select(ControlStore.id).where(ControlStore.name == "default"))
        if existing is not None:
            return int(existing)

        store = ControlStore(name="default")
        session.add(store)
        session.commit()
        return int(store.id)


def _create_control(
    client: TestClient,
    *,
    name: str | None = None,
    data: dict[str, object] | None = None,
) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    payload = deepcopy(data) if data is not None else deepcopy(VALID_CONTROL_PAYLOAD)
    response = client.put("/api/v1/controls", json={"name": control_name, "data": payload})
    assert response.status_code == 200, response.text
    return int(response.json()["control_id"]), control_name


def _create_policy(client: TestClient, *, name: str | None = None) -> int:
    response = client.put(
        "/api/v1/policies",
        json={"name": name or f"policy-{uuid.uuid4()}"},
    )
    assert response.status_code == 200, response.text
    return int(response.json()["policy_id"])


def _create_agent(client: TestClient, *, name: str | None = None) -> str:
    agent_name = name or f"agent-{uuid.uuid4().hex[:12]}"
    response = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert response.status_code == 200, response.text
    return agent_name


async def _create_versioned_control(
    *,
    name: str | None = None,
    data: dict[str, object] | None = None,
) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    payload = deepcopy(data) if data is not None else deepcopy(VALID_CONTROL_PAYLOAD)

    async with AsyncSessionTest() as session:
        service = ControlService(session)
        control = service.create_control(name=control_name, data=payload)
        await service.create_version(
            control,
            event_type="created",
            note="Initial creation",
        )
        await session.commit()
        return control.id, control_name


async def _create_policy_row(*, name: str | None = None) -> int:
    async with AsyncSessionTest() as session:
        policy = Policy(name=name or f"policy-{uuid.uuid4()}")
        session.add(policy)
        await session.commit()
        return policy.id


def _insert_raw_control(
    *,
    name: str | None = None,
    data: dict[str, object] | None = None,
) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    control = Control(
        name=control_name,
        data=deepcopy(data) if data is not None else {},
    )
    with Session(engine) as session:
        session.add(control)
        session.commit()
        session.refresh(control)
        return int(control.id), control_name


def _fetch_control(control_id: int) -> Control | None:
    with Session(engine) as session:
        return session.scalars(select(Control).where(Control.id == control_id)).first()


def _fetch_versions(control_id: int) -> list[ControlVersion]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(ControlVersion)
                .where(ControlVersion.control_id == control_id)
                .order_by(ControlVersion.version_num)
            ).all()
        )


def _published_rows(control_id: int | None = None) -> list[tuple[int, int, dt.datetime]]:
    with Session(engine) as session:
        stmt = select(
            control_stores_controls.c.store_id,
            control_stores_controls.c.control_id,
            control_stores_controls.c.published_at,
        ).order_by(control_stores_controls.c.control_id)
        if control_id is not None:
            stmt = stmt.where(control_stores_controls.c.control_id == control_id)
        return [
            (int(store_id), int(published_control_id), published_at)
            for store_id, published_control_id, published_at in session.execute(stmt).all()
        ]


def _set_published_at(control_id: int, published_at: dt.datetime) -> None:
    with Session(engine) as session:
        session.execute(
            update(control_stores_controls)
            .where(control_stores_controls.c.control_id == control_id)
            .values(published_at=published_at)
        )
        session.commit()


def test_publish_control_is_idempotent(client: TestClient) -> None:
    _ensure_default_store()
    control_id, _ = _create_control(client)

    first = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    second = client.post(f"/api/v1/control-stores/default/controls/{control_id}")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert _published_rows(control_id) == [_published_rows(control_id)[0]]


def test_publish_control_rejects_missing_and_deleted_controls(client: TestClient) -> None:
    _ensure_default_store()
    missing = client.post("/api/v1/control-stores/default/controls/99999")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "CONTROL_NOT_FOUND"

    control_id, _ = _create_control(client)
    delete_response = client.delete(f"/api/v1/controls/{control_id}")
    assert delete_response.status_code == 200, delete_response.text

    deleted = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert deleted.status_code == 404
    assert deleted.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_publish_control_accepts_rendered_and_unrendered_controls(client: TestClient) -> None:
    _ensure_default_store()
    rendered_id, _ = _create_control(client)
    unrendered_id, _ = _create_control(
        client,
        data=_unrendered_template_payload(),
    )

    rendered_response = client.post(f"/api/v1/control-stores/default/controls/{rendered_id}")
    unrendered_response = client.post(f"/api/v1/control-stores/default/controls/{unrendered_id}")

    assert rendered_response.status_code == 200, rendered_response.text
    assert unrendered_response.status_code == 200, unrendered_response.text
    assert [row[1] for row in _published_rows()] == [rendered_id, unrendered_id]


def test_publish_control_rejects_runtime_associations(client: TestClient) -> None:
    _ensure_default_store()

    policy_control_id, _ = _create_control(client)
    policy_id = _create_policy(client)
    policy_assoc = client.post(f"/api/v1/policies/{policy_id}/controls/{policy_control_id}")
    assert policy_assoc.status_code == 200, policy_assoc.text

    policy_publish = client.post(f"/api/v1/control-stores/default/controls/{policy_control_id}")
    assert policy_publish.status_code == 409
    assert policy_publish.json()["error_code"] == "CONTROL_IN_USE"

    agent_control_id, _ = _create_control(client)
    agent_name = _create_agent(client)
    agent_assoc = client.post(f"/api/v1/agents/{agent_name}/controls/{agent_control_id}")
    assert agent_assoc.status_code == 200, agent_assoc.text

    agent_publish = client.post(f"/api/v1/control-stores/default/controls/{agent_control_id}")
    assert agent_publish.status_code == 409
    assert agent_publish.json()["error_code"] == "CONTROL_IN_USE"


def test_unpublish_control_removes_publication_state(client: TestClient) -> None:
    # Given: a published control in the default store
    _ensure_default_store()
    control_id, _ = _create_control(client)
    publish_response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert publish_response.status_code == 200, publish_response.text

    # When: unpublishing it twice
    first = client.delete(f"/api/v1/control-stores/default/controls/{control_id}")
    second = client.delete(f"/api/v1/control-stores/default/controls/{control_id}")

    # Then: the endpoint is idempotent and leaves no publication rows behind
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert _published_rows(control_id) == []


def test_unpublish_control_rejects_missing_and_deleted_controls(client: TestClient) -> None:
    # Given: the default store exists
    _ensure_default_store()

    # When: unpublishing a control that does not exist
    missing = client.delete("/api/v1/control-stores/default/controls/99999")

    # Then: the API reports the control as missing
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "CONTROL_NOT_FOUND"

    # Given: a control that has already been soft-deleted
    control_id, _ = _create_control(client)
    delete_response = client.delete(f"/api/v1/controls/{control_id}")
    assert delete_response.status_code == 200, delete_response.text

    # When: unpublishing the soft-deleted control
    deleted = client.delete(f"/api/v1/control-stores/default/controls/{control_id}")

    # Then: the deleted control is treated as not found
    assert deleted.status_code == 404
    assert deleted.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_list_published_controls_uses_cursor_pagination_and_name_filter(
    client: TestClient,
) -> None:
    _ensure_default_store()
    alpha_id, _ = _create_control(client, name="AlphaControl")
    beta_id, _ = _create_control(client, name="BetaDetector")
    gamma_id, _ = _create_control(client, name="GammaControl")

    for control_id in (alpha_id, beta_id, gamma_id):
        response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
        assert response.status_code == 200, response.text

    _set_published_at(alpha_id, dt.datetime(2026, 4, 15, 10, 0, tzinfo=dt.UTC))
    _set_published_at(beta_id, dt.datetime(2026, 4, 15, 11, 0, tzinfo=dt.UTC))
    _set_published_at(gamma_id, dt.datetime(2026, 4, 15, 12, 0, tzinfo=dt.UTC))

    first_page = client.get("/api/v1/control-stores/default/controls", params={"limit": 2})
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()

    assert [item["id"] for item in first_body["controls"]] == [gamma_id, beta_id]
    assert first_body["pagination"]["has_more"] is True
    assert first_body["pagination"]["next_cursor"] is not None

    second_page = client.get(
        "/api/v1/control-stores/default/controls",
        params={"limit": 2, "cursor": first_body["pagination"]["next_cursor"]},
    )
    assert second_page.status_code == 200, second_page.text
    second_body = second_page.json()

    assert [item["id"] for item in second_body["controls"]] == [alpha_id]
    assert second_body["pagination"]["has_more"] is False
    assert second_body["pagination"]["next_cursor"] is None

    filtered = client.get(
        "/api/v1/control-stores/default/controls",
        params={"name": "detec"},
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["controls"]] == [beta_id]


def test_list_published_controls_filters_by_tag_and_enabled(client: TestClient) -> None:
    _ensure_default_store()
    enabled_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    enabled_payload["tags"] = ["pci"]
    enabled_id, _ = _create_control(client, name="enabled-control", data=enabled_payload)

    disabled_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    disabled_payload["enabled"] = False
    disabled_payload["tags"] = ["pci"]
    disabled_id, _ = _create_control(client, name="disabled-control", data=disabled_payload)

    other_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    other_payload["tags"] = ["other"]
    other_id, _ = _create_control(client, name="other-control", data=other_payload)

    for control_id in (enabled_id, disabled_id, other_id):
        response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
        assert response.status_code == 200, response.text

    tag_filtered = client.get("/api/v1/control-stores/default/controls", params={"tag": "pci"})
    assert tag_filtered.status_code == 200, tag_filtered.text
    assert {item["id"] for item in tag_filtered.json()["controls"]} == {enabled_id, disabled_id}

    disabled_filtered = client.get(
        "/api/v1/control-stores/default/controls",
        params={"enabled": "false"},
    )
    assert disabled_filtered.status_code == 200, disabled_filtered.text
    assert [item["id"] for item in disabled_filtered.json()["controls"]] == [disabled_id]


def test_list_published_controls_cursor_survives_unpublished_cursor_row(
    client: TestClient,
) -> None:
    _ensure_default_store()
    first_id, _ = _create_control(client, name="first-control")
    second_id, _ = _create_control(client, name="second-control")

    for control_id in (first_id, second_id):
        response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
        assert response.status_code == 200, response.text

    _set_published_at(first_id, dt.datetime(2026, 4, 15, 10, 0, tzinfo=dt.UTC))
    _set_published_at(second_id, dt.datetime(2026, 4, 15, 11, 0, tzinfo=dt.UTC))

    first_page = client.get("/api/v1/control-stores/default/controls", params={"limit": 1})
    assert first_page.status_code == 200, first_page.text
    next_cursor = first_page.json()["pagination"]["next_cursor"]

    unpublish_response = client.delete(f"/api/v1/control-stores/default/controls/{second_id}")
    assert unpublish_response.status_code == 200, unpublish_response.text

    next_page = client.get(
        "/api/v1/control-stores/default/controls",
        params={"limit": 1, "cursor": next_cursor},
    )
    assert next_page.status_code == 200, next_page.text
    assert [item["id"] for item in next_page.json()["controls"]] == [first_id]


def test_list_published_controls_cursor_survives_unpublish_and_republish(
    client: TestClient,
) -> None:
    _ensure_default_store()
    alpha_id, _ = _create_control(client, name="AlphaControl")
    beta_id, _ = _create_control(client, name="BetaDetector")
    gamma_id, _ = _create_control(client, name="GammaControl")

    for control_id in (alpha_id, beta_id, gamma_id):
        response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
        assert response.status_code == 200, response.text

    _set_published_at(alpha_id, dt.datetime(2026, 4, 15, 10, 0, tzinfo=dt.UTC))
    _set_published_at(beta_id, dt.datetime(2026, 4, 15, 11, 0, tzinfo=dt.UTC))
    _set_published_at(gamma_id, dt.datetime(2026, 4, 15, 12, 0, tzinfo=dt.UTC))

    first_page = client.get("/api/v1/control-stores/default/controls", params={"limit": 2})
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()
    assert [item["id"] for item in first_body["controls"]] == [gamma_id, beta_id]

    unpublish_response = client.delete(f"/api/v1/control-stores/default/controls/{beta_id}")
    assert unpublish_response.status_code == 200, unpublish_response.text
    republish_response = client.post(f"/api/v1/control-stores/default/controls/{beta_id}")
    assert republish_response.status_code == 200, republish_response.text
    _set_published_at(beta_id, dt.datetime(2026, 4, 15, 13, 0, tzinfo=dt.UTC))

    next_page = client.get(
        "/api/v1/control-stores/default/controls",
        params={"limit": 2, "cursor": first_body["pagination"]["next_cursor"]},
    )
    assert next_page.status_code == 200, next_page.text
    assert [item["id"] for item in next_page.json()["controls"]] == [alpha_id]


def test_list_published_controls_rejects_malformed_cursor(client: TestClient) -> None:
    _ensure_default_store()
    control_id, _ = _create_control(client, name="cursor-target")
    response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert response.status_code == 200, response.text

    malformed_page = client.get(
        "/api/v1/control-stores/default/controls",
        params={"limit": 1, "cursor": "not-a-valid-cursor"},
    )
    assert malformed_page.status_code == 422
    assert malformed_page.json()["error_code"] == "VALIDATION_ERROR"


def test_list_published_controls_uses_control_id_tie_breaker_for_equal_timestamps(
    client: TestClient,
) -> None:
    # Given: three published controls with the exact same publication timestamp
    _ensure_default_store()
    control_ids = [
        _create_control(client, name=f"tie-break-{index}")[0]
        for index in range(3)
    ]
    for control_id in control_ids:
        response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
        assert response.status_code == 200, response.text
        _set_published_at(control_id, dt.datetime(2026, 4, 15, 12, 0, tzinfo=dt.UTC))

    expected_order = sorted(control_ids, reverse=True)

    # When: requesting the first page
    first_page = client.get("/api/v1/control-stores/default/controls", params={"limit": 2})

    # Then: equal timestamps fall back to control_id descending order
    assert first_page.status_code == 200, first_page.text
    first_body = first_page.json()
    assert [item["id"] for item in first_body["controls"]] == expected_order[:2]
    assert first_body["pagination"]["next_cursor"] is not None

    # When: requesting the next page from that cursor
    second_page = client.get(
        "/api/v1/control-stores/default/controls",
        params={"limit": 2, "cursor": first_body["pagination"]["next_cursor"]},
    )

    # Then: the remaining lower-id control is returned
    assert second_page.status_code == 200, second_page.text
    assert [item["id"] for item in second_page.json()["controls"]] == expected_order[2:]


@pytest.mark.asyncio
@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Control-store concurrency coverage requires PostgreSQL row locking semantics",
)
async def test_publish_waits_for_policy_association_and_preserves_catalog_invariant() -> None:
    control_id, _ = await _create_versioned_control()
    policy_id = await _create_policy_row()

    association_has_lock = asyncio.Event()
    publish_started = asyncio.Event()
    release_association = asyncio.Event()

    async def associate_control() -> None:
        async with AsyncSessionTest() as session:
            service = ControlService(session)
            await service.get_active_control_or_404(control_id, for_update=True)
            assert not await service.is_control_published(control_id)
            association_has_lock.set()
            await release_association.wait()
            await service.add_control_to_policy(policy_id=policy_id, control_id=control_id)
            await session.commit()

    async def publish_control() -> None:
        async with AsyncSessionTest() as session:
            service = ControlService(session)
            publish_started.set()
            await service.get_active_control_or_404(control_id, for_update=True)
            associations = await service.list_control_associations(control_id)
            if not associations.policy_ids and not associations.agent_names:
                await service.publish_control(control_id)
            await session.commit()

    association_task = asyncio.create_task(associate_control())
    await association_has_lock.wait()
    publish_task = asyncio.create_task(publish_control())
    await publish_started.wait()
    release_association.set()
    await asyncio.gather(association_task, publish_task)

    with Session(engine) as session:
        policy_link = session.execute(
            select(policy_controls.c.control_id).where(
                policy_controls.c.policy_id == policy_id,
                policy_controls.c.control_id == control_id,
            )
        ).first()

    assert policy_link is not None
    assert _published_rows(control_id) == []


@pytest.mark.asyncio
@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Control-store concurrency coverage requires PostgreSQL row locking semantics",
)
async def test_policy_association_waits_for_publish_and_preserves_catalog_invariant() -> None:
    control_id, _ = await _create_versioned_control()
    policy_id = await _create_policy_row()

    publish_has_lock = asyncio.Event()
    association_started = asyncio.Event()
    release_publish = asyncio.Event()

    async def publish_control() -> None:
        async with AsyncSessionTest() as session:
            service = ControlService(session)
            await service.get_active_control_or_404(control_id, for_update=True)
            associations = await service.list_control_associations(control_id)
            assert associations.policy_ids == []
            publish_has_lock.set()
            await release_publish.wait()
            await service.publish_control(control_id)
            await session.commit()

    async def associate_control() -> None:
        async with AsyncSessionTest() as session:
            service = ControlService(session)
            association_started.set()
            await service.get_active_control_or_404(control_id, for_update=True)
            if not await service.is_control_published(control_id):
                await service.add_control_to_policy(policy_id=policy_id, control_id=control_id)
            await session.commit()

    publish_task = asyncio.create_task(publish_control())
    await publish_has_lock.wait()
    association_task = asyncio.create_task(associate_control())
    await association_started.wait()
    release_publish.set()
    await asyncio.gather(publish_task, association_task)

    with Session(engine) as session:
        policy_link = session.execute(
            select(policy_controls.c.control_id).where(
                policy_controls.c.policy_id == policy_id,
                policy_controls.c.control_id == control_id,
            )
        ).first()

    assert policy_link is None
    assert len(_published_rows(control_id)) == 1


@pytest.mark.asyncio
@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Control-store concurrency coverage requires PostgreSQL row locking semantics",
)
async def test_unpublish_waits_for_publish_and_applies_afterward() -> None:
    # Given: a publish request that acquires the control-row lock first
    control_id, _ = await _create_versioned_control()
    publish_has_lock = asyncio.Event()
    unpublish_started = asyncio.Event()
    release_publish = asyncio.Event()

    async def publish_control() -> None:
        async with AsyncSessionTest() as session:
            service = ControlService(session)
            await service.get_active_control_or_404(control_id, for_update=True)
            publish_has_lock.set()
            await release_publish.wait()
            await service.publish_control(control_id)
            await session.commit()

    async def unpublish_control() -> None:
        async with AsyncSessionTest() as session:
            service = ControlService(session)
            unpublish_started.set()
            await service.get_active_control_or_404(control_id, for_update=True)
            await service.unpublish_control(control_id)
            await session.commit()

    # When: unpublish starts while publish still holds the lock
    publish_task = asyncio.create_task(publish_control())
    await publish_has_lock.wait()
    unpublish_task = asyncio.create_task(unpublish_control())
    await unpublish_started.wait()
    release_publish.set()
    await asyncio.gather(publish_task, unpublish_task)

    # Then: the later unpublish takes effect after publish commits
    assert _published_rows(control_id) == []


def test_publish_control_rejects_corrupted_stored_data(client: TestClient) -> None:
    # Given: a control row whose stored JSON is not a valid control definition
    _ensure_default_store()
    control_id, _ = _insert_raw_control(data={"description": "broken"})

    # When: publishing the corrupted control
    response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")

    # Then: the endpoint reports corrupted stored data rather than publishing it
    assert response.status_code == 422
    assert response.json()["error_code"] == "CORRUPTED_DATA"


def test_default_store_seed_keeps_create_all_identity_usable() -> None:
    # Given: the session-level test schema has already seeded the default store
    _ensure_default_store()

    with Session(engine) as session:
        # When: inserting another control store directly through the ORM
        store = ControlStore(name="secondary-store")
        session.add(store)
        session.commit()

        # Then: the identity sequence advances past the seeded default row
        assert store.id is not None
        assert store.id > 1


def test_clone_control_creates_independent_control_with_provenance_and_version(
    client: TestClient,
) -> None:
    source_id, source_name = _create_control(client)

    clone_response = client.post(
        f"/api/v1/controls/{source_id}/clone",
        json={"name": f"{source_name}-clone"},
    )
    assert clone_response.status_code == 200, clone_response.text
    clone_id = int(clone_response.json()["control_id"])

    clone = _fetch_control(clone_id)
    source = _fetch_control(source_id)
    assert clone is not None
    assert source is not None
    assert clone.cloned_control_id == source_id
    assert clone.data == source.data

    updated_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    updated_payload["description"] = "Clone only"
    update_response = client.put(
        f"/api/v1/controls/{clone_id}/data",
        json={"data": updated_payload},
    )
    assert update_response.status_code == 200, update_response.text

    refreshed_clone = _fetch_control(clone_id)
    refreshed_source = _fetch_control(source_id)
    assert refreshed_clone is not None
    assert refreshed_source is not None
    assert refreshed_clone.data["description"] == "Clone only"
    assert refreshed_source.data["description"] == VALID_CONTROL_PAYLOAD["description"]

    versions = _fetch_versions(clone_id)
    assert [version.version_num for version in versions] == [1, 2]
    assert versions[0].event_type == "cloned"
    assert versions[0].snapshot["cloned_control_id"] == source_id
    assert versions[0].note == f"Cloned from '{source_name}' (id:{source_id}) at version 1"


def test_clone_control_without_name_generates_unique_copy_name(client: TestClient) -> None:
    source_id, source_name = _create_control(client, name="PII-Detection")
    _create_control(client, name=f"{source_name}-copy")

    clone_response = client.post(f"/api/v1/controls/{source_id}/clone")
    assert clone_response.status_code == 200, clone_response.text
    assert clone_response.json()["name"] == f"{source_name}-copy-2"


def test_clone_control_without_name_truncates_generated_copy_name(client: TestClient) -> None:
    # Given: a control name already at the maximum allowed length
    source_name = "x" * 255
    source_id, _ = _create_control(client, name=source_name)

    # When: cloning without an explicit name
    clone_response = client.post(f"/api/v1/controls/{source_id}/clone")

    # Then: the generated copy name stays within the control name limit
    assert clone_response.status_code == 200, clone_response.text
    cloned_name = clone_response.json()["name"]
    assert len(cloned_name) == 255
    assert cloned_name.endswith("-copy")
    assert cloned_name == f"{source_name[:250]}-copy"


def test_clone_control_rejects_requested_name_conflict(client: TestClient) -> None:
    # Given: a source control and a different active control already using the requested clone name
    source_id, _ = _create_control(client, name="source-control")
    _, existing_name = _create_control(client, name="existing-clone-name")

    # When: cloning into that existing name
    clone_response = client.post(
        f"/api/v1/controls/{source_id}/clone",
        json={"name": existing_name},
    )

    # Then: the API reports a control-name conflict
    assert clone_response.status_code == 409
    assert clone_response.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_clone_control_rejects_corrupted_source_data(client: TestClient) -> None:
    # Given: a source control whose stored JSON is corrupted
    source_id, _ = _insert_raw_control(data={"description": "broken"})

    # When: cloning that control
    clone_response = client.post(f"/api/v1/controls/{source_id}/clone")

    # Then: the endpoint rejects the corrupted source row
    assert clone_response.status_code == 422
    assert clone_response.json()["error_code"] == "CORRUPTED_DATA"


def test_clone_control_records_latest_source_version_in_provenance_note(
    client: TestClient,
) -> None:
    # Given: a source control with multiple recorded versions
    source_id, source_name = _create_control(client)
    updated_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    updated_payload["description"] = "Version two"
    update_response = client.put(
        f"/api/v1/controls/{source_id}/data",
        json={"data": updated_payload},
    )
    assert update_response.status_code == 200, update_response.text
    patch_response = client.patch(
        f"/api/v1/controls/{source_id}",
        json={"enabled": False},
    )
    assert patch_response.status_code == 200, patch_response.text

    # When: cloning the latest source state
    clone_response = client.post(f"/api/v1/controls/{source_id}/clone")

    # Then: the clone provenance points at the latest source version number
    assert clone_response.status_code == 200, clone_response.text
    clone_id = int(clone_response.json()["control_id"])
    clone_versions = _fetch_versions(clone_id)
    assert clone_versions[0].event_type == "cloned"
    assert clone_versions[0].note == f"Cloned from '{source_name}' (id:{source_id}) at version 3"


def test_clone_control_preserves_unrendered_template_shape(client: TestClient) -> None:
    source_id, source_name = _create_control(
        client,
        name="template-control",
        data=_unrendered_template_payload(),
    )

    clone_response = client.post(
        f"/api/v1/controls/{source_id}/clone",
        json={"name": f"{source_name}-copy"},
    )
    assert clone_response.status_code == 200, clone_response.text
    clone_id = int(clone_response.json()["control_id"])

    get_response = client.get(f"/api/v1/controls/{clone_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]

    assert data["enabled"] is False
    assert "template" in data
    assert "condition" not in data
    assert _fetch_control(clone_id) is not None
    assert _fetch_control(clone_id).cloned_control_id == source_id  # type: ignore[union-attr]


def test_clone_control_rejects_deleted_source(client: TestClient) -> None:
    source_id, _ = _create_control(client)
    delete_response = client.delete(f"/api/v1/controls/{source_id}")
    assert delete_response.status_code == 200, delete_response.text

    clone_response = client.post(f"/api/v1/controls/{source_id}/clone")
    assert clone_response.status_code == 404
    assert clone_response.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_add_agent_control_rejects_published_control(client: TestClient) -> None:
    _ensure_default_store()
    control_id, _ = _create_control(client)
    publish_response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert publish_response.status_code == 200, publish_response.text

    agent_name = _create_agent(client)
    response = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")

    assert response.status_code == 409
    assert response.json()["error_code"] == "CONTROL_PUBLISHED"


def test_add_control_to_policy_rejects_published_control(client: TestClient) -> None:
    _ensure_default_store()
    control_id, _ = _create_control(client)
    publish_response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert publish_response.status_code == 200, publish_response.text

    policy_id = _create_policy(client)
    response = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")

    assert response.status_code == 409
    assert response.json()["error_code"] == "CONTROL_PUBLISHED"


def test_delete_control_removes_store_publication_rows(client: TestClient) -> None:
    _ensure_default_store()
    control_id, _ = _create_control(client)
    publish_response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert publish_response.status_code == 200, publish_response.text

    delete_response = client.delete(f"/api/v1/controls/{control_id}")

    assert delete_response.status_code == 200, delete_response.text
    assert _published_rows(control_id) == []


def test_delete_control_with_runtime_association_still_requires_force_even_if_published(
    client: TestClient,
) -> None:
    store_id = _ensure_default_store()
    control_id, _ = _create_control(client)
    policy_id = _create_policy(client)
    assoc_response = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc_response.status_code == 200, assoc_response.text

    with Session(engine) as session:
        session.execute(
            insert(control_stores_controls).values(store_id=store_id, control_id=control_id)
        )
        session.commit()

    blocked = client.delete(f"/api/v1/controls/{control_id}")
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "CONTROL_IN_USE"
    assert _published_rows(control_id) != []

    forced = client.delete(f"/api/v1/controls/{control_id}?force=true")
    assert forced.status_code == 200, forced.text
    assert _published_rows(control_id) == []


def test_browse_published_controls_marks_unrendered_templates(client: TestClient) -> None:
    _ensure_default_store()
    control_id, _ = _create_control(
        client,
        name="template-published",
        data=_unrendered_template_payload(),
    )
    publish_response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert publish_response.status_code == 200, publish_response.text

    response = client.get("/api/v1/control-stores/default/controls")
    assert response.status_code == 200, response.text
    summary = response.json()["controls"][0]

    assert summary["id"] == control_id
    assert summary["template_backed"] is True
    assert summary["template_rendered"] is False
    assert summary["enabled"] is False


def test_publish_control_database_error_returns_500(
    app: FastAPI,
    client: TestClient,
) -> None:
    # Given: a valid control lookup path whose commit fails during publish
    control = Control(
        id=123,
        name="publish-db-error",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        deleted_at=None,
    )
    control_result = MagicMock()
    control_result.scalars.return_value.first.return_value = control
    associations_result = MagicMock()
    associations_result.all.return_value = []
    store_result = MagicMock()
    store_result.scalar_one_or_none.return_value = 1
    publish_result = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        side_effect=[
            control_result,
            associations_result,
            store_result,
            publish_result,
        ]
    )
    mock_session.commit.side_effect = Exception("Database error")
    mock_session.rollback = AsyncMock()

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db
    try:
        # When: publishing the control
        response = client.post("/api/v1/control-stores/default/controls/123")
    finally:
        app.dependency_overrides.clear()

    # Then: the endpoint rolls back and reports a database error
    assert response.status_code == 500
    assert response.json()["error_code"] == "DATABASE_ERROR"
    assert mock_session.rollback.await_count == 1
    lock_stmt = mock_session.execute.await_args_list[0].args[0]
    assert getattr(lock_stmt, "_for_update_arg", None) is not None


def test_unpublish_control_database_error_returns_500(
    app: FastAPI,
    client: TestClient,
) -> None:
    # Given: a valid unpublish path whose commit fails after removing the publication row
    control = Control(
        id=123,
        name="unpublish-db-error",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        deleted_at=None,
    )
    control_result = MagicMock()
    control_result.scalars.return_value.first.return_value = control
    store_result = MagicMock()
    store_result.scalar_one_or_none.return_value = 1
    delete_result = MagicMock()
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        side_effect=[
            control_result,
            store_result,
            delete_result,
        ]
    )
    mock_session.commit.side_effect = Exception("Database error")
    mock_session.rollback = AsyncMock()

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db
    try:
        # When: unpublishing the control
        response = client.delete("/api/v1/control-stores/default/controls/123")
    finally:
        app.dependency_overrides.clear()

    # Then: the endpoint rolls back and reports a database error
    assert response.status_code == 500
    assert response.json()["error_code"] == "DATABASE_ERROR"
    assert mock_session.rollback.await_count == 1


def test_clone_control_integrity_name_conflict_returns_conflict(
    app: FastAPI,
    client: TestClient,
) -> None:
    # Given: a clone request that races with another writer on the target control name
    source_control = Control(
        id=123,
        name="clone-source",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        deleted_at=None,
    )
    control_result = MagicMock()
    control_result.scalars.return_value.first.return_value = source_control
    name_lookup_result = MagicMock()
    name_lookup_result.first.return_value = None
    source_version_result = MagicMock()
    source_version_result.scalar_one.return_value = 1
    insert_result = MagicMock()
    insert_result.scalar_one.return_value = 201
    lock_result = MagicMock()
    clone_version_result = MagicMock()
    clone_version_result.scalar_one.return_value = 1
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        side_effect=[
            control_result,
            name_lookup_result,
            source_version_result,
            insert_result,
            lock_result,
            clone_version_result,
        ]
    )
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit.side_effect = _make_integrity_error("idx_controls_name_active")
    mock_session.rollback = AsyncMock()

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db
    try:
        # When: cloning into a name claimed concurrently by another transaction
        response = client.post(
            "/api/v1/controls/123/clone",
            json={"name": "race-target"},
        )
    finally:
        app.dependency_overrides.clear()

    # Then: the endpoint maps the integrity failure to a control-name conflict
    assert response.status_code == 409
    assert response.json()["error_code"] == "CONTROL_NAME_CONFLICT"
    assert mock_session.rollback.await_count == 1


def test_clone_control_without_name_retries_generated_name_conflict(
    app: FastAPI,
    client: TestClient,
) -> None:
    # Given: an auto-generated clone name that collides on the first commit attempt
    source_control = Control(
        id=123,
        name="source-control",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        deleted_at=None,
    )
    control_result = MagicMock()
    control_result.scalars.return_value.first.return_value = source_control
    first_name_lookup_result = MagicMock()
    first_name_lookup_result.first.return_value = None
    first_source_version_result = MagicMock()
    first_source_version_result.scalar_one.return_value = 3
    first_insert_result = MagicMock()
    first_insert_result.scalar_one.return_value = 201
    first_lock_result = MagicMock()
    first_clone_version_result = MagicMock()
    first_clone_version_result.scalar_one.return_value = 1
    retry_control_result = MagicMock()
    retry_control_result.scalars.return_value.first.return_value = source_control
    retry_first_name_lookup_result = MagicMock()
    retry_first_name_lookup_result.first.return_value = object()
    retry_second_name_lookup_result = MagicMock()
    retry_second_name_lookup_result.first.return_value = None
    retry_source_version_result = MagicMock()
    retry_source_version_result.scalar_one.return_value = 3
    retry_insert_result = MagicMock()
    retry_insert_result.scalar_one.return_value = 202
    retry_lock_result = MagicMock()
    retry_clone_version_result = MagicMock()
    retry_clone_version_result.scalar_one.return_value = 1

    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        side_effect=[
            control_result,
            first_name_lookup_result,
            first_source_version_result,
            first_insert_result,
            first_lock_result,
            first_clone_version_result,
            retry_control_result,
            retry_first_name_lookup_result,
            retry_second_name_lookup_result,
            retry_source_version_result,
            retry_insert_result,
            retry_lock_result,
            retry_clone_version_result,
        ]
    )
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit.side_effect = [
        _make_integrity_error("idx_controls_name_active"),
        None,
    ]
    mock_session.rollback = AsyncMock()

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db
    try:
        # When: cloning without an explicit name
        response = client.post("/api/v1/controls/123/clone")
    finally:
        app.dependency_overrides.clear()

    # Then: the endpoint retries and returns the next unique generated name
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "source-control-copy-2"
    assert response.json()["control_id"] == 202
    assert mock_session.rollback.await_count == 1


def test_clone_control_non_name_integrity_error_returns_500(
    app: FastAPI,
    client: TestClient,
) -> None:
    # Given: a clone request that hits a non-name integrity failure during commit
    source_control = Control(
        id=123,
        name="clone-source",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        deleted_at=None,
    )
    control_result = MagicMock()
    control_result.scalars.return_value.first.return_value = source_control
    name_lookup_result = MagicMock()
    name_lookup_result.first.return_value = None
    source_version_result = MagicMock()
    source_version_result.scalar_one.return_value = 1
    insert_result = MagicMock()
    insert_result.scalar_one.return_value = 201
    lock_result = MagicMock()
    clone_version_result = MagicMock()
    clone_version_result.scalar_one.return_value = 1
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute = AsyncMock(
        side_effect=[
            control_result,
            name_lookup_result,
            source_version_result,
            insert_result,
            lock_result,
            clone_version_result,
        ]
    )
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit.side_effect = _make_integrity_error(
        "uq_control_versions_control_version"
    )
    mock_session.rollback = AsyncMock()

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db
    try:
        # When: cloning the control
        response = client.post("/api/v1/controls/123/clone", json={"name": "clone-target"})
    finally:
        app.dependency_overrides.clear()

    # Then: the endpoint reports a database error instead of a name conflict
    assert response.status_code == 500
    assert response.json()["error_code"] == "DATABASE_ERROR"
    assert mock_session.rollback.await_count == 1
