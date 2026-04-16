from __future__ import annotations

import datetime as dt
import uuid
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from agent_control_server.models import (
    Control,
    ControlStore,
    ControlVersion,
    control_stores_controls,
)

from .conftest import engine
from .utils import VALID_CONTROL_PAYLOAD


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

        store = ControlStore(id=1, name="default")
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
    _ensure_default_store()
    control_id, _ = _create_control(client)
    publish_response = client.post(f"/api/v1/control-stores/default/controls/{control_id}")
    assert publish_response.status_code == 200, publish_response.text

    first = client.delete(f"/api/v1/control-stores/default/controls/{control_id}")
    second = client.delete(f"/api/v1/control-stores/default/controls/{control_id}")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert _published_rows(control_id) == []


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
    assert first_body["pagination"]["next_cursor"] == str(beta_id)

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
