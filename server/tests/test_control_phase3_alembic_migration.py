"""Alembic coverage for Phase 3 control-store schema changes."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_control_server.config import db_config
from agent_control_server.db import get_async_db
from alembic import command

from .conftest import TEST_ADMIN_API_KEY
from .utils import VALID_CONTROL_PAYLOAD

SERVER_DIR = Path(__file__).resolve().parents[1]
PRE_MIGRATION_REVISION = "c1e9f9c4a1d2"
MIGRATION_REVISION = "7d9c2f1a3b44"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Phase 3 Alembic migration tests require PostgreSQL.",
)


def _insert_control(
    engine: Engine,
    *,
    name: str,
    data: dict[str, object] | None = None,
) -> int:
    payload = data if data is not None else {"description": "pre-phase3"}
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
                {"name": name, "data": json.dumps(payload)},
            ).scalar_one()
        )


def _insert_policy(engine: Engine, *, name: str) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO policies (name)
                    VALUES (:name)
                    RETURNING id
                    """
                ),
                {"name": name},
            ).scalar_one()
        )


def _insert_agent(engine: Engine, *, name: str) -> str:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO agents (name, data)
                VALUES (:name, CAST(:data AS JSONB))
                """
            ),
            {
                "name": name,
                "data": json.dumps(
                    {
                        "agent_metadata": {},
                        "steps": [],
                        "evaluators": [],
                    }
                ),
            },
        )
    return name


@pytest.fixture
def temp_db_url() -> str:
    temp_db_name = f"agent_control_phase3_{uuid.uuid4().hex[:12]}"
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


def test_upgrade_seeds_default_store_and_adds_clone_provenance(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    control_id = _insert_control(temp_engine, name="pre-phase3-control")

    upgrade_to(MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        stores = conn.execute(
            text("SELECT id, name FROM control_stores ORDER BY id")
        ).mappings().all()
        control = conn.execute(
            text(
                """
                SELECT id, cloned_control_id
                FROM controls
                WHERE id = :control_id
                """
            ),
            {"control_id": control_id},
        ).mappings().one()

    assert stores == [{"id": 1, "name": "default"}]
    assert control["cloned_control_id"] is None
    assert "control_stores_controls" in inspect(temp_engine).get_table_names()


def test_upgrade_advances_control_store_identity_after_default_seed(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)
    upgrade_to(MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        next_store_id = int(
            conn.execute(
                text(
                    """
                    INSERT INTO control_stores (name)
                    VALUES ('post-seed-store')
                    RETURNING id
                    """
                )
            ).scalar_one()
        )

    assert next_store_id > 1


def test_pre_phase3_runtime_control_endpoints_remain_usable_during_rollout(
    app: FastAPI,
    upgrade_to,
    temp_db_url: str,
    temp_engine: Engine,
) -> None:
    # Given: a database upgraded only to the pre-Phase-3 schema
    upgrade_to(PRE_MIGRATION_REVISION)
    policy_control_id = _insert_control(
        temp_engine,
        name="pre-phase3-policy-control",
        data=VALID_CONTROL_PAYLOAD,
    )
    agent_control_id = _insert_control(
        temp_engine,
        name="pre-phase3-agent-control",
        data=VALID_CONTROL_PAYLOAD,
    )
    delete_control_id = _insert_control(
        temp_engine,
        name="pre-phase3-delete-control",
        data=VALID_CONTROL_PAYLOAD,
    )
    policy_id = _insert_policy(temp_engine, name="pre-phase3-policy")
    agent_name = _insert_agent(temp_engine, name="pre-phase3-agent")

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
            # When: using existing runtime endpoints against legacy rows before store tables exist
            create_response = client.put(
                "/api/v1/controls",
                json={
                    "name": "pre-phase3-created-control",
                    "data": VALID_CONTROL_PAYLOAD,
                },
            )
            policy_assoc = client.post(
                f"/api/v1/policies/{policy_id}/controls/{policy_control_id}"
            )

            agent_assoc = client.post(
                f"/api/v1/agents/{agent_name}/controls/{agent_control_id}"
            )

            controls_response = client.get("/api/v1/controls")
            agent_controls_response = client.get(f"/api/v1/agents/{agent_name}/controls")
            delete_response = client.delete(f"/api/v1/controls/{delete_control_id}")

            # Then: the legacy runtime endpoints and read paths still succeed
            # without control-store tables
            assert create_response.status_code == 200, create_response.text
            assert policy_assoc.status_code == 200, policy_assoc.text
            assert agent_assoc.status_code == 200, agent_assoc.text
            assert controls_response.status_code == 200, controls_response.text
            assert agent_controls_response.status_code == 200, agent_controls_response.text
            assert delete_response.status_code == 200, delete_response.text
            assert {
                control["name"] for control in controls_response.json()["controls"]
            } >= {
                "pre-phase3-created-control",
                "pre-phase3-policy-control",
                "pre-phase3-agent-control",
            }
            assert [
                control["id"] for control in agent_controls_response.json()["controls"]
            ] == [agent_control_id]
    finally:
        app.dependency_overrides.pop(get_async_db, None)
        asyncio.run(async_engine.dispose())


def test_pre_phase3_control_store_endpoints_fail_gracefully(
    app: FastAPI,
    upgrade_to,
    temp_db_url: str,
    temp_engine: Engine,
) -> None:
    # Given: a database that has not yet received the Phase 3 store schema
    upgrade_to(PRE_MIGRATION_REVISION)
    control_id = _insert_control(
        temp_engine,
        name="pre-phase3-store-control",
        data=VALID_CONTROL_PAYLOAD,
    )

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
            # When: calling new control-store endpoints before the migration lands
            publish_response = client.post(
                f"/api/v1/control-stores/default/controls/{control_id}"
            )
            unpublish_response = client.delete(
                f"/api/v1/control-stores/default/controls/{control_id}"
            )
            list_response = client.get("/api/v1/control-stores/default/controls")

            # Then: the endpoints fail with the standard database error envelope
            assert publish_response.status_code == 500, publish_response.text
            assert publish_response.json()["error_code"] == "DATABASE_ERROR"
            assert unpublish_response.status_code == 500, unpublish_response.text
            assert unpublish_response.json()["error_code"] == "DATABASE_ERROR"
            assert list_response.status_code == 500, list_response.text
            assert list_response.json()["error_code"] == "DATABASE_ERROR"
    finally:
        app.dependency_overrides.pop(get_async_db, None)
        asyncio.run(async_engine.dispose())
