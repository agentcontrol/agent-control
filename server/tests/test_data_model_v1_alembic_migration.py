"""Alembic coverage for the namespace scoping and control bindings migration."""

from __future__ import annotations

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
MIGRATION_REVISION = "a7f3b1e0d9c5"
OBSERVABILITY_NAMESPACE_REVISION = "b6f4c2d8e9a1"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Alembic migration tests require PostgreSQL.",
)


@pytest.fixture
def temp_db_url() -> str:
    temp_db_name = f"agent_control_dmv1_{uuid.uuid4().hex[:12]}"
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


def _column_names(engine: Engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def _index_names(engine: Engine, table: str) -> set[str]:
    return {i["name"] for i in inspect(engine).get_indexes(table)}


def _foreign_key_names(engine: Engine, table: str) -> set[str]:
    return {fk["name"] for fk in inspect(engine).get_foreign_keys(table)}


def _unique_constraint_names(engine: Engine, table: str) -> set[str]:
    return {uc["name"] for uc in inspect(engine).get_unique_constraints(table)}


def _pk_columns(engine: Engine, table: str) -> list[str]:
    return list(inspect(engine).get_pk_constraint(table)["constrained_columns"])


def _assert_observability_namespace_schema(engine: Engine) -> None:
    assert "namespace_key" in _column_names(engine, "control_execution_events")
    assert _pk_columns(engine, "control_execution_events") == [
        "namespace_key",
        "control_execution_id",
    ]
    indexes = _index_names(engine, "control_execution_events")
    assert "ix_events_namespace_agent_time" in indexes
    assert "ix_events_agent_time" not in indexes


def test_upgrade_applies_namespace_columns_and_constraints(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)

    for table in (
        "agents",
        "controls",
        "policies",
        "agent_controls",
        "agent_policies",
        "policy_controls",
    ):
        assert "namespace_key" in _column_names(temp_engine, table), table

    assert _pk_columns(temp_engine, "agents") == ["namespace_key", "name"]
    assert _pk_columns(temp_engine, "agent_controls") == [
        "namespace_key",
        "agent_name",
        "control_id",
    ]
    assert _pk_columns(temp_engine, "agent_policies") == [
        "namespace_key",
        "agent_name",
        "policy_id",
    ]
    assert _pk_columns(temp_engine, "policy_controls") == [
        "namespace_key",
        "policy_id",
        "control_id",
    ]

    assert "uq_policies_namespace_name" in _unique_constraint_names(
        temp_engine, "policies"
    )
    assert "uq_policies_namespace_id" in _unique_constraint_names(
        temp_engine, "policies"
    )
    assert "uq_controls_namespace_id" in _unique_constraint_names(
        temp_engine, "controls"
    )
    assert "idx_controls_namespace_name_active" in _index_names(
        temp_engine, "controls"
    )

    assert {
        "agent_controls_agent_fkey",
        "agent_controls_control_fkey",
    } <= _foreign_key_names(temp_engine, "agent_controls")
    assert {
        "agent_policies_agent_fkey",
        "agent_policies_policy_fkey",
    } <= _foreign_key_names(temp_engine, "agent_policies")
    assert {
        "policy_controls_policy_fkey",
        "policy_controls_control_fkey",
    } <= _foreign_key_names(temp_engine, "policy_controls")

    # Plain natural-key indexes preserve name-only lookup performance while
    # service code is still namespace-blind.
    assert "ix_agents_name" in _index_names(temp_engine, "agents")
    assert "ix_policies_name" in _index_names(temp_engine, "policies")
    assert "ix_controls_name" in _index_names(temp_engine, "controls")


def test_upgrade_creates_control_bindings(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)

    assert "control_bindings" in inspect(temp_engine).get_table_names()

    columns = _column_names(temp_engine, "control_bindings")
    assert {
        "id",
        "namespace_key",
        "target_type",
        "target_id",
        "control_id",
        "enabled",
        "created_at",
        "updated_at",
    } <= columns

    assert "idx_control_bindings_lookup" in _index_names(
        temp_engine, "control_bindings"
    )
    assert "uq_control_bindings_target_control" in _unique_constraint_names(
        temp_engine, "control_bindings"
    )
    assert "control_bindings_control_fkey" in _foreign_key_names(
        temp_engine, "control_bindings"
    )


def test_downgrade_restores_original_constraints(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)
    command.downgrade(alembic_config, PRE_MIGRATION_REVISION)

    for table in (
        "agents",
        "controls",
        "policies",
        "agent_controls",
        "agent_policies",
        "policy_controls",
    ):
        assert "namespace_key" not in _column_names(temp_engine, table), table

    assert _pk_columns(temp_engine, "agents") == ["name"]
    assert _pk_columns(temp_engine, "agent_controls") == [
        "agent_name",
        "control_id",
    ]
    assert "control_bindings" not in inspect(temp_engine).get_table_names()
    assert "idx_controls_name_active" in _index_names(temp_engine, "controls")
    assert "ix_agents_name" not in _index_names(temp_engine, "agents")
    assert "ix_policies_name" not in _index_names(temp_engine, "policies")
    assert "ix_controls_name" not in _index_names(temp_engine, "controls")


def test_downgrade_round_trip(alembic_config: Config, temp_engine: Engine) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)
    command.downgrade(alembic_config, PRE_MIGRATION_REVISION)
    command.upgrade(alembic_config, MIGRATION_REVISION)

    assert "namespace_key" in _column_names(temp_engine, "agents")
    assert "control_bindings" in inspect(temp_engine).get_table_names()


def test_observability_namespace_migration_scopes_event_primary_key(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, OBSERVABILITY_NAMESPACE_REVISION)

    _assert_observability_namespace_schema(temp_engine)


def test_observability_namespace_migration_recovers_when_column_preexists(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE control_execution_events "
                "ADD COLUMN namespace_key VARCHAR(255) DEFAULT 'default' NOT NULL"
            )
        )

    command.upgrade(alembic_config, OBSERVABILITY_NAMESPACE_REVISION)

    _assert_observability_namespace_schema(temp_engine)


def test_observability_namespace_migration_recovers_when_primary_key_preexists(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE control_execution_events "
                "ADD COLUMN namespace_key VARCHAR(255) DEFAULT 'default' NOT NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE control_execution_events "
                "DROP CONSTRAINT control_execution_events_pkey"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE control_execution_events "
                "ADD CONSTRAINT control_execution_events_pkey "
                "PRIMARY KEY (namespace_key, control_execution_id)"
            )
        )

    command.upgrade(alembic_config, OBSERVABILITY_NAMESPACE_REVISION)

    _assert_observability_namespace_schema(temp_engine)


def test_downgrade_rejects_cross_namespace_agents_duplicates(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agents (namespace_key, name, data) "
                "VALUES ('ns-one', 'shared-name-agent', '{}'::jsonb)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO agents (namespace_key, name, data) "
                "VALUES ('ns-two', 'shared-name-agent', '{}'::jsonb)"
            )
        )

    with pytest.raises(RuntimeError, match="agents"):
        command.downgrade(alembic_config, PRE_MIGRATION_REVISION)


def test_downgrade_rejects_cross_namespace_policies_duplicates(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO policies (namespace_key, name) "
                "VALUES ('ns-one', 'shared-policy')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO policies (namespace_key, name) "
                "VALUES ('ns-two', 'shared-policy')"
            )
        )

    with pytest.raises(RuntimeError, match="policies"):
        command.downgrade(alembic_config, PRE_MIGRATION_REVISION)


def test_downgrade_rejects_cross_namespace_live_controls_duplicates(
    alembic_config: Config, temp_engine: Engine
) -> None:
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO controls (namespace_key, name, data) "
                "VALUES ('ns-one', 'shared-control', '{}'::jsonb)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO controls (namespace_key, name, data) "
                "VALUES ('ns-two', 'shared-control', '{}'::jsonb)"
            )
        )

    with pytest.raises(RuntimeError, match="controls"):
        command.downgrade(alembic_config, PRE_MIGRATION_REVISION)


def test_downgrade_allows_cross_namespace_soft_deleted_controls(
    alembic_config: Config, temp_engine: Engine
) -> None:
    """Soft-deleted controls don't block downgrade.

    The legacy partial unique index on controls.name is also restricted to
    ``deleted_at IS NULL``, so a name shared across namespaces is fine as long
    as at most one row per name is live.
    """
    command.upgrade(alembic_config, MIGRATION_REVISION)

    with temp_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO controls (namespace_key, name, data, deleted_at) "
                "VALUES ('ns-one', 'tombstoned', '{}'::jsonb, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO controls (namespace_key, name, data, deleted_at) "
                "VALUES ('ns-two', 'tombstoned', '{}'::jsonb, CURRENT_TIMESTAMP)"
            )
        )

    command.downgrade(alembic_config, PRE_MIGRATION_REVISION)
    assert "namespace_key" not in _column_names(temp_engine, "controls")
