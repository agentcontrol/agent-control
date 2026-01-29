"""Agent entity and step models."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .base import BaseModel

type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]

STEP_TYPE_TOOL = "tool"
STEP_TYPE_LLM = "llm"
BUILTIN_STEP_TYPES: tuple[str, str] = (STEP_TYPE_TOOL, STEP_TYPE_LLM)


class Agent(BaseModel):
    """
    Agent metadata for registration and tracking.

    An agent represents an AI system that can be protected and monitored.
    Each agent has a unique ID and can have multiple steps registered with it.
    """
    agent_id: UUID = Field(
        ..., description="Unique identifier for the agent (UUID format)"
    )
    agent_name: str = Field(
        ..., description="Human-readable name for the agent", min_length=1
    )
    agent_description: str | None = Field(
        None, description="Optional description of the agent's purpose"
    )
    agent_created_at: str | None = Field(
        None, description="ISO 8601 timestamp when agent was created"
    )
    agent_updated_at: str | None = Field(
        None, description="ISO 8601 timestamp when agent was last updated"
    )
    agent_version: str | None = Field(
        None, description="Semantic version string (e.g. '1.0.0')"
    )
    agent_metadata: dict[str, Any] | None = Field(
        None, description="Free-form metadata dictionary for custom properties"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "agent_id": "550e8400-e29b-41d4-a716-446655440000",
                    "agent_name": "customer-service-bot",
                    "agent_description": "Handles customer inquiries and support tickets",
                    "agent_version": "1.0.0",
                    "agent_metadata": {"team": "support", "environment": "production"}
                }
            ]
        }
    }


class StepSchema(BaseModel):
    """Schema for a registered agent step."""

    type: str = Field(
        ...,
        min_length=1,
        description="Step type for this schema (e.g., 'tool', 'llm')",
    )
    name: str = Field(..., description="Unique name for the step", min_length=1)
    description: str | None = Field(
        None, description="Optional description of the step"
    )
    input_schema: dict[str, Any] | None = Field(
        default=None, description="JSON schema describing step input"
    )
    output_schema: dict[str, Any] | None = Field(
        default=None, description="JSON schema describing step output"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata for the step"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "type": "tool",
                    "name": "search_knowledge_base",
                    "description": "Search the internal knowledge base",
                    "input_schema": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "output_schema": {
                        "results": {"type": "array", "items": {"type": "object"}}
                    },
                },
                {
                    "type": "llm",
                    "name": "support-answer",
                    "description": "Customer support response generation",
                    "input_schema": {
                        "messages": {"type": "array", "items": {"type": "object"}}
                    },
                    "output_schema": {"text": {"type": "string"}},
                },
            ]
        }
    }

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if not v:
            raise ValueError("type cannot be empty")
        return v


class Step(BaseModel):
    """Runtime payload for an agent step invocation."""

    type: str = Field(
        ...,
        min_length=1,
        description="Step type (e.g., 'tool', 'llm')",
    )
    name: str = Field(
        ..., min_length=1, description="Step name (tool name or model/chain id)"
    )
    input: JSONValue = Field(
        ..., description="Input content for this step"
    )
    output: JSONValue | None = Field(
        None, description="Output content for this step (None for pre-checks)"
    )
    context: JSONObject | None = Field(
        None, description="Optional context (conversation history, metadata, etc.)"
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if not v:
            raise ValueError("type cannot be empty")
        return v

    @model_validator(mode="after")
    def validate_builtin_types(self) -> Step:
        if self.type == STEP_TYPE_TOOL:
            if not isinstance(self.input, dict):
                raise ValueError("tool steps require object input")
        return self
