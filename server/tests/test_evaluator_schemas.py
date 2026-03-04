"""Tests for evaluator schema functionality."""

import uuid

import pytest
from fastapi.testclient import TestClient

from agent_control_server.services.schema_compat import check_schema_compatibility


def make_agent_payload(
    agent_name: str | None = None,
    name: str | None = None,
    evaluators: list | None = None,
):
    """Helper to create agent payload with evaluators."""
    if agent_name is not None:
        name = agent_name
    elif name is None:
        name = f"agent-{uuid.uuid4().hex[:12]}"
    canonical_name = name.lower().replace(" ", "-")
    if len(canonical_name) < 10:
        canonical_name = f"{canonical_name}-agent".replace("--", "-")
    return {
        "agent": {
            "agent_name": canonical_name,
            "agent_name": canonical_name,
            "agent_description": "desc",
            "agent_version": "1.0",
        },
        "steps": [],
        "evaluators": evaluators or [],
    }


# =============================================================================
# initAgent with evaluators
# =============================================================================


def test_init_agent_with_evaluators(client: TestClient) -> None:
    """Test creating agent with evaluator schemas."""
    # Given: A payload with custom evaluator
    payload = make_agent_payload(
        evaluators=[
            {
                "name": "my-custom-eval",
                "description": "A custom evaluator",
                "config_schema": {
                    "type": "object",
                    "properties": {"threshold": {"type": "number"}},
                },
            }
        ]
    )
    # When: Initializing agent
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    # Then: Agent created successfully
    assert resp.status_code == 200
    assert resp.json()["created"] is True


def test_init_agent_evaluator_name_collision_rejected(client: TestClient) -> None:
    """Test that evaluator names conflicting with built-in evaluators are rejected."""
    # Given: Evaluator name conflicting with built-in
    payload = make_agent_payload(
        evaluators=[
            {
                "name": "regex",  # Conflicts with built-in
                "description": "Trying to override regex",
                "config_schema": {},
            }
        ]
    )
    # When: Initializing agent
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    # Then: Should be rejected (RFC 7807 format)
    assert resp.status_code == 409
    response_data = resp.json()
    assert "conflicts with built-in evaluator" in response_data.get("detail", "")


def test_init_agent_evaluator_name_collision_list(client: TestClient) -> None:
    """Test that 'list' built-in name is also rejected."""
    # Given: Evaluator named 'list'
    payload = make_agent_payload(
        evaluators=[{"name": "list", "config_schema": {}}]
    )
    # When: Initializing agent
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    # Then: Should be rejected (RFC 7807 format - ConflictError returns 409)
    assert resp.status_code == 409


def test_init_agent_update_evaluator_compatible_schema(client: TestClient) -> None:
    """Test updating evaluator with compatible schema change (add optional field)."""
    # Given: Agent with evaluator
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload1 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {"threshold": {"type": "number"}},
                    "required": ["threshold"],
                },
            }
        ],
    )
    resp1 = client.post("/api/v1/agents/initAgent", json=payload1)
    assert resp1.status_code == 200

    # When: Updating with compatible schema (add optional field)
    payload2 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "threshold": {"type": "number"},
                        "max_retries": {"type": "integer"},  # New optional
                    },
                    "required": ["threshold"],
                },
            }
        ],
    )
    resp2 = client.post("/api/v1/agents/initAgent", json=payload2)
    # Then: Should be accepted
    assert resp2.status_code == 200


def test_init_agent_update_evaluator_incompatible_schema_rejected(
    client: TestClient,
) -> None:
    """Test that incompatible schema change is rejected."""
    # Given: Agent with evaluator
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload1 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {"threshold": {"type": "number"}},
                },
            }
        ],
    )
    resp1 = client.post("/api/v1/agents/initAgent", json=payload1)
    assert resp1.status_code == 200

    # When: Updating with incompatible schema (remove property)
    payload2 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {},  # Removed threshold
                },
            }
        ],
    )
    resp2 = client.post("/api/v1/agents/initAgent", json=payload2)
    # Then: Should be rejected
    assert resp2.status_code == 409
    assert "not backward compatible" in resp2.json()["detail"]


def test_init_agent_update_evaluator_type_change_rejected(client: TestClient) -> None:
    """Test that changing property type is rejected."""
    # Given: Agent with evaluator
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload1 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                },
            }
        ],
    )
    client.post("/api/v1/agents/initAgent", json=payload1)

    # When: Changing property type
    payload2 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "number"}},
                },
            }
        ],
    )
    resp2 = client.post("/api/v1/agents/initAgent", json=payload2)
    # Then: Should be rejected
    assert resp2.status_code == 409
    assert "type changed" in resp2.json()["detail"]


def test_init_agent_add_required_property_rejected(client: TestClient) -> None:
    """Test that adding a new required property is rejected."""
    # Given: Agent with evaluator
    agent_name = str(uuid.uuid4())
    name = f"Test Agent {uuid.uuid4().hex[:8]}"
    payload1 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                },
            }
        ],
    )
    client.post("/api/v1/agents/initAgent", json=payload1)

    # When: Adding new required property
    payload2 = make_agent_payload(
        agent_name=agent_name,
        name=name,
        evaluators=[
            {
                "name": "my-eval",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "string"},
                        "b": {"type": "string"},
                    },
                    "required": ["b"],  # New required
                },
            }
        ],
    )
    resp2 = client.post("/api/v1/agents/initAgent", json=payload2)
    # Then: Should be rejected
    assert resp2.status_code == 409
    assert "Added required property" in resp2.json()["detail"]


# =============================================================================
# Evaluator listing endpoints
# =============================================================================


def test_list_agent_evaluators(client: TestClient) -> None:
    """Test listing agent's evaluator schemas."""
    # Given: Agent with two evaluators
    payload = make_agent_payload(
        evaluators=[
            {"name": "eval-a", "description": "First", "config_schema": {}},
            {"name": "eval-b", "description": "Second", "config_schema": {}},
        ]
    )
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 200
    agent_name = payload["agent"]["agent_name"]

    # When: Listing evaluators
    list_resp = client.get(f"/api/v1/agents/{agent_name}/evaluators")
    # Then: Should return both evaluators
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert len(data["evaluators"]) == 2
    names = {e["name"] for e in data["evaluators"]}
    assert names == {"eval-a", "eval-b"}
    assert data["pagination"]["total"] == 2


def test_list_agent_evaluators_pagination(client: TestClient) -> None:
    """Test pagination of evaluator list."""
    # Given: Agent with 5 evaluators
    payload = make_agent_payload(
        evaluators=[{"name": f"eval-{i}", "config_schema": {}} for i in range(5)]
    )
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 200
    agent_name = payload["agent"]["agent_name"]

    # When: Fetching first page
    resp1 = client.get(f"/api/v1/agents/{agent_name}/evaluators?offset=0&limit=2")
    # Then: Should return 2 items with total=5
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["evaluators"]) == 2
    assert data1["pagination"]["total"] == 5

    # When: Fetching second page
    resp2 = client.get(f"/api/v1/agents/{agent_name}/evaluators?offset=2&limit=2")
    # Then: Should return 2 more items
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["evaluators"]) == 2


def test_get_agent_evaluator_by_name(client: TestClient) -> None:
    """Test getting specific evaluator by name."""
    # Given: Agent with evaluator
    payload = make_agent_payload(
        evaluators=[
            {
                "name": "my-eval",
                "description": "Test evaluator",
                "config_schema": {"type": "object"},
            }
        ]
    )
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 200
    agent_name = payload["agent"]["agent_name"]

    # When: Getting evaluator by name
    get_resp = client.get(f"/api/v1/agents/{agent_name}/evaluators/my-eval")
    # Then: Should return evaluator details
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["name"] == "my-eval"
    assert data["description"] == "Test evaluator"


def test_get_agent_evaluator_not_found(client: TestClient) -> None:
    """Test 404 for non-existent evaluator name."""
    # Given: Agent with no evaluators
    payload = make_agent_payload(evaluators=[])
    resp = client.post("/api/v1/agents/initAgent", json=payload)
    assert resp.status_code == 200
    agent_name = payload["agent"]["agent_name"]

    # When: Getting nonexistent evaluator
    get_resp = client.get(f"/api/v1/agents/{agent_name}/evaluators/nonexistent")
    # Then: Should return 404
    assert get_resp.status_code == 404


def test_list_evaluators_agent_not_found(client: TestClient) -> None:
    """Test 404 for non-existent agent."""
    # Given: Nonexistent agent ID
    fake_id = str(uuid.uuid4())
    # When: Listing evaluators
    resp = client.get(f"/api/v1/agents/{fake_id}/evaluators")
    # Then: Should return 404
    assert resp.status_code == 404


# =============================================================================
# Schema compatibility unit tests
# =============================================================================


class TestSchemaCompatibility:
    """Unit tests for schema compatibility checker."""

    def test_empty_old_schema_compatible(self):
        """Empty old schema is always compatible."""
        # Given:/When: Empty old schema
        is_compat, errors = check_schema_compatibility({}, {"type": "object"})
        # Then: Should be compatible
        assert is_compat
        assert errors == []

    def test_add_optional_property_compatible(self):
        """Adding optional property is compatible."""
        # Given: Old and new schemas with added optional property
        old = {"properties": {"a": {"type": "string"}}}
        new = {"properties": {"a": {"type": "string"}, "b": {"type": "number"}}}
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be compatible
        assert is_compat

    def test_remove_property_incompatible(self):
        """Removing property is incompatible."""
        # Given: Old and new schemas with removed property
        old = {"properties": {"a": {"type": "string"}, "b": {"type": "number"}}}
        new = {"properties": {"a": {"type": "string"}}}
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be incompatible
        assert not is_compat
        assert any("Removed property" in e for e in errors)

    def test_type_change_incompatible(self):
        """Changing property type is incompatible."""
        # Given: Old and new schemas with changed type
        old = {"properties": {"a": {"type": "string"}}}
        new = {"properties": {"a": {"type": "number"}}}
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be incompatible
        assert not is_compat
        assert any("type changed" in e for e in errors)

    def test_add_required_incompatible(self):
        """Adding new required property is incompatible."""
        # Given: Old and new schemas with new required property
        old = {"properties": {"a": {"type": "string"}}}
        new = {
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["b"],
        }
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be incompatible
        assert not is_compat
        assert any("Added required property" in e for e in errors)

    def test_optional_to_required_incompatible(self):
        """Changing optional to required is incompatible."""
        # Given: Old and new schemas where optional becomes required
        old = {"properties": {"a": {"type": "string"}}}
        new = {"properties": {"a": {"type": "string"}}, "required": ["a"]}
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be incompatible
        assert not is_compat
        assert any("optional to required" in e for e in errors)

    def test_required_to_optional_compatible(self):
        """Changing required to optional is compatible."""
        # Given: Old and new schemas where required becomes optional
        old = {"properties": {"a": {"type": "string"}}, "required": ["a"]}
        new = {"properties": {"a": {"type": "string"}}}
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be compatible
        assert is_compat

    def test_nested_property_removal_incompatible(self):
        """Removing nested property is incompatible."""
        # Given: Old and new schemas with removed nested property
        old = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
                }
            }
        }
        new = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                }
            }
        }
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be incompatible
        assert not is_compat
        assert any("config.b" in e for e in errors)

    def test_nested_type_change_incompatible(self):
        """Changing nested property type is incompatible."""
        # Given: Old and new schemas with changed nested type
        old = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                }
            }
        }
        new = {
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                }
            }
        }
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be incompatible
        assert not is_compat
        assert any("config.value" in e and "type changed" in e for e in errors)

    def test_array_item_schema_change_incompatible(self):
        """Changing array item schema is incompatible."""
        # Given: Old and new schemas with changed array item schema
        old = {
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            }
        }
        new = {
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {},  # Removed name
                    },
                }
            }
        }
        # When: Checking compatibility
        is_compat, errors = check_schema_compatibility(old, new)
        # Then: Should be incompatible
        assert not is_compat
        assert any("items[].name" in e for e in errors)
