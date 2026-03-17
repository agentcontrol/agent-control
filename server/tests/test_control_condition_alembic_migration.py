"""Alembic coverage for legacy control condition normalization."""

from __future__ import annotations

import asyncio
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_control_server.config import db_config
from agent_control_server.db import get_async_db
from alembic import command

from .utils import VALID_CONTROL_PAYLOAD

SERVER_DIR = Path(__file__).resolve().parents[1]
PRE_MIGRATION_REVISION = "4b8c7d4a1f31"
MIGRATION_REVISION = "9f2f5a4e6c1b"
TEST_ADMIN_API_KEY = "test-admin-key-12345"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Control condition Alembic migration tests require PostgreSQL.",
)


def _legacy_control_payload() -> dict[str, Any]:
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["selector"] = payload["condition"]["selector"]
    payload["evaluator"] = payload["condition"]["evaluator"]
    payload.pop("condition")
    return payload


def _composite_control_payload() -> dict[str, Any]:
    first_leaf = deepcopy(VALID_CONTROL_PAYLOAD["condition"])
    second_leaf = {
        "selector": {"path": "output"},
        "evaluator": {"name": "regex", "config": {"pattern": "blocked"}},
    }
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"] = {"and": [first_leaf, second_leaf]}
    return payload


def _insert_control(engine: Engine, *, name: str, data: Any) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO controls (name, data)
                    VALUES (:name, CAST(:data AS JSONB))
                    RETURNING id
                    """
                ),
                {"name": name, "data": json.dumps(data)},
            ).scalar_one()
        )


def _fetch_controls(engine: Engine) -> list[tuple[int, str, Any]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, name, data FROM controls ORDER BY id")
        ).mappings()
        return [(int(row["id"]), str(row["name"]), row["data"]) for row in rows]


def _fetch_control_data(engine: Engine, control_id: int) -> Any:
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT data FROM controls WHERE id = :id"),
            {"id": control_id},
        ).scalar_one()


def _current_revision(engine: Engine) -> str | None:
    with engine.begin() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


@pytest.fixture
def temp_db_url() -> str:
    temp_db_name = f"agent_control_migration_{uuid.uuid4().hex[:12]}"
    admin_url = _BASE_DB_URL.set(database="postgres").render_as_string(hide_password=False)
    target_url = _BASE_DB_URL.set(database=temp_db_name).render_as_string(hide_password=False)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{temp_db_name}"'))
    admin_engine.dispose()

    try:
        yield target_url
    finally:
        cleanup_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with cleanup_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :db_name AND pid <> pg_backend_pid()
                    """
                ),
                {"db_name": temp_db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{temp_db_name}"'))
        cleanup_engine.dispose()


@pytest.fixture
def alembic_config(temp_db_url: str) -> Config:
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", temp_db_url)
    return cfg


@pytest.fixture
def temp_engine(temp_db_url: str) -> Engine:
    engine = create_engine(temp_db_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def upgrade_to(alembic_config: Config):
    def _upgrade(revision: str, *, sql: bool = False) -> None:
        command.upgrade(alembic_config, revision, sql=sql)

    return _upgrade


def test_upgrade_noops_when_no_legacy_rows_exist(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    _insert_control(temp_engine, name="canonical", data=deepcopy(VALID_CONTROL_PAYLOAD))
    _insert_control(temp_engine, name="draft", data={})

    before = _fetch_controls(temp_engine)

    upgrade_to(MIGRATION_REVISION)

    assert _fetch_controls(temp_engine) == before
    assert _current_revision(temp_engine) == MIGRATION_REVISION


def test_upgrade_rewrites_valid_legacy_rows(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    legacy_payload = _legacy_control_payload()
    control_id = _insert_control(temp_engine, name="legacy", data=legacy_payload)

    upgrade_to(MIGRATION_REVISION)

    migrated = _fetch_control_data(temp_engine, control_id)
    assert "selector" not in migrated
    assert "evaluator" not in migrated
    assert migrated["condition"]["selector"] == legacy_payload["selector"]
    assert migrated["condition"]["evaluator"] == legacy_payload["evaluator"]
    for field in ("description", "enabled", "execution", "scope", "action"):
        assert migrated[field] == legacy_payload[field]


def test_upgrade_rewrites_multiple_valid_legacy_rows(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    first_legacy = _legacy_control_payload()
    second_legacy = _legacy_control_payload()
    second_legacy["description"] = "second legacy control"
    second_legacy["scope"] = {"step_types": ["tool"], "stages": ["post"]}

    first_id = _insert_control(temp_engine, name="legacy-one", data=first_legacy)
    second_id = _insert_control(temp_engine, name="legacy-two", data=second_legacy)

    upgrade_to(MIGRATION_REVISION)

    first_migrated = _fetch_control_data(temp_engine, first_id)
    second_migrated = _fetch_control_data(temp_engine, second_id)

    for migrated, original in (
        (first_migrated, first_legacy),
        (second_migrated, second_legacy),
    ):
        assert "selector" not in migrated
        assert "evaluator" not in migrated
        assert migrated["condition"]["selector"] == original["selector"]
        assert migrated["condition"]["evaluator"] == original["evaluator"]
        for field in ("description", "enabled", "execution", "scope", "action"):
            assert migrated[field] == original[field]


def test_upgrade_preserves_empty_draft_rows(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    control_id = _insert_control(temp_engine, name="draft", data={})

    upgrade_to(MIGRATION_REVISION)

    assert _fetch_control_data(temp_engine, control_id) == {}


def test_upgrade_preserves_existing_composite_condition_trees(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    composite_payload = _composite_control_payload()
    control_id = _insert_control(temp_engine, name="composite", data=composite_payload)

    upgrade_to(MIGRATION_REVISION)

    assert _fetch_control_data(temp_engine, control_id) == composite_payload


def test_upgrade_fails_on_mixed_rows(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    mixed_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    mixed_payload["selector"] = {"path": "output"}
    control_id = _insert_control(temp_engine, name="mixed", data=mixed_payload)

    with pytest.raises(RuntimeError, match="mixed_invalid=1"):
        upgrade_to(MIGRATION_REVISION)

    assert _current_revision(temp_engine) == PRE_MIGRATION_REVISION
    assert _fetch_control_data(temp_engine, control_id) == mixed_payload


def test_upgrade_fails_on_partial_legacy_rows(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    partial_payload = _legacy_control_payload()
    partial_payload.pop("evaluator")
    control_id = _insert_control(temp_engine, name="partial", data=partial_payload)

    with pytest.raises(RuntimeError, match="partial_invalid=1"):
        upgrade_to(MIGRATION_REVISION)

    assert _current_revision(temp_engine) == PRE_MIGRATION_REVISION
    assert _fetch_control_data(temp_engine, control_id) == partial_payload


@pytest.mark.parametrize("payload", [[], "text", 123, None])
def test_upgrade_fails_on_non_object_json_rows(
    upgrade_to,
    temp_engine: Engine,
    payload: Any,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    control_id = _insert_control(temp_engine, name="non-object", data=payload)

    with pytest.raises(RuntimeError, match="non_object_invalid=1"):
        upgrade_to(MIGRATION_REVISION)

    assert _current_revision(temp_engine) == PRE_MIGRATION_REVISION
    assert _fetch_control_data(temp_engine, control_id) == payload


def test_upgrade_is_atomic_when_valid_and_invalid_rows_are_mixed(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    valid_legacy = _legacy_control_payload()
    valid_id = _insert_control(temp_engine, name="legacy", data=valid_legacy)
    invalid_partial = _legacy_control_payload()
    invalid_partial.pop("evaluator")
    _insert_control(temp_engine, name="invalid", data=invalid_partial)

    with pytest.raises(RuntimeError, match="partial_invalid=1"):
        upgrade_to(MIGRATION_REVISION)

    assert _current_revision(temp_engine) == PRE_MIGRATION_REVISION
    assert _fetch_control_data(temp_engine, valid_id) == valid_legacy


def test_upgrade_error_message_includes_invalid_counts_and_sample_ids(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    mixed_id = _insert_control(
        temp_engine,
        name="mixed",
        data={**deepcopy(VALID_CONTROL_PAYLOAD), "selector": {"path": "output"}},
    )
    partial_payload = _legacy_control_payload()
    partial_payload.pop("evaluator")
    partial_id = _insert_control(temp_engine, name="partial", data=partial_payload)
    missing_id = _insert_control(
        temp_engine,
        name="missing-condition",
        data={"description": "not empty but missing all condition fields"},
    )
    non_object_id = _insert_control(temp_engine, name="non-object", data=[])

    with pytest.raises(RuntimeError) as exc_info:
        upgrade_to(MIGRATION_REVISION)

    message = str(exc_info.value)
    assert "mixed_invalid=1" in message
    assert "partial_invalid=1" in message
    assert "missing_condition_invalid=1" in message
    assert "non_object_invalid=1" in message
    assert f"id={mixed_id}" in message
    assert f"id={partial_id}" in message
    assert f"id={missing_id}" in message
    assert f"id={non_object_id}" in message


def test_offline_upgrade_is_rejected(
    alembic_config: Config,
) -> None:
    with pytest.raises(RuntimeError, match="live database connection"):
        command.upgrade(alembic_config, MIGRATION_REVISION, sql=True)


def test_post_migration_api_returns_canonical_shape_for_rewritten_rows(
    app: FastAPI,
    upgrade_to,
    temp_db_url: str,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    control_id = _insert_control(temp_engine, name="legacy-api", data=_legacy_control_payload())

    upgrade_to("head")

    async_engine = create_async_engine(temp_db_url, echo=False)
    session_factory = async_sessionmaker(
        bind=async_engine,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async def _override_get_async_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_db] = _override_get_async_db
    try:
        with TestClient(
            app,
            raise_server_exceptions=True,
            headers={"X-API-Key": TEST_ADMIN_API_KEY},
        ) as client:
            response = client.get(f"/api/v1/controls/{control_id}/data")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "selector" not in data
        assert "evaluator" not in data
        assert data["condition"]["selector"]["path"] == "input"
        assert data["condition"]["evaluator"]["name"] == "regex"
    finally:
        app.dependency_overrides.pop(get_async_db, None)
        asyncio.run(async_engine.dispose())
