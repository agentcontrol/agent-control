"""Coverage for the ``control_bindings`` table: uniqueness, foreign-key
behavior, and same-namespace integrity."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def clean_tables(db_engine: Engine):
    def _truncate() -> None:
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE control_bindings, agent_controls, "
                    "agent_policies, policy_controls, agents, policies, "
                    "controls RESTART IDENTITY CASCADE"
                )
            )

    _truncate()
    yield
    _truncate()


def _insert_control(engine: Engine, *, namespace_key: str, name: str) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO controls (namespace_key, name, data) "
                    "VALUES (:ns, :name, '{}'::jsonb) RETURNING id"
                ),
                {"ns": namespace_key, "name": name},
            ).scalar_one()
        )


def _insert_binding(
    engine: Engine,
    *,
    namespace_key: str,
    target_type: str,
    target_id: str,
    control_id: int,
    enabled: bool = True,
) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO control_bindings "
                    "(namespace_key, target_type, target_id, control_id, enabled) "
                    "VALUES (:ns, :ttype, :tid, :ctrl, :enabled) "
                    "RETURNING id"
                ),
                {
                    "ns": namespace_key,
                    "ttype": target_type,
                    "tid": target_id,
                    "ctrl": control_id,
                    "enabled": enabled,
                },
            ).scalar_one()
        )


def test_target_binding_inserts(db_engine: Engine, clean_tables: None) -> None:
    control_id = _insert_control(db_engine, namespace_key="ns-one", name="pii")
    _insert_binding(
        db_engine,
        namespace_key="ns-one",
        target_type="env",
        target_id="prod",
        control_id=control_id,
    )


def test_duplicate_binding_rejected(
    db_engine: Engine, clean_tables: None
) -> None:
    control_id = _insert_control(db_engine, namespace_key="ns-one", name="pii")
    _insert_binding(
        db_engine,
        namespace_key="ns-one",
        target_type="env",
        target_id="prod",
        control_id=control_id,
    )
    with pytest.raises(IntegrityError):
        _insert_binding(
            db_engine,
            namespace_key="ns-one",
            target_type="env",
            target_id="prod",
            control_id=control_id,
        )


def test_same_control_can_bind_to_different_targets(
    db_engine: Engine, clean_tables: None
) -> None:
    control_id = _insert_control(db_engine, namespace_key="ns-one", name="pii")
    _insert_binding(
        db_engine,
        namespace_key="ns-one",
        target_type="env",
        target_id="prod",
        control_id=control_id,
    )
    _insert_binding(
        db_engine,
        namespace_key="ns-one",
        target_type="env",
        target_id="dev",
        control_id=control_id,
    )


def test_binding_rejects_cross_namespace_control_reference(
    db_engine: Engine, clean_tables: None
) -> None:
    control_id = _insert_control(db_engine, namespace_key="ns-two", name="pii")
    with pytest.raises(IntegrityError):
        _insert_binding(
            db_engine,
            namespace_key="ns-one",
            target_type="env",
            target_id="prod",
            control_id=control_id,
        )


def test_binding_cascades_on_control_hard_delete(
    db_engine: Engine, clean_tables: None
) -> None:
    control_id = _insert_control(db_engine, namespace_key="ns-one", name="pii")
    binding_id = _insert_binding(
        db_engine,
        namespace_key="ns-one",
        target_type="env",
        target_id="prod",
        control_id=control_id,
    )

    with db_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM controls WHERE id = :id"),
            {"id": control_id},
        )
        remaining = conn.execute(
            text("SELECT COUNT(*) FROM control_bindings WHERE id = :id"),
            {"id": binding_id},
        ).scalar_one()

    assert remaining == 0


def test_binding_survives_control_soft_delete(
    db_engine: Engine, clean_tables: None
) -> None:
    control_id = _insert_control(db_engine, namespace_key="ns-one", name="pii")
    binding_id = _insert_binding(
        db_engine,
        namespace_key="ns-one",
        target_type="env",
        target_id="prod",
        control_id=control_id,
    )

    # Soft-deleting a control sets deleted_at; bindings remain intact. The
    # runtime resolver is responsible for excluding soft-deleted controls.
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET deleted_at = NOW() WHERE id = :id"),
            {"id": control_id},
        )
        remaining = conn.execute(
            text("SELECT COUNT(*) FROM control_bindings WHERE id = :id"),
            {"id": binding_id},
        ).scalar_one()

    assert remaining == 1
