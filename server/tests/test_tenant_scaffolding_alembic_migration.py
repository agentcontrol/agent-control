"""Alembic coverage for the tenant scaffolding and targets schema migration."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from agent_control_server.config import db_config
from agent_control_server.models import DEFAULT_TENANT_ID

SERVER_DIR = Path(__file__).resolve().parents[1]
PRE_MIGRATION_REVISION = "5f2b5f4e1a90"
MIGRATION_REVISION = "7c1a9b4e2d30"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Tenant scaffolding Alembic migration tests require PostgreSQL.",
)

_AGENT_NAME = "legacy-agent-01"
_CONTROL_NAME = "legacy-control"
_POLICY_NAME = "legacy-policy"


@pytest.fixture
def temp_db_url() -> str:
    temp_db_name = f"agent_control_tenant_{uuid.uuid4().hex[:12]}"
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


def _seed_pre_migration_rows(engine: Engine) -> tuple[int, int]:
    """Insert one row each into the tenant-bearing tables and return (control_id, policy_id)."""
    with engine.begin() as conn:
        control_id = int(
            conn.execute(
                text(
                    "INSERT INTO controls (name, data) "
                    "VALUES (:name, CAST(:data AS JSONB)) RETURNING id"
                ),
                {"name": _CONTROL_NAME, "data": json.dumps({})},
            ).scalar_one()
        )
        policy_id = int(
            conn.execute(
                text("INSERT INTO policies (name) VALUES (:name) RETURNING id"),
                {"name": _POLICY_NAME},
            ).scalar_one()
        )
        conn.execute(
            text(
                "INSERT INTO agents (name, data) "
                "VALUES (:name, CAST(:data AS JSONB))"
            ),
            {"name": _AGENT_NAME, "data": json.dumps({})},
        )
        conn.execute(
            text(
                "INSERT INTO agent_controls (agent_name, control_id) "
                "VALUES (:agent, :control)"
            ),
            {"agent": _AGENT_NAME, "control": control_id},
        )
        conn.execute(
            text(
                "INSERT INTO agent_policies (agent_name, policy_id) "
                "VALUES (:agent, :policy)"
            ),
            {"agent": _AGENT_NAME, "policy": policy_id},
        )
    return control_id, policy_id


def test_migration_backfills_existing_rows_to_default_tenant(
    alembic_config: Config,
    temp_engine: Engine,
) -> None:
    """Pre-existing rows on all tenant-bearing tables must land in DEFAULT_TENANT_ID."""
    command.upgrade(alembic_config, PRE_MIGRATION_REVISION)
    _seed_pre_migration_rows(temp_engine)

    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        for table in ("agents", "controls", "policies", "agent_controls", "agent_policies"):
            rows = conn.execute(text(f"SELECT tenant_id FROM {table}")).all()
            assert rows, f"expected at least one seeded row in {table}"
            for (tenant_id,) in rows:
                assert tenant_id == DEFAULT_TENANT_ID, (
                    f"{table} row was not backfilled to the default tenant"
                )


def test_migration_creates_targets_and_target_controls(
    alembic_config: Config,
    temp_engine: Engine,
) -> None:
    """New tables exist with the expected uniqueness constraints."""
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO targets (tenant_id, target_type, external_id, name) "
                "VALUES (:tenant, 'environment', 'ext-1', 'production')"
            ),
            {"tenant": DEFAULT_TENANT_ID},
        )
        # Duplicate on (tenant_id, target_type, external_id) must be rejected.
        with pytest.raises(Exception):
            conn.execute(
                text(
                    "INSERT INTO targets (tenant_id, target_type, external_id, name) "
                    "VALUES (:tenant, 'environment', 'ext-1', 'dup')"
                ),
                {"tenant": DEFAULT_TENANT_ID},
            )


def test_migration_server_default_preserves_oss_writes(
    alembic_config: Config,
    temp_engine: Engine,
) -> None:
    """Inserting without tenant_id after migration still lands on DEFAULT_TENANT_ID."""
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO controls (name, data) "
                "VALUES (:name, CAST('{}' AS JSONB))"
            ),
            {"name": "post-migration-control"},
        )
        tenant_id = conn.execute(
            text("SELECT tenant_id FROM controls WHERE name = :name"),
            {"name": "post-migration-control"},
        ).scalar_one()
        assert tenant_id == DEFAULT_TENANT_ID


def test_migration_downgrade_drops_tenant_and_target_objects(
    alembic_config: Config,
    temp_engine: Engine,
) -> None:
    """Downgrade is complete: tenant_id columns are gone and new tables are dropped."""
    command.upgrade(alembic_config, MIGRATION_REVISION)
    command.downgrade(alembic_config, PRE_MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        tables = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        ).scalars().all()
        assert "targets" not in tables
        assert "target_controls" not in tables

        for table in ("agents", "controls", "policies", "agent_controls", "agent_policies"):
            columns = conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table},
            ).scalars().all()
            assert "tenant_id" not in columns, f"tenant_id leaked on {table} after downgrade"
