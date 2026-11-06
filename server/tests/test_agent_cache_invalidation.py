"""Regression tests for invalidating Agent snapshots after data mutations."""

from __future__ import annotations

import agent_control_server.endpoints.agents as agents_endpoint
import pytest
from agent_control_server.models import DEFAULT_NAMESPACE_KEY
from fastapi.testclient import TestClient


def _init_payload(agent_name: str, description: str, step_name: str) -> dict[str, object]:
    return {
        "agent": {
            "agent_name": agent_name,
            "agent_description": description,
            "agent_version": "1.0",
            "agent_metadata": {},
        },
        "steps": [
            {
                "type": "tool",
                "name": step_name,
                "input_schema": {},
                "output_schema": {},
            }
        ],
    }


def test_init_agent_invalidates_existing_agent_after_update(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalidations: list[tuple[str, str]] = []

    async def record_invalidation(namespace: str, agent: str) -> None:
        invalidations.append((namespace, agent))

    monkeypatch.setattr(agents_endpoint, "invalidate_agent_scope", record_invalidation)
    agent_name = "cache-init-update-agent"

    created = client.post(
        "/api/v1/agents/initAgent", json=_init_payload(agent_name, "before", "step-a")
    )
    assert created.status_code == 200
    assert created.json()["created"] is True
    assert invalidations == []

    updated = client.post(
        "/api/v1/agents/initAgent", json=_init_payload(agent_name, "after", "step-a")
    )

    assert updated.status_code == 200
    assert updated.json()["created"] is False
    assert invalidations == [(DEFAULT_NAMESPACE_KEY, agent_name)]


def test_patch_agent_invalidates_after_agent_data_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalidations: list[tuple[str, str]] = []

    async def record_invalidation(namespace: str, agent: str) -> None:
        invalidations.append((namespace, agent))

    monkeypatch.setattr(agents_endpoint, "invalidate_agent_scope", record_invalidation)
    agent_name = "cache-patch-update-agent"
    initialized = client.post(
        "/api/v1/agents/initAgent", json=_init_payload(agent_name, "before", "remove-me")
    )
    assert initialized.status_code == 200
    assert invalidations == []

    patched = client.patch(
        f"/api/v1/agents/{agent_name}",
        json={"remove_steps": [{"type": "tool", "name": "remove-me"}]},
    )

    assert patched.status_code == 200
    assert patched.json()["steps_removed"] == [{"type": "tool", "name": "remove-me"}]
    assert invalidations == [(DEFAULT_NAMESPACE_KEY, agent_name)]
