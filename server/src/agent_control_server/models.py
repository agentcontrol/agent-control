import datetime as dt
import uuid as _uuid
from typing import Any, Optional

from agent_control_models.agent import AgentTool
from agent_control_models.base import BaseModel
from agent_control_models.server import EvaluatorSchema
from pydantic import Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class AgentData(BaseModel):
    """Agent metadata stored in JSONB."""

    agent_metadata: dict[str, Any]
    tools: list[AgentTool] = Field(default_factory=list)
    evaluators: list[EvaluatorSchema] = Field(default_factory=list)


# Association table for Policy <> Control many-to-many relationship
policy_controls: Table = Table(
    "policy_controls",
    Base.metadata,
    Column("policy_id", ForeignKey("policies.id"), primary_key=True, index=True),
    Column("control_id", ForeignKey("controls.id"), primary_key=True, index=True),
)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="policy")
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



