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


def test_set_agent_policy_accepts_legacy_stored_control_payload(client: TestClient) -> None:
    agent_name = _init_agent(client)
    policy_id = _create_policy(client)

    control_resp = client.put("/api/v1/controls", json={"name": f"control-{uuid.uuid4()}"})
    assert control_resp.status_code == 200
    control_id = control_resp.json()["control_id"]

    set_resp = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": VALID_CONTROL_PAYLOAD},
    )
    assert set_resp.status_code == 200

    assoc = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc.status_code == 200

    legacy_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    legacy_payload["selector"] = legacy_payload["condition"]["selector"]
    legacy_payload["evaluator"] = legacy_payload["condition"]["evaluator"]
    legacy_payload.pop("condition")

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(legacy_payload), "id": control_id},
        )

    resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

    assert resp.status_code == 200
    assert resp.json()["success"] is True
