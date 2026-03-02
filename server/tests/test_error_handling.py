"""Tests for database error handling and rollback scenarios."""

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from agent_control_server.db import get_async_db


async def mock_db_with_commit_failure() -> AsyncGenerator[AsyncSession, None]:
    """Mock database session that fails on commit."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.side_effect = Exception("Database error")
    
    # Mock execute to return an awaitable that resolves to a result with scalars/first
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_result.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    
    yield mock_session


def test_init_agent_rollback_on_create_failure(
    app: FastAPI, client: TestClient
) -> None:
    """Test that init_agent rolls back transaction when commit fails on create."""
    # Given: a valid agent init payload
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    payload = {
        "agent": {
            "agent_name": agent_name,
            "agent_name": agent_name,
            "agent_description": "test",
            "agent_version": "1.0",
            "agent_metadata": {},
        },
        "steps": [],
    }

    # When: commit fails during agent creation
    app.dependency_overrides[get_async_db] = mock_db_with_commit_failure
    try:
        resp = client.post("/api/v1/agents/initAgent", json=payload)

        # Then: rollback is called and 500 error is returned
        assert resp.status_code == 500
        assert "database error" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_delete_agent_policy_rollback_on_failure(
    app: FastAPI, client: TestClient, db_engine: object
) -> None:
    """Test that delete_agent_policy rolls back when commit fails."""
    # Given: an agent with an assigned policy
    agent_payload = {
        "agent": {
            "agent_name": str(uuid.uuid4()),
            "agent_name": f"test-agent-{uuid.uuid4()}",
            "agent_description": "test",
            "agent_version": "1.0",
            "agent_metadata": {},
        },
        "steps": [],
    }
    r1 = client.post("/api/v1/agents/initAgent", json=agent_payload)
    assert r1.status_code == 200
    agent_name = agent_payload["agent"]["agent_name"]

    policy_name = f"test-policy-{uuid.uuid4()}"
    r2 = client.put("/api/v1/policies", json={"name": policy_name})
    assert r2.status_code == 200
    policy_id = r2.json()["policy_id"]

    assign_resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    assert assign_resp.status_code == 200

    # And: a database session that fails on commit
    from agent_control_server.models import Agent
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        existing_agent = (
            session.query(Agent).filter(Agent.name == agent_name).first()
        )
        assert existing_agent is not None

        async def mock_db_for_delete_policy() -> AsyncGenerator[AsyncSession, None]:
            mock_session = AsyncMock(spec=AsyncSession)
            mock_session.commit.side_effect = Exception("Database error")

            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = existing_agent
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.rollback = AsyncMock()
            yield mock_session

        # When: deleting policy and commit fails
        app.dependency_overrides[get_async_db] = mock_db_for_delete_policy
        try:
            resp = client.delete(f"/api/v1/agents/{agent_name}/policy")
        finally:
            app.dependency_overrides.clear()

        # Then: rollback is called and 500 error is returned
        assert resp.status_code == 500
        assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_init_agent_rollback_on_update_failure(
    app: FastAPI, client: TestClient, db_engine: object
) -> None:
    """Test that init_agent rolls back transaction when commit fails on update."""
    # Given: an existing agent
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    payload = {
        "agent": {
            "agent_name": agent_name,
            "agent_name": agent_name,
            "agent_description": "test",
            "agent_version": "1.0",
            "agent_metadata": {},
        },
        "steps": [
            {
                "type": "tool",
                "name": "tool_a",
                "input_schema": {"a": "int"},
                "output_schema": {"ok": "bool"},
            }
        ],
    }
    # Create the agent first
    r1 = client.post("/api/v1/agents/initAgent", json=payload)
    assert r1.status_code == 200

    # When: adding a new tool and commit fails
    updated_payload = {
        **payload,
        "steps": [
            # Keep original tool_a unchanged (to avoid schema conflict)
            {
                "type": "tool",
                "name": "tool_a",
                "input_schema": {"a": "int"},
                "output_schema": {"ok": "bool"},
            },
            # Add new tool_b
            {
                "type": "tool",
                "name": "tool_b",
                "input_schema": {"b": "str"},
                "output_schema": {"result": "bool"},
            }
        ],
    }

    from agent_control_server.models import Agent
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        existing_agent = (
            session.query(Agent).filter(Agent.name == agent_name).first()
        )
        assert existing_agent is not None

        async def mock_db_returns_agent() -> AsyncGenerator[AsyncSession, None]:
            from unittest.mock import MagicMock
            
            mock_session = AsyncMock(spec=AsyncSession)
            mock_session.commit.side_effect = Exception("Database error")
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = existing_agent
            mock_session.execute = AsyncMock(return_value=mock_result)
            
            yield mock_session

        app.dependency_overrides[get_async_db] = mock_db_returns_agent
        try:
            resp = client.post("/api/v1/agents/initAgent", json=updated_payload)

            # Then: rollback is called and 500 error is returned
            assert resp.status_code == 500
            assert "database error" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


def test_create_policy_rollback_on_failure(
    app: FastAPI, client: TestClient
) -> None:
    """Test that create_policy rolls back transaction when commit fails."""
    # Given: a valid policy creation request
    policy_name = f"test-policy-{uuid.uuid4()}"

    # When: commit fails during policy creation
    app.dependency_overrides[get_async_db] = mock_db_with_commit_failure
    try:
        resp = client.put("/api/v1/policies", json={"name": policy_name})

        # Then: rollback is called and 500 error is returned
        assert resp.status_code == 500
        assert "database error" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_patch_agent_rollback_on_failure(
    app: FastAPI, client: TestClient, db_engine: object
) -> None:
    """Test that patch_agent rolls back when commit fails."""
    # Given: an existing agent with a step to remove
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    payload = {
        "agent": {
            "agent_name": agent_name,
            "agent_name": agent_name,
            "agent_description": "test",
            "agent_version": "1.0",
            "agent_metadata": {},
        },
        "steps": [
            {
                "type": "tool",
                "name": "tool_a",
                "input_schema": {"a": "int"},
                "output_schema": {"ok": "bool"},
            }
        ],
    }
    r1 = client.post("/api/v1/agents/initAgent", json=payload)
    assert r1.status_code == 200

    # And: a database session that fails on commit
    from agent_control_server.models import Agent
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        existing_agent = (
            session.query(Agent).filter(Agent.name == agent_name).first()
        )
        assert existing_agent is not None

        async def mock_db_for_patch_agent() -> AsyncGenerator[AsyncSession, None]:
            mock_session = AsyncMock(spec=AsyncSession)
            mock_session.commit.side_effect = Exception("Database error")

            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = existing_agent
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.rollback = AsyncMock()
            yield mock_session

        # When: patching the agent and commit fails
        app.dependency_overrides[get_async_db] = mock_db_for_patch_agent
        try:
            resp = client.patch(
                f"/api/v1/agents/{agent_name}",
                json={"remove_steps": [{"type": "tool", "name": "tool_a"}]},
            )
        finally:
            app.dependency_overrides.clear()

        # Then: rollback is called and 500 error is returned
        assert resp.status_code == 500
        assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_create_control_rollback_on_failure(
    app: FastAPI, client: TestClient
) -> None:
    """Test that create_control rolls back transaction when commit fails."""
    # Given: a valid control creation request
    control_name = f"test-control-{uuid.uuid4()}"

    # When: commit fails during control creation
    app.dependency_overrides[get_async_db] = mock_db_with_commit_failure
    try:
        resp = client.put("/api/v1/controls", json={"name": control_name})

        # Then: rollback is called and 500 error is returned
        assert resp.status_code == 500
        assert "database error" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_delete_control_rollback_on_failure(
    app: FastAPI, client: TestClient, db_engine: object
) -> None:
    """Test that delete_control rolls back when commit fails."""
    # Given: an existing control
    control_name = f"test-control-{uuid.uuid4()}"
    create_resp = client.put("/api/v1/controls", json={"name": control_name})
    assert create_resp.status_code == 200
    control_id = create_resp.json()["control_id"]

    from agent_control_server.models import Control
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        existing_control = (
            session.query(Control).filter(Control.id == int(control_id)).first()
        )
        assert existing_control is not None

        async def mock_db_for_delete_control() -> AsyncGenerator[AsyncSession, None]:
            mock_session = AsyncMock(spec=AsyncSession)
            mock_session.commit.side_effect = Exception("Database error")

            control_result = MagicMock()
            control_result.scalars.return_value.first.return_value = existing_control
            assoc_result = MagicMock()
            assoc_result.all.return_value = []
            mock_session.execute = AsyncMock(
                side_effect=[control_result, assoc_result]
            )
            mock_session.delete = AsyncMock()
            mock_session.rollback = AsyncMock()
            yield mock_session

        # When: deleting the control and commit fails
        app.dependency_overrides[get_async_db] = mock_db_for_delete_control
        try:
            resp = client.delete(f"/api/v1/controls/{control_id}")
        finally:
            app.dependency_overrides.clear()

        # Then: rollback is called and 500 error is returned
        assert resp.status_code == 500
        assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_set_agent_policy_rollback_on_failure(
    app: FastAPI, client: TestClient, db_engine: object
) -> None:
    """Test that set_agent_policy rolls back transaction when commit fails."""
    # Given: an existing agent and policy
    agent_payload = {
        "agent": {
            "agent_name": str(uuid.uuid4()),
            "agent_name": f"test-agent-{uuid.uuid4()}",
            "agent_description": "test",
            "agent_version": "1.0",
            "agent_metadata": {},
        },
        "steps": [],
    }
    r1 = client.post("/api/v1/agents/initAgent", json=agent_payload)
    assert r1.status_code == 200
    agent_name = agent_payload["agent"]["agent_name"]

    policy_name = f"test-policy-{uuid.uuid4()}"
    r2 = client.put("/api/v1/policies", json={"name": policy_name})
    assert r2.status_code == 200
    policy_id = r2.json()["policy_id"]

    # When: commit fails during policy assignment
    from agent_control_server.models import Agent, Policy
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        existing_agent = (
            session.query(Agent)
            .filter(Agent.name == agent_name)
            .first()
        )
        existing_policy = (
            session.query(Policy)
            .filter(Policy.id == int(policy_id))
            .first()
        )
        assert existing_agent is not None
        assert existing_policy is not None

        async def mock_db_for_policy_assignment() -> AsyncGenerator[AsyncSession, None]:
            from unittest.mock import MagicMock
            
            mock_session = AsyncMock(spec=AsyncSession)
            mock_session.commit.side_effect = Exception("Database error")

            # Mock the agent query
            mock_agent_result = MagicMock()
            mock_agent_result.scalars.return_value.first.return_value = (
                existing_agent
            )

            # Mock the policy query
            mock_policy_result = MagicMock()
            mock_policy_result.scalars.return_value.first.return_value = (
                existing_policy
            )

            # Mock the controls query (for validation - returns empty list)
            mock_controls_result = MagicMock()
            mock_controls_result.scalars.return_value.unique.return_value.all.return_value = []

            # Mock existing policy associations query
            mock_existing_policy_assoc_result = MagicMock()
            mock_existing_policy_assoc_result.all.return_value = []

            # Mock delete/insert association statements
            mock_mutation_result = MagicMock()

            # Return different results for different queries
            mock_session.execute = AsyncMock(side_effect=[
                mock_agent_result,
                mock_policy_result,
                mock_controls_result,
                mock_existing_policy_assoc_result,
                mock_mutation_result,
                mock_mutation_result,
            ])
            yield mock_session

        app.dependency_overrides[get_async_db] = mock_db_for_policy_assignment
        try:
            resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")

            # Then: rollback is called and 500 error is returned
            assert resp.status_code == 500
            assert "database error" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


def test_set_control_data_rollback_on_failure(
    app: FastAPI, client: TestClient, db_engine: object
) -> None:
    """Test that set_control_data rolls back transaction when commit fails."""
    # Given: an existing control
    control_name = f"test-control-{uuid.uuid4()}"
    r1 = client.put("/api/v1/controls", json={"name": control_name})
    assert r1.status_code == 200
    control_id = r1.json()["control_id"]

    # When: commit fails during data update
    from agent_control_server.models import Control
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        existing_control = (
            session.query(Control).filter(Control.id == int(control_id)).first()
        )
        assert existing_control is not None

        async def mock_db_returns_control() -> AsyncGenerator[AsyncSession, None]:
            from unittest.mock import MagicMock
            
            mock_session = AsyncMock(spec=AsyncSession)
            mock_session.commit.side_effect = Exception("Database error")
            
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = existing_control
            mock_session.execute = AsyncMock(return_value=mock_result)
            
            yield mock_session

        app.dependency_overrides[get_async_db] = mock_db_returns_control
        try:
            valid_payload = {
                "description": "Valid Control",
                "enabled": True,
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "selector": {"path": "input"},
                "evaluator": {"name": "regex", "config": {"pattern": "x"}},
                "action": {"decision": "deny"}
            }
            resp = client.put(
                f"/api/v1/controls/{control_id}/data", json={"data": valid_payload}
            )

            # Then: rollback is called and 500 error is returned
            assert resp.status_code == 500
            assert "database error" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


def test_patch_control_rollback_on_failure(
    app: FastAPI, client: TestClient, db_engine: object
) -> None:
    """Test that patch_control rolls back when commit fails."""
    # Given: an existing control
    control_name = f"test-control-{uuid.uuid4()}"
    create_resp = client.put("/api/v1/controls", json={"name": control_name})
    assert create_resp.status_code == 200
    control_id = create_resp.json()["control_id"]

    from agent_control_server.models import Control
    from sqlalchemy.orm import Session

    with Session(db_engine) as session:
        existing_control = (
            session.query(Control).filter(Control.id == int(control_id)).first()
        )
        assert existing_control is not None

        async def mock_db_for_patch_control() -> AsyncGenerator[AsyncSession, None]:
            mock_session = AsyncMock(spec=AsyncSession)
            mock_session.commit.side_effect = Exception("Database error")

            control_result = MagicMock()
            control_result.scalars.return_value.first.return_value = existing_control
            name_check_result = MagicMock()
            name_check_result.first.return_value = None
            mock_session.execute = AsyncMock(
                side_effect=[control_result, name_check_result]
            )
            mock_session.rollback = AsyncMock()
            yield mock_session

        # When: patching the control and commit fails
        app.dependency_overrides[get_async_db] = mock_db_for_patch_control
        try:
            resp = client.patch(
                f"/api/v1/controls/{control_id}",
                json={"name": f"{control_name}-renamed"},
            )
        finally:
            app.dependency_overrides.clear()

        # Then: rollback is called and 500 error is returned
        assert resp.status_code == 500
        assert resp.json()["error_code"] == "DATABASE_ERROR"
