"""Real PostgreSQL migration coverage with a disposable database."""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from agent_control_server.config import db_config

SERVER_DIR = Path(__file__).resolve().parents[1]
URL = make_url(db_config.get_url())
pytestmark = pytest.mark.skipif(
    URL.get_backend_name() != "postgresql", reason="Requires PostgreSQL"
)


@pytest.fixture
def migration_db() -> Iterator[tuple[Config, Engine]]:
    name = "ac_owner_" + uuid4().hex[:12]
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    target = URL.set(database=name)
    engine = create_engine(target)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", target.render_as_string(hide_password=False))
    try:
        yield cfg, engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def test_ownership_upgrade_preserves_legacy_and_downgrade_fails_closed(migration_db):
    cfg, engine = migration_db
    # Given: legacy organization data, including a detached clone, before ownership.
    command.upgrade(cfg, "d7e4a9b2c6f1")
    with engine.begin() as conn:
        source = conn.execute(
            text(
                "INSERT INTO controls(namespace_key,name,data) "
                "VALUES('org','source','{}'::jsonb) RETURNING id"
            )
        ).scalar_one()
        clone = conn.execute(
            text(
                "INSERT INTO controls(namespace_key,name,data,cloned_from_control_id) "
                "VALUES('org','detached','{}'::jsonb,:source) RETURNING id"
            ),
            {"source": source},
        ).scalar_one()
    # When: upgrading the additive migration.
    command.upgrade(cfg, "q8c1e0f4a2b6")
    # Then: ownership is not guessed from lineage or attachments.
    with engine.connect() as conn:
        legacy = conn.execute(text("SELECT id,owner_project_id FROM controls ORDER BY id")).all()
    assert (source, None) in legacy and (clone, None) in legacy
    assert "control_project_scopes" in inspect(engine).get_table_names()
    assert "control_target_scopes" in inspect(engine).get_table_names()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO control_project_scopes(namespace_key,project_id,state) "
                "VALUES('org','project-A','active')"
            )
        )
        conn.execute(
            text("UPDATE controls SET owner_project_id='project-A' WHERE id=:clone"),
            {"clone": clone},
        )
    # When/Then: downgrade cannot erase a private definition's ownership.
    with pytest.raises(RuntimeError, match="Cannot remove ownership"):
        command.downgrade(cfg, "d7e4a9b2c6f1")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET owner_project_id=NULL WHERE id=:clone"), {"clone": clone}
        )
    command.downgrade(cfg, "d7e4a9b2c6f1")
    assert "owner_project_id" not in {
        column["name"] for column in inspect(engine).get_columns("controls")
    }
