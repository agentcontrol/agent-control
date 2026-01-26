"""Add observability tables for control execution tracking.

Revision ID: add_observability_tables
Revises: 9f2c5f7a722f
Create Date: 2026-01-11

This migration adds:
1. control_execution_events - Raw event storage (7-day retention)
2. control_execution_aggregates_5s - Pre-aggregated metrics (kept forever)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_observability_tables"
down_revision = "9f2c5f7a722f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create raw events table (optional, 7-day retention)
    op.create_table(
        "control_execution_events",
        # Primary key
        sa.Column("control_execution_id", sa.String(36), primary_key=True),
        # OpenTelemetry-compatible IDs
        sa.Column("trace_id", sa.String(32), nullable=False),
        sa.Column("span_id", sa.String(16), nullable=False),
        # Agent identity
        sa.Column("agent_uuid", sa.UUID(), nullable=False),
        sa.Column("agent_name", sa.String(255), nullable=False),
        # Control info
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column("control_name", sa.String(255), nullable=False),
        sa.Column("control_set_id", sa.Integer(), nullable=True),
        sa.Column("control_set_name", sa.String(255), nullable=True),
        # Execution context
        sa.Column("check_stage", sa.String(10), nullable=False),  # pre/post
        sa.Column("applies_to", sa.String(20), nullable=False),  # llm_call/tool_call
        # Result
        sa.Column("action", sa.String(10), nullable=False),  # allow/deny/warn/log
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        # Timing
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("execution_duration_ms", sa.Float(), nullable=True),
        # Optional details
        sa.Column("evaluator_plugin", sa.String(255), nullable=True),
        sa.Column("selector_path", sa.String(255), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        # Extensibility (named event_metadata to avoid SQLAlchemy reserved 'metadata')
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # Create indexes for raw events table
    op.create_index(
        "ix_control_events_trace_id",
        "control_execution_events",
        ["trace_id"],
    )
    op.create_index(
        "ix_control_events_span_id",
        "control_execution_events",
        ["span_id"],
    )
    op.create_index(
        "ix_control_events_trace_span",
        "control_execution_events",
        ["trace_id", "span_id"],
    )
    op.create_index(
        "ix_control_events_timestamp",
        "control_execution_events",
        ["timestamp"],
    )
    op.create_index(
        "ix_control_events_agent_uuid",
        "control_execution_events",
        ["agent_uuid"],
    )
    op.create_index(
        "ix_control_events_control_id",
        "control_execution_events",
        ["control_id"],
    )

    # Create aggregates table (required, keep forever)
    op.create_table(
        "control_execution_aggregates_5s",
        # Composite primary key
        sa.Column("bucket_timestamp", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("agent_uuid", sa.UUID(), primary_key=True),
        sa.Column("control_id", sa.Integer(), primary_key=True),
        sa.Column("check_stage", sa.String(10), primary_key=True),  # pre/post
        sa.Column("applies_to", sa.String(20), primary_key=True),  # llm_call/tool_call
        # Denormalized for queries
        sa.Column("control_name", sa.String(255), nullable=False),
        # Aggregated counts
        sa.Column("execution_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("match_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("non_match_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("allow_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("deny_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("warn_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("log_count", sa.BigInteger(), default=0, nullable=False),
        sa.Column("error_count", sa.BigInteger(), default=0, nullable=False),
        # Confidence (sum + count for avg at query time)
        sa.Column("confidence_sum", sa.Float(), default=0.0, nullable=False),
        sa.Column("confidence_count", sa.BigInteger(), default=0, nullable=False),
        # Duration (sum + count for avg at query time)
        sa.Column("duration_ms_sum", sa.Float(), default=0.0, nullable=False),
        sa.Column("duration_ms_count", sa.BigInteger(), default=0, nullable=False),
    )

    # Create indexes for aggregates table
    op.create_index(
        "ix_aggregates_5s_time",
        "control_execution_aggregates_5s",
        ["bucket_timestamp"],
    )
    op.create_index(
        "ix_aggregates_5s_agent",
        "control_execution_aggregates_5s",
        ["agent_uuid", "bucket_timestamp"],
    )


def downgrade() -> None:
    # Drop aggregates table indexes
    op.drop_index("ix_aggregates_5s_agent", table_name="control_execution_aggregates_5s")
    op.drop_index("ix_aggregates_5s_time", table_name="control_execution_aggregates_5s")

    # Drop aggregates table
    op.drop_table("control_execution_aggregates_5s")

    # Drop raw events table indexes
    op.drop_index("ix_control_events_control_id", table_name="control_execution_events")
    op.drop_index("ix_control_events_agent_uuid", table_name="control_execution_events")
    op.drop_index("ix_control_events_timestamp", table_name="control_execution_events")
    op.drop_index("ix_control_events_trace_span", table_name="control_execution_events")
    op.drop_index("ix_control_events_span_id", table_name="control_execution_events")
    op.drop_index("ix_control_events_trace_id", table_name="control_execution_events")

    # Drop raw events table
    op.drop_table("control_execution_events")
