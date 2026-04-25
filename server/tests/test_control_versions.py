from __future__ import annotations

import uuid
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_control_server.models import Agent, Control, ControlVersion

from .conftest import engine
from .utils import VALID_CONTROL_PAYLOAD


def _create_control(
    client: TestClient,
    *,
    name: str | None = None,
    data: dict[str, object] | None = None,
) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    payload = deepcopy(data) if data is not None else deepcopy(VALID_CONTROL_PAYLOAD)
    resp = client.put("/api/v1/controls", json={"name": control_name, "data": payload})
    assert resp.status_code == 200, resp.text
    return resp.json()["control_id"], control_name


def _fetch_versions(control_id: int) -> list[ControlVersion]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(ControlVersion)
                .where(ControlVersion.control_id == control_id)
                .order_by(ControlVersion.version_num)
            ).all()
        )


def _fetch_control_data(control_id: int) -> dict[str, object]:
    with Session(engine) as session:
        control = session.scalars(select(Control).where(Control.id == control_id)).one()
        return deepcopy(control.data)


def _replace_version_snapshot(
    control_id: int,
    version_num: int,
    snapshot: dict[str, object],
) -> None:
    with Session(engine) as session:
        version = session.scalars(
            select(ControlVersion).where(
                ControlVersion.control_id == control_id,
                ControlVersion.version_num == version_num,
            )
        ).one()
        version.snapshot = deepcopy(snapshot)
        session.commit()


def _remove_agent_evaluators(agent_name: str) -> None:
    with Session(engine) as session:
        agent = session.scalars(select(Agent).where(Agent.name == agent_name)).one()
        agent.data = {**agent.data, "evaluators": []}
        session.commit()


def _unrendered_template_payload() -> dict[str, object]:
    return {
        "template": {
            "description": "Regex denial template",
            "parameters": {
                "pattern": {
                    "type": "regex_re2",
                    "label": "Pattern",
                    "required": True,
                }
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
                "tags": ["template"],
            },
        },
        "template_values": {},
    }


def test_create_control_creates_initial_version_row(client: TestClient) -> None:
    # Given: a valid control create request
    control_id, control_name = _create_control(client)

    # When: inspecting persisted control versions
    versions = _fetch_versions(control_id)

    # Then: the control has a single initial version row
    assert len(versions) == 1
    version = versions[0]
    assert version.version_num == 1
    assert version.event_type == "created"
    assert version.note == "Initial creation"
    assert version.snapshot["name"] == control_name
    assert version.snapshot["data"]["description"] == VALID_CONTROL_PAYLOAD["description"]
    assert version.snapshot["deleted_at"] is None
    assert version.snapshot["cloned_control_id"] is None


def test_set_control_data_creates_edited_version_row(client: TestClient) -> None:
    # Given: an existing control
    control_id, _ = _create_control(client)
    updated_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    updated_payload["description"] = "Updated description"

    # When: replacing the control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": updated_payload})

    # Then: a new edited version is recorded
    assert resp.status_code == 200, resp.text
    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1, 2]
    latest = versions[-1]
    assert latest.event_type == "updated"
    assert latest.note == "Edited"
    assert latest.snapshot["data"]["description"] == "Updated description"


def test_set_control_data_noop_does_not_create_extra_version(client: TestClient) -> None:
    # Given: an existing control
    control_id, _ = _create_control(client)

    # When: replacing the control data with the already-current payload
    resp = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": deepcopy(VALID_CONTROL_PAYLOAD)},
    )

    # Then: no new version is recorded
    assert resp.status_code == 200, resp.text
    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1]


def test_patch_control_creates_edited_version_row(client: TestClient) -> None:
    # Given: an existing control
    control_id, _ = _create_control(client)
    new_name = f"control-{uuid.uuid4()}"

    # When: renaming and disabling the control
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": new_name, "enabled": False},
    )

    # Then: a new edited version captures the updated state
    assert resp.status_code == 200, resp.text
    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1, 2]
    latest = versions[-1]
    assert latest.event_type == "updated"
    assert latest.note == "Edited"
    assert latest.snapshot["name"] == new_name
    assert latest.snapshot["data"]["enabled"] is False


def test_patch_control_noop_does_not_create_extra_version(client: TestClient) -> None:
    # Given: an existing enabled control
    control_id, _ = _create_control(client)

    # When: PATCH submits the already-current enabled state
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": True})

    # Then: no new version is recorded
    assert resp.status_code == 200, resp.text
    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1]


def test_rename_followed_by_noop_set_data_does_not_create_extra_version(
    client: TestClient,
) -> None:
    # Given: an existing control
    control_id, _ = _create_control(client)
    new_name = f"control-{uuid.uuid4()}"

    # When: renaming the control, then saving unchanged data
    patch_resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": new_name},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    set_resp = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": deepcopy(VALID_CONTROL_PAYLOAD)},
    )

    # Then: the rename version is preserved without an extra empty data version
    assert set_resp.status_code == 200, set_resp.text
    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1, 2]


def test_delete_control_creates_deleted_version_row(client: TestClient) -> None:
    # Given: an existing control
    control_id, _ = _create_control(client)

    # When: soft-deleting the control
    resp = client.delete(f"/api/v1/controls/{control_id}")

    # Then: a deleted version row is appended with tombstone metadata
    assert resp.status_code == 200, resp.text
    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1, 2]
    deleted_version = versions[-1]
    assert deleted_version.event_type == "deleted"
    assert deleted_version.note == "Deleted"
    assert deleted_version.snapshot["deleted_at"] is not None


def test_delete_control_force_creates_deleted_version_row(client: TestClient) -> None:
    # Given: an existing control associated with a policy
    control_id, _ = _create_control(client)
    policy_resp = client.put("/api/v1/policies", json={"name": f"policy-{uuid.uuid4()}"})
    assert policy_resp.status_code == 200, policy_resp.text
    policy_id = policy_resp.json()["policy_id"]
    assoc_resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc_resp.status_code == 200, assoc_resp.text

    # When: force-deleting the in-use control
    resp = client.delete(f"/api/v1/controls/{control_id}?force=true")

    # Then: the deleted version is still recorded
    assert resp.status_code == 200, resp.text
    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1, 2]
    latest = versions[-1]
    assert latest.event_type == "deleted"
    assert latest.note == "Deleted"
    assert latest.snapshot["deleted_at"] is not None


def test_list_control_versions_paginates_newest_first_without_snapshot(
    client: TestClient,
) -> None:
    # Given: a control with three recorded versions
    control_id, _ = _create_control(client)

    updated_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    updated_payload["description"] = "Second version"
    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": updated_payload})
    assert set_resp.status_code == 200, set_resp.text

    patch_resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"enabled": False},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    # When: fetching the first page of version history
    resp = client.get(f"/api/v1/controls/{control_id}/versions", params={"limit": 2})

    # Then: newest versions are returned first without inline snapshots
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["version_num"] for item in body["versions"]] == [3, 2]
    assert all("snapshot" not in item for item in body["versions"])
    assert body["pagination"] == {
        "limit": 2,
        "total": 3,
        "next_cursor": "2",
        "has_more": True,
    }

    # And: the next page returns the remaining oldest version
    page_2 = client.get(
        f"/api/v1/controls/{control_id}/versions",
        params={"limit": 2, "cursor": 2},
    )
    assert page_2.status_code == 200, page_2.text
    body_2 = page_2.json()
    assert [item["version_num"] for item in body_2["versions"]] == [1]
    assert body_2["pagination"]["has_more"] is False
    assert body_2["pagination"]["next_cursor"] is None


def test_list_control_versions_returns_history_for_deleted_control(
    client: TestClient,
) -> None:
    # Given: a control that has been soft-deleted
    control_id, _ = _create_control(client)
    delete_resp = client.delete(f"/api/v1/controls/{control_id}")
    assert delete_resp.status_code == 200, delete_resp.text

    # When: listing version history after deletion
    resp = client.get(f"/api/v1/controls/{control_id}/versions")

    # Then: the deleted control's history remains browsable
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["version_num"] for item in body["versions"]] == [2, 1]
    assert [item["event_type"] for item in body["versions"]] == ["deleted", "created"]
    assert body["pagination"]["total"] == 2
    assert body["pagination"]["has_more"] is False


def test_get_control_version_returns_full_snapshot_for_deleted_control(
    client: TestClient,
) -> None:
    # Given: a control that has been soft-deleted
    control_id, control_name = _create_control(client)
    delete_resp = client.delete(f"/api/v1/controls/{control_id}")
    assert delete_resp.status_code == 200, delete_resp.text

    # When: fetching the deleted version snapshot directly
    resp = client.get(f"/api/v1/controls/{control_id}/versions/2")

    # Then: the full snapshot remains readable for audit/history use
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version_num"] == 2
    assert body["event_type"] == "deleted"
    assert body["note"] == "Deleted"
    assert body["snapshot"]["name"] == control_name
    assert body["snapshot"]["deleted_at"] is not None
    assert body["snapshot"]["data"]["description"] == VALID_CONTROL_PAYLOAD["description"]


def test_control_version_endpoints_return_404_for_missing_resources(
    client: TestClient,
) -> None:
    # Given: an existing control
    control_id, _ = _create_control(client)

    # When: listing versions for a missing control
    missing_control_resp = client.get("/api/v1/controls/999999/versions")

    # Then: the API reports the missing control
    assert missing_control_resp.status_code == 404
    assert missing_control_resp.json()["error_code"] == "CONTROL_NOT_FOUND"

    # When: fetching a missing version for an existing control
    missing_version_resp = client.get(f"/api/v1/controls/{control_id}/versions/99")

    # Then: the API reports the missing version
    assert missing_version_resp.status_code == 404
    assert missing_version_resp.json()["error_code"] == "CONTROL_VERSION_NOT_FOUND"


def test_restore_control_version_replays_name_and_data_in_one_version(
    client: TestClient,
) -> None:
    # Given: a control whose current name and payload differ from version 1
    original_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    original_payload["description"] = "Original description"
    control_id, original_name = _create_control(
        client,
        name=f"restore-original-{uuid.uuid4()}",
        data=original_payload,
    )
    updated_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    updated_payload["description"] = "Updated description"
    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": updated_payload})
    assert set_resp.status_code == 200, set_resp.text

    current_name = f"restore-current-{uuid.uuid4()}"
    patch_resp = client.patch(f"/api/v1/controls/{control_id}", json={"name": current_name})
    assert patch_resp.status_code == 200, patch_resp.text

    # When: restoring the initial version
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: the active row is restored and exactly one restored version is appended
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["control_id"] == control_id
    assert body["restored_from_version_num"] == 1
    assert body["current_version_num"] == 4
    assert body["name"] == original_name
    assert body["data"]["description"] == "Original description"

    active = client.get(f"/api/v1/controls/{control_id}")
    assert active.status_code == 200, active.text
    assert active.json()["name"] == original_name
    assert active.json()["data"]["description"] == "Original description"

    versions = _fetch_versions(control_id)
    assert [version.version_num for version in versions] == [1, 2, 3, 4]
    latest = versions[-1]
    assert latest.event_type == "restored"
    assert latest.note == "Restored from version 1"
    assert latest.snapshot["name"] == original_name
    assert latest.snapshot["data"]["description"] == "Original description"


def test_restore_control_version_preserves_unknown_snapshot_fields(
    client: TestClient,
) -> None:
    # Given: a historical snapshot with a forward-compatible field unknown to current models
    original_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    original_payload["description"] = "Original with future metadata"
    control_id, _ = _create_control(client, data=original_payload)

    version = _fetch_versions(control_id)[0]
    snapshot = deepcopy(version.snapshot)
    snapshot["data"]["x_future_metadata"] = {
        "source": "future-server",
        "flags": ["preserve-me"],
    }
    _replace_version_snapshot(control_id, 1, snapshot)

    updated_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    updated_payload["description"] = "Updated description"
    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": updated_payload})
    assert set_resp.status_code == 200, set_resp.text

    # When: restoring that version
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: validation still succeeds and responses preserve the snapshot shape
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["x_future_metadata"] == {
        "source": "future-server",
        "flags": ["preserve-me"],
    }
    active_data = _fetch_control_data(control_id)
    assert active_data["description"] == "Original with future metadata"
    assert active_data["x_future_metadata"] == {
        "source": "future-server",
        "flags": ["preserve-me"],
    }
    get_resp = client.get(f"/api/v1/controls/{control_id}")
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["data"]["x_future_metadata"] == {
        "source": "future-server",
        "flags": ["preserve-me"],
    }

    get_data_resp = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_data_resp.status_code == 200, get_data_resp.text
    assert get_data_resp.json()["data"]["x_future_metadata"] == {
        "source": "future-server",
        "flags": ["preserve-me"],
    }

    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert init_resp.status_code == 200, init_resp.text
    assoc_resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert assoc_resp.status_code == 200, assoc_resp.text

    agent_controls_resp = client.get(f"/api/v1/agents/{agent_name}/controls")
    assert agent_controls_resp.status_code == 200, agent_controls_resp.text
    restored_control = next(
        control
        for control in agent_controls_resp.json()["controls"]
        if control["id"] == control_id
    )
    assert restored_control["control"]["x_future_metadata"] == {
        "source": "future-server",
        "flags": ["preserve-me"],
    }

    versions = _fetch_versions(control_id)
    assert versions[-1].event_type == "restored"
    assert versions[-1].snapshot["data"]["x_future_metadata"] == {
        "source": "future-server",
        "flags": ["preserve-me"],
    }


def test_restore_control_version_canonicalizes_legacy_snapshot_shape(
    client: TestClient,
) -> None:
    # Given: a historical snapshot rewritten into the legacy flat selector/evaluator shape
    control_id, _ = _create_control(client)
    version = _fetch_versions(control_id)[0]
    snapshot = deepcopy(version.snapshot)
    snapshot["data"]["selector"] = snapshot["data"]["condition"]["selector"]
    snapshot["data"]["evaluator"] = snapshot["data"]["condition"]["evaluator"]
    snapshot["data"].pop("condition")
    _replace_version_snapshot(control_id, 1, snapshot)

    updated_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    updated_payload["description"] = "Updated description"
    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": updated_payload})
    assert set_resp.status_code == 200, set_resp.text

    # When: restoring that legacy-shaped version
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: the restored active row and new version snapshot are persisted canonically
    assert resp.status_code == 200, resp.text
    active_data = _fetch_control_data(control_id)
    assert "selector" not in active_data
    assert "evaluator" not in active_data
    assert active_data["condition"]["selector"]["path"] == "input"

    latest = _fetch_versions(control_id)[-1]
    assert latest.event_type == "restored"
    assert "selector" not in latest.snapshot["data"]
    assert "evaluator" not in latest.snapshot["data"]
    assert latest.snapshot["data"]["condition"]["selector"]["path"] == "input"


def test_restore_control_version_replays_unrendered_template_payload(
    client: TestClient,
) -> None:
    # Given: a template-backed control created as unrendered, then rendered later
    unrendered_payload = _unrendered_template_payload()
    control_id, _ = _create_control(client, data=unrendered_payload)

    rendered_payload = deepcopy(unrendered_payload)
    rendered_payload["template_values"] = {"pattern": "secret"}
    set_resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": rendered_payload})
    assert set_resp.status_code == 200, set_resp.text

    # When: restoring the unrendered version
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: the saved unrendered template state is restored
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_version_num"] == 3
    assert body["data"]["enabled"] is False
    assert body["data"]["template_values"] == {}
    assert "condition" not in body["data"]

    active = client.get(f"/api/v1/controls/{control_id}")
    assert active.status_code == 200, active.text
    active_data = active.json()["data"]
    assert active_data["enabled"] is False
    assert active_data["template_values"] == {}
    assert "condition" not in active_data


def test_restore_control_version_rejects_name_conflict(client: TestClient) -> None:
    # Given: a historical name that is now used by another active control
    original_name = f"restore-conflict-{uuid.uuid4()}"
    control_id, _ = _create_control(client, name=original_name)
    patch_resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": f"restore-renamed-{uuid.uuid4()}"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    _create_control(client, name=original_name)

    # When: restoring the version that has the conflicting name
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: the restore is rejected without writing another version row
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"
    assert [version.version_num for version in _fetch_versions(control_id)] == [1, 2]


def test_restore_control_version_rejects_invalid_snapshot_data(
    client: TestClient,
) -> None:
    # Given: a historical snapshot referencing an agent-scoped evaluator that was removed
    agent_name = f"restore-agent-{uuid.uuid4().hex[:8]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name},
            "evaluators": [
                {
                    "name": "risk",
                    "config_schema": {
                        "type": "object",
                        "properties": {"threshold": {"type": "number"}},
                    },
                }
            ],
        },
    )
    assert init_resp.status_code == 200, init_resp.text

    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {
        "name": f"{agent_name}:risk",
        "config": {"threshold": 0.5},
    }
    control_id, _ = _create_control(client, data=payload)
    _remove_agent_evaluators(agent_name)

    # When: restoring the invalid snapshot
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: current validation rejects the restore and no version is appended
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "EVALUATOR_NOT_FOUND"
    assert [version.version_num for version in _fetch_versions(control_id)] == [1]


def test_restore_control_version_rejects_deleted_snapshot(client: TestClient) -> None:
    # Given: a version snapshot that represents a deleted control state
    control_id, _ = _create_control(client)
    version = _fetch_versions(control_id)[0]
    snapshot = deepcopy(version.snapshot)
    snapshot["deleted_at"] = "2026-04-24T00:00:00+00:00"
    _replace_version_snapshot(control_id, 1, snapshot)

    # When: attempting to restore it
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: deleted snapshots are out of scope for v1 restore
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "VALIDATION_ERROR"
    assert [version.version_num for version in _fetch_versions(control_id)] == [1]


def test_restore_control_version_noop_does_not_create_version(
    client: TestClient,
) -> None:
    # Given: the selected version already matches the current saved state
    control_id, control_name = _create_control(client)

    # When: restoring the current version
    resp = client.post(f"/api/v1/controls/{control_id}/versions/1/restore")

    # Then: the response succeeds but no restored version row is created
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_version_num"] == 1
    assert body["name"] == control_name
    assert [version.version_num for version in _fetch_versions(control_id)] == [1]
