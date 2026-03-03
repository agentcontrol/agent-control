"""Tests for initAgent conflict_mode behavior."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD


def _init_payload(
    *,
    agent_name: str,
    agent_description: str = "desc",
    agent_version: str = "1.0",
    steps: list[dict[str, Any]] | None = None,
    evaluators: list[dict[str, Any]] | None = None,
    conflict_mode: str | None = None,
) -> dict[str, Any]:
    canonical_name = agent_name.lower()
    payload: dict[str, Any] = {
        "agent": {
            "agent_name": canonical_name,
            "agent_description": agent_description,
            "agent_version": agent_version,
        },
        "steps": steps or [],
        "evaluators": evaluators or [],
    }
    if conflict_mode is not None:
        payload["conflict_mode"] = conflict_mode
    return payload


def _create_policy_with_agent_evaluator_control(
    client: TestClient,
    *,
    agent_name: str,
    evaluator_name: str,
) -> tuple[int, int, str]:
    control_name = f"control-{uuid.uuid4().hex[:8]}"
    create_control_resp = client.put("/api/v1/controls", json={"name": control_name})
    assert create_control_resp.status_code == 200
    control_id = create_control_resp.json()["control_id"]

    control_data = deepcopy(VALID_CONTROL_PAYLOAD)
    control_data["evaluator"] = {
        "name": f"{agent_name}:{evaluator_name}",
        "config": {},
    }
    set_data_resp = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": control_data},
    )
    assert set_data_resp.status_code == 200

    policy_name = f"policy-{uuid.uuid4().hex[:8]}"
    create_policy_resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert create_policy_resp.status_code == 200
    policy_id = create_policy_resp.json()["policy_id"]

    assoc_resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc_resp.status_code == 200

    return policy_id, control_id, control_name


def test_init_agent_overwrite_replaces_steps_and_evaluators(client: TestClient) -> None:
    # Given: an existing agent registration with baseline steps and evaluators.
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"

    create_payload = _init_payload(
        agent_name=agent_name,
        steps=[
            {
                "type": "tool",
                "name": "tool-a",
                "description": "v1",
                "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
                "output_schema": {"type": "array"},
            },
            {
                "type": "tool",
                "name": "tool-b",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "boolean"},
            },
        ],
        evaluators=[
            {"name": "eval-a", "description": "v1", "config_schema": {"type": "object"}},
            {"name": "eval-b", "description": "v1", "config_schema": {"type": "object"}},
        ],
    )
    create_resp = client.post("/api/v1/agents/initAgent", json=create_payload)
    assert create_resp.status_code == 200
    assert create_resp.json()["created"] is True

    # When: initAgent is called in overwrite mode with an updated registration payload.
    overwrite_payload = _init_payload(
        agent_name=agent_name,
        agent_description="updated desc",
        agent_version="2.0",
        steps=[
            {
                "type": "tool",
                "name": "tool-a",
                "description": "v2",
                "input_schema": {"type": "object", "properties": {"q": {"type": "number"}}},
                "output_schema": {"type": "array"},
            },
            {
                "type": "tool",
                "name": "tool-c",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "string"},
            },
        ],
        evaluators=[
            {"name": "eval-a", "description": "v2", "config_schema": {"type": "string"}},
            {"name": "eval-c", "description": "new", "config_schema": {"type": "object"}},
        ],
        conflict_mode="overwrite",
    )
    overwrite_resp = client.post("/api/v1/agents/initAgent", json=overwrite_payload)
    assert overwrite_resp.status_code == 200
    body = overwrite_resp.json()

    # Then: overwrite changes are reported and persisted state matches the new payload.
    assert body["created"] is False
    assert body["overwrite_applied"] is True

    changes = body["overwrite_changes"]
    assert changes["metadata_changed"] is True
    assert changes["steps_added"] == [{"type": "tool", "name": "tool-c"}]
    assert changes["steps_updated"] == [{"type": "tool", "name": "tool-a"}]
    assert changes["steps_removed"] == [{"type": "tool", "name": "tool-b"}]
    assert changes["evaluators_added"] == ["eval-c"]
    assert changes["evaluators_updated"] == ["eval-a"]
    assert changes["evaluators_removed"] == ["eval-b"]
    assert changes["evaluator_removals"] == [
        {
            "name": "eval-b",
            "referenced_by_active_controls": False,
            "control_ids": [],
            "control_names": [],
        }
    ]

    get_resp = client.get(f"/api/v1/agents/{agent_name}")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["agent"]["agent_description"] == "updated desc"
    assert {step["name"] for step in get_data["steps"]} == {"tool-a", "tool-c"}
    assert {evaluator["name"] for evaluator in get_data["evaluators"]} == {"eval-a", "eval-c"}


def test_init_agent_overwrite_warns_on_removed_referenced_evaluator(client: TestClient) -> None:
    # Given: an agent whose assigned policy contains a control referencing an agent evaluator.
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    evaluator_name = "custom-eval"

    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json=_init_payload(
            agent_name=agent_name,
            evaluators=[{"name": evaluator_name, "config_schema": {"type": "object"}}],
        ),
    )
    assert init_resp.status_code == 200

    policy_id, control_id, control_name = _create_policy_with_agent_evaluator_control(
        client, agent_name=agent_name, evaluator_name=evaluator_name
    )
    assign_resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    assert assign_resp.status_code == 200

    # When: overwrite mode removes the evaluator from the incoming registration payload.
    overwrite_resp = client.post(
        "/api/v1/agents/initAgent",
        json=_init_payload(
            agent_name=agent_name,
            evaluators=[],
            conflict_mode="overwrite",
        ),
    )
    assert overwrite_resp.status_code == 200
    body = overwrite_resp.json()

    # Then: the response includes active-control reference warnings and evaluator removal.
    assert body["overwrite_applied"] is True
    assert body["overwrite_changes"]["evaluators_removed"] == [evaluator_name]
    assert body["overwrite_changes"]["evaluator_removals"] == [
        {
            "name": evaluator_name,
            "referenced_by_active_controls": True,
            "control_ids": [control_id],
            "control_names": [control_name],
        }
    ]

    get_resp = client.get(f"/api/v1/agents/{agent_name}/evaluators")
    assert get_resp.status_code == 200
    assert get_resp.json()["evaluators"] == []


def test_init_agent_overwrite_noop_reports_not_applied(client: TestClient) -> None:
    # Given: an existing agent registration and an equivalent overwrite payload.
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    payload = _init_payload(
        agent_name=agent_name,
        steps=[{"type": "tool", "name": "tool-a", "input_schema": {}, "output_schema": {}}],
        evaluators=[{"name": "eval-a", "description": "x", "config_schema": {"type": "object"}}],
    )
    first_resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert first_resp.status_code == 200

    # When: initAgent is called in overwrite mode with no effective registration changes.
    second_payload = dict(payload)
    second_payload["conflict_mode"] = "overwrite"
    second_resp = client.post("/api/v1/agents/initAgent", json=second_payload)
    assert second_resp.status_code == 200

    # Then: overwrite is reported as a no-op and all change collections stay empty.
    body = second_resp.json()
    assert body["overwrite_applied"] is False
    assert body["overwrite_changes"] == {
        "metadata_changed": False,
        "steps_added": [],
        "steps_updated": [],
        "steps_removed": [],
        "evaluators_added": [],
        "evaluators_updated": [],
        "evaluators_removed": [],
        "evaluator_removals": [],
    }
