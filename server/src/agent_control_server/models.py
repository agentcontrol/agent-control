import datetime as dt
from typing import Any

from agent_control_models.agent import StepSchema, normalize_agent_name
from agent_control_models.base import BaseModel
from agent_control_models.server import EvaluatorSchema
from pydantic import Field
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .db import Base


class AgentData(BaseModel):
    """Agent metadata stored in JSONB."""

    agent_metadata: dict[str, Any]
    steps: list[StepSchema] = Field(default_factory=list)
    evaluators: list[EvaluatorSchema] = Field(default_factory=list)


# Association table for Policy <> Control many-to-many relationship
policy_controls: Table = Table(
    "policy_controls",
    Base.metadata,
    Column("policy_id", ForeignKey("policies.id"), primary_key=True, index=True),
    Column("control_id", ForeignKey("controls.id"), primary_key=True, index=True),
)

# Association table for Agent <> Policy many-to-many relationship
agent_policies: Table = Table(
    "agent_policies",
    Base.metadata,
    Column("agent_name", ForeignKey("agents.name"), primary_key=True, index=True),
    Column("policy_id", ForeignKey("policies.id"), primary_key=True, index=True),
)

# Association table for Agent <> Control many-to-many direct relationship
agent_controls: Table = Table(
    "agent_controls",
    Base.metadata,
    Column("agent_name", ForeignKey("agents.name"), primary_key=True, index=True),
    Column("control_id", ForeignKey("controls.id"), primary_key=True, index=True),
)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    agents: Mapped[list["Agent"]] = relationship(
        "Agent", secondary=lambda: agent_policies, back_populates="policies"
    )
    # Many-to-many: Policy <> Control (direct relationship, no ControlSet layer)
    controls: Mapped[list["Control"]] = relationship(
        "Control", secondary=lambda: policy_controls, back_populates="policies"
    )


class Control(Base):
    __tablename__ = "controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # JSONB payload describing control specifics
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    # Many-to-many backref: Control <> Policy
    policies: Mapped[list["Policy"]] = relationship(
        "Policy", secondary=lambda: policy_controls, back_populates="controls"
    )
    # Many-to-many backref: Control <> Agent (direct relationship)
    agents: Mapped[list["Agent"]] = relationship(
        "Agent", secondary=lambda: agent_controls, back_populates="controls"
    )


class EvaluatorConfigDB(Base):
    __tablename__ = "evaluator_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    evaluator: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("char_length(name) >= 10", name="ck_agents_name_min_length"),
        CheckConstraint("name ~ '^[a-z0-9:_-]+$'", name="ck_agents_name_format"),
    )

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    policies: Mapped[list["Policy"]] = relationship(
        "Policy", secondary=lambda: agent_policies, back_populates="agents"
    )
    controls: Mapped[list["Control"]] = relationship(
        "Control", secondary=lambda: agent_controls, back_populates="agents"
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(), server_default=text("CURRENT_TIMESTAMP"), nullable=False, index=True
    )

    @validates("name")
    def _normalize_name(self, _key: str, value: str) -> str:
        return normalize_agent_name(value)


# =============================================================================
# Observability Models
# =============================================================================


class ControlExecutionEventDB(Base):
    """
    Raw control execution events with minimal indexed columns + JSONB.

    Schema designed for simplicity and flexibility:
    - Only 4 columns: control_execution_id, timestamp, agent_name, data
    - Full event stored in JSONB 'data' column
    - Query-time aggregation from JSONB fields
    - No migrations needed for new event fields

    Primary access pattern: (agent_name, timestamp DESC) for stats queries.
    Expression index on (data->>'control_id') for grouping.
    """

    __tablename__ = "control_execution_events"

    # Primary key
    control_execution_id: Mapped[str] = mapped_column(
        String(36), primary_key=True
    )

    # Minimal indexed columns for efficient queries
    timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Full event data as JSONB
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False,
    )

    # Composite index for agent + time queries (primary access pattern)
    __table_args__ = (
        Index("ix_events_agent_time", "agent_name", timestamp.desc()),
        Index("ix_events_data_control_id", text("(data ->> 'control_id'::text)")),
    )
