"""Alembic coverage for Phase 0 control cleanup and audit backfill."""

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
PRE_MIGRATION_REVISION = "5f2b5f4e1a90"
MIGRATION_REVISION = "c1e9f9c4a1d2"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Phase 0 Alembic migration tests require PostgreSQL.",
)


def _unrendered_template_payload() -> dict[str, Any]:
    return {
        "template": {
            "description": "Regex denial template",
            "parameters": {
                "pattern": {
                    "type": "regex_re2",
                    "label": "Pattern",
                },
            },
            "definition_template": {
                "description": "Template-backed control",
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": {"$param": "pattern"}},
                    },
                },
                "action": {"decision": "deny"},
            },
        },
        "template_values": {},
    }


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


def _insert_agent(engine: Engine, *, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO agents (name, data)
                VALUES (:name, '{}'::jsonb)
                """
            ),
            {"name": name},
        )


def _associate_policy_control(engine: Engine, *, policy_id: int, control_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO policy_controls (policy_id, control_id)
                VALUES (:policy_id, :control_id)
                """
            ),
            {"policy_id": policy_id, "control_id": control_id},
        )


def _associate_agent_control(engine: Engine, *, agent_name: str, control_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO agent_controls (agent_name, control_id)
                VALUES (:agent_name, :control_id)
                """
            ),
            {"agent_name": agent_name, "control_id": control_id},
        )


def _fetch_control(engine: Engine, control_id: int) -> dict[str, Any]:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, name, data, deleted_at
                FROM controls
                WHERE id = :id
                """
            ),
            {"id": control_id},
        ).mappings().one()
        return dict(row)


def _fetch_versions(engine: Engine, control_id: int) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT version_num, event_type, snapshot, note
                FROM control_versions
                WHERE control_id = :control_id
                ORDER BY version_num
                """
            ),
            {"control_id": control_id},
        ).mappings()
        return [dict(row) for row in rows]


def _policy_control_count(engine: Engine, control_id: int) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM policy_controls WHERE control_id = :control_id"
                ),
                {"control_id": control_id},
            ).scalar_one()
        )


def _agent_control_count(engine: Engine, control_id: int) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM agent_controls WHERE control_id = :control_id"
                ),
                {"control_id": control_id},
            ).scalar_one()
        )


@pytest.fixture
def temp_db_url() -> str:
    temp_db_name = f"agent_control_phase0_{uuid.uuid4().hex[:12]}"
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


def test_upgrade_backfills_versions_for_usable_controls(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)

    rendered_id = _insert_control(
        temp_engine,
        name="rendered-control",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
    )
    unrendered_id = _insert_control(
        temp_engine,
        name="unrendered-control",
        data=_unrendered_template_payload(),
    )

    upgrade_to(MIGRATION_REVISION)

    for control_id, expected_name in (
        (rendered_id, "rendered-control"),
        (unrendered_id, "unrendered-control"),
    ):
        control = _fetch_control(temp_engine, control_id)
        versions = _fetch_versions(temp_engine, control_id)

        assert control["deleted_at"] is None
        assert len(versions) == 1
        assert versions[0]["version_num"] == 1
        assert versions[0]["event_type"] == "migration_backfill"
        assert versions[0]["note"] == "Backfilled from existing control"
        assert versions[0]["snapshot"]["name"] == expected_name
        assert versions[0]["snapshot"]["deleted_at"] is None
        assert versions[0]["snapshot"]["cloned_control_id"] is None


def test_upgrade_soft_deletes_unusable_controls_and_removes_associations(
    upgrade_to,
    temp_engine: Engine,
) -> None:
    upgrade_to(PRE_MIGRATION_REVISION)

    empty_id = _insert_control(temp_engine, name="empty-control", data={})
    corrupted_id = _insert_control(temp_engine, name="corrupted-control", data={"bad": "data"})

    policy_id = _insert_policy(temp_engine, name="policy-phase0")
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    _insert_agent(temp_engine, name=agent_name)
    _associate_policy_control(temp_engine, policy_id=policy_id, control_id=empty_id)
    _associate_agent_control(temp_engine, agent_name=agent_name, control_id=corrupted_id)

    upgrade_to(MIGRATION_REVISION)

    empty_control = _fetch_control(temp_engine, empty_id)
    corrupted_control = _fetch_control(temp_engine, corrupted_id)
    empty_versions = _fetch_versions(temp_engine, empty_id)
    corrupted_versions = _fetch_versions(temp_engine, corrupted_id)

    assert empty_control["deleted_at"] is not None
    assert corrupted_control["deleted_at"] is not None
    assert _policy_control_count(temp_engine, empty_id) == 0
    assert _agent_control_count(temp_engine, corrupted_id) == 0

    assert [version["event_type"] for version in empty_versions] == [
        "migration_backfill",
        "migration_autodelete",
    ]
    assert [version["event_type"] for version in corrupted_versions] == [
        "migration_backfill",
        "migration_autodelete",
    ]
    assert empty_versions[1]["note"] == "Auto-soft-deleted during migration: empty payload"
    assert (
        corrupted_versions[1]["note"]
        == "Auto-soft-deleted during migration: invalid control payload"
    )
    assert empty_versions[1]["snapshot"]["deleted_at"] is not None
    assert corrupted_versions[1]["snapshot"]["deleted_at"] is not None
