"""Tests for template-backed control API flows."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy

from agent_control_models import EvaluationRequest, Step
from fastapi.testclient import TestClient
from sqlalchemy import text

from .conftest import engine


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


def _case_sensitive_template_payload(
    *,
    values: list[str] | None = None,
    case_sensitive: bool | None = None,
    action: str = "deny",
) -> dict[str, object]:
    template_values: dict[str, object] = {}
    if values is not None:
        template_values["values"] = values
    if case_sensitive is not None:
        template_values["case_sensitive"] = case_sensitive

    return {
        "template": {
            "description": "Case sensitivity template",
            "parameters": {
                "values": {
                    "type": "string_list",
                    "label": "Values",
                    "required": False,
                    "default": ["HELLO"],
                },
                "case_sensitive": {
                    "type": "boolean",
                    "label": "Case Sensitive",
                    "required": False,
                    "default": True,
                },
            },
            "definition_template": {
                "description": "Case sensitivity control",
                "execution": "server",
                "scope": {
                    "step_names": ["templated-step"],
                    "stages": ["pre"],
                },
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {
                        "name": "list",
                        "config": {
                            "values": {"$param": "values"},
                            "match_mode": "exact",
                            "case_sensitive": {"$param": "case_sensitive"},
                        },
                    },
                },
                "action": {"decision": action},
            },
        },
        "template_values": template_values,
    }


def _raw_control_payload(pattern: str = "raw", *, action: str = "deny") -> dict[str, object]:
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
        "action": {"decision": action},
    }


def _nested_template_value(depth: int) -> object:
    value: object = "leaf"
    for _ in range(depth):
        value = {"nested": value}
    return value


def _create_template_control(client: TestClient) -> int:
    control_id, _ = _create_template_control_with_name(client)
    return control_id


def _create_template_control_with_name(
    client: TestClient,
    payload: dict[str, object] | None = None,
    *,
    name_prefix: str = "template-control",
) -> tuple[int, str]:
    control_name = f"{name_prefix}-{uuid.uuid4()}"
    response = client.put(
        "/api/v1/controls",
        json={
            "name": control_name,
            "data": payload or _template_payload(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["control_id"], control_name


def _assign_control_to_agent(
    client: TestClient,
    control_id: int,
    *,
    agent_name: str | None = None,
    via_policy: bool = True,
) -> str:
    effective_agent_name = agent_name or f"template-agent-{uuid.uuid4().hex[:12]}"
    init_response = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": effective_agent_name}, "steps": []},
    )
    assert init_response.status_code == 200, init_response.text

    if via_policy:
        policy_response = client.put("/api/v1/policies", json={"name": f"policy-{uuid.uuid4()}"})
        assert policy_response.status_code == 200, policy_response.text
        policy_id = policy_response.json()["policy_id"]

        add_control_response = client.post(
            f"/api/v1/policies/{policy_id}/controls/{control_id}"
        )
        assert add_control_response.status_code == 200, add_control_response.text

        assign_response = client.post(
            f"/api/v1/agents/{effective_agent_name}/policy/{policy_id}"
        )
        assert assign_response.status_code == 200, assign_response.text
    else:
        assign_response = client.post(
            f"/api/v1/agents/{effective_agent_name}/controls/{control_id}"
        )
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


def _evaluate_step(
    client: TestClient,
    agent_name: str,
    *,
    step_name: str,
    input_value: str,
    step_type: str = "llm",
    stage: str = "pre",
):
    request = EvaluationRequest(
        agent_name=agent_name,
        step=Step(type=step_type, name=step_name, input=input_value, output=None),
        stage=stage,
    )
    return client.post("/api/v1/evaluation", json=request.model_dump(mode="json"))


def test_render_control_template_preview_returns_rendered_control(client: TestClient) -> None:
    # Given: a valid template-backed control payload
    # When: rendering a template preview through the public API
    response = client.post("/api/v1/control-templates/render", json=_template_payload())

    # Then: the rendered control includes resolved template metadata and values
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
    # Given: a template whose defaults fully satisfy all parameters
    # When: rendering a template preview without explicit template values
    response = client.post(
        "/api/v1/control-templates/render",
        json=_defaults_only_template_payload(),
    )

    # Then: the rendered control uses the parameter defaults
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


def test_render_control_template_preview_rejects_excessive_definition_nesting(
    client: TestClient,
) -> None:
    # Given: a template definition that exceeds the nesting limit
    payload = _template_payload()
    payload["template"]["definition_template"] = _nested_template_value(12)

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API rejects the request with a clear validation error
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"].startswith("Request validation failed")
    assert "definition_template nesting depth exceeds maximum" in body["errors"][0]["message"]


def test_render_control_template_preview_rejects_excessive_definition_size(
    client: TestClient,
) -> None:
    # Given: a template definition that exceeds the size limit
    payload = _template_payload()
    payload["template"]["definition_template"] = list(range(1001))

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API rejects the oversized template definition
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["detail"].startswith("Request validation failed")
    assert "definition_template size exceeds maximum" in body["errors"][0]["message"]


def test_create_template_backed_control_persists_template_metadata(client: TestClient) -> None:
    # Given: a valid template-backed control created through the API
    control_id = _create_template_control(client)

    # When: fetching the stored control data
    response = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: both template metadata and rendered values are persisted
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["template"]["description"] == "Regex denial template"
    assert data["template_values"] == {
        "pattern": "hello",
        "step_name": "templated-step",
    }
    assert data["condition"]["evaluator"]["config"]["pattern"] == "hello"
    assert data["scope"]["step_names"] == ["templated-step"]


def test_get_control_returns_template_metadata_for_template_backed_control(
    client: TestClient,
) -> None:
    # Given: a template-backed control created through the API
    control_id, control_name = _create_template_control_with_name(client)

    # When: fetching the full control resource
    response = client.get(f"/api/v1/controls/{control_id}")

    # Then: the response includes template metadata alongside normal control metadata
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == control_id
    assert body["name"] == control_name
    assert body["data"]["template"]["description"] == "Regex denial template"
    assert body["data"]["template_values"] == {
        "pattern": "hello",
        "step_name": "templated-step",
    }


def test_create_template_backed_control_persists_resolved_defaults_when_values_omitted(
    client: TestClient,
) -> None:
    # Given: a template-backed control created without explicit template values
    control_id, _ = _create_template_control_with_name(
        client,
        _defaults_only_template_payload(),
        name_prefix="defaulted-template-control",
    )

    # When: fetching the stored control data
    response = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: the persisted template values and rendered config include resolved defaults
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["template_values"] == {
        "values": ["secret", "blocked"],
        "logic": "any",
        "case_sensitive": False,
    }
    assert data["condition"]["evaluator"]["config"] == {
        "values": ["secret", "blocked"],
        "logic": "any",
        "case_sensitive": False,
    }


def test_create_template_backed_control_failure_does_not_persist_control(
    client: TestClient,
) -> None:
    # Given: an invalid template-backed create payload and the current control list
    invalid_payload = _template_payload()
    invalid_payload["template_values"] = {"pattern": "["}
    control_name = f"invalid-template-control-{uuid.uuid4()}"

    before_response = client.get("/api/v1/controls")
    assert before_response.status_code == 200, before_response.text
    before_controls = before_response.json()["controls"]
    before_ids = {control["id"] for control in before_controls}

    # When: creating the invalid template-backed control
    response = client.put(
        "/api/v1/controls",
        json={"name": control_name, "data": invalid_payload},
    )

    # Then: the request fails and no control is persisted
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "TEMPLATE_PARAMETER_INVALID"

    after_response = client.get("/api/v1/controls")
    assert after_response.status_code == 200, after_response.text
    after_controls = after_response.json()["controls"]
    after_ids = {control["id"] for control in after_controls}
    assert after_ids == before_ids
    assert all(control["name"] != control_name for control in after_controls)


def test_template_backed_control_evaluates_after_policy_attachment(client: TestClient) -> None:
    # Given: a template-backed control attached to an agent through a policy
    control_id, control_name = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, control_id)

    # When: evaluating a non-matching step and then a matching step
    safe_response = _evaluate_step(
        client,
        agent_name,
        step_name="other-step",
        input_value="hello",
    )
    assert safe_response.status_code == 200, safe_response.text
    assert safe_response.json()["is_safe"] is True

    deny_response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    # Then: only the matching step is denied by the attached template-backed control
    assert deny_response.status_code == 200, deny_response.text
    body = deny_response.json()
    assert body["is_safe"] is False
    assert body["matches"][0]["control_name"] == control_name


def test_template_backed_control_can_be_disabled_and_reenabled_in_evaluation(
    client: TestClient,
) -> None:
    # Given: an attached template-backed control
    control_id, control_name = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, control_id)

    # When: evaluating before disabling, after disabling, and after re-enabling the control
    initial_response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    assert initial_response.status_code == 200, initial_response.text
    assert initial_response.json()["is_safe"] is False

    disable_response = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": False})
    assert disable_response.status_code == 200, disable_response.text

    disabled_eval = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    assert disabled_eval.status_code == 200, disabled_eval.text
    assert disabled_eval.json()["is_safe"] is True

    enable_response = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": True})
    assert enable_response.status_code == 200, enable_response.text

    reenabled_eval = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    # Then: evaluation reflects the user-managed enabled state
    assert reenabled_eval.status_code == 200, reenabled_eval.text
    body = reenabled_eval.json()
    assert body["is_safe"] is False
    assert body["matches"][0]["control_name"] == control_name


def test_template_backed_control_rename_is_reflected_in_evaluation(client: TestClient) -> None:
    # Given: an attached template-backed control
    control_id, _ = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, control_id)
    renamed_control_name = f"renamed-template-control-{uuid.uuid4()}"

    # When: renaming the control and evaluating a matching step
    patch_response = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": renamed_control_name},
    )
    assert patch_response.status_code == 200, patch_response.text
    assert patch_response.json()["name"] == renamed_control_name

    eval_response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )

    # Then: the evaluation match reflects the updated control name
    assert eval_response.status_code == 200, eval_response.text
    body = eval_response.json()
    assert body["is_safe"] is False
    assert body["matches"][0]["control_name"] == renamed_control_name


def test_template_backed_control_patch_updates_name_and_enabled_together(
    client: TestClient,
) -> None:
    # Given: a template-backed control
    control_id, _ = _create_template_control_with_name(client)
    renamed_control_name = f"patched-template-control-{uuid.uuid4()}"

    # When: patching both user-managed metadata fields together
    patch_response = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": renamed_control_name, "enabled": False},
    )

    # Then: the metadata updates persist without losing template metadata
    assert patch_response.status_code == 200, patch_response.text
    body = patch_response.json()
    assert body["name"] == renamed_control_name
    assert body["enabled"] is False

    get_response = client.get(f"/api/v1/controls/{control_id}")
    assert get_response.status_code == 200, get_response.text
    get_body = get_response.json()
    assert get_body["name"] == renamed_control_name
    assert get_body["data"]["enabled"] is False
    assert get_body["data"]["template"]["description"] == "Regex denial template"
    assert get_body["data"]["template_values"] == {
        "pattern": "hello",
        "step_name": "templated-step",
    }


def test_template_backed_control_update_changes_scope_behavior(client: TestClient) -> None:
    # Given: an attached template-backed control
    control_id, control_name = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, control_id)

    # When: updating the template values to change the rendered scope
    initial_eval = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    assert initial_eval.status_code == 200, initial_eval.text
    assert initial_eval.json()["is_safe"] is False

    updated_payload = _template_payload()
    updated_payload["template_values"] = {
        "pattern": "hello",
        "step_name": "updated-step",
    }
    update_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": updated_payload},
    )
    assert update_response.status_code == 200, update_response.text

    old_scope_eval = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    assert old_scope_eval.status_code == 200, old_scope_eval.text
    assert old_scope_eval.json()["is_safe"] is True

    updated_scope_eval = _evaluate_step(
        client,
        agent_name,
        step_name="updated-step",
        input_value="hello",
    )
    # Then: the old scope stops matching and the new scope starts matching
    assert updated_scope_eval.status_code == 200, updated_scope_eval.text
    body = updated_scope_eval.json()
    assert body["is_safe"] is False
    assert body["matches"][0]["control_name"] == control_name


def test_template_backed_control_supports_direct_agent_attachment(client: TestClient) -> None:
    # Given: a template-backed control attached directly to an agent
    control_id, control_name = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, control_id, via_policy=False)

    # When: evaluating a matching step
    response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )

    # Then: the directly attached control participates in evaluation
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_safe"] is False
    assert body["matches"][0]["control_name"] == control_name


def test_template_backed_observe_control_evaluates_as_safe_with_observe_match(
    client: TestClient,
) -> None:
    # Given: a template-backed control whose rendered action is observe
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["action"]["decision"] = "observe"  # type: ignore[index]
    control_id, control_name = _create_template_control_with_name(
        client,
        payload,
        name_prefix="observe-template-control",
    )
    agent_name = _assign_control_to_agent(client, control_id)

    # When: evaluating a matching step
    response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )

    # Then: the evaluation remains safe and returns the canonical observe action
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_safe"] is True
    assert len(body["matches"]) == 1
    assert body["matches"][0]["control_name"] == control_name
    assert body["matches"][0]["action"] == "observe"


def test_template_backed_control_preserves_falsey_values_and_uses_them_in_behavior(
    client: TestClient,
) -> None:
    # Given: a template-backed control created with falsey template values
    payload = _case_sensitive_template_payload(values=[], case_sensitive=False)
    control_id, control_name = _create_template_control_with_name(
        client,
        payload,
        name_prefix="falsey-template-control",
    )
    agent_name = _assign_control_to_agent(client, control_id)

    # When: inspecting stored data, evaluating, then updating to non-empty values
    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]
    assert data["template_values"] == {
        "values": [],
        "case_sensitive": False,
    }

    non_applicable_eval = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    assert non_applicable_eval.status_code == 200, non_applicable_eval.text
    assert non_applicable_eval.json()["is_safe"] is True

    updated_payload = _case_sensitive_template_payload(
        values=["HELLO"],
        case_sensitive=False,
    )
    update_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": updated_payload},
    )
    assert update_response.status_code == 200, update_response.text

    deny_eval = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    # Then: falsey values persist and later updates change evaluation behavior
    assert deny_eval.status_code == 200, deny_eval.text
    body = deny_eval.json()
    assert body["is_safe"] is False
    assert body["matches"][0]["control_name"] == control_name


def test_mixed_raw_and_template_backed_controls_obey_deny_precedence(
    client: TestClient,
) -> None:
    # Given: an agent with both a template-backed deny control and a raw observe control
    template_control_id, template_control_name = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, template_control_id)

    policy_response = client.get(f"/api/v1/agents/{agent_name}/policy")
    assert policy_response.status_code == 200, policy_response.text
    policy_id = policy_response.json()["policy_id"]

    raw_observe_name = f"raw-observe-{uuid.uuid4()}"
    raw_observe_response = client.put(
        "/api/v1/controls",
        json={
            "name": raw_observe_name,
            "data": _raw_control_payload("hello", action="observe"),
        },
    )
    assert raw_observe_response.status_code == 200, raw_observe_response.text
    raw_observe_control_id = raw_observe_response.json()["control_id"]

    add_control_response = client.post(
        f"/api/v1/policies/{policy_id}/controls/{raw_observe_control_id}"
    )
    assert add_control_response.status_code == 200, add_control_response.text

    # When: evaluating a step that matches both controls
    response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )

    # Then: both matches are returned, advisory actions are canonicalized, and deny wins
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_safe"] is False
    assert len(body["matches"]) == 2
    names = {match["control_name"] for match in body["matches"]}
    actions = {match["action"] for match in body["matches"]}
    assert names == {template_control_name, raw_observe_name}
    assert actions == {"deny", "observe"}


def test_raw_control_can_be_replaced_with_template_backed_control(client: TestClient) -> None:
    # Given: an existing raw control
    control_id = _create_raw_control(client)

    # When: replacing its data with template-backed control input
    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": _template_payload()},
    )
    assert put_response.status_code == 200, put_response.text

    # Then: the stored control becomes template-backed and persists rendered values
    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]
    assert data["template"]["description"] == "Regex denial template"
    assert data["template_values"]["pattern"] == "hello"
    assert data["condition"]["evaluator"]["config"]["pattern"] == "hello"


def test_raw_control_failed_template_replacement_does_not_mutate_raw_control(
    client: TestClient,
) -> None:
    # Given: an existing raw control and invalid template-backed replacement input
    control_id = _create_raw_control(client)
    original_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert original_response.status_code == 200, original_response.text
    original_data = original_response.json()["data"]

    invalid_payload = _template_payload()
    invalid_payload["template_values"] = {"pattern": "["}

    # When: replacing the raw control with invalid template-backed input
    response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": invalid_payload},
    )

    # Then: the conversion fails and the raw control stays unchanged
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "TEMPLATE_PARAMETER_INVALID"

    refreshed_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert refreshed_response.status_code == 200, refreshed_response.text
    refreshed_data = refreshed_response.json()["data"]
    assert refreshed_data == original_data
    assert "template" not in refreshed_data
    assert "template_values" not in refreshed_data


def test_template_update_preserves_enabled_value(client: TestClient) -> None:
    # Given: a template-backed control that has been disabled through the metadata patch API
    control_id = _create_template_control(client)

    patch_response = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"enabled": False},
    )
    assert patch_response.status_code == 200, patch_response.text

    # When: updating the template-backed control data
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

    # Then: the stored enabled value is preserved across the template update
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


def test_template_update_failure_does_not_mutate_existing_template_backed_control(
    client: TestClient,
) -> None:
    # Given: an existing template-backed control and invalid updated template values
    control_id = _create_template_control(client)
    original_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert original_response.status_code == 200, original_response.text
    original_data = original_response.json()["data"]

    invalid_payload = _template_payload()
    invalid_payload["template_values"] = {"pattern": "["}

    # When: updating the stored template-backed control with invalid input
    response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": invalid_payload},
    )

    # Then: the update fails and the stored control remains unchanged
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "TEMPLATE_PARAMETER_INVALID"

    refreshed_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert refreshed_response.status_code == 200, refreshed_response.text
    assert refreshed_response.json()["data"] == original_data


def test_template_update_preview_matches_persisted_rendered_control(client: TestClient) -> None:
    # Given: an existing template-backed control and updated template values
    control_id = _create_template_control(client)
    updated_payload = _template_payload()
    updated_payload["template_values"] = {
        "pattern": "updated",
        "step_name": "updated-step",
    }

    # When: previewing the updated template render and then persisting the update
    preview_response = client.post("/api/v1/control-templates/render", json=updated_payload)
    assert preview_response.status_code == 200, preview_response.text
    preview_control = preview_response.json()["control"]

    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": updated_payload},
    )
    assert put_response.status_code == 200, put_response.text

    get_response = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: the persisted rendered control matches the preview output
    assert get_response.status_code == 200, get_response.text
    persisted_control = get_response.json()["data"]
    assert persisted_control == preview_control


def test_template_update_accepts_different_template_structure(client: TestClient) -> None:
    # Given: an attached template-backed control using the regex template shape
    control_id, _ = _create_template_control_with_name(client)
    agent_name = _assign_control_to_agent(client, control_id)

    # When: replacing its data with a different template structure
    old_behavior_response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    assert old_behavior_response.status_code == 200, old_behavior_response.text
    assert old_behavior_response.json()["is_safe"] is False

    replacement_payload = _defaults_only_template_payload()
    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": replacement_payload},
    )
    assert put_response.status_code == 200, put_response.text

    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]
    assert data["template"]["description"] == "List evaluator template"
    assert data["template_values"] == {
        "values": ["secret", "blocked"],
        "logic": "any",
        "case_sensitive": False,
    }
    assert data["condition"]["evaluator"]["name"] == "list"
    assert data["condition"]["evaluator"]["config"] == {
        "values": ["secret", "blocked"],
        "logic": "any",
        "case_sensitive": False,
    }
    assert data["scope"]["step_types"] == ["llm"]

    old_match_response = _evaluate_step(
        client,
        agent_name,
        step_name="templated-step",
        input_value="hello",
    )
    assert old_match_response.status_code == 200, old_match_response.text
    assert old_match_response.json()["is_safe"] is True

    new_match_response = _evaluate_step(
        client,
        agent_name,
        step_name="other-step",
        input_value="secret",
    )
    # Then: the stored template metadata and runtime behavior both follow the new template
    assert new_match_response.status_code == 200, new_match_response.text
    assert new_match_response.json()["is_safe"] is False


def test_template_update_defaults_enabled_to_true_when_stored_key_is_missing(
    client: TestClient,
) -> None:
    # Given: a stored template-backed control whose persisted JSON is missing enabled
    control_id = _create_template_control(client)
    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    stored_data = get_response.json()["data"]
    stored_data.pop("enabled", None)

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(stored_data), "id": control_id},
        )

    # When: updating the template-backed control data
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

    # Then: the update path preserves the default enabled=True behavior
    refreshed_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert refreshed_response.status_code == 200, refreshed_response.text
    data = refreshed_response.json()["data"]
    assert data["enabled"] is True
    assert data["template_values"] == {
        "pattern": "updated",
        "step_name": "updated-step",
    }


def test_template_validate_accepts_incomplete_values_as_unrendered(
    client: TestClient,
) -> None:
    # Given: a template payload with empty values (would be stored as unrendered)
    payload = _template_payload()
    payload["template_values"] = {}

    # When: validating the payload
    response = client.post("/api/v1/controls/validate", json={"data": payload})

    # Then: validation succeeds (mirrors create behavior for unrendered templates)
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True


def test_template_validate_rejects_structurally_invalid_unrendered(
    client: TestClient,
) -> None:
    # Given: a template with an undefined $param reference and empty values
    payload = _template_payload()
    payload["template_values"] = {}
    payload["template"]["definition_template"]["condition"]["evaluator"]["config"]["extra"] = {  # type: ignore[index]
        "$param": "nonexistent",
    }

    # When: validating the payload
    response = client.post("/api/v1/controls/validate", json={"data": payload})

    # Then: structural validation catches the error even without values
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"


def test_template_validate_succeeds_with_defaults_only_payload(client: TestClient) -> None:
    # Given: a template-backed control payload whose defaults satisfy every parameter
    # When: validating it through the public API
    response = client.post(
        "/api/v1/controls/validate",
        json={"data": _defaults_only_template_payload()},
    )

    # Then: validation succeeds without requiring explicit template values
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True


def test_render_control_template_rejects_unknown_template_value_key(client: TestClient) -> None:
    # Given: a template payload with an undeclared template value key
    payload = _template_payload()
    payload["template_values"] = {"pattern": "hello", "unknown": "value"}

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API rejects the unknown parameter key clearly
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("field") == "template_values.unknown"
        and err.get("code") == "unknown_parameter"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_undefined_param_reference(client: TestClient) -> None:
    # Given: a template definition that references an undeclared parameter
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["condition"]["evaluator"]["config"]["pattern"] = {  # type: ignore[index]
        "$param": "undefined_pattern",
    }

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API reports the undefined parameter reference on the rendered field
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "undefined_parameter_reference"
        and err.get("field") == "condition.evaluator.config.pattern"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_non_object_definition_template(
    client: TestClient,
) -> None:
    # Given: a template whose top-level definition_template is not an object
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"] = "not-an-object"  # type: ignore[index]

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API rejects the template with a clear top-level type error
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("field") == "template.definition_template"
        and err.get("code") == "invalid_definition_template_type"
        for err in body.get("errors", [])
    )


def test_template_backed_control_rejects_raw_put_update(client: TestClient) -> None:
    # Given: a template-backed control and a raw replacement payload
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

    # When: replacing template-backed data with raw control data
    response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": raw_payload},
    )

    # Then: the API rejects the conversion back to raw control data
    assert response.status_code == 409
    assert response.json()["error_code"] == "CONTROL_TEMPLATE_CONFLICT"


def test_create_control_rejects_mixed_raw_and_template_payload_at_api_boundary(
    client: TestClient,
) -> None:
    # Given: a create payload that mixes template-backed and rendered control fields
    payload = _template_payload()
    payload["execution"] = "server"

    # When: creating the control through the public API
    response = client.put(
        "/api/v1/controls",
        json={
            "name": f"mixed-template-control-{uuid.uuid4()}",
            "data": payload,
        },
    )

    # Then: the request is rejected with the mixed-payload validation message
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert any(
        "cannot mix template fields with rendered control fields" in err.get("message", "")
        for err in body.get("errors", [])
    )


def test_validate_control_rejects_mixed_raw_and_template_payload_at_api_boundary(
    client: TestClient,
) -> None:
    # Given: a validate payload that mixes template-backed and rendered control fields
    payload = _template_payload()
    payload["execution"] = "server"

    # When: validating the mixed payload through the public API
    response = client.post("/api/v1/controls/validate", json={"data": payload})

    # Then: the request is rejected with the mixed-payload validation message
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert any(
        "cannot mix template fields with rendered control fields" in err.get("message", "")
        for err in body.get("errors", [])
    )


def test_list_controls_includes_template_backed_flag_and_filter(client: TestClient) -> None:
    # Given: a template-backed control in the system
    control_id = _create_template_control(client)

    # When: listing controls with the template_backed=true filter
    response = client.get("/api/v1/controls", params={"template_backed": True})

    # Then: the matching summary row is marked as template-backed
    assert response.status_code == 200, response.text
    controls = response.json()["controls"]
    template_control = next(control for control in controls if control["id"] == control_id)
    assert template_control["template_backed"] is True


def test_list_controls_template_backed_false_returns_only_raw_controls(client: TestClient) -> None:
    # Given: one template-backed control and one raw control
    template_control_id = _create_template_control(client)
    raw_control_id = _create_raw_control(client)

    # When: listing controls with the template_backed=false filter
    response = client.get("/api/v1/controls", params={"template_backed": False})

    # Then: only raw controls are returned
    assert response.status_code == 200, response.text
    control_ids = {control["id"] for control in response.json()["controls"]}
    assert raw_control_id in control_ids
    assert template_control_id not in control_ids


def test_render_control_template_rejects_extra_request_fields(client: TestClient) -> None:
    # Given: a render request payload with extra top-level fields
    payload = _template_payload()
    payload["execution"] = "server"

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: request validation rejects the extra fields
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_render_control_template_maps_invalid_regex_parameter(client: TestClient) -> None:
    # Given: a template payload with an invalid regex parameter value
    payload = _template_payload()
    payload["template_values"] = {"pattern": "["}

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the regex validation error is remapped back to the template parameter
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("field") == "template_values.pattern"
        and err.get("parameter") == "pattern"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_optional_referenced_parameter_without_default(
    client: TestClient,
) -> None:
    # Given: an optional parameter that is referenced in the template without a default
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["parameters"]["step_name"] = {  # type: ignore[index]
        "type": "string",
        "label": "Step Name",
        "required": False,
    }

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API reports that referenced optional parameters require defaults
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("field") == "template.parameters.step_name"
        and err.get("code") == "optional_referenced_parameter_requires_default"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_malformed_param_binding(client: TestClient) -> None:
    # Given: a malformed $param binding object with extra keys
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["condition"]["evaluator"]["config"]["pattern"] = {  # type: ignore[index]
        "$param": "pattern",
        "extra": True,
    }

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the invalid binding is rejected as a template render error
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(err.get("code") == "invalid_param_binding" for err in body.get("errors", []))


def test_render_control_template_rejects_non_string_param_reference(client: TestClient) -> None:
    # Given: a malformed $param binding whose reference is not a string
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["condition"]["evaluator"]["config"]["pattern"] = {  # type: ignore[index]
        "$param": 123,
    }

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the invalid binding is rejected as a template render error
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(err.get("code") == "invalid_param_binding" for err in body.get("errors", []))


def test_render_control_template_rejects_unused_parameter(client: TestClient) -> None:
    # Given: a template definition that declares an unused parameter
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["parameters"]["unused"] = {  # type: ignore[index]
        "type": "string",
        "label": "Unused",
        "default": "still-unused",
    }

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the unused parameter is reported on the template definition
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("field") == "template.parameters.unused"
        and err.get("code") == "unused_template_parameter"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_agent_scoped_evaluator(client: TestClient) -> None:
    # Given: a template definition that uses an agent-scoped evaluator directly
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["condition"]["evaluator"]["name"] = "agent-x:custom"  # type: ignore[index]

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API rejects agent-scoped evaluators for template-backed controls
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "agent_scoped_evaluator_not_supported"
        for err in body.get("errors", [])
    )


def test_render_control_template_remaps_param_bound_agent_scoped_evaluator_error(
    client: TestClient,
) -> None:
    # Given: a template whose evaluator name comes from a bound parameter
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["parameters"]["evaluator_name"] = {  # type: ignore[index]
        "type": "string",
        "label": "Evaluator Name",
    }
    payload["template"]["definition_template"]["condition"]["evaluator"]["name"] = {  # type: ignore[index]
        "$param": "evaluator_name",
    }
    payload["template_values"]["evaluator_name"] = "agent-x:custom"  # type: ignore[index]

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the agent-scoped evaluator error is remapped to the bound parameter
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("field") == "template_values.evaluator_name"
        and err.get("parameter") == "evaluator_name"
        and err.get("rendered_field") == "condition.evaluator.name"
        and err.get("code") == "template_parameter_invalid"
        for err in body.get("errors", [])
    )


def test_render_control_template_rejects_forbidden_top_level_template_fields(
    client: TestClient,
) -> None:
    # Given: templates that try to manage forbidden top-level control fields
    for forbidden_field, value in (("enabled", True), ("name", "templated-name")):
        payload = _template_payload()
        payload["template"] = deepcopy(payload["template"])
        payload["template"]["definition_template"][forbidden_field] = value  # type: ignore[index]

        # When: rendering a template preview
        response = client.post("/api/v1/control-templates/render", json=payload)

        # Then: the forbidden field is rejected clearly
        assert response.status_code == 422
        body = response.json()
        assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
        assert any(
            err.get("field") == forbidden_field and err.get("code") == "forbidden_template_field"
            for err in body.get("errors", [])
        )


def test_render_control_template_rejects_legacy_flat_format(client: TestClient) -> None:
    # Given: a template that uses the legacy flat selector/evaluator format
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

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the API requires the canonical condition wrapper
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
    # Given: a render request with an invalid template parameter name
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["parameters"] = {  # type: ignore[index]
        "bad.name": {
            "type": "string",
            "label": "Bad Name",
        }
    }

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: request validation rejects the invalid parameter name
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_render_control_template_keeps_non_parameterized_errors_on_rendered_fields(
    client: TestClient,
) -> None:
    # Given: a template whose rendered action is invalid independently of any parameter
    payload = _template_payload()
    payload["template"] = deepcopy(payload["template"])
    payload["template"]["definition_template"]["action"]["decision"] = "block"  # type: ignore[index]

    # When: rendering a template preview
    response = client.post("/api/v1/control-templates/render", json=payload)

    # Then: the error remains attached to the rendered field path
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("field") == "action.decision"
        and err.get("rendered_field") == "action.decision"
        for err in body.get("errors", [])
    )


# =============================================================================
# Unrendered template control flows
# =============================================================================


def _unrendered_template_payload() -> dict[str, object]:
    """Template payload with no template_values — creates an unrendered control."""
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


def _create_unrendered_control(client: TestClient) -> tuple[int, str]:
    control_name = f"unrendered-control-{uuid.uuid4()}"
    response = client.put(
        "/api/v1/controls",
        json={"name": control_name, "data": _unrendered_template_payload()},
    )
    assert response.status_code == 200, response.text
    return response.json()["control_id"], control_name


def test_create_unrendered_template_control_without_values(client: TestClient) -> None:
    # Given: a template payload with no template_values

    # When: creating a control
    control_id, _ = _create_unrendered_control(client)

    # Then: the control is created and stored as unrendered
    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]
    assert data["template"]["description"] == "Regex denial template"
    assert data["template_values"] == {}
    assert data["enabled"] is False

    # And: the stored data has no rendered fields
    assert "condition" not in data
    assert "action" not in data
    assert "execution" not in data


def test_get_control_returns_unrendered_template_metadata(client: TestClient) -> None:
    # Given: an unrendered template control
    control_id, control_name = _create_unrendered_control(client)

    # When: getting the control by ID
    response = client.get(f"/api/v1/controls/{control_id}")

    # Then: the response includes template metadata but no rendered fields
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == control_name
    assert body["data"]["template"]["parameters"]["pattern"]["type"] == "regex_re2"
    assert body["data"]["enabled"] is False
    assert "condition" not in body["data"]


def test_update_unrendered_template_with_complete_values_renders(client: TestClient) -> None:
    # Given: an unrendered template control
    control_id, _ = _create_unrendered_control(client)

    # When: updating with complete template values
    rendered_payload = _template_payload()
    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": rendered_payload},
    )

    # Then: the control is now rendered
    assert put_response.status_code == 200, put_response.text
    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()["data"]
    assert data["condition"]["evaluator"]["config"]["pattern"] == "hello"
    assert data["template_values"]["pattern"] == "hello"
    # And: enabled remains false (preserved from unrendered state)
    assert data["enabled"] is False


def test_update_unrendered_template_with_still_incomplete_values_stays_unrendered(
    client: TestClient,
) -> None:
    # Given: an unrendered template control
    control_id, _ = _create_unrendered_control(client)

    # When: updating with still-empty values
    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": _unrendered_template_payload()},
    )

    # Then: the control stays unrendered
    assert put_response.status_code == 200, put_response.text
    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    data = get_response.json()["data"]
    assert data["enabled"] is False
    assert "condition" not in data


def test_patch_enable_on_unrendered_template_is_rejected(client: TestClient) -> None:
    # Given: an unrendered template control
    control_id, _ = _create_unrendered_control(client)

    # When: trying to enable it
    response = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"enabled": True},
    )

    # Then: the server rejects with 422
    assert response.status_code == 422
    body = response.json()
    assert any(
        err.get("code") == "unrendered_template_cannot_enable"
        for err in body.get("errors", [])
    )


def test_patch_name_on_unrendered_template_returns_correct_enabled(
    client: TestClient,
) -> None:
    # Given: an unrendered template control
    control_id, _ = _create_unrendered_control(client)
    new_name = f"renamed-unrendered-{uuid.uuid4()}"

    # When: renaming it
    response = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": new_name},
    )

    # Then: the rename succeeds and enabled is correctly reported as False
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == new_name
    assert body["enabled"] is False


def test_create_unrendered_template_rejects_optional_param_without_default(
    client: TestClient,
) -> None:
    # Given: a template with an optional parameter that has no default but is
    # referenced in definition_template
    payload = _unrendered_template_payload()
    payload["template"]["parameters"]["pattern"]["required"] = False  # type: ignore[index]

    # When: creating an unrendered control
    response = client.put(
        "/api/v1/controls",
        json={"name": f"bad-optional-{uuid.uuid4()}", "data": payload},
    )

    # Then: the server rejects — this template can never render
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "optional_referenced_parameter_requires_default"
        for err in body.get("errors", [])
    )


def test_unrendered_template_excluded_from_evaluation(client: TestClient) -> None:
    # Given: an unrendered template control attached to an agent
    control_id, _ = _create_unrendered_control(client)
    agent_name = _assign_control_to_agent(client, control_id)

    # When: evaluating a step
    eval_response = _evaluate_step(
        client, agent_name, step_name="any-step", input_value="hello",
    )

    # Then: evaluation succeeds (unrendered control is skipped)
    assert eval_response.status_code == 200, eval_response.text
    assert eval_response.json()["is_safe"] is True


def test_agent_controls_endpoint_defaults_to_all_and_supports_state_filters(
    client: TestClient,
) -> None:
    # Given: an agent with active, disabled, and unrendered associated controls
    active_control_id = _create_raw_control(client)
    disabled_control_id = _create_raw_control(client)
    disable_response = client.patch(
        f"/api/v1/controls/{disabled_control_id}",
        json={"enabled": False},
    )
    assert disable_response.status_code == 200, disable_response.text

    unrendered_control_id, _ = _create_unrendered_control(client)
    agent_name = _assign_control_to_agent(client, active_control_id, via_policy=False)
    _assign_control_to_agent(
        client,
        disabled_control_id,
        agent_name=agent_name,
        via_policy=False,
    )
    _assign_control_to_agent(
        client,
        unrendered_control_id,
        agent_name=agent_name,
        via_policy=False,
    )

    # When: listing controls with no explicit state filters
    default_response = client.get(f"/api/v1/agents/{agent_name}/controls")

    # Then: the full associated set is returned by default
    assert default_response.status_code == 200, default_response.text
    assert {control["id"] for control in default_response.json()["controls"]} == {
        active_control_id,
        disabled_control_id,
        unrendered_control_id,
    }

    # When: requesting disabled rendered controls
    disabled_response = client.get(
        f"/api/v1/agents/{agent_name}/controls",
        params={"rendered_state": "rendered", "enabled_state": "disabled"},
    )

    # Then: the disabled rendered control is returned
    assert disabled_response.status_code == 200, disabled_response.text
    assert {control["id"] for control in disabled_response.json()["controls"]} == {
        disabled_control_id
    }

    # When: requesting unrendered controls
    unrendered_response = client.get(
        f"/api/v1/agents/{agent_name}/controls",
        params={"rendered_state": "unrendered", "enabled_state": "all"},
    )

    # Then: only the unrendered template draft is returned
    assert unrendered_response.status_code == 200, unrendered_response.text
    assert {control["id"] for control in unrendered_response.json()["controls"]} == {
        unrendered_control_id
    }

    # When: requesting unrendered and enabled controls simultaneously
    impossible_response = client.get(
        f"/api/v1/agents/{agent_name}/controls",
        params={"rendered_state": "unrendered", "enabled_state": "enabled"},
    )

    # Then: the impossible intersection yields an empty list
    assert impossible_response.status_code == 200, impossible_response.text
    assert impossible_response.json()["controls"] == []

    # When: requesting all rendered and enabled states
    all_response = client.get(
        f"/api/v1/agents/{agent_name}/controls",
        params={"rendered_state": "all", "enabled_state": "all"},
    )

    # Then: the full associated set is returned
    assert all_response.status_code == 200, all_response.text
    assert {control["id"] for control in all_response.json()["controls"]} == {
        active_control_id,
        disabled_control_id,
        unrendered_control_id,
    }


def test_create_unrendered_template_rejects_unknown_value_key(
    client: TestClient,
) -> None:
    # Given: a template payload with values for a nonexistent parameter
    payload = _unrendered_template_payload()
    payload["template_values"] = {"nonexistent": "value"}  # type: ignore[assignment]

    # When: creating the unrendered control
    response = client.put(
        "/api/v1/controls",
        json={"name": f"unknown-val-{uuid.uuid4()}", "data": payload},
    )

    # Then: the server rejects with unknown parameter error
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("code") == "unknown_parameter"
        and err.get("field") == "template_values.nonexistent"
        for err in body.get("errors", [])
    )


def test_create_unrendered_template_rejects_wrong_type_value(
    client: TestClient,
) -> None:
    # Given: a template with a regex_re2 parameter but we provide a list value
    payload = _unrendered_template_payload()
    payload["template_values"] = {"pattern": ["not", "a", "string"]}  # type: ignore[assignment]

    # When: creating the unrendered control
    response = client.put(
        "/api/v1/controls",
        json={"name": f"wrong-type-{uuid.uuid4()}", "data": payload},
    )

    # Then: the server rejects with a type error
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"
    assert any(
        err.get("parameter") == "pattern"
        for err in body.get("errors", [])
    )


def test_unrendered_template_list_shows_template_description_as_fallback(
    client: TestClient,
) -> None:
    # Given: an unrendered template control whose template has a description
    control_id, _ = _create_unrendered_control(client)

    # When: listing controls
    response = client.get("/api/v1/controls", params={"template_backed": True})

    # Then: the summary description falls back to the template description
    assert response.status_code == 200, response.text
    controls = response.json()["controls"]
    unrendered = next((c for c in controls if c["id"] == control_id), None)
    assert unrendered is not None
    assert unrendered["description"] == "Regex denial template"


def test_unrendered_template_shows_in_list_with_correct_flags(client: TestClient) -> None:
    # Given: an unrendered template control
    control_id, _ = _create_unrendered_control(client)

    # When: listing controls
    response = client.get("/api/v1/controls", params={"template_backed": True})

    # Then: the control appears with template_backed=True and template_rendered=False
    assert response.status_code == 200, response.text
    controls = response.json()["controls"]
    unrendered = next((c for c in controls if c["id"] == control_id), None)
    assert unrendered is not None
    assert unrendered["template_backed"] is True
    assert unrendered["template_rendered"] is False


def test_unrendered_template_excluded_from_rendered_field_filters(
    client: TestClient,
) -> None:
    # Given: an unrendered template control
    control_id, _ = _create_unrendered_control(client)

    # When: filtering by execution (a rendered-only field)
    exec_response = client.get("/api/v1/controls", params={"execution": "server"})
    assert exec_response.status_code == 200
    exec_ids = {c["id"] for c in exec_response.json()["controls"]}

    # Then: unrendered template is excluded
    assert control_id not in exec_ids

    # When: filtering by step_type
    step_response = client.get("/api/v1/controls", params={"step_type": "llm"})
    assert step_response.status_code == 200
    step_ids = {c["id"] for c in step_response.json()["controls"]}

    # Then: unrendered template is excluded
    assert control_id not in step_ids

    # When: listing without rendered-field filters
    all_response = client.get("/api/v1/controls")
    assert all_response.status_code == 200
    all_ids = {c["id"] for c in all_response.json()["controls"]}

    # Then: unrendered template IS included in the unfiltered listing
    assert control_id in all_ids


def test_unrendered_template_can_be_deleted(client: TestClient) -> None:
    # Given: an unrendered template control
    control_id, _ = _create_unrendered_control(client)

    # When: deleting it
    response = client.delete(f"/api/v1/controls/{control_id}", params={"force": True})

    # Then: deletion succeeds
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True


def test_patch_disable_on_unrendered_template_is_noop(client: TestClient) -> None:
    # Given: an unrendered template control (already enabled=false)
    control_id, _ = _create_unrendered_control(client)

    # When: patching enabled=false (redundant, but should not crash)
    response = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"enabled": False},
    )

    # Then: the request succeeds without error (no CORRUPTED_DATA)
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is False


def test_create_unrendered_template_rejects_undefined_param_reference(
    client: TestClient,
) -> None:
    # Given: a template whose definition_template references an undefined parameter
    payload = _unrendered_template_payload()
    payload["template"]["definition_template"]["condition"]["evaluator"]["config"]["extra"] = {  # type: ignore[index]
        "$param": "nonexistent",
    }

    # When: creating the unrendered control
    response = client.put(
        "/api/v1/controls",
        json={"name": f"bad-unrendered-{uuid.uuid4()}", "data": payload},
    )

    # Then: the server rejects with a structural validation error
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "undefined_parameter_reference"
        for err in body.get("errors", [])
    )


def test_create_unrendered_template_rejects_unused_parameter(
    client: TestClient,
) -> None:
    # Given: a template with an extra parameter never referenced in definition_template
    payload = _unrendered_template_payload()
    payload["template"]["parameters"]["unused_param"] = {  # type: ignore[index]
        "type": "string",
        "label": "Unused",
        "default": "val",
    }

    # When: creating the unrendered control
    response = client.put(
        "/api/v1/controls",
        json={"name": f"unused-param-{uuid.uuid4()}", "data": payload},
    )

    # Then: the server rejects with unused parameter error
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "unused_template_parameter"
        for err in body.get("errors", [])
    )


def test_create_unrendered_template_rejects_agent_scoped_evaluator(
    client: TestClient,
) -> None:
    # Given: a template with a hardcoded agent-scoped evaluator name
    payload = _unrendered_template_payload()
    payload["template"]["definition_template"]["condition"]["evaluator"]["name"] = "agent-x:custom"  # type: ignore[index]

    # When: creating the unrendered control
    response = client.put(
        "/api/v1/controls",
        json={"name": f"agent-scoped-{uuid.uuid4()}", "data": payload},
    )

    # Then: the server rejects
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "TEMPLATE_RENDER_ERROR"
    assert any(
        err.get("code") == "agent_scoped_evaluator_not_supported"
        for err in body.get("errors", [])
    )


def test_rendered_template_rejects_update_with_incomplete_values(
    client: TestClient,
) -> None:
    # Given: a rendered template control
    control_id = _create_template_control(client)

    # When: updating with empty values (attempting to "un-render")
    put_response = client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": _unrendered_template_payload()},
    )

    # Then: the server rejects (missing required parameter for a rendered control)
    assert put_response.status_code == 422
    body = put_response.json()
    assert body["error_code"] == "TEMPLATE_PARAMETER_INVALID"

    # And: the control remains rendered and unchanged
    get_response = client.get(f"/api/v1/controls/{control_id}/data")
    data = get_response.json()["data"]
    assert "condition" in data
    assert data["condition"]["evaluator"]["config"]["pattern"] == "hello"
