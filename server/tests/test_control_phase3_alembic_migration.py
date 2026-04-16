"""Alembic coverage for Phase 3 control-store schema changes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from agent_control_server.config import db_config
from alembic import command

SERVER_DIR = Path(__file__).resolve().parents[1]
PRE_MIGRATION_REVISION = "c1e9f9c4a1d2"
MIGRATION_REVISION = "7d9c2f1a3b44"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Phase 3 Alembic migration tests require PostgreSQL.",
)


def _insert_control(engine: Engine, *, name: str) -> int:
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
                {"name": name, "data": json.dumps({"description": "pre-phase3"})},
            ).scalar_one()
        )


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
