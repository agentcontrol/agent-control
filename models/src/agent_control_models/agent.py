"""Agent entity and step models."""
from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from .base import BaseModel

type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]

STEP_TYPE_TOOL = "tool"
STEP_TYPE_LLM = "llm"
BUILTIN_STEP_TYPES: tuple[str, str] = (STEP_TYPE_TOOL, STEP_TYPE_LLM)

AGENT_NAME_MIN_LENGTH = 10
AGENT_NAME_PATTERN = r"^[a-z0-9:_-]+$"
_AGENT_NAME_REGEX = re.compile(AGENT_NAME_PATTERN)


def normalize_agent_name(value: str) -> str:
    """Normalize and validate an agent identifier."""
    normalized = value.strip().lower()
    if len(normalized) < AGENT_NAME_MIN_LENGTH:
        raise ValueError(
            f"agent_name must be at least {AGENT_NAME_MIN_LENGTH} characters long"
        )
    if not _AGENT_NAME_REGEX.fullmatch(normalized):
        raise ValueError(
            "agent_name may only contain lowercase letters, digits, ':', '_' or '-'"
        )
    return normalized


class Agent(BaseModel):
    """
    Agent metadata for registration and tracking.

    An agent represents an AI system that can be protected and monitored.
    Each agent has a unique immutable name and can have multiple steps registered with it.
    """
    agent_name: str = Field(
        ...,
        min_length=AGENT_NAME_MIN_LENGTH,
        pattern=AGENT_NAME_PATTERN,
        description="Unique immutable identifier for the agent",
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
                    "agent_name": "customer-service-bot",
                    "agent_description": "Handles customer inquiries and support tickets",
                    "agent_version": "1.0.0",
                    "agent_metadata": {"team": "support", "environment": "production"}
                }
            ]
        }
    }

    @field_validator("agent_name", mode="before")
    @classmethod
    def validate_and_normalize_agent_name(cls, value: str) -> str:
        return normalize_agent_name(str(value))


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
