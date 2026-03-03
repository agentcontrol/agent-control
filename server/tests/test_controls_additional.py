from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from agent_control_server.db import get_async_db
from agent_control_server.models import Control

from agent_control_evaluators import RegexEvaluatorConfig
from agent_control_server.endpoints import controls as controls_module
from agent_control_server.main import app

from .conftest import engine
from .utils import VALID_CONTROL_PAYLOAD


def _create_control(client: TestClient, name: str | None = None) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    resp = client.put("/api/v1/controls", json={"name": control_name})
    assert resp.status_code == 200
    return resp.json()["control_id"], control_name


def _set_control_data(client: TestClient, control_id: int, data: dict) -> None:
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": data})
    assert resp.status_code == 200, resp.text


def test_create_control_integrity_error_returns_conflict(client: TestClient) -> None:
    """DB uniqueness violations during create should be surfaced as 409 conflicts."""

    async def mock_db_integrity_error() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        existing_result = MagicMock()
        existing_result.first.return_value = None

        mock_session.execute = AsyncMock(return_value=existing_result)
        mock_session.add = MagicMock()
        mock_session.refresh = AsyncMock()
        mock_session.commit = AsyncMock(
            side_effect=IntegrityError(
                "INSERT INTO controls ...",
                {"name": "duplicate-control"},
                Exception("duplicate key value violates unique constraint"),
            )
        )
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db_integrity_error
    try:
        resp = client.put("/api/v1/controls", json={"name": "duplicate-control"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_patch_control_rename_integrity_error_returns_conflict(client: TestClient) -> None:
    """DB uniqueness violations during rename should be surfaced as 409 conflicts."""
    control_obj = SimpleNamespace(id=1, name="old-control", data={})

    async def mock_db_integrity_error() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)

        control_lookup_result = MagicMock()
        control_lookup_result.scalars.return_value.first.return_value = control_obj

        name_lookup_result = MagicMock()
        name_lookup_result.first.return_value = None

        mock_session.execute = AsyncMock(
            side_effect=[control_lookup_result, name_lookup_result]
        )
        mock_session.commit = AsyncMock(
            side_effect=IntegrityError(
                "UPDATE controls ...",
                {"name": "existing-control"},
                Exception("duplicate key value violates unique constraint"),
            )
        )
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db_integrity_error
    try:
        resp = client.patch("/api/v1/controls/1", json={"name": "existing-control"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_list_controls_filters_and_pagination(client: TestClient) -> None:
    # Given: three controls with varying data
    control1_id, control1_name = _create_control(client, name=f"AlphaControl-{uuid.uuid4()}")
    control2_id, control2_name = _create_control(client, name=f"BetaControl-{uuid.uuid4()}")
    control3_id, control3_name = _create_control(client, name=f"GammaControl-{uuid.uuid4()}")

    data1 = deepcopy(VALID_CONTROL_PAYLOAD)
    data1.update(
        {
            "description": "alpha",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "tags": ["pci"],
        }
    )

    data2 = deepcopy(VALID_CONTROL_PAYLOAD)
    data2.update(
        {
            "description": "beta",
            "enabled": False,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["post"]},
            "tags": ["hipaa"],
        }
    )

    data3 = deepcopy(VALID_CONTROL_PAYLOAD)
    data3.pop("enabled", None)
    data3.pop("scope", None)
    data3.update({"description": "gamma", "tags": ["misc"]})

    _set_control_data(client, control1_id, data1)
    _set_control_data(client, control2_id, data2)
    _set_control_data(client, control3_id, data3)

    # When: filtering by name (case-insensitive partial match)
    resp = client.get("/api/v1/controls", params={"name": "alpha"})
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["controls"]]
    # Then: only the matching control is returned
    assert names == [control1_name]

    # When: filtering by enabled=false
    resp = client.get("/api/v1/controls", params={"enabled": "false"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: only explicitly disabled controls are returned
    assert names == {control2_name}

    # When: filtering by step_type=tool (controls without scope still match)
    resp = client.get("/api/v1/controls", params={"step_type": "tool"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: controls with matching step_type or missing scope are included
    assert control1_name in names
    assert control3_name in names
    assert control2_name not in names

    # When: filtering by tag
    resp = client.get("/api/v1/controls", params={"tag": "pci"})
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["controls"]]
    # Then: only controls with the tag are returned
    assert names == [control1_name]

    # Then: enabled defaults to True when missing
    resp = client.get("/api/v1/controls", params={"name": "gamma"})
    assert resp.status_code == 200
    control = resp.json()["controls"][0]
    assert control["name"] == control3_name
    assert control["enabled"] is True

    # When: paginating
    resp = client.get("/api/v1/controls", params={"limit": 1})
    assert resp.status_code == 200
    page1 = resp.json()
    # Then: response indicates more pages
    assert page1["pagination"]["has_more"] is True
    assert page1["pagination"]["next_cursor"] is not None
    first_id = page1["controls"][0]["id"]

    # When: fetching the next page
    resp2 = client.get(
        "/api/v1/controls",
        params={"limit": 1, "cursor": page1["pagination"]["next_cursor"]},
    )
    assert resp2.status_code == 200
    page2 = resp2.json()
    # Then: the next page has a different item
    assert page2["controls"][0]["id"] != first_id


def test_patch_control_enabled_requires_data(client: TestClient) -> None:
    # Given: a control without configured data
    control_id, _ = _create_control(client)

    # When: toggling enabled without data
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": False})

    # Then: validation error
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    assert any(err.get("code") == "no_data_configured" for err in data.get("errors", []))


def test_patch_control_rename_conflict(client: TestClient) -> None:
    # Given: two controls
    _, existing_name = _create_control(client)
    control_id, _ = _create_control(client)

    # When: renaming to an existing name
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"name": existing_name})

    # Then: conflict
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_list_controls_filters_stage_and_execution(client: TestClient) -> None:
    # Given: controls with differing stages and execution targets
    control1_id, control1_name = _create_control(client)
    control2_id, control2_name = _create_control(client)
    control3_id, control3_name = _create_control(client)

    data1 = deepcopy(VALID_CONTROL_PAYLOAD)
    data1.update(
        {
            "execution": "server",
            "scope": {"stages": ["pre"], "step_types": ["llm"]},
        }
    )
    data2 = deepcopy(VALID_CONTROL_PAYLOAD)
    data2.update(
        {
            "execution": "sdk",
            "scope": {"stages": ["post"], "step_types": ["llm"]},
        }
    )
    data3 = deepcopy(VALID_CONTROL_PAYLOAD)
    data3.update({"execution": "server"})
    data3.pop("scope", None)

    _set_control_data(client, control1_id, data1)
    _set_control_data(client, control2_id, data2)
    _set_control_data(client, control3_id, data3)

    # When: filtering by stage=pre
    resp = client.get("/api/v1/controls", params={"stage": "pre"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: matching stage and missing scope are included
    assert names == {control1_name, control3_name}

    # When: filtering by stage=post
    resp = client.get("/api/v1/controls", params={"stage": "post"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: matching stage and missing scope are included
    assert names == {control2_name, control3_name}

    # When: filtering by execution=server
    resp = client.get("/api/v1/controls", params={"execution": "server"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: only server-executed controls are returned
    assert names == {control1_name, control3_name}

    # When: filtering by execution=sdk
    resp = client.get("/api/v1/controls", params={"execution": "sdk"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: only sdk-executed controls are returned
    assert names == {control2_name}


def test_list_controls_combined_filters(client: TestClient) -> None:
    # Given: controls with distinct names/tags
    control1_id, control1_name = _create_control(client, name=f"Alpha-{uuid.uuid4()}")
    control2_id, control2_name = _create_control(client, name=f"Alpha-{uuid.uuid4()}")

    data1 = deepcopy(VALID_CONTROL_PAYLOAD)
    data1.update({"tags": ["pci"], "enabled": True})
    data2 = deepcopy(VALID_CONTROL_PAYLOAD)
    data2.update({"tags": ["hipaa"], "enabled": True})

    _set_control_data(client, control1_id, data1)
    _set_control_data(client, control2_id, data2)

    # When: filtering by name and tag together
    resp = client.get(
        "/api/v1/controls",
        params={"name": "alpha", "tag": "pci"},
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["controls"]]

    # Then: only controls matching all filters are returned
    assert names == [control1_name]


def test_list_controls_enabled_true_includes_missing_enabled(client: TestClient) -> None:
    # Given: controls with enabled true, enabled false, and missing enabled
    control_true_id, control_true_name = _create_control(client, name=f"Enabled-{uuid.uuid4()}")
    control_false_id, control_false_name = _create_control(client, name=f"Disabled-{uuid.uuid4()}")
    control_missing_id, control_missing_name = _create_control(client, name=f"Missing-{uuid.uuid4()}")

    data_true = deepcopy(VALID_CONTROL_PAYLOAD)
    data_true["enabled"] = True
    data_false = deepcopy(VALID_CONTROL_PAYLOAD)
    data_false["enabled"] = False
    data_missing = deepcopy(VALID_CONTROL_PAYLOAD)
    data_missing.pop("enabled", None)

    _set_control_data(client, control_true_id, data_true)
    _set_control_data(client, control_false_id, data_false)
    _set_control_data(client, control_missing_id, data_missing)

    # When: filtering by enabled=true
    resp = client.get("/api/v1/controls", params={"enabled": "true"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}

    # Then: enabled=true and missing enabled are included; enabled=false is excluded
    assert names == {control_true_name, control_missing_name}


def test_list_controls_cursor_with_tag_filter(client: TestClient) -> None:
    # Given: multiple controls sharing a tag and one without it
    control_ids = []
    control_names = []
    for _ in range(3):
        cid, name = _create_control(client, name=f"Tagged-{uuid.uuid4()}")
        control_ids.append(cid)
        control_names.append(name)

    other_id, other_name = _create_control(client, name=f"Other-{uuid.uuid4()}")

    data_tagged = deepcopy(VALID_CONTROL_PAYLOAD)
    data_tagged.update({"tags": ["pci"]})
    data_other = deepcopy(VALID_CONTROL_PAYLOAD)
    data_other.update({"tags": ["hipaa"]})

    for cid in control_ids:
        _set_control_data(client, cid, data_tagged)
    _set_control_data(client, other_id, data_other)

    # When: requesting the first page filtered by tag
    resp = client.get("/api/v1/controls", params={"tag": "pci", "limit": 2})
    assert resp.status_code == 200
    page1 = resp.json()

    # Then: pagination reflects filtered total and has more pages
    assert page1["pagination"]["total"] == 3
    assert page1["pagination"]["has_more"] is True
    assert page1["pagination"]["next_cursor"] is not None
    assert len(page1["controls"]) == 2
    assert all("pci" in c["tags"] for c in page1["controls"])

    # When: requesting the next page with cursor
    resp2 = client.get(
        "/api/v1/controls",
        params={"tag": "pci", "limit": 2, "cursor": page1["pagination"]["next_cursor"]},
    )
    assert resp2.status_code == 200
    page2 = resp2.json()

    # Then: remaining tagged control is returned
    assert page2["pagination"]["has_more"] is False
    assert len(page2["controls"]) == 1
    assert page2["controls"][0]["name"] in control_names


def test_list_controls_cursor_with_name_and_enabled_filters(client: TestClient) -> None:
    # Given: controls with shared name prefix and mixed enabled states
    matching_ids = []
    matching_names = []
    for enabled in (True, True, False):
        cid, name = _create_control(client, name=f"Match-{uuid.uuid4()}")
        matching_ids.append(cid)
        matching_names.append(name)
        data = deepcopy(VALID_CONTROL_PAYLOAD)
        data["enabled"] = enabled
        _set_control_data(client, cid, data)

    non_match_id, non_match_name = _create_control(client, name=f"Other-{uuid.uuid4()}")
    non_match_data = deepcopy(VALID_CONTROL_PAYLOAD)
    non_match_data["enabled"] = True
    _set_control_data(client, non_match_id, non_match_data)

    # When: listing with name filter and enabled=true
    resp = client.get(
        "/api/v1/controls",
        params={"name": "match", "enabled": "true", "limit": 1},
    )
    assert resp.status_code == 200
    page1 = resp.json()

    # Then: pagination reflects filtered total and results are enabled only
    assert page1["pagination"]["total"] == 2
    assert page1["pagination"]["has_more"] is True
    assert len(page1["controls"]) == 1
    assert page1["controls"][0]["enabled"] is True
    assert "Match-" in page1["controls"][0]["name"]

    # When: fetching next page with cursor
    resp2 = client.get(
        "/api/v1/controls",
        params={
            "name": "match",
            "enabled": "true",
            "limit": 1,
            "cursor": page1["pagination"]["next_cursor"],
        },
    )
    assert resp2.status_code == 200
    page2 = resp2.json()

    # Then: second enabled control is returned and pagination ends
    assert page2["pagination"]["has_more"] is False
    assert len(page2["controls"]) == 1
    assert page2["controls"][0]["enabled"] is True


def test_list_controls_includes_used_by_agent_mapping(client: TestClient) -> None:
    # Given: one control linked through Policy -> Agent
    control_id, control_name = _create_control(client, name=f"Mapped-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    policy_name = f"pol-{uuid.uuid4()}"
    policy_resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert policy_resp.status_code == 200
    policy_id = policy_resp.json()["policy_id"]

    assoc_resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc_resp.status_code == 200

    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert init_resp.status_code == 200

    assign_resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    assert assign_resp.status_code == 200

    # When: listing controls
    resp = client.get("/api/v1/controls", params={"name": "mapped"})
    assert resp.status_code == 200
    controls = resp.json()["controls"]

    # Then: used_by_agent is populated from the join traversal
    assert len(controls) == 1
    assert controls[0]["id"] == control_id
    assert controls[0]["name"] == control_name
    assert controls[0]["used_by_agent"] == {"agent_name": agent_name}


def test_delete_control_force_dissociates(client: TestClient) -> None:
    # Given: a control associated with a policy
    control_id, _ = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    _set_control_data(client, control_id, data)

    policy_name = f"pol-{uuid.uuid4()}"
    policy_resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert policy_resp.status_code == 200
    policy_id = policy_resp.json()["policy_id"]

    assoc_resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc_resp.status_code == 200

    # When: deleting without force
    resp = client.delete(f"/api/v1/controls/{control_id}")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_IN_USE"

    # When: deleting with force
    resp2 = client.delete(f"/api/v1/controls/{control_id}?force=true")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["success"] is True
    assert policy_id in body.get("dissociated_from", [])

    # Then: policy no longer lists the control
    list_resp = client.get(f"/api/v1/policies/{policy_id}/controls")
    assert list_resp.status_code == 200
    assert control_id not in list_resp.json()["control_ids"]


def test_delete_control_force_dissociates_direct_agent_links(client: TestClient) -> None:
    # Given: a control directly associated with an agent
    control_id, _ = _create_control(client)
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert init_resp.status_code == 200

    assoc_resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert assoc_resp.status_code == 200

    # When: force-deleting the control
    resp = client.delete(f"/api/v1/controls/{control_id}?force=true")
    assert resp.status_code == 200
    body = resp.json()

    # Then: direct agent dissociation details are returned
    assert body["success"] is True
    assert body.get("dissociated_from_policies", []) == []
    assert body.get("dissociated_from_agents", []) == [agent_name]


def test_get_control_corrupted_data_returns_none(client: TestClient) -> None:
    # Given: a control with corrupted data in DB
    control_id, control_name = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: fetching the control
    resp = client.get(f"/api/v1/controls/{control_id}")

    # Then: data is None but the control metadata is intact
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == control_name
    assert body["data"] is None


def test_get_control_data_corrupted_returns_422(client: TestClient) -> None:
    # Given: a control with corrupted data in DB
    control_id, _ = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: fetching control data
    resp = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: validation error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "CORRUPTED_DATA"


def test_patch_control_enabled_with_corrupted_data(client: TestClient) -> None:
    # Given: a control with corrupted data in DB
    control_id, _ = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: toggling enabled
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": False})

    # Then: corrupted data error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "CORRUPTED_DATA"
    assert body["errors"][0]["message"] == "Stored control data is corrupted and cannot be parsed."
    assert "ValidationError" not in body["errors"][0]["message"]


def test_set_control_data_agent_scoped_agent_not_found(client: TestClient) -> None:
    # Given: a control
    control_id, _ = _create_control(client)

    # When: setting data with a missing agent in evaluator ref
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["evaluator"] = {"name": "missing-agent:custom", "config": {"pattern": "x"}}
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: not found
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"


def test_set_control_data_agent_scoped_evaluator_missing(client: TestClient) -> None:
    # Given: an agent without the referenced evaluator
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name, "agent_name": agent_name},
            "steps": [],
            "evaluators": [],
        },
    )
    assert resp.status_code == 200

    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["evaluator"] = {"name": f"{agent_name}:missing", "config": {"pattern": "x"}}

    # When: setting data with evaluator not registered on agent
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: validation error
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "EVALUATOR_NOT_FOUND"
    assert any(err.get("field") == "data.evaluator.name" for err in body.get("errors", []))


def test_set_control_data_agent_scoped_invalid_schema(client: TestClient) -> None:
    # Given: an agent with evaluator schema requiring "pattern"
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name, "agent_name": agent_name},
            "steps": [],
            "evaluators": [
                {
                    "name": "custom",
                    "description": "custom",
                    "config_schema": {
                        "type": "object",
                        "properties": {"pattern": {"type": "string"}},
                        "required": ["pattern"],
                    },
                }
            ],
        },
    )
    assert resp.status_code == 200

    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["evaluator"] = {"name": f"{agent_name}:custom", "config": {}}

    # When: setting data with config missing required fields
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: invalid config error
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "INVALID_CONFIG"
    assert any(err.get("field") == "data.evaluator.config" for err in body.get("errors", []))


def test_patch_control_updates_name_and_enabled(client: TestClient) -> None:
    # Given: a control with configured data
    control_id, _ = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    data["enabled"] = True
    _set_control_data(client, control_id, data)

    # When: updating name and enabled status
    new_name = f"control-{uuid.uuid4()}"
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": new_name, "enabled": False},
    )

    # Then: patch succeeds with updated fields
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == new_name
    assert body["enabled"] is False

    # And: stored data reflects enabled=false
    get_resp = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["enabled"] is False


def test_patch_control_not_found_returns_404(client: TestClient) -> None:
    # Given: a non-existent control id
    missing_id = 999999

    # When: patching the control
    resp = client.patch(f"/api/v1/controls/{missing_id}", json={"enabled": True})

    # Then: not found error is returned
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_delete_control_not_found_returns_404(client: TestClient) -> None:
    # Given: a non-existent control id
    missing_id = 999999

    # When: deleting the control
    resp = client.delete(f"/api/v1/controls/{missing_id}")

    # Then: not found error is returned
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_set_control_data_agent_scoped_corrupted_agent_data_returns_422(
    client: TestClient,
) -> None:
    # Given: an agent whose stored data is corrupted
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name, "agent_name": agent_name},
            "steps": [],
            "evaluators": [{"name": "custom", "config_schema": {"type": "object"}}],
        },
    )
    assert resp.status_code == 200

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE agents SET data = CAST(:data AS JSONB) WHERE name = :id"),
            {"data": json.dumps({"bad": "data"}), "id": agent_name},
        )

    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["evaluator"] = {"name": f"{agent_name}:custom", "config": {}}

    # When: setting control data referencing the corrupted agent's evaluator
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: corrupted agent data error is returned
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "CORRUPTED_DATA"


def test_set_control_data_unknown_evaluator_allowed(client: TestClient) -> None:
    # Given: a control with a non-registered evaluator name
    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["evaluator"] = {"name": "unknown-eval", "config": {}}

    # When: setting the control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: update succeeds (unknown evaluators are allowed)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_set_control_data_builtin_evaluator_validation_error(
    client: TestClient, monkeypatch
) -> None:
    # Given: a control and a server-side evaluator that enforces a schema
    control_id, _ = _create_control(client)

    class DummyEvaluator:
        config_model = RegexEvaluatorConfig

    monkeypatch.setattr(
        controls_module,
        "list_evaluators",
        lambda: {"dummy": DummyEvaluator},
    )

    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["evaluator"] = {"name": "dummy", "config": {}}

    # When: setting control data with invalid config
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: invalid config error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "INVALID_CONFIG"
    assert any("data.evaluator.config" in err.get("field", "") for err in body.get("errors", []))


def test_set_control_data_builtin_evaluator_invalid_parameters(
    client: TestClient, monkeypatch
) -> None:
    # Given: a control and a server-side evaluator that raises TypeError
    control_id, _ = _create_control(client)

    class DummyEvaluator:
        @staticmethod
        def config_model(**_kwargs):  # type: ignore[no-untyped-def]
            raise TypeError("unexpected parameter")

    monkeypatch.setattr(
        controls_module,
        "list_evaluators",
        lambda: {"dummy": DummyEvaluator},
    )

    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["evaluator"] = {"name": "dummy", "config": {"unexpected": "value"}}

    # When: setting control data with invalid parameters
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: invalid parameters error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "INVALID_CONFIG"
    assert any(err.get("code") == "invalid_parameters" for err in body.get("errors", []))
    assert any(
        err.get("message") == "Invalid config parameters for evaluator."
        for err in body.get("errors", [])
    )
    assert "unexpected parameter" not in resp.text


@pytest.mark.asyncio
async def test_set_control_data_selector_without_model_dump_uses_original_serialization(
    async_db,
) -> None:
    # Given: a control and a request whose selector cannot be re-dumped
    control = Control(name=f"control-{uuid.uuid4()}", data=None)
    async_db.add(control)
    await async_db.flush()

    payload = deepcopy(VALID_CONTROL_PAYLOAD)

    class DummyData:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = data
            self.selector = data["selector"]
            self.evaluator = SimpleNamespace(
                name=data["evaluator"]["name"],
                config=data["evaluator"]["config"],
            )

        def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
            return self._data

    request = SimpleNamespace(data=DummyData(payload))

    # When: updating the control data with a non-Pydantic selector
    response = await controls_module.set_control_data(control.id, request, async_db)

    # Then: the update succeeds and uses the original selector serialization
    assert response.success is True
    await async_db.refresh(control)
    assert control.data["selector"] == payload["selector"]


def test_patch_control_rename_preserves_enabled(client: TestClient) -> None:
    # Given: a control with enabled=false in its data
    control_id, control_name = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    data["enabled"] = False
    _set_control_data(client, control_id, data)

    # When: renaming the control without providing enabled
    new_name = f"{control_name}-renamed"
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"name": new_name})

    # Then: response preserves enabled status
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == new_name
    assert body["enabled"] is False


def test_patch_control_enabled_preserves_extra_fields(client: TestClient) -> None:
    # Given: a control with extra metadata in stored data
    control_id, _ = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    _set_control_data(client, control_id, data)

    data_with_extra = deepcopy(data)
    data_with_extra["custom_meta"] = {"source": "unit-test"}
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(data_with_extra), "id": control_id},
        )

    # When: toggling enabled via PATCH
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": False})

    # Then: enabled is updated and extra fields are preserved
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    with Session(engine) as session:
        control = session.query(Control).filter(Control.id == control_id).first()
        assert control is not None
        assert control.data.get("custom_meta") == {"source": "unit-test"}


def test_patch_control_rename_with_corrupted_data_returns_enabled_none(
    client: TestClient,
) -> None:
    # Given: a control with corrupted data in DB
    control_id, control_name = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: renaming the control without enabled
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": f"{control_name}-renamed"},
    )

    # Then: rename succeeds and enabled is omitted (None)
    assert resp.status_code == 200
    assert resp.json()["enabled"] is None
