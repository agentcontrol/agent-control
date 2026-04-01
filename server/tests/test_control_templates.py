"""Tests for template-backed control API flows."""

from __future__ import annotations

import uuid
from copy import deepcopy

from agent_control_models import EvaluationRequest, Step
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


def _defaults_only_template_payload() -> dict[str, object]:
    return {
        "template": {
            "description": "List evaluator template",
            "parameters": {
                "values": {
                    "type": "string_list",
                    "label": "Values",
                    "default": ["secret", "blocked"],
                },
                "logic": {
                    "type": "enum",
                    "label": "Logic",
                    "allowed_values": ["any", "all"],
                    "default": "any",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "label": "Case Sensitive",
                    "default": False,
                },
            },
            "definition_template": {
                "description": "Defaulted list control",
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {
                        "name": "list",
                        "config": {
                            "values": {"$param": "values"},
                            "logic": {"$param": "logic"},
                            "case_sensitive": {"$param": "case_sensitive"},
                        },
                    },
                },
                "action": {"decision": "deny"},
            },
        }
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
    control_id, _ = _create_template_control_with_name(client)
    return control_id


def _create_template_control_with_name(client: TestClient) -> tuple[int, str]:
    control_name = f"template-control-{uuid.uuid4()}"
    response = client.put(
        "/api/v1/controls",
        json={
            "name": control_name,
            "data": _template_payload(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["control_id"], control_name


def _assign_control_to_agent(
    client: TestClient,
    control_id: int,
    *,
    agent_name: str | None = None,
) -> str:
    policy_response = client.put("/api/v1/policies", json={"name": f"policy-{uuid.uuid4()}"})
    assert policy_response.status_code == 200, policy_response.text
    policy_id = policy_response.json()["policy_id"]

    add_control_response = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert add_control_response.status_code == 200, add_control_response.text

    effective_agent_name = agent_name or f"template-agent-{uuid.uuid4().hex[:12]}"
    init_response = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": effective_agent_name}, "steps": []},
    )
    assert init_response.status_code == 200, init_response.text

    assign_response = client.post(f"/api/v1/agents/{effective_agent_name}/policy/{policy_id}")
    assert assign_response.status_code == 200, assign_response.text
    return effective_agent_name


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


def test_render_control_template_preview_uses_defaults_when_values_omitted(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/control-templates/render", json=_defaults_only_template_payload())

    assert response.status_code == 200, response.text
    control = response.json()["control"]
    assert control["template_values"] == {
        "values": ["secret", "blocked"],
        "logic": "any",
        "case_sensitive": False,
    }
    assert control["condition"]["evaluator"]["name"] == "list"
    assert control["condition"]["evaluator"]["config"] == {
        "values": ["secret", "blocked"],
        "logic": "any",
        "case_sensitive": False,
    }


def test_create_template_backed_control_persists_template_metadata(client: TestClient) -> None:
    control_id = _create_template_control(client)

    response = client.get(f"/api/v1/controls/{control_id}/data")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["template"]["description"] == "Regex denial template"
    assert data["template_values"] == {
        "pattern": "hello",
        "step_name": "templated-step",
    }
    assert data["condition"]["evaluator"]["config"]["pattern"] == "hello"


def test_template_backed_control_evaluates_after_policy_attachment(client: TestClient) -> None:
    control_id, control_name = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, control_id)

    safe_request = EvaluationRequest(
        agent_name=agent_name,
        step=Step(type="llm", name="other-step", input="hello", output=None),
        stage="pre",
    )
    safe_response = client.post("/api/v1/evaluation", json=safe_request.model_dump(mode="json"))
    assert safe_response.status_code == 200, safe_response.text
    assert safe_response.json()["is_safe"] is True

    deny_request = EvaluationRequest(
        agent_name=agent_name,
        step=Step(type="llm", name="templated-step", input="hello", output=None),
        stage="pre",
    )
    deny_response = client.post("/api/v1/evaluation", json=deny_request.model_dump(mode="json"))
    assert deny_response.status_code == 200, deny_response.text
    body = deny_response.json()
    assert body["is_safe"] is False
    assert body["matches"][0]["control_name"] == control_name


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


def test_render_control_template_rejects_unknown_template_value_key(client: TestClient) -> None:
    payload = _template_payload()
    payload["template_values"] = {"pattern": "hello", "unknown": "value"}

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("field") == "template_values.unknown"
        and err.get("code") == "unknown_parameter"
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


def test_render_control_template_rejects_unused_parameter(client: TestClient) -> None:
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["parameters"]["unused"] = {  # type: ignore[index]
        "type": "string",
        "label": "Unused",
        "default": "still-unused",
    }

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("field") == "template.parameters.unused"
        and err.get("code") == "unused_template_parameter"
        for err in body.get("errors", [])
    )


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


def test_render_control_template_rejects_forbidden_top_level_template_fields(
    client: TestClient,
) -> None:
    for forbidden_field, value in (("enabled", True), ("name", "templated-name")):
        payload = _template_payload()
        payload["template"] = deepcopy(payload["template"])
        payload["template"]["definition_template"][forbidden_field] = value  # type: ignore[index]

        response = client.post("/api/v1/control-templates/render", json=payload)

        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
        assert any(
            err.get("field") == forbidden_field and err.get("code") == "forbidden_template_field"
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


def test_render_control_template_keeps_non_parameterized_errors_on_rendered_fields(
    client: TestClient,
) -> None:
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["action"]["decision"] = "block"  # type: ignore[index]

    response = client.post("/api/v1/control-templates/render", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("field") == "action.decision"
        and err.get("rendered_field") == "action.decision"
        for err in body.get("errors", [])
    )
