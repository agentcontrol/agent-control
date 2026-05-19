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
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .db import Base

DEFAULT_NAMESPACE_KEY = "default"
_NAMESPACE_SERVER_DEFAULT = text("'default'")


class AgentData(BaseModel):
    """Agent metadata stored in JSONB."""

    agent_metadata: dict[str, Any]
    steps: list[StepSchema] = Field(default_factory=list)
    evaluators: list[EvaluatorSchema] = Field(default_factory=list)


# Association table for Policy <> Control many-to-many relationship.
# Composite FKs enforce same-namespace references on both sides.
policy_controls: Table = Table(
    "policy_controls",
    Base.metadata,
    Column(
        "namespace_key",
        String(255),
        primary_key=True,
        nullable=False,
        server_default=_NAMESPACE_SERVER_DEFAULT,
    ),
    Column("policy_id", Integer, primary_key=True, index=True),
    Column("control_id", Integer, primary_key=True, index=True),
    ForeignKeyConstraint(
        ["namespace_key", "policy_id"],
        ["policies.namespace_key", "policies.id"],
        name="policy_controls_policy_fkey",
    ),
    ForeignKeyConstraint(
        ["namespace_key", "control_id"],
        ["controls.namespace_key", "controls.id"],
        name="policy_controls_control_fkey",
    ),
)

# Association table for Agent <> Policy many-to-many relationship.
agent_policies: Table = Table(
    "agent_policies",
    Base.metadata,
    Column(
        "namespace_key",
        String(255),
        primary_key=True,
        nullable=False,
        server_default=_NAMESPACE_SERVER_DEFAULT,
    ),
    Column("agent_name", String(255), primary_key=True, index=True),
    Column("policy_id", Integer, primary_key=True, index=True),
    ForeignKeyConstraint(
        ["namespace_key", "agent_name"],
        ["agents.namespace_key", "agents.name"],
        name="agent_policies_agent_fkey",
    ),
    ForeignKeyConstraint(
        ["namespace_key", "policy_id"],
        ["policies.namespace_key", "policies.id"],
        name="agent_policies_policy_fkey",
    ),
)

# Association table for Agent <> Control direct many-to-many relationship.
agent_controls: Table = Table(
    "agent_controls",
    Base.metadata,
    Column(
        "namespace_key",
        String(255),
        primary_key=True,
        nullable=False,
        server_default=_NAMESPACE_SERVER_DEFAULT,
    ),
    Column("agent_name", String(255), primary_key=True, index=True),
    Column("control_id", Integer, primary_key=True, index=True),
    ForeignKeyConstraint(
        ["namespace_key", "agent_name"],
        ["agents.namespace_key", "agents.name"],
        name="agent_controls_agent_fkey",
    ),
    ForeignKeyConstraint(
        ["namespace_key", "control_id"],
        ["controls.namespace_key", "controls.id"],
        name="agent_controls_control_fkey",
    ),
)


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint(
            "namespace_key", "name", name="uq_policies_namespace_name"
        ),
        UniqueConstraint(
            "namespace_key", "id", name="uq_policies_namespace_id"
        ),
        # Plain index on name preserves name-only lookup performance while
        # service code is still namespace-blind.
        Index("ix_policies_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    namespace_key: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=_NAMESPACE_SERVER_DEFAULT
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agents: Mapped[list["Agent"]] = relationship(
        "Agent", secondary=lambda: agent_policies, back_populates="policies"
    )
    # Many-to-many: Policy <> Control (direct relationship, no ControlSet layer)
    controls: Mapped[list["Control"]] = relationship(
        "Control", secondary=lambda: policy_controls, back_populates="policies"
    )


class Control(Base):
    __tablename__ = "controls"
    __table_args__ = (
        Index(
            "idx_controls_namespace_name_active",
            "namespace_key",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        UniqueConstraint(
            "namespace_key", "id", name="uq_controls_namespace_id"
        ),
        # Hard deletes of clone sources are restricted. The request path
        # soft-deletes controls so clone lineage remains intact.
        ForeignKeyConstraint(
            ["namespace_key", "cloned_from_control_id"],
            ["controls.namespace_key", "controls.id"],
            name="controls_cloned_from_control_fkey",
        ),
        # Plain partial index on name preserves name-only lookup performance
        # while service code is still namespace-blind. Mirrors the pattern
        # used for agents and policies; the partial filter matches the
        # existing call sites that already require deleted_at IS NULL.
        Index(
            "ix_controls_name",
            "name",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "idx_controls_cloned_from",
            "namespace_key",
            "cloned_from_control_id",
            postgresql_where=text("cloned_from_control_id IS NOT NULL"),
            sqlite_where=text("cloned_from_control_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    namespace_key: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=_NAMESPACE_SERVER_DEFAULT
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # JSONB payload describing control specifics
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    cloned_from_control_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Many-to-many backref: Control <> Policy
    policies: Mapped[list["Policy"]] = relationship(
        "Policy", secondary=lambda: policy_controls, back_populates="controls"
    )
    # Many-to-many backref: Control <> Agent (direct relationship)
    agents: Mapped[list["Agent"]] = relationship(
        "Agent", secondary=lambda: agent_controls, back_populates="controls"
    )


class ControlVersion(Base):
    __tablename__ = "control_versions"
    __table_args__ = (
        UniqueConstraint("control_id", "version_num", name="uq_control_versions_control_version"),
        Index("idx_control_versions_control_created", "control_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("controls.id"), nullable=False
    )
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("char_length(name) >= 10", name="ck_agents_name_min_length"),
        CheckConstraint("name ~ '^[a-z0-9:_-]+$'", name="ck_agents_name_format"),
        # Plain index on name preserves name-only lookup performance while
        # service code is still namespace-blind.
        Index("ix_agents_name", "name"),
    )

    namespace_key: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
        nullable=False,
        server_default=_NAMESPACE_SERVER_DEFAULT,
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


class ControlBinding(Base):
    """Attaches a control to an opaque external target.

    Each row is a single attachment scoped to a namespace. Uniqueness is
    enforced on ``(namespace_key, target_type, target_id, control_id)``.
    The ``enabled`` flag is a soft toggle - a disabled binding is preserved
    but excluded from the effective control set at runtime.

    Same-namespace integrity is enforced by the composite foreign key on
    ``(namespace_key, control_id)``: a binding cannot reference a control
    from another namespace.

    Soft deletes on the parent control (``deleted_at IS NOT NULL``) do not
    cascade to bindings; only hard deletes do. The runtime resolver is
    responsible for excluding soft-deleted controls when computing the
    effective control set.

    Future evolution: per-agent overrides and exemptions within a target
    are intentionally not modeled here. Two paths are possible if and when
    they become a product requirement:

    - re-introduce an ``agent_name`` column (with a partial-index pair on
      ``agent_name IS NULL`` / ``IS NOT NULL``) and an ``enabled``-aware
      most-specific-wins resolver. Supports both per-agent additions and
      per-agent exemptions.
    - or merge target-bearing resolution with the existing
      ``agent_controls`` table at runtime. Supports per-agent additions
      only; exemptions still require schema work because ``agent_controls``
      has no ``enabled`` flag.
    """

    __tablename__ = "control_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["namespace_key", "control_id"],
            ["controls.namespace_key", "controls.id"],
            name="control_bindings_control_fkey",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "namespace_key",
            "target_type",
            "target_id",
            "control_id",
            name="uq_control_bindings_target_control",
        ),
        Index(
            "idx_control_bindings_lookup",
            "namespace_key",
            "target_type",
            "target_id",
        ),
        # Leading-control_id index covers list_bindings(control_id=...)
        # filters and the ON DELETE CASCADE path from controls.
        Index(
            "idx_control_bindings_control",
            "namespace_key",
            "control_id",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    namespace_key: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=_NAMESPACE_SERVER_DEFAULT
    )
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    control_id: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


# =============================================================================
# Observability Models
# =============================================================================


class ControlExecutionEventDB(Base):
    """
    Raw control execution events with minimal indexed columns + JSONB.

    Schema designed for simplicity and flexibility:
    - Indexed columns: namespace_key, control_execution_id, timestamp, agent_name
    - Full event stored in JSONB 'data' column
    - Query-time aggregation from JSONB fields
    - No migrations needed for new event fields

    Primary access pattern: (namespace_key, agent_name, timestamp DESC) for stats queries.
    Expression index on (data->>'control_id') for grouping.
    """

    __tablename__ = "control_execution_events"

    # Primary key
    control_execution_id: Mapped[str] = mapped_column(
        String(36)
    )

    # Minimal indexed columns for efficient queries
    namespace_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=_NAMESPACE_SERVER_DEFAULT,
    )
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
        PrimaryKeyConstraint(
            "namespace_key",
            "control_execution_id",
            name="control_execution_events_pkey",
        ),
        Index("ix_events_namespace_agent_time", "namespace_key", "agent_name", timestamp.desc()),
        Index("ix_events_data_control_id", text("(data ->> 'control_id'::text)")),
    )
