"""Unit tests for agent_control.controls API wrappers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import agent_control
from agent_control_models import TemplateControlInput


class _AsyncClientContext:
    def __init__(self, client: object) -> None:
        self.client = client

    async def __aenter__(self) -> object:
        return self.client

    async def __aexit__(self, *args: object) -> None:
        return None


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
async def test_list_control_versions_forwards_cursor_and_limit() -> None:
    # Given: an SDK client stub and version-history pagination params
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"versions": [], "pagination": {}})
    client = SimpleNamespace(http_client=SimpleNamespace(get=AsyncMock(return_value=response)))

    # When: listing control versions through the SDK wrapper
    await agent_control.controls.list_control_versions(client, control_id=123, cursor=7, limit=5)

    # Then: the request is sent to the correct endpoint with pagination params
    client.http_client.get.assert_awaited_once_with(
        "/api/v1/controls/123/versions",
        params={"limit": 5, "cursor": 7},
    )


@pytest.mark.asyncio
async def test_get_control_version_calls_specific_version_endpoint() -> None:
    # Given: an SDK client stub for fetching a specific version
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(return_value={"version_num": 2, "snapshot": {}})
    client = SimpleNamespace(http_client=SimpleNamespace(get=AsyncMock(return_value=response)))

    # When: fetching a specific control version
    await agent_control.controls.get_control_version(client, control_id=123, version_num=2)

    # Then: the SDK calls the version-detail endpoint
    client.http_client.get.assert_awaited_once_with("/api/v1/controls/123/versions/2")


@pytest.mark.asyncio
async def test_restore_control_version_calls_restore_endpoint() -> None:
    # Given: an SDK client stub for restoring a version
    response = Mock()
    response.raise_for_status = Mock()
    response.json = Mock(
        return_value={
            "success": True,
            "control_id": 123,
            "restored_from_version_num": 2,
            "current_version_num": 4,
            "name": "restored-control",
            "data": {},
        }
    )
    client = SimpleNamespace(http_client=SimpleNamespace(post=AsyncMock(return_value=response)))

    # When: restoring a specific control version
    result = await agent_control.controls.restore_control_version(
        client,
        control_id=123,
        version_num=2,
    )

    # Then: the SDK calls the restore endpoint
    client.http_client.post.assert_awaited_once_with("/api/v1/controls/123/versions/2/restore")
    assert result["current_version_num"] == 4


@pytest.mark.asyncio
async def test_top_level_control_version_helpers_delegate_to_controls_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: top-level SDK helpers and a fake client context
    client = object()
    created_clients: list[tuple[str, str | None]] = []

    def fake_client_factory(base_url: str, api_key: str | None = None) -> _AsyncClientContext:
        created_clients.append((base_url, api_key))
        return _AsyncClientContext(client)

    list_versions = AsyncMock(return_value={"versions": []})
    get_version = AsyncMock(return_value={"version_num": 2})
    restore_version = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(agent_control, "AgentControlClient", fake_client_factory)
    monkeypatch.setattr(agent_control.controls, "list_control_versions", list_versions)
    monkeypatch.setattr(agent_control.controls, "get_control_version", get_version)
    monkeypatch.setattr(agent_control.controls, "restore_control_version", restore_version)

    # When: calling the public top-level version helpers
    await agent_control.list_control_versions(
        123,
        server_url="http://server.test",
        api_key="secret",
        cursor=7,
        limit=5,
    )
    await agent_control.get_control_version(123, 2, server_url="http://server.test")
    await agent_control.restore_control_version(123, 2, server_url="http://server.test")

    # Then: they are exported and delegate to the lower-level controls module
    assert "list_control_versions" in agent_control.__all__
    assert "get_control_version" in agent_control.__all__
    assert "restore_control_version" in agent_control.__all__
    assert created_clients == [
        ("http://server.test", "secret"),
        ("http://server.test", None),
        ("http://server.test", None),
    ]
    list_versions.assert_awaited_once_with(client, control_id=123, cursor=7, limit=5)
    get_version.assert_awaited_once_with(client, control_id=123, version_num=2)
    restore_version.assert_awaited_once_with(client, control_id=123, version_num=2)


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
