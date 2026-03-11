"""Tests for evaluator config store endpoints."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_control_server.db import get_async_db
from agent_control_server.endpoints import evaluator_configs as evaluator_configs_module
from agent_control_server.models import EvaluatorConfigDB


def _default_config_for_evaluator(evaluator: str) -> dict:
    if evaluator == "list":
        return {"values": ["blocked"], "logic": "any", "match_on": "match"}
    if evaluator == "regex":
        return {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"}
    return {}


def _create_config_payload(
    name: str,
    evaluator: str = "regex",
    config: dict | None = None,
    description: str | None = None,
) -> dict:
    return {
        "name": name,
        "description": description,
        "evaluator": evaluator,
        "config": config if config is not None else _default_config_for_evaluator(evaluator),
    }


def _create_config(client: TestClient, name: str, evaluator: str = "regex") -> dict:
    payload = _create_config_payload(name=name, evaluator=evaluator)
    resp = client.post("/api/v1/evaluator-configs", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _make_config(
    *,
    config_id: int,
    name: str,
    evaluator: str = "regex",
    config: dict | None = None,
) -> EvaluatorConfigDB:
    return EvaluatorConfigDB(
        id=config_id,
        name=name,
        description=None,
        evaluator=evaluator,
        config=config or {"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def test_create_evaluator_config_success(client: TestClient) -> None:
    # Given: a valid evaluator config payload
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name)

    # When: creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: it is created and returned
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["name"] == name
    assert data["evaluator"] == "regex"
    assert data["config"]["pattern"] == payload["config"]["pattern"]
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


def test_create_evaluator_config_duplicate_name_409(client: TestClient) -> None:
    # Given: an existing evaluator config name
    name = f"config-{uuid.uuid4().hex}"
    _create_config(client, name=name)

    # When: creating another with the same name
    resp = client.post("/api/v1/evaluator-configs", json=_create_config_payload(name=name))

    # Then: conflict error is returned
    assert resp.status_code == 409
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NAME_CONFLICT"


def test_create_evaluator_config_unknown_evaluator_allowed(client: TestClient) -> None:
    # Given: a payload with an unknown evaluator name
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="unknown-evaluator", config={})

    # When: creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: it succeeds (validation skipped)
    assert resp.status_code == 201
    data = resp.json()
    assert data["evaluator"] == "unknown-evaluator"


def test_create_evaluator_config_agent_scoped_rejected(client: TestClient) -> None:
    # Given: a payload referencing an agent-scoped evaluator
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="agent:custom", config={})

    # When: creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: validation error is returned
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    assert any(err.get("field") == "evaluator" for err in data.get("errors", []))


def test_create_evaluator_config_invalid_config_422(client: TestClient) -> None:
    # Given: a payload with invalid config for regex evaluator
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="regex", config={"flags": ["IGNORECASE"]})

    # When: creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: validation error is returned
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "INVALID_CONFIG"
    assert any("config" in str(err.get("field", "")) for err in data.get("errors", []))


def test_create_evaluator_config_invalid_parameters_type_error_422(
    client: TestClient, monkeypatch
) -> None:
    # Given: a known evaluator whose config model raises TypeError
    class DummyEvaluator:
        @staticmethod
        def config_model(**_kwargs):  # type: ignore[no-untyped-def]
            raise TypeError("unexpected parameter")

    monkeypatch.setattr(
        evaluator_configs_module,
        "list_evaluators",
        lambda: {"dummy": DummyEvaluator},
    )

    payload = _create_config_payload(name=f"config-{uuid.uuid4().hex}", evaluator="dummy")

    # When: creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: invalid config is returned with parameter error details
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "INVALID_CONFIG"
    assert any(err.get("code") == "invalid_parameters" for err in data.get("errors", []))
    assert any(
        err.get("message") == "Invalid config parameters for evaluator."
        for err in data.get("errors", [])
    )
    assert "unexpected parameter" not in resp.text


def test_create_evaluator_config_integrity_error_name_conflict(
    app: FastAPI, client: TestClient
) -> None:
    # Given: a database constraint name matching the unique index
    class DummyOrig:
        constraint_name = "evaluator_configs_name_key"

        def __str__(self) -> str:
            return "duplicate key value violates unique constraint"

    integrity_error = IntegrityError("stmt", {}, DummyOrig())

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = integrity_error
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: creating a config and the DB raises a name conflict
    app.dependency_overrides[get_async_db] = mock_db
    try:
        payload = _create_config_payload(name=f"config-{uuid.uuid4().hex}")
        resp = client.post("/api/v1/evaluator-configs", json=payload)
    finally:
        app.dependency_overrides.clear()

    # Then: a conflict error is returned
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "EVALUATOR_CONFIG_NAME_CONFLICT"


def test_create_evaluator_config_integrity_error_returns_500(
    app: FastAPI, client: TestClient
) -> None:
    # Given: a database integrity error that is not a name conflict
    class DummyOrig:
        constraint_name = "other_constraint"

        def __str__(self) -> str:
            return "foreign key violation"

    integrity_error = IntegrityError("stmt", {}, DummyOrig())

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = integrity_error
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: creating the evaluator config
    app.dependency_overrides[get_async_db] = mock_db
    try:
        payload = _create_config_payload(name=f"config-{uuid.uuid4().hex}")
        resp = client.post("/api/v1/evaluator-configs", json=payload)
    finally:
        app.dependency_overrides.clear()

    # Then: a database error is returned
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_create_evaluator_config_commit_failure_returns_500(
    app: FastAPI, client: TestClient
) -> None:
    # Given: a database session that fails on commit
    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.add = MagicMock()
        mock_session.commit.side_effect = Exception("db error")
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: creating the evaluator config
    app.dependency_overrides[get_async_db] = mock_db
    try:
        payload = _create_config_payload(name=f"config-{uuid.uuid4().hex}")
        resp = client.post("/api/v1/evaluator-configs", json=payload)
    finally:
        app.dependency_overrides.clear()

    # Then: a database error is returned
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_update_evaluator_config_replaces_fields_and_updates_timestamp(
    client: TestClient,
) -> None:
    # Given: an existing evaluator config
    name = f"config-{uuid.uuid4().hex}"
    created = _create_config(client, name=name)

    # And: a time gap to ensure updated_at changes
    time.sleep(0.01)

    # When: updating the evaluator config via PUT
    payload = _create_config_payload(
        name=f"{name}-v2",
        evaluator="regex",
        config={"pattern": r"\b\d{4}\b"},
        description="Updated description",
    )
    resp = client.put(f"/api/v1/evaluator-configs/{created['id']}", json=payload)

    # Then: the config is replaced and updated_at changes
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == payload["name"]
    assert data["config"]["pattern"] == payload["config"]["pattern"]
    assert data["description"] == payload["description"]

    created_at = datetime.fromisoformat(created["created_at"])
    updated_at_before = datetime.fromisoformat(created["updated_at"])
    updated_at_after = datetime.fromisoformat(data["updated_at"])

    assert updated_at_after >= updated_at_before
    assert updated_at_after >= created_at


def test_update_evaluator_config_name_conflict_409(client: TestClient) -> None:
    # Given: two existing evaluator configs
    first = _create_config(client, name=f"config-{uuid.uuid4().hex}")
    second = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: updating second to use first's name
    payload = _create_config_payload(
        name=first["name"],
        evaluator="regex",
        config={"pattern": r"\btest\b"},
    )
    resp = client.put(f"/api/v1/evaluator-configs/{second['id']}", json=payload)

    # Then: conflict error is returned
    assert resp.status_code == 409
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NAME_CONFLICT"


def test_update_evaluator_config_invalid_config_422(client: TestClient) -> None:
    # Given: an existing evaluator config
    created = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: updating with invalid config for regex evaluator
    payload = _create_config_payload(
        name=created["name"],
        evaluator="regex",
        config={"flags": ["IGNORECASE"]},
    )
    resp = client.put(f"/api/v1/evaluator-configs/{created['id']}", json=payload)

    # Then: validation error is returned
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "INVALID_CONFIG"


def test_update_evaluator_config_agent_scoped_rejected(client: TestClient) -> None:
    # Given: an existing evaluator config
    created = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: updating with agent-scoped evaluator
    payload = _create_config_payload(
        name=created["name"],
        evaluator="agent:custom",
        config={},
    )
    resp = client.put(f"/api/v1/evaluator-configs/{created['id']}", json=payload)

    # Then: validation error is returned
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "VALIDATION_ERROR"


def test_update_evaluator_config_unknown_evaluator_allowed(client: TestClient) -> None:
    # Given: an existing evaluator config
    created = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: updating to an unknown evaluator
    payload = _create_config_payload(
        name=created["name"],
        evaluator="unknown-evaluator",
        config={},
    )
    resp = client.put(f"/api/v1/evaluator-configs/{created['id']}", json=payload)

    # Then: update succeeds and evaluator name is persisted
    assert resp.status_code == 200
    data = resp.json()
    assert data["evaluator"] == "unknown-evaluator"


def test_update_evaluator_config_integrity_error_returns_500(
    app: FastAPI, client: TestClient
) -> None:
    # Given: an existing evaluator config resolved from the DB
    existing = _make_config(config_id=42, name="config-error")
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing

    class DummyOrig:
        constraint_name = "other_constraint"

        def __str__(self) -> str:
            return "foreign key violation"

    integrity_error = IntegrityError("stmt", {}, DummyOrig())

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(return_value=result)
        mock_session.commit.side_effect = integrity_error
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: updating the evaluator config and the DB raises an integrity error
    app.dependency_overrides[get_async_db] = mock_db
    try:
        payload = _create_config_payload(
            name="config-error",
            evaluator="regex",
            config={"pattern": "ok"},
        )
        resp = client.put("/api/v1/evaluator-configs/42", json=payload)
    finally:
        app.dependency_overrides.clear()

    # Then: a database error is returned
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_update_evaluator_config_commit_failure_returns_500(
    app: FastAPI, client: TestClient
) -> None:
    # Given: an existing evaluator config resolved from the DB
    existing = _make_config(config_id=43, name="config-commit-error")
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(return_value=result)
        mock_session.commit.side_effect = Exception("db error")
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: updating the evaluator config and the commit fails
    app.dependency_overrides[get_async_db] = mock_db
    try:
        payload = _create_config_payload(
            name="config-commit-error",
            evaluator="regex",
            config={"pattern": "ok"},
        )
        resp = client.put("/api/v1/evaluator-configs/43", json=payload)
    finally:
        app.dependency_overrides.clear()

    # Then: a database error is returned
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_list_evaluator_configs_cursor_pagination(client: TestClient) -> None:
    # Given: multiple evaluator configs
    base = f"config-{uuid.uuid4().hex}"
    _create_config(client, name=f"{base}-a")
    _create_config(client, name=f"{base}-b")
    _create_config(client, name=f"{base}-c")

    # When: requesting first page with limit=2
    resp = client.get("/api/v1/evaluator-configs", params={"limit": 2})
    assert resp.status_code == 200
    page1 = resp.json()
    assert page1["pagination"]["has_more"] is True
    assert page1["pagination"]["next_cursor"] is not None

    # When: requesting next page using cursor
    cursor = page1["pagination"]["next_cursor"]
    resp2 = client.get("/api/v1/evaluator-configs", params={"limit": 2, "cursor": cursor})
    assert resp2.status_code == 200
    page2 = resp2.json()

    # Then: remaining items are returned and has_more is False
    assert page2["pagination"]["has_more"] is False
    assert len(page2["evaluator_configs"]) >= 1


def test_get_evaluator_config_not_found(client: TestClient) -> None:
    # Given: a non-existent evaluator config ID
    missing_id = 999999

    # When: fetching the evaluator config
    resp = client.get(f"/api/v1/evaluator-configs/{missing_id}")

    # Then: not found error is returned
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NOT_FOUND"


def test_get_evaluator_config_success(client: TestClient) -> None:
    # Given: an existing evaluator config
    created = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: fetching the evaluator config by id
    resp = client.get(f"/api/v1/evaluator-configs/{created['id']}")

    # Then: the config details are returned
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == created["id"]
    assert data["name"] == created["name"]
    assert data["evaluator"] == created["evaluator"]


def test_list_evaluator_configs_with_filters_and_pagination(
    client: TestClient,
) -> None:
    # Given: multiple evaluator configs
    base = f"config-{uuid.uuid4().hex}"
    _create_config(client, name=f"{base}-a", evaluator="regex")
    _create_config(client, name=f"{base}-b", evaluator="regex")
    _create_config(client, name=f"{base}-c", evaluator="regex")
    _create_config(client, name=f"{base}-d", evaluator="list")

    # When: listing with limit and evaluator filter
    resp = client.get(
        "/api/v1/evaluator-configs",
        params={"limit": 2, "evaluator": "regex", "name": base},
    )

    # Then: pagination metadata is correct
    assert resp.status_code == 200
    data = resp.json()
    assert data["pagination"]["limit"] == 2
    assert data["pagination"]["has_more"] is True
    assert len(data["evaluator_configs"]) == 2
    assert all(cfg["evaluator"] == "regex" for cfg in data["evaluator_configs"])
    assert data["pagination"]["total"] == 3


def test_list_evaluator_configs_filter_by_evaluator_only(client: TestClient) -> None:
    # Given: configs across different evaluators
    _create_config(client, name=f"config-{uuid.uuid4().hex}", evaluator="regex")
    _create_config(client, name=f"config-{uuid.uuid4().hex}", evaluator="regex")
    _create_config(client, name=f"config-{uuid.uuid4().hex}", evaluator="list")

    # When: filtering by evaluator only
    resp = client.get("/api/v1/evaluator-configs", params={"evaluator": "regex"})

    # Then: only regex configs are returned
    assert resp.status_code == 200
    data = resp.json()
    assert data["pagination"]["total"] == 2
    assert all(cfg["evaluator"] == "regex" for cfg in data["evaluator_configs"])


def test_list_evaluator_configs_filter_by_name_only(client: TestClient) -> None:
    # Given: configs with a shared name prefix
    base = f"config-{uuid.uuid4().hex}"
    _create_config(client, name=f"{base}-a", evaluator="regex")
    _create_config(client, name=f"{base}-b", evaluator="list")
    _create_config(client, name=f"other-{uuid.uuid4().hex}", evaluator="regex")

    # When: filtering by name prefix only
    resp = client.get("/api/v1/evaluator-configs", params={"name": base})

    # Then: only matching names are returned
    assert resp.status_code == 200
    data = resp.json()
    assert data["pagination"]["total"] == 2
    assert all(base in cfg["name"] for cfg in data["evaluator_configs"])


def test_update_evaluator_config_not_found(client: TestClient) -> None:
    # Given: a non-existent evaluator config ID
    missing_id = 999999

    # When: updating the evaluator config
    payload = _create_config_payload(
        name=f"config-{uuid.uuid4().hex}",
        evaluator="regex",
        config={"pattern": r"\\btest\\b"},
    )
    resp = client.put(f"/api/v1/evaluator-configs/{missing_id}", json=payload)

    # Then: not found error is returned
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NOT_FOUND"


def test_delete_evaluator_config_success(client: TestClient) -> None:
    # Given: an existing evaluator config
    created = _create_config(client, name=f"config-{uuid.uuid4().hex}")

    # When: deleting the evaluator config
    resp = client.delete(f"/api/v1/evaluator-configs/{created['id']}")

    # Then: success is returned and the config is gone
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    get_resp = client.get(f"/api/v1/evaluator-configs/{created['id']}")
    assert get_resp.status_code == 404


def test_delete_evaluator_config_not_found(client: TestClient) -> None:
    # Given: a non-existent evaluator config ID
    missing_id = 999999

    # When: deleting the evaluator config
    resp = client.delete(f"/api/v1/evaluator-configs/{missing_id}")

    # Then: not found error is returned
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "EVALUATOR_CONFIG_NOT_FOUND"


def test_delete_evaluator_config_commit_failure_returns_500(
    app: FastAPI, client: TestClient
) -> None:
    # Given: an existing evaluator config resolved from the DB
    existing = _make_config(config_id=99, name="config-delete-error")
    result = MagicMock()
    result.scalars.return_value.first.return_value = existing

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(return_value=result)
        mock_session.delete = AsyncMock()
        mock_session.commit.side_effect = Exception("db error")
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: deleting the evaluator config and the commit fails
    app.dependency_overrides[get_async_db] = mock_db
    try:
        resp = client.delete("/api/v1/evaluator-configs/99")
    finally:
        app.dependency_overrides.clear()

    # Then: a database error is returned
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_create_evaluator_config_empty_config_allowed(client: TestClient) -> None:
    # Given: a payload with an empty config object
    name = f"config-{uuid.uuid4().hex}"
    payload = _create_config_payload(name=name, evaluator="unknown-evaluator", config={})

    # When: creating the evaluator config
    resp = client.post("/api/v1/evaluator-configs", json=payload)

    # Then: it succeeds (empty config is valid)
    assert resp.status_code == 201
    data = resp.json()
    assert data["config"] == {}


def test_list_evaluator_configs_name_filter_escapes_like_wildcards(
    client: TestClient,
) -> None:
    # Given: configs where one name contains a literal underscore
    base = f"config-{uuid.uuid4().hex}"
    _create_config(client, name=f"{base}_special")
    _create_config(client, name=f"{base}Xnomatch")

    # When: searching with "_" which is a LIKE wildcard for "any single character"
    resp = client.get("/api/v1/evaluator-configs", params={"name": f"{base}_"})

    # Then: only the config with a literal underscore matches, not the one with "X"
    assert resp.status_code == 200
    data = resp.json()
    names = [cfg["name"] for cfg in data["evaluator_configs"]]
    assert f"{base}_special" in names
    assert f"{base}Xnomatch" not in names
