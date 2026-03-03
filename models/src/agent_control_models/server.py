from enum import StrEnum
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


class ConflictMode(StrEnum):
    """Conflict handling mode for initAgent registration updates.

    STRICT preserves compatibility checks and raises conflicts on incompatible changes.
    OVERWRITE applies latest-init-wins replacement for steps and evaluators.
    """

    STRICT = "strict"
    OVERWRITE = "overwrite"


class InitAgentEvaluatorRemoval(BaseModel):
    """Details for an evaluator removed during overwrite mode."""

    name: str = Field(..., description="Evaluator name removed by overwrite")
    referenced_by_active_controls: bool = Field(
        default=False,
        description="Whether this evaluator is still referenced by active controls",
    )
    control_ids: list[int] = Field(
        default_factory=list,
        description="IDs of active controls referencing this evaluator",
    )
    control_names: list[str] = Field(
        default_factory=list,
        description="Names of active controls referencing this evaluator",
    )


class InitAgentOverwriteChanges(BaseModel):
    """Detailed change summary for initAgent overwrite mode."""

    metadata_changed: bool = Field(
        default=False, description="Whether agent metadata changed"
    )
    steps_added: list["StepKey"] = Field(
        default_factory=list,
        description="Steps added by overwrite",
    )
    steps_updated: list["StepKey"] = Field(
        default_factory=list,
        description="Existing steps updated by overwrite",
    )
    steps_removed: list["StepKey"] = Field(
        default_factory=list,
        description="Steps removed by overwrite",
    )
    evaluators_added: list[str] = Field(
        default_factory=list,
        description="Evaluator names added by overwrite",
    )
    evaluators_updated: list[str] = Field(
        default_factory=list,
        description="Existing evaluator names updated by overwrite",
    )
    evaluators_removed: list[str] = Field(
        default_factory=list,
        description="Evaluator names removed by overwrite",
    )
    evaluator_removals: list[InitAgentEvaluatorRemoval] = Field(
        default_factory=list,
        description="Per-evaluator removal details, including active control references",
    )


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
    conflict_mode: ConflictMode = Field(
        default=ConflictMode.STRICT,
        description=(
            "Conflict handling mode for init registration updates. "
            "'strict' preserves existing compatibility checks. "
            "'overwrite' applies latest-init-wins replacement for steps and evaluators."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "agent": {
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
        description="Active protection controls for the agent",
    )
    overwrite_applied: bool = Field(
        default=False,
        description="True if overwrite mode changed registration data on an existing agent",
    )
    overwrite_changes: InitAgentOverwriteChanges = Field(
        default_factory=InitAgentOverwriteChanges,
        description="Detailed list of changes applied in overwrite mode",
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


class GetAgentPoliciesResponse(BaseModel):
    policy_ids: list[int] = Field(
        default_factory=list, description="IDs of policies associated with the agent"
    )


class SetPolicyResponse(BaseModel):
    """Compatibility response for singular policy assignment endpoint."""

    success: bool = Field(description="Whether the request succeeded")
    old_policy_id: int | None = Field(
        default=None,
        description="Previously associated policy ID, if any",
    )


class GetPolicyResponse(BaseModel):
    """Compatibility response for singular policy retrieval endpoint."""

    policy_id: int = Field(description="Associated policy ID")


class DeletePolicyResponse(BaseModel):
    """Compatibility response for singular policy deletion endpoint."""

    success: bool = Field(description="Whether the request succeeded")


class AgentControlsResponse(BaseModel):
    controls: list[Control] = Field(
        description="List of active controls associated with the agent"
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


class RemoveAgentControlResponse(BaseModel):
    """Response for removing a direct agent-control association."""

    success: bool = Field(description="Whether the request succeeded")
    removed_direct_association: bool = Field(
        description="True if a direct agent-control link was removed"
    )
    control_still_active: bool = Field(
        description="True if the control remains active via policy association(s)"
    )


class GetControlDataResponse(BaseModel):
    data: ControlDefinition = Field(description="Control data payload")


class SetControlDataRequest(BaseModel):
    """Request to update control configuration data."""
    data: ControlDefinition = Field(
        ...,
        description="Control configuration data (replaces existing)",
    )


class ValidateControlDataRequest(BaseModel):
    """Request to validate control configuration data without saving."""

    data: ControlDefinition = Field(
        ...,
        description="Control configuration data to validate",
    )


class SetControlDataResponse(BaseModel):
    success: bool = Field(description="Whether the control data was updated")


class ValidateControlDataResponse(BaseModel):
    success: bool = Field(description="Whether the control data is valid")


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

    agent_name: str = Field(..., description="Unique identifier of the agent")
    policy_ids: list[int] = Field(
        default_factory=list, description="IDs of policies associated with the agent"
    )
    created_at: str | None = Field(None, description="ISO 8601 timestamp when agent was created")
    step_count: int = Field(0, description="Number of steps registered with the agent")
    evaluator_count: int = Field(0, description="Number of evaluators registered with the agent")
    active_controls_count: int = Field(
        0, description="Number of active controls for this agent"
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


class AgentRef(BaseModel):
    """Reference to an agent (for listing which agents use a control)."""

    agent_name: str = Field(..., description="Agent name")


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
    used_by_agent: AgentRef | None = Field(None, description="Agent using this control")
    # TODO: Follow-up with full `used_by_agents` list for richer attribution.
    used_by_agents_count: int = Field(
        0, description="Number of unique agents using this control"
    )


class ListControlsResponse(BaseModel):
    """Response for listing controls."""

    controls: list[ControlSummary] = Field(..., description="List of control summaries")
    pagination: PaginationInfo = Field(..., description="Pagination metadata")


class DeleteControlResponse(BaseModel):
    """Response for deleting a control."""

    success: bool = Field(..., description="Whether the control was deleted")
    dissociated_from: list[int] = Field(
        default_factory=list,
        description="Deprecated: policy IDs the control was removed from before deletion",
    )
    dissociated_from_policies: list[int] = Field(
        default_factory=list,
        description="Policy IDs the control was removed from before deletion",
    )
    dissociated_from_agents: list[str] = Field(
        default_factory=list,
        description="Agent names the control was removed from before deletion",
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
