"""Typed contracts for Agent Control's inference gateway POC."""

from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .actions import ActionDecision
from .agent import AGENT_NAME_MIN_LENGTH, AGENT_NAME_PATTERN, JSONObject, normalize_agent_name
from .base import BaseModel

GatewayProtocol = Literal["openai", "anthropic"]


class GatewayModelCandidate(BaseModel):
    """A model and wire protocol the gateway can route to."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    protocol: GatewayProtocol


class GatewayModelTier(BaseModel):
    """Ordered model candidates configured for one capability or budget tier."""

    models: list[GatewayModelCandidate] = Field(min_length=1)


class GatewayPreflightRequest(BaseModel):
    """Candidate routes and task information supplied before inference."""

    # Legacy field retained for old POC clients. Policy lookup still comes
    # from the authenticated route target, and the server checks this value.
    agent_name: str | None = Field(
        default=None,
        min_length=AGENT_NAME_MIN_LENGTH,
        pattern=AGENT_NAME_PATTERN,
    )
    # When present, runtime authorization is bound to this Galileo stream UUID.
    # Agent name remains the policy and attribution identity in the route.
    log_stream_id: UUID | None = None
    task_type: str = Field(default="default", min_length=1)
    task_context: JSONObject | None = None
    candidate_models: list[GatewayModelCandidate] = Field(default_factory=list)
    # Compatibility input for clients using the original single-model POC.
    model: str | None = Field(default=None, min_length=1)
    prompt: str | None = None

    @field_validator("agent_name", mode="before")
    @classmethod
    def normalize_legacy_agent_name(cls, value: str | None) -> str | None:
        return None if value is None else normalize_agent_name(value)

    @model_validator(mode="after")
    def require_candidate(self) -> Self:
        if not self.candidate_models and self.model is None:
            raise ValueError("Provide candidate_models or the legacy model field.")
        return self


class GatewayUsageSettlementRequest(BaseModel):
    """Actual token usage reported by the gateway after inference."""

    log_stream_id: UUID | None = None
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class GatewayBudgetState(BaseModel):
    """Accumulated token use and configured budget threshold state."""

    used_tokens: int = Field(ge=0)
    limit_tokens: int = Field(gt=0)
    utilization: float = Field(ge=0.0, le=1.0)
    threshold: float = Field(gt=0.0, le=1.0)
    threshold_reached: bool
    over_limit: bool


class GatewayPreflightResponse(BaseModel):
    """Control and budget decision returned before inference."""

    allowed: bool
    policy: str
    budget: GatewayBudgetState | None
    reason: str


class GatewayRouteDecisionResponse(GatewayPreflightResponse):
    """Route result directly consumable by an inference gateway adapter."""

    provider: str | None
    model: str | None
    protocol: GatewayProtocol | None
    task_type: str
    decision: Literal["route", "deny"]
    action: ActionDecision | None = None


class GatewayUsageSettlementResponse(BaseModel):
    """Budget state after actual usage has been accumulated."""

    policy: str
    budget: GatewayBudgetState
    reason: str
