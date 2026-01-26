"""Simplify observability schema: minimal columns + JSONB.

Revision ID: simplify_observability_schema
Revises: add_observability_tables
Create Date: 2026-01-19

This migration:
1. Drops the control_execution_aggregates_5s table (no more pre-aggregation)
2. Recreates control_execution_events with minimal schema:
   - control_execution_id (PK)
   - timestamp (indexed)
   - agent_uuid (indexed)
   - data (JSONB containing full event)
3. Creates optimized indexes for query-time aggregation

The new design stores raw events with minimal indexed columns + JSONB data.
Stats are computed at query time from JSONB fields.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "simplify_observability_schema"
down_revision = "add_observability_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop the aggregates table (no more pre-aggregation)
    op.drop_index("ix_aggregates_5s_agent", table_name="control_execution_aggregates_5s")
    op.drop_index("ix_aggregates_5s_time", table_name="control_execution_aggregates_5s")
    op.drop_table("control_execution_aggregates_5s")

    # 2. Drop the old events table (will recreate with simpler schema)
    op.drop_index("ix_control_events_control_id", table_name="control_execution_events")
    op.drop_index("ix_control_events_agent_uuid", table_name="control_execution_events")
    op.drop_index("ix_control_events_timestamp", table_name="control_execution_events")
    op.drop_index("ix_control_events_trace_span", table_name="control_execution_events")
    op.drop_index("ix_control_events_span_id", table_name="control_execution_events")
    op.drop_index("ix_control_events_trace_id", table_name="control_execution_events")
    op.drop_table("control_execution_events")

    # 3. Create new simplified events table
    op.create_table(
        "control_execution_events",
        sa.Column("control_execution_id", sa.String(36), primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("agent_uuid", sa.UUID(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    # 4. Create optimized index for agent + time queries (primary access pattern)
    op.create_index(
        "ix_events_agent_time",
        "control_execution_events",
        ["agent_uuid", sa.text("timestamp DESC")],
    )

    # 5. Create expression index on control_id from JSONB for grouping
    op.execute(
        """
        CREATE INDEX ix_events_data_control_id
        ON control_execution_events ((data->>'control_id'))
        """
    )


def downgrade() -> None:
    # Drop the new simplified table
    op.execute("DROP INDEX IF EXISTS ix_events_data_control_id")
    op.drop_index("ix_events_agent_time", table_name="control_execution_events")
    op.drop_table("control_execution_events")

    # Recreate the original events table with all columns
    op.create_table(
        "control_execution_events",
        sa.Column("control_execution_id", sa.String(36), primary_key=True),
        sa.Column("trace_id", sa.String(32), nullable=False),
        sa.Column("span_id", sa.String(16), nullable=False),
        sa.Column("agent_uuid", sa.UUID(), nullable=False),
        sa.Column("agent_name", sa.String(255), nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column("control_name", sa.String(255), nullable=False),
        sa.Column("control_set_id", sa.Integer(), nullable=True),
        sa.Column("control_set_name", sa.String(255), nullable=True),
        sa.Column("check_stage", sa.String(10), nullable=False),
        sa.Column("applies_to", sa.String(20), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("execution_duration_ms", sa.Float(), nullable=True),
        sa.Column("evaluator_plugin", sa.String(255), nullable=True),
        sa.Column("selector_path", sa.String(255), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # Recreate indexes
    op.create_index("ix_control_events_trace_id", "control_execution_events", ["trace_id"])
    op.create_index("ix_control_events_span_id", "control_execution_events", ["span_id"])
    op.create_index("ix_control_events_trace_span", "control_execution_events", ["trace_id", "span_id"])
    op.create_index("ix_control_events_timestamp", "control_execution_events", ["timestamp"])
    op.create_index("ix_control_events_agent_uuid", "control_execution_events", ["agent_uuid"])
    op.create_index("ix_control_events_control_id", "control_execution_events", ["control_id"])

    # Recreate aggregates table
    op.create_table(
        "control_execution_aggregates_5s",
        sa.Column("bucket_timestamp", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("agent_uuid", sa.UUID(), primary_key=True),
        sa.Column("control_id", sa.Integer(), primary_key=True),
        sa.Column("check_stage", sa.String(10), primary_key=True),
        sa.Column("applies_to", sa.String(20), primary_key=True),
        sa.Column("control_name", sa.String(255), nullable=False),
        sa.Column("execution_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("match_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("non_match_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("allow_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("deny_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("warn_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("log_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("error_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("confidence_sum", sa.Float(), default=0.0, nullable=False),
        sa.Column("confidence_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("duration_ms_sum", sa.Float(), default=0.0, nullable=False),
        sa.Column("duration_ms_count", sa.BigInteger(), default=0, nullable=False),
    )

    op.create_index("ix_aggregates_5s_time", "control_execution_aggregates_5s", ["bucket_timestamp"])
    op.create_index("ix_aggregates_5s_agent", "control_execution_aggregates_5s", ["agent_uuid", "bucket_timestamp"])
