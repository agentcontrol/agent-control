"""Alembic coverage for collapsing advisory actions to observe."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from agent_control_server.config import db_config

from .utils import VALID_CONTROL_PAYLOAD

SERVER_DIR = Path(__file__).resolve().parents[1]
PRE_MIGRATION_REVISION = "8b23d645f86d"
MIGRATION_REVISION = "5f2b5f4e1a90"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Control action Alembic migration tests require PostgreSQL.",
)


def _control_payload(action: str) -> dict[str, Any]:
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["action"]["decision"] = action
    return payload


def _insert_control(engine: Engine, *, name: str, data: dict[str, Any]) -> int:
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


def _fetch_control_data(engine: Engine, control_id: int) -> Any:
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT data FROM controls WHERE id = :id"),
            {"id": control_id},
        ).scalar_one()


@pytest.fixture
def temp_db_url() -> str:
    temp_db_name = f"agent_control_action_{uuid.uuid4().hex[:12]}"
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


def test_upgrade_collapses_legacy_advisory_actions(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)

    allow_id = _insert_control(temp_engine, name="allow-legacy", data=_control_payload("allow"))
    warn_id = _insert_control(temp_engine, name="warn-legacy", data=_control_payload("warn"))
    log_id = _insert_control(temp_engine, name="log-legacy", data=_control_payload("log"))

    upgrade_to(MIGRATION_REVISION)

    for control_id in (allow_id, warn_id, log_id):
        assert _fetch_control_data(temp_engine, control_id)["action"]["decision"] == "observe"


def test_upgrade_preserves_canonical_actions(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)

    deny_id = _insert_control(temp_engine, name="deny", data=_control_payload("deny"))
    steer_id = _insert_control(temp_engine, name="steer", data=_control_payload("steer"))
    observe_id = _insert_control(
        temp_engine, name="observe", data=_control_payload("observe")
    )

    upgrade_to(MIGRATION_REVISION)

    assert _fetch_control_data(temp_engine, deny_id)["action"]["decision"] == "deny"
    assert _fetch_control_data(temp_engine, steer_id)["action"]["decision"] == "steer"
    assert _fetch_control_data(temp_engine, observe_id)["action"]["decision"] == "observe"
