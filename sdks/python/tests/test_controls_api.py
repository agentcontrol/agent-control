"""Unit tests for agent_control.controls API wrappers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import agent_control
from agent_control_models import TemplateControlInput


@pytest.mark.asyncio
async def test_list_controls_passes_template_backed_filter() -> None:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"controls": [], "pagination": {}})
    client = SimpleNamespace(http_client=SimpleNamespace(get=AsyncMock(return_value=response)))

    await agent_control.controls.list_controls(client, template_backed=True)

    client.http_client.get.assert_awaited_once_with(
        "/api/v1/controls",
        params={"limit": 20, "template_backed": True},
    )


@pytest.mark.asyncio
async def test_create_control_accepts_template_control_input() -> None:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"control_id": 123})
    client = SimpleNamespace(http_client=SimpleNamespace(put=AsyncMock(return_value=response)))
    template_input = TemplateControlInput.model_validate(
        {
            "template": {
                "parameters": {
                    "pattern": {
                        "type": "regex_re2",
                        "label": "Pattern",
                    }
                },
                "definition_template": {
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
            "template_values": {"pattern": "hello"},
        }
    )

    await agent_control.controls.create_control(client, "templated", template_input)

    client.http_client.put.assert_awaited_once()
    _, kwargs = client.http_client.put.await_args
    assert kwargs["json"]["data"]["template_values"]["pattern"] == "hello"


@pytest.mark.asyncio
async def test_render_control_template_calls_preview_endpoint() -> None:
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"control": {"execution": "server"}})
    client = SimpleNamespace(http_client=SimpleNamespace(post=AsyncMock(return_value=response)))

    await agent_control.controls.render_control_template(
        client,
        template={
            "parameters": {},
            "definition_template": {
                "execution": "server",
                "scope": {},
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {"name": "regex", "config": {"pattern": "x"}},
                },
                "action": {"decision": "deny"},
            },
        },
        template_values={},
    )

    client.http_client.post.assert_awaited_once_with(
        "/api/v1/control-templates/render",
        json={
            "template": {
                "parameters": {},
                "definition_template": {
                    "execution": "server",
                    "scope": {},
                    "condition": {
                        "selector": {"path": "input"},
                        "evaluator": {"name": "regex", "config": {"pattern": "x"}},
                    },
                    "action": {"decision": "deny"},
                },
            },
            "template_values": {},
        },
    )


def test_to_template_control_input_reshapes_stored_control_data() -> None:
    template_input = agent_control.controls.to_template_control_input(
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {
                    "name": "regex",
                    "config": {"pattern": "hello"},
                },
            },
            "action": {"decision": "deny"},
            "template": {
                "parameters": {
                    "pattern": {
                        "type": "regex_re2",
                        "label": "Pattern",
                    }
                },
                "definition_template": {
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
            "template_values": {"pattern": "hello"},
        }
    )

    assert isinstance(template_input, TemplateControlInput)
    assert template_input.template_values == {"pattern": "hello"}
