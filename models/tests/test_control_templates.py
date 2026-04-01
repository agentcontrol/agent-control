"""Tests for template-backed control model contracts."""

from __future__ import annotations

import pytest
from agent_control_models import ControlDefinition, TemplateControlInput, TemplateDefinition
from agent_control_models.server import CreateControlRequest
from pydantic import ValidationError


VALID_TEMPLATE = {
    "parameters": {
        "pattern": {
            "type": "regex_re2",
            "label": "Pattern",
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
    },
}


def test_control_definition_requires_template_fields_together() -> None:
    with pytest.raises(
        ValidationError,
        match="template and template_values must both be present or both absent",
    ):
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": "ok"},
                    },
                },
                "action": {"decision": "deny"},
                "template": VALID_TEMPLATE,
            }
        )


def test_template_definition_rejects_invalid_parameter_name() -> None:
    with pytest.raises(
        ValidationError,
        match=r"Parameter names must match \[a-zA-Z_\]\[a-zA-Z0-9_\]\*",
    ):
        TemplateDefinition.model_validate(
            {
                "parameters": {
                    "bad.name": {
                        "type": "string",
                        "label": "Bad Name",
                    }
                },
                "definition_template": {},
            }
        )


def test_create_control_request_parses_template_payload_as_template_input() -> None:
    request = CreateControlRequest.model_validate(
        {
            "name": "template-control",
            "data": {
                "template": VALID_TEMPLATE,
                "template_values": {"pattern": "hello"},
            },
        }
    )

    assert isinstance(request.data, TemplateControlInput)


def test_create_control_request_rejects_mixed_raw_and_template_payload() -> None:
    with pytest.raises(ValidationError):
        CreateControlRequest.model_validate(
            {
                "name": "template-control",
                "data": {
                    "template": VALID_TEMPLATE,
                    "template_values": {"pattern": "hello"},
                    "execution": "server",
                },
            }
        )
