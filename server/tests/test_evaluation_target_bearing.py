"""End-to-end coverage for target-bearing evaluation requests.

These tests verify that supplying ``target_type`` and ``target_id`` on an
evaluation request resolves controls from the ``control_bindings`` table
instead of the agent-attached path. No ``agents`` row needs to exist for
the request to succeed.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from .utils import VALID_CONTROL_PAYLOAD, canonicalize_control_payload


def _create_control(client: TestClient) -> int:
    payload = canonicalize_control_payload(deepcopy(VALID_CONTROL_PAYLOAD))
    resp = client.put(
        "/api/v1/controls",
        json={"name": f"control-{uuid.uuid4().hex[:12]}", "data": payload},
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


def _create_binding(
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


def _evaluate(
    client: TestClient,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    input_text: str = "x marks the spot",
    agent_name: str = "mytestagent01",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "agent_name": agent_name,
        "step": {
            "type": "llm",
            "name": "test-step",
            "input": input_text,
            "context": {},
        },
        "stage": "pre",
    }
    if target_type is not None:
        body["target_type"] = target_type
    if target_id is not None:
        body["target_id"] = target_id
    resp = client.post("/api/v1/evaluation", json=body)
    return {"status": resp.status_code, "body": resp.json()}


def test_target_bearing_request_runs_bindings_path(client: TestClient) -> None:
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id)

    # No agent registered; the bindings path does not look it up.
    result = _evaluate(client, target_type="env", target_id="prod")
    assert result["status"] == 200
    body = result["body"]
    # The control denies on regex 'x' which appears in the default input.
    assert body["is_safe"] is False
    assert body["matches"] and body["matches"][0]["control_id"] == control_id


def test_target_bearing_request_with_no_matching_bindings_returns_safe(
    client: TestClient,
) -> None:
    # No binding exists for this target.
    result = _evaluate(client, target_type="env", target_id="dev")
    assert result["status"] == 200
    assert result["body"]["is_safe"] is True


def test_disabled_binding_excludes_control_at_runtime(
    client: TestClient,
) -> None:
    control_id = _create_control(client)
    _create_binding(client, control_id=control_id, enabled=False)

    # The binding is disabled; the control must not run.
    result = _evaluate(client, target_type="env", target_id="prod")
    assert result["status"] == 200
    assert result["body"]["is_safe"] is True


def test_partial_target_pair_rejected(client: TestClient) -> None:
    # Only target_type, no target_id - should fail validation at the model.
    body = {
        "agent_name": "mytestagent01",
        "step": {"type": "llm", "name": "s", "input": "hi"},
        "stage": "pre",
        "target_type": "env",
    }
    resp = client.post("/api/v1/evaluation", json=body)
    assert resp.status_code == 422
