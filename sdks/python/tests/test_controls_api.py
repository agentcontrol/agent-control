"""Unit tests for agent_control.controls API wrappers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import agent_control
from agent_control_models import TemplateControlInput


@pytest.mark.asyncio
async def test_list_controls_passes_template_backed_filter() -> None:
    # Given: an SDK client stub and a template-backed list filter
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"controls": [], "pagination": {}})
    client = SimpleNamespace(http_client=SimpleNamespace(get=AsyncMock(return_value=response)))

    # When: listing controls through the SDK wrapper
    await agent_control.controls.list_controls(client, template_backed=True)

    # Then: the filter is forwarded to the API request
    client.http_client.get.assert_awaited_once_with(
        "/api/v1/controls",
        params={"limit": 20, "template_backed": True},
    )


@pytest.mark.asyncio
async def test_create_control_accepts_template_control_input() -> None:
    # Given: an SDK client stub and template-backed control input
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

    # When: creating a control through the SDK wrapper
    await agent_control.controls.create_control(client, "templated", template_input)

    # Then: the template values are serialized into the request body
    client.http_client.put.assert_awaited_once()
    _, kwargs = client.http_client.put.await_args
    assert kwargs["json"]["data"]["template_values"]["pattern"] == "hello"


@pytest.mark.asyncio
async def test_render_control_template_calls_preview_endpoint() -> None:
    # Given: an SDK client stub and template preview input
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"control": {"execution": "server"}})
    client = SimpleNamespace(http_client=SimpleNamespace(post=AsyncMock(return_value=response)))

    # When: rendering a control template through the SDK wrapper
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

    # Then: the SDK calls the preview endpoint with the expected payload
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


@pytest.mark.asyncio
async def test_validate_control_data_accepts_template_control_input() -> None:
    # Given: an SDK client stub and template-backed control input
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"success": True})
    client = SimpleNamespace(http_client=SimpleNamespace(post=AsyncMock(return_value=response)))
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

    # When: validating template-backed control input through the SDK wrapper
    await agent_control.controls.validate_control_data(client, template_input)

    # Then: the template-backed payload is posted to the validate endpoint
    client.http_client.post.assert_awaited_once()
    _, kwargs = client.http_client.post.await_args
    assert kwargs["json"]["data"]["template_values"]["pattern"] == "hello"
    assert kwargs["json"] == {
        "data": {
            "template": kwargs["json"]["data"]["template"],
            "template_values": {"pattern": "hello"},
        }
    }


@pytest.mark.asyncio
async def test_set_control_data_accepts_template_control_input() -> None:
    # Given: an SDK client stub and template-backed control input
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"success": True})
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

    # When: updating control data through the SDK wrapper
    await agent_control.controls.set_control_data(client, 123, template_input)

    # Then: the template values are serialized into the request body
    client.http_client.put.assert_awaited_once()
    _, kwargs = client.http_client.put.await_args
    assert kwargs["json"]["data"]["template_values"]["pattern"] == "hello"


def test_to_template_control_input_reshapes_stored_control_data() -> None:
    # Given: stored template-backed control data returned by the API
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

    # When: reshaping the stored data into template input
    # Then: the result is template-backed input with the original values
    assert isinstance(template_input, TemplateControlInput)
    assert template_input.template_values == {"pattern": "hello"}


def test_to_template_control_input_rejects_raw_control_data() -> None:
    # Given: raw control data without template metadata
    # When: reshaping it into template-backed control input
    with pytest.raises(ValueError, match="not template-backed"):
        agent_control.controls.to_template_control_input(
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
            }
        )
    # Then: the helper rejects the raw control data


def test_to_template_control_input_accepts_unrendered_template_data() -> None:
    # Given: unrendered template data (template + template_values, no condition)
    template_input = agent_control.controls.to_template_control_input(
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
            "enabled": False,
        }
    )

    # When/Then: the helper extracts template + values successfully
    assert isinstance(template_input, TemplateControlInput)
    assert template_input.template_values == {}
    assert "pattern" in template_input.template.parameters
