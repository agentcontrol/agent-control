import datetime as dt
import uuid as _uuid
from typing import Any, Optional

from agent_control_models.agent import AgentTool
from agent_control_models.base import BaseModel
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class AgentVersionedTool(BaseModel):
    version: int
    tool: AgentTool

class AgentData(BaseModel):
    agent_metadata: dict[str, Any]
    tools: list[AgentVersionedTool]
    # Renamed to agent_schema to avoid Pydantic BaseModel.schema() conflict
    agent_schema: dict[str, Any] | None = None

class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="policy")
    # Many-to-many: Policy <> ControlSet
    control_sets: Mapped[list["ControlSet"]] = relationship(
        "ControlSet", secondary=lambda: policy_control_sets, back_populates="policies"
    )


# Association tables for many-to-many relationships
policy_control_sets: Table = Table(
    "policy_control_sets",
    Base.metadata,
    Column("policy_id", ForeignKey("policies.id"), primary_key=True, index=True),
    Column("control_set_id", ForeignKey("control_sets.id"), primary_key=True, index=True),
)

control_set_controls: Table = Table(
    "control_set_controls",
    Base.metadata,
    Column("control_set_id", ForeignKey("control_sets.id"), primary_key=True, index=True),
    Column("control_id", ForeignKey("controls.id"), primary_key=True, index=True),
)


class ControlSet(Base):
    __tablename__ = "control_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Many-to-many: ControlSet <> Policy
    policies: Mapped[list["Policy"]] = relationship(
        "Policy", secondary=lambda: policy_control_sets, back_populates="control_sets"
    )
    # Many-to-many: ControlSet <> Control
    controls: Mapped[list["Control"]] = relationship(
        "Control", secondary=lambda: control_set_controls, back_populates="control_sets"
    )


class Control(Base):
    __tablename__ = "controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # JSONB payload describing control specifics
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    # Many-to-many backref: Control <> ControlSet
    control_sets: Mapped[list["ControlSet"]] = relationship(
        "ControlSet", secondary=lambda: control_set_controls, back_populates="controls"
    )


class Agent(Base):
    __tablename__ = "agents"

    agent_uuid: Mapped[_uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("policies.id"), nullable=True, index=True
    )
    policy: Mapped[Optional["Policy"]] = relationship("Policy", back_populates="agents")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(), server_default=text("CURRENT_TIMESTAMP"), nullable=False, index=True
    )


class CustomEvaluator(Base):
    """Custom evaluator plugin stored in database.

    These are user-defined evaluators with Python code that can be referenced
    by name in Controls, just like built-in plugins (regex, list).
    """

    __tablename__ = "custom_evaluators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    code: Mapped[str] = mapped_column(String, nullable=False)  # Python code
    config_schema: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), nullable=False
    )
    entrypoint: Mapped[str] = mapped_column(
        String(255), server_default=text("'evaluate'"), nullable=False
    )
    timeout_ms: Mapped[int] = mapped_column(
        Integer, server_default=text("5000"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=dt.datetime.utcnow,
        nullable=False,
    )


