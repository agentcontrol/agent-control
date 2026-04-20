import datetime as dt
from typing import Any

from agent_control_models.agent import StepSchema, normalize_agent_name
from agent_control_models.base import BaseModel
from agent_control_models.server import EvaluatorSchema
from pydantic import Field
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .db import Base

# Synthetic tenant used when no explicit tenant is resolved for a request.
# In this initial rollout tenant_id is inert metadata on existing tables:
# writes stamp it via an ORM/DB default, but read paths do not filter on it.
DEFAULT_TENANT_ID = "default-tenant"


class AgentData(BaseModel):
    """Agent metadata stored in JSONB."""

    agent_metadata: dict[str, Any]
    steps: list[StepSchema] = Field(default_factory=list)
    evaluators: list[EvaluatorSchema] = Field(default_factory=list)


# Association table for Policy <> Control many-to-many relationship.
# ``policy_controls`` deliberately does not carry tenant_id: tenant scope is
# inherited transitively through policy_id and control_id, both of which
# already point to tenant-owned rows.
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
    Column(
        "tenant_id",
        String(64),
        nullable=False,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
        default=DEFAULT_TENANT_ID,
    ),
)

# Association table for Agent <> Control many-to-many direct relationship
agent_controls: Table = Table(
    "agent_controls",
    Base.metadata,
    Column("agent_name", ForeignKey("agents.name"), primary_key=True, index=True),
    Column("control_id", ForeignKey("controls.id"), primary_key=True, index=True),
    Column(
        "tenant_id",
        String(64),
        nullable=False,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
        default=DEFAULT_TENANT_ID,
    ),
)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
        default=DEFAULT_TENANT_ID,
    )
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
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
        default=DEFAULT_TENANT_ID,
    )
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


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("char_length(name) >= 10", name="ck_agents_name_min_length"),
        CheckConstraint("name ~ '^[a-z0-9:_-]+$'", name="ck_agents_name_format"),
    )

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
        default=DEFAULT_TENANT_ID,
    )
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
# Target Models
# =============================================================================
#
# Targets are typed, tenant-scoped attachable objects. The schema is introduced
# here without being wired into runtime control resolution or management APIs;
# both are added in follow-up changes. ``target_controls`` inherits tenant
# scope transitively through ``target_id``.


class Target(Base):
    """A typed, tenant-scoped attachable object (e.g. ``environment``).

    The column is named ``target_type`` rather than ``type`` to avoid
    shadowing Python's builtin and to keep greps for the field specific.
    """

    __tablename__ = "targets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "target_type",
            "external_id",
            name="uq_targets_tenant_type_external_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default=text(f"'{DEFAULT_TENANT_ID}'"),
        default=DEFAULT_TENANT_ID,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class TargetControl(Base):
    """Attachment of a control to a target with per-target enablement."""

    __tablename__ = "target_controls"
    __table_args__ = (
        UniqueConstraint("target_id", "control_id", name="uq_target_controls_target_control"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # CASCADE on target_id: a target_control row has no meaning without its target.
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # RESTRICT (default) on control_id: do not silently fan control deletes into
    # attachment cleanup; callers must remove attachments explicitly.
    control_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("controls.id"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


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
