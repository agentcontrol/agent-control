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


def _raw_control_payload(pattern: str = "raw") -> dict[str, object]:
    return {
        "description": "Raw control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "condition": {
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": pattern},
            },
        },
        "action": {"decision": "deny"},
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


def _create_raw_control(client: TestClient) -> int:
    response = client.put(
        "/api/v1/controls",
        json={
            "name": f"raw-control-{uuid.uuid4()}",
            "data": _raw_control_payload(),
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


def test_raw_control_can_be_replaced_with_template_backed_control(client: TestClient) -> None:
    control_id = _create_raw_control(client)

    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": _template_payload()},
    )
    assert put_response.status_code == 200, put_response.text

    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]
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
    assert response.json()["error_code"] == "CONTROL_TEMPLATE_CONFLICT"


def test_list_controls_includes_template_backed_flag_and_filter(client: TestClient) -> None:
    control_id = _create_template_control(client)

    response = client.get("/api/v1/controls", params={"template_backed": True})
    assert response.status_code == 200, response.text
    controls = response.json()["controls"]
    template_control = next(control for control in controls if control["id"] == control_id)
    assert template_control["template_backed"] is True


def test_list_controls_template_backed_false_returns_only_raw_controls(client: TestClient) -> None:
    template_control_id = _create_template_control(client)
    raw_control_id = _create_raw_control(client)

    response = client.get("/api/v1/controls", params={"template_backed": False})
    assert response.status_code == 200, response.text
    control_ids = {control["id"] for control in response.json()["controls"]}
    assert raw_control_id in control_ids
    assert template_control_id not in control_ids


def test_render_control_template_rejects_extra_request_fields(client: TestClient) -> None:
    payload = _template_payload()
    payload["execution"] = "server"

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_render_control_template_maps_invalid_regex_parameter(client: TestClient) -> None:
    payload = _template_payload()
    payload["template_values"] = {"pattern": "["}

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("field") == "template_values.pattern"
        and err.get("parameter") == "pattern"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_malformed_param_binding(client: TestClient) -> None:
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["condition"]["evaluator"]["config"]["pattern"] = {  # type: ignore[index]
        "$param": "pattern",
        "extra": True,
    }

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(err.get("code") == "invalid_param_binding" for err in body.get("errors", []))


def test_render_control_template_rejects_non_string_param_reference(client: TestClient) -> None:
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["condition"]["evaluator"]["config"]["pattern"] = {  # type: ignore[index]
        "$param": 123,
    }

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(err.get("code") == "invalid_param_binding" for err in body.get("errors", []))


def test_render_control_template_rejects_agent_scoped_evaluator(client: TestClient) -> None:
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["condition"]["evaluator"]["name"] = "agent-x:custom"  # type: ignore[index]

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "agent_scoped_evaluator_not_supported"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_legacy_flat_format(client: TestClient) -> None:
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"] = {  # type: ignore[index]
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": "regex",
            "config": {"pattern": {"$param": "pattern"}},
        },
        "action": {"decision": "deny"},
    }

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "legacy_condition_format_not_supported"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_invalid_parameter_name_at_api_boundary(
    client: TestClient,
) -> None:
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["parameters"] = {  # type: ignore[index]
        "bad.name": {
            "type": "string",
            "label": "Bad Name",
        }
    }

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"
