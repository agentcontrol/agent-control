"""Tests for template-backed control API flows."""

from __future__ import annotations

import uuid
from copy import deepcopy

from fastapi.testclient import TestClient


def _template_payload() -> dict[str, object]:
    return {
        "template": {
            "description": "Regex denial template",
            "parameters": {
                "pattern": {
                    "type": "regex_re2",
                    "label": "Pattern",
                },
                "step_name": {
                    "type": "string",
                    "label": "Step Name",
                    "required": False,
                    "default": "templated-step",
                },
            },
            "definition_template": {
                "description": "Template-backed control",
                "execution": "server",
                "scope": {
                    "step_names": [{"$param": "step_name"}],
                    "stages": ["pre"],
                },
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
        "template_values": {"pattern": "hello"},
    }


def _create_template_control(client: TestClient) -> int:
    response = client.put(
        "/api/v1/controls",
        json={
            "name": f"template-control-{uuid.uuid4()}",
            "data": _template_payload(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["control_id"]


def test_render_control_template_preview_returns_rendered_control(client: TestClient) -> None:
    response = client.post("/api/v1/control-templates/render", json=_template_payload())

    assert response.status_code == 200, response.text
    control = response.json()["control"]
    assert control["enabled"] is True
    assert control["template"]["description"] == "Regex denial template"
    assert control["template_values"] == {
        "pattern": "hello",
        "step_name": "templated-step",
    }
    assert control["condition"]["evaluator"]["config"]["pattern"] == "hello"
    assert control["scope"]["step_names"] == ["templated-step"]


def test_create_template_backed_control_persists_template_metadata(client: TestClient) -> None:
    control_id = _create_template_control(client)

    response = client.get(f"/api/v1/controls/{control_id}/data")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["template"]["description"] == "Regex denial template"
    assert data["template_values"]["pattern"] == "hello"
    assert data["condition"]["evaluator"]["config"]["pattern"] == "hello"


def test_template_update_preserves_enabled_value(client: TestClient) -> None:
    control_id = _create_template_control(client)

    patch_response = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"enabled": False},
    )
    assert patch_response.status_code == 200, patch_response.text

    updated_payload = _template_payload()
    updated_payload["template_values"] = {
        "pattern": "updated",
        "step_name": "updated-step",
    }
    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": updated_payload},
    )
    assert put_response.status_code == 200, put_response.text

    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]
    assert data["enabled"] is False
    assert data["template_values"] == {
        "pattern": "updated",
        "step_name": "updated-step",
    }
    assert data["condition"]["evaluator"]["config"]["pattern"] == "updated"
    assert data["scope"]["step_names"] == ["updated-step"]


def test_template_validate_maps_missing_parameter_error(client: TestClient) -> None:
    payload = _template_payload()
    payload["template_values"] = {}

    response = client.post("/api/v1/controls/validate", json={"data": payload})

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("field") == "template_values.pattern"
        and err.get("parameter") == "pattern"
        for err in body.get("errors", [])
    )


def test_template_backed_control_rejects_raw_put_update(client: TestClient) -> None:
    control_id = _create_template_control(client)
    raw_payload = deepcopy(
        {
            "description": "Raw replacement",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {
                    "name": "regex",
                    "config": {"pattern": "raw"},
                },
            },
            "action": {"decision": "deny"},
        }
    )

    response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": raw_payload},
    )

    assert response.status_code == 409


def test_list_controls_includes_template_backed_flag_and_filter(client: TestClient) -> None:
    control_id = _create_template_control(client)

    response = client.get("/api/v1/controls", params={"template_backed": True})
    assert response.status_code == 200, response.text
    controls = response.json()["controls"]
    template_control = next(control for control in controls if control["id"] == control_id)
    assert template_control["template_backed"] is True
