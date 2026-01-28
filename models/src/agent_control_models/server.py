from typing import Any

from pydantic import Field

from .agent import Agent, StepSchema
from .base import BaseModel
from .controls import ControlDefinition
from .policy import Control


class EvaluatorSchema(BaseModel):
    """Schema for a custom evaluator registered with an agent.

    Custom evaluators are Evaluator classes deployed with the engine.
    This schema is registered via initAgent for validation and UI purposes.
    """

    name: str = Field(..., min_length=1, max_length=255, description="Unique evaluator name")
    config_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for evaluator config validation",
    )
    description: str | None = Field(None, max_length=1000, description="Optional description")


class CreatePolicyRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
        description="Unique policy name (letters, numbers, hyphens, underscores)",
    )


class CreateControlRequest(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
        description="Unique control name (letters, numbers, hyphens, underscores)",
    )


class InitAgentRequest(BaseModel):
    """Request to initialize or update an agent registration."""

    agent: Agent = Field(..., description="Agent metadata including ID, name, and version")
    steps: list[StepSchema] = Field(
        default_factory=list, description="List of steps available to the agent"
    )
    evaluators: list[EvaluatorSchema] = Field(
        default_factory=list,
        description="Custom evaluator schemas for config validation",
    )
    force_replace: bool = Field(
        default=False,
        description=(
            "If true, replace corrupted agent data instead of failing. "
            "Use only when agent data is corrupted and cannot be parsed."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "agent": {
                        "agent_id": "550e8400-e29b-41d4-a716-446655440000",
                        "agent_name": "customer-service-bot",
                        "agent_description": "Handles customer inquiries",
                        "agent_version": "1.0.0",
                    },
                    "steps": [
                        {
                            "type": "tool",
                            "name": "search_kb",
                            "input_schema": {"query": {"type": "string"}},
                            "output_schema": {"results": {"type": "array"}},
                        }
                    ],
                    "evaluators": [
                        {
                            "name": "pii-detector",
                            "config_schema": {
                                "type": "object",
                                "properties": {"sensitivity": {"type": "string"}},
                            },
                            "description": "Detects PII in text",
                        }
                    ],
                }
            ]
        }
    }

class InitAgentResponse(BaseModel):
    """Response from agent initialization."""
    created: bool = Field(
        ..., description="True if agent was newly created, False if updated"
    )
    controls: list[Control] = Field(
        default_factory=list,
        description="Active protection controls for the agent (if policy assigned)",
    )


class GetAgentResponse(BaseModel):
    """Response containing agent details and registered steps."""
    agent: Agent = Field(..., description="Agent metadata")
    steps: list[StepSchema] = Field(..., description="Steps registered with this agent")
    evaluators: list[EvaluatorSchema] = Field(
        default_factory=list, description="Custom evaluators registered with this agent"
    )


class CreatePolicyResponse(BaseModel):
    policy_id: int = Field(description="Identifier of the created policy")


class SetPolicyResponse(BaseModel):
    success: bool = Field(description="Whether the policy was successfully assigned")
    old_policy_id: int | None = Field(
        default=None, description="Previous policy id if one was replaced"
    )


class GetPolicyResponse(BaseModel):
    policy_id: int = Field(description="Identifier of the policy assigned to the agent")


class DeletePolicyResponse(BaseModel):
    success: bool = Field(description="Whether the policy was successfully removed")


class AgentControlsResponse(BaseModel):
    controls: list[Control] = Field(
        description="List of controls associated with the agent via its policy"
    )


class CreateControlResponse(BaseModel):
    control_id: int = Field(description="Identifier of the created control")


class GetControlResponse(BaseModel):
    """Response containing control details."""

    id: int = Field(..., description="Control ID")
    name: str = Field(..., description="Control name")
    data: ControlDefinition | None = Field(
        None, description="Control configuration data (None if not yet configured)"
    )


class GetPolicyControlsResponse(BaseModel):
    """Response containing control IDs associated with a policy."""

    control_ids: list[int] = Field(
        description="List of control IDs associated with the policy"
    )


class AssocResponse(BaseModel):
    success: bool = Field(description="Whether the association change succeeded")


class GetControlDataResponse(BaseModel):
    data: ControlDefinition = Field(description="Control data payload")


class SetControlDataRequest(BaseModel):
    """Request to update control configuration data."""
    data: ControlDefinition = Field(
        ...,
        description="Control configuration data (replaces existing)",
    )


class SetControlDataResponse(BaseModel):
    success: bool = Field(description="Whether the control data was updated")


class StepKey(BaseModel):
    """Identifies a registered step schema by type and name."""

    type: str = Field(..., min_length=1, description="Step type")
    name: str = Field(..., description="Registered step name")


class PatchAgentRequest(BaseModel):
    """Request to modify an agent (remove steps/evaluators)."""

    remove_steps: list[StepKey] = Field(
        default_factory=list, description="Step identifiers to remove from the agent"
    )
    remove_evaluators: list[str] = Field(
        default_factory=list, description="Evaluator names to remove from the agent"
    )


class PatchAgentResponse(BaseModel):
    """Response from agent modification."""

    steps_removed: list[StepKey] = Field(
        default_factory=list, description="Step identifiers that were removed"
    )
    evaluators_removed: list[str] = Field(
        default_factory=list, description="Evaluator names that were removed"
    )


class AgentSummary(BaseModel):
    """Summary of an agent for list responses."""

    agent_id: str = Field(..., description="UUID of the agent")
    agent_name: str = Field(..., description="Human-readable name of the agent")
    policy_id: int | None = Field(None, description="ID of assigned policy, if any")
    created_at: str | None = Field(None, description="ISO 8601 timestamp when agent was created")
    step_count: int = Field(0, description="Number of steps registered with the agent")
    evaluator_count: int = Field(0, description="Number of evaluators registered with the agent")
    active_controls_count: int = Field(
        0, description="Number of active controls from agent's policy"
    )


class PaginationInfo(BaseModel):
    """Pagination metadata for cursor-based pagination."""

    limit: int = Field(..., description="Number of items per page")
    total: int = Field(..., description="Total number of items")
    next_cursor: str | None = Field(
        None, description="Cursor for fetching the next page (null if no more pages)"
    )
    has_more: bool = Field(..., description="Whether there are more pages available")


class ListAgentsResponse(BaseModel):
    """Response for listing agents."""

    agents: list[AgentSummary] = Field(..., description="List of agent summaries")
    pagination: PaginationInfo = Field(..., description="Pagination metadata")


# =============================================================================
# Control List/Update/Delete Models
# =============================================================================


class ControlSummary(BaseModel):
    """Summary of a control for list responses."""

    id: int = Field(..., description="Control ID")
    name: str = Field(..., description="Control name")
    description: str | None = Field(None, description="Control description")
    enabled: bool = Field(True, description="Whether control is enabled")
    execution: str | None = Field(None, description="'server' or 'sdk'")
    step_types: list[str] | None = Field(None, description="Step types in scope")
    stages: list[str] | None = Field(None, description="Evaluation stages in scope")
    tags: list[str] = Field(default_factory=list, description="Control tags")


class ListControlsResponse(BaseModel):
    """Response for listing controls."""

    controls: list[ControlSummary] = Field(..., description="List of control summaries")
    pagination: PaginationInfo = Field(..., description="Pagination metadata")


class DeleteControlResponse(BaseModel):
    """Response for deleting a control."""

    success: bool = Field(..., description="Whether the control was deleted")
    dissociated_from: list[int] = Field(
        default_factory=list,
        description="Policy IDs the control was removed from before deletion",
    )


class PatchControlRequest(BaseModel):
    """Request to update control metadata (name, enabled status)."""

    name: str | None = Field(None, description="New name for the control")
    enabled: bool | None = Field(None, description="Enable or disable the control")


class PatchControlResponse(BaseModel):
    """Response from control metadata update."""

    success: bool = Field(..., description="Whether the update succeeded")
    name: str = Field(..., description="Current control name (may have changed)")
    enabled: bool | None = Field(
        None, description="Current enabled status (if control has data configured)"
    )


# =============================================================================
# Evaluator Config Store Models
# =============================================================================


class EvaluatorConfigItem(BaseModel):
    """Evaluator config template stored in the server."""

    id: int = Field(..., description="Evaluator config ID")
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
        description="Unique evaluator config name (letters, numbers, hyphens, underscores)",
    )
    description: str | None = Field(
        None, max_length=1000, description="Optional description"
    )
    evaluator: str = Field(..., min_length=1, description="Evaluator name (built-in or custom)")
    config: dict[str, Any] = Field(..., description="Evaluator-specific configuration")
    created_at: str | None = Field(None, description="ISO 8601 created timestamp")
    updated_at: str | None = Field(None, description="ISO 8601 updated timestamp")


class CreateEvaluatorConfigRequest(BaseModel):
    """Request to create an evaluator config template."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
        description="Unique evaluator config name (letters, numbers, hyphens, underscores)",
    )
    description: str | None = Field(
        None, max_length=1000, description="Optional description"
    )
    evaluator: str = Field(..., min_length=1, description="Evaluator name (built-in or custom)")
    config: dict[str, Any] = Field(..., description="Evaluator-specific configuration")


class UpdateEvaluatorConfigRequest(BaseModel):
    """Request to replace an evaluator config template."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
        description="Unique evaluator config name (letters, numbers, hyphens, underscores)",
    )
    description: str | None = Field(
        None, max_length=1000, description="Optional description"
    )
    evaluator: str = Field(..., min_length=1, description="Evaluator name (built-in or custom)")
    config: dict[str, Any] = Field(..., description="Evaluator-specific configuration")


class ListEvaluatorConfigsResponse(BaseModel):
    """Response for listing evaluator configs."""

    evaluator_configs: list[EvaluatorConfigItem] = Field(
        ..., description="List of evaluator configs"
    )
    pagination: PaginationInfo = Field(..., description="Pagination metadata")


class DeleteEvaluatorConfigResponse(BaseModel):
    """Response for deleting an evaluator config."""

    success: bool = Field(..., description="Whether the evaluator config was deleted")
