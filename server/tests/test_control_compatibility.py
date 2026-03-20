"""Compatibility coverage for legacy flat control payloads."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import text

from .conftest import engine
from .utils import VALID_CONTROL_PAYLOAD


def _init_agent(client: TestClient, *, agent_name: str | None = None) -> str:
    name = (agent_name or f"agent-{uuid.uuid4().hex[:12]}").lower()
    if len(name) < 10:
        name = f"{name}-agent".replace("--", "-")
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {
                "agent_name": name,
                "agent_description": "desc",
                "agent_version": "1.0",
            },
            "steps": [],
            "evaluators": [],
        },
    )
    assert resp.status_code == 200
    return name


def _create_policy(client: TestClient) -> int:
    resp = client.put("/api/v1/policies", json={"name": f"policy-{uuid.uuid4()}"})
    assert resp.status_code == 200
    return resp.json()["policy_id"]


def _legacy_control_payload() -> dict[str, object]:
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["selector"] = payload["condition"]["selector"]
    payload["evaluator"] = payload["condition"]["evaluator"]
    payload.pop("condition")
    return payload


def test_set_agent_policy_accepts_legacy_stored_control_payload(client: TestClient) -> None:
    # Given: an assigned policy whose stored control row has been reverted to the legacy flat shape
    agent_name = _init_agent(client)
    policy_id = _create_policy(client)

    control_resp = client.put(
        "/api/v1/controls",
        json={"name": f"control-{uuid.uuid4()}", "data": VALID_CONTROL_PAYLOAD},
    )
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    assoc = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc.status_code == 200

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(_legacy_control_payload()), "id": control_id},
        )

    # When: assigning the policy to the agent
    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    # Then: assignment succeeds because the legacy payload is canonicalized on read
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_get_control_data_returns_canonical_shape_for_legacy_stored_payload(
    client: TestClient,
) -> None:
    # Given: a control whose stored row has been reverted to the legacy flat shape
    control_resp = client.put(
        "/api/v1/controls",
        json={"name": f"control-{uuid.uuid4()}", "data": VALID_CONTROL_PAYLOAD},
    )
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(_legacy_control_payload()), "id": control_id},
        )

    # When: fetching control data through the typed API endpoint
    resp = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: the response is accepted and serialized back in canonical condition form
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "selector" not in data
    assert "evaluator" not in data
    assert data["condition"]["selector"]["path"] == "input"
    assert data["condition"]["evaluator"]["name"] == "regex"


def test_list_agent_controls_returns_canonical_shape_for_legacy_stored_payload(
    client: TestClient,
) -> None:
    # Given: an agent assigned a policy whose control row is stored in legacy flat shape
    agent_name = _init_agent(client)
    policy_id = _create_policy(client)

    control_resp = client.put(
        "/api/v1/controls",
        json={"name": f"control-{uuid.uuid4()}", "data": VALID_CONTROL_PAYLOAD},
    )
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    assoc = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc.status_code == 200
    assign = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    assert assign.status_code == 200

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(_legacy_control_payload()), "id": control_id},
        )

    # When: listing active controls for the agent
    resp = client.get(f"/api/v1/agents/{agent_name}/controls")

    # Then: the control is returned and serialized in canonical condition form
    assert resp.status_code == 200
    controls = resp.json()["controls"]
    assert len(controls) == 1
    control = controls[0]["control"]
    assert "selector" not in control
    assert "evaluator" not in control
    assert control["condition"]["selector"]["path"] == "input"
    assert control["condition"]["evaluator"]["name"] == "regex"


def test_get_control_data_rejects_partial_legacy_stored_payload(
    client: TestClient,
) -> None:
    # Given: a stored control row with only one half of the legacy flat shape
    control_resp = client.put(
        "/api/v1/controls",
        json={"name": f"control-{uuid.uuid4()}", "data": VALID_CONTROL_PAYLOAD},
    )
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    invalid_payload = _legacy_control_payload()
    invalid_payload.pop("evaluator")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(invalid_payload), "id": control_id},
        )

    # When: fetching control data through the typed API endpoint
    resp = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: the API reports structured corrupted-data validation instead of silently accepting it
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "CORRUPTED_DATA"
    assert any(
        "Legacy control definition must include both selector and evaluator."
        in error.get("message", "")
        for error in body.get("errors", [])
    )
