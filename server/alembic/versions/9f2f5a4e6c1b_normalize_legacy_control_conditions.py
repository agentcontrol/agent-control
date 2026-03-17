"""normalize legacy control condition payloads

Revision ID: 9f2f5a4e6c1b
Revises: 4b8c7d4a1f31
Create Date: 2026-03-17 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import context, op

# revision identifiers, used by Alembic.
revision = "9f2f5a4e6c1b"
down_revision = "4b8c7d4a1f31"
branch_labels = None
depends_on = None

_SAMPLE_LIMIT = 5
_JSON_OBJECT = "jsonb_typeof(data) = 'object'"
_JSON_NON_OBJECT = "jsonb_typeof(data) <> 'object'"
_HAS_CONDITION = "data ? 'condition'"
_HAS_SELECTOR = "data ? 'selector'"
_HAS_EVALUATOR = "data ? 'evaluator'"
_EMPTY_OBJECT = "data = '{}'::jsonb"
_LEGACY_VALID_PREDICATE = (
    f"{_JSON_OBJECT} AND NOT {_HAS_CONDITION} AND {_HAS_SELECTOR} AND {_HAS_EVALUATOR}"
)
_INVALID_BUCKET_PREDICATES: dict[str, str] = {
    "mixed_invalid": (
        f"{_JSON_OBJECT} AND {_HAS_CONDITION} AND ({_HAS_SELECTOR} OR {_HAS_EVALUATOR})"
    ),
    "partial_invalid": (
        f"{_JSON_OBJECT} AND NOT {_HAS_CONDITION} AND "
        f"(({_HAS_SELECTOR} AND NOT {_HAS_EVALUATOR}) OR "
        f"({_HAS_EVALUATOR} AND NOT {_HAS_SELECTOR}))"
    ),
    "missing_condition_invalid": (
        f"{_JSON_OBJECT} AND NOT {_EMPTY_OBJECT} AND NOT {_HAS_CONDITION} "
        f"AND NOT {_HAS_SELECTOR} AND NOT {_HAS_EVALUATOR}"
    ),
    "non_object_invalid": _JSON_NON_OBJECT,
}


def _count_rows(bind: sa.engine.Connection, predicate: str) -> int:
    return int(
        bind.execute(
            sa.text(f"SELECT COUNT(*) FROM controls WHERE {predicate}")
        ).scalar_one()
    )


def _sample_rows(bind: sa.engine.Connection, predicate: str) -> list[str]:
    rows = (
        bind.execute(
            sa.text(
                f"""
                SELECT id, name
                FROM controls
                WHERE {predicate}
                ORDER BY id
                LIMIT :limit
                """
            ),
            {"limit": _SAMPLE_LIMIT},
        )
        .mappings()
        .all()
    )
    return [f"(id={row['id']}, name={row['name']})" for row in rows]


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "This migration requires a live database connection and cannot run in offline mode."
        )

    bind = op.get_bind()
    invalid_summaries: list[str] = []
    for bucket_name, predicate in _INVALID_BUCKET_PREDICATES.items():
        count = _count_rows(bind, predicate)
        if count == 0:
            continue
        samples = ", ".join(_sample_rows(bind, predicate))
        invalid_summaries.append(
            f"{bucket_name}={count} samples=[{samples or 'none'}]"
        )

    if invalid_summaries:
        raise RuntimeError(
            "Control condition migration aborted because invalid stored control rows were found: "
            + "; ".join(invalid_summaries)
        )

    legacy_count = _count_rows(bind, _LEGACY_VALID_PREDICATE)
    if legacy_count == 0:
        return

    bind.execute(
        sa.text(
            f"""
            UPDATE controls
            SET data = (data - 'selector' - 'evaluator')
                       || jsonb_build_object(
                            'condition',
                            jsonb_build_object(
                                'selector', data->'selector',
                                'evaluator', data->'evaluator'
                            )
                        )
            WHERE {_LEGACY_VALID_PREDICATE}
            """
        )
    )


def downgrade() -> None:
    raise NotImplementedError(
        "This migration is irreversible and does not reconstruct legacy flat control shapes."
    )
