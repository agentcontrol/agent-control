"""Alembic coverage for evaluator-to-rule payload migration."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from agent_control_server.config import db_config
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

SERVER_DIR = Path(__file__).resolve().parents[1]
PRE_MIGRATION_REVISION = "e2b7f4a9c6d1"
MIGRATION_REVISION = "d4f0b2e1c9a8"
_BASE_DB_URL = make_url(db_config.get_url())

pytestmark = pytest.mark.skipif(
    _BASE_DB_URL.get_backend_name() != "postgresql",
    reason="Rule terminology Alembic migration tests require PostgreSQL.",
)


@pytest.fixture
def temp_db_url() -> str:
    temp_db_name = f"agent_control_rules_{uuid.uuid4().hex[:12]}"
    admin_url = _BASE_DB_URL.set(database="postgres").render_as_string(
        hide_password=False
    )
    target_url = _BASE_DB_URL.set(database=temp_db_name).render_as_string(
        hide_password=False
    )

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


def _insert_json_payloads(engine: Engine) -> dict[str, int | str]:
    agent_data = {
        "agent_metadata": {"evaluator": "user metadata should stay untouched"},
        "steps": [],
        "evaluators": [
            {
                "name": "custom",
                "description": "custom rule",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "evaluator": {"type": "string"},
                    },
                },
            }
        ],
    }
    control_data = {
        "description": "legacy control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "condition": {
            "and": [
                {
                    "selector": {"path": "input"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": "secret", "evaluator": "keep"},
                    },
                },
                {
                    "not": {
                        "selector": {"path": "output"},
                        "evaluator": {
                            "name": "list",
                            "config": {"values": ["ok"]},
                        },
                    }
                },
            ]
        },
        "template": {
            "metadata": {"name": "templated", "evaluator": "keep"},
            "parameters": {},
            "definition_template": {
                "selector": {"path": "input"},
                "evaluator": {
                    "name": "regex",
                    "config": {"pattern": "$param", "evaluator": "keep"},
                },
            },
        },
        "action": {"decision": "deny"},
    }
    event_data = {
        "evaluator_name": "regex",
        "metadata": {
            "primary_evaluator": "regex",
            "all_evaluators": ["regex", "list"],
            "evaluator": "user metadata should stay untouched",
            "condition_trace": {
                "type": "and",
                "children": [
                    {"type": "leaf", "evaluator_name": "regex"},
                    {"type": "leaf", "evaluator_name": "list"},
                ],
            },
        },
    }

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO agents (name, data)
                VALUES (:name, CAST(:data AS JSONB))
                """
            ),
            {"name": "agent-rules", "data": json.dumps(agent_data)},
        )
        control_id = int(
            conn.execute(
                text(
                    """
                    INSERT INTO controls (name, data)
                    VALUES (:name, CAST(:data AS JSONB))
                    RETURNING id
                    """
                ),
                {"name": "legacy-control", "data": json.dumps(control_data)},
            ).scalar_one()
        )
        conn.execute(
            text(
                """
                INSERT INTO control_versions (control_id, version_num, event_type, snapshot)
                VALUES (:control_id, 1, 'migration_backfill', CAST(:snapshot AS JSONB))
                """
            ),
            {
                "control_id": control_id,
                "snapshot": json.dumps({"name": "legacy-control", "data": control_data}),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO control_execution_events (
                    control_execution_id, agent_name, data
                )
                VALUES (:execution_id, :agent_name, CAST(:data AS JSONB))
                """
            ),
            {
                "execution_id": "terminology-migration-event",
                "agent_name": "agent-rules",
                "data": json.dumps(event_data),
            },
        )

    return {
        "control_id": control_id,
        "execution_id": "terminology-migration-event",
    }


def _fetch_payloads(engine: Engine, ids: dict[str, int | str]) -> dict[str, Any]:
    with engine.begin() as conn:
        return {
            "agent": conn.execute(
                text("SELECT data FROM agents WHERE name = 'agent-rules'")
            ).scalar_one(),
            "control": conn.execute(
                text("SELECT data FROM controls WHERE id = :id"),
                {"id": ids["control_id"]},
            ).scalar_one(),
            "snapshot": conn.execute(
                text("SELECT snapshot FROM control_versions WHERE control_id = :id"),
                {"id": ids["control_id"]},
            ).scalar_one(),
            "event": conn.execute(
                text(
                    """
                    SELECT data
                    FROM control_execution_events
                    WHERE control_execution_id = :execution_id
                    """
                ),
                {"execution_id": ids["execution_id"]},
            ).scalar_one(),
        }


def test_upgrade_rewrites_evaluator_payload_keys_without_touching_user_config(
    alembic_config: Config,
    temp_engine: Engine,
) -> None:
    command.upgrade(alembic_config, PRE_MIGRATION_REVISION)
    ids = _insert_json_payloads(temp_engine)

    command.upgrade(alembic_config, MIGRATION_REVISION)

    payloads = _fetch_payloads(temp_engine, ids)
    agent = payloads["agent"]
    assert "rules" in agent
    assert "evaluators" not in agent
    assert "evaluator" in agent["agent_metadata"]
    assert "evaluator" in agent["rules"][0]["config_schema"]["properties"]

    control = payloads["control"]
    first_leaf = control["condition"]["and"][0]
    second_leaf = control["condition"]["and"][1]["not"]
    assert "rule" in first_leaf
    assert "evaluator" not in first_leaf
    assert first_leaf["rule"]["config"]["evaluator"] == "keep"
    assert "rule" in second_leaf
    assert "evaluator" not in second_leaf
    template_definition = control["template"]["definition_template"]
    assert "rule" in template_definition
    assert "evaluator" not in template_definition
    assert template_definition["rule"]["config"]["evaluator"] == "keep"
    assert control["template"]["metadata"]["evaluator"] == "keep"

    snapshot_data = payloads["snapshot"]["data"]
    assert "rule" in snapshot_data["condition"]["and"][0]
    assert "evaluator" not in snapshot_data["condition"]["and"][0]

    event = payloads["event"]
    assert event["rule_name"] == "regex"
    assert "evaluator_name" not in event
    assert event["metadata"]["primary_rule"] == "regex"
    assert event["metadata"]["all_rules"] == ["regex", "list"]
    assert event["metadata"]["evaluator"] == "user metadata should stay untouched"
    trace_children = event["metadata"]["condition_trace"]["children"]
    assert trace_children[0]["rule_name"] == "regex"
    assert trace_children[1]["rule_name"] == "list"


def test_downgrade_restores_evaluator_payload_keys(
    alembic_config: Config,
    temp_engine: Engine,
) -> None:
    command.upgrade(alembic_config, PRE_MIGRATION_REVISION)
    ids = _insert_json_payloads(temp_engine)
    command.upgrade(alembic_config, MIGRATION_REVISION)

    command.downgrade(alembic_config, PRE_MIGRATION_REVISION)

    payloads = _fetch_payloads(temp_engine, ids)
    agent = payloads["agent"]
    assert "evaluators" in agent
    assert "rules" not in agent
    control = payloads["control"]
    assert "evaluator" in control["condition"]["and"][0]
    assert "rule" not in control["condition"]["and"][0]
    event = payloads["event"]
    assert event["evaluator_name"] == "regex"
    assert "rule_name" not in event
