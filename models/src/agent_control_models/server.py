import datetime as dt
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from .agent import Agent, StepSchema
from .base import BaseModel
from .controls import (
    ControlAction,
    ControlDefinition,
    TemplateControlInput,
    TemplateDefinition,
    TemplateValue,
    UnrenderedTemplateControl,
)
from .policy import Control


def _strip_slug_name(v: str) -> str:
    """Strip leading/trailing whitespace for slug-style names."""
    return v.strip() if isinstance(v, str) else v


_CONTROL_DEFINITION_ADAPTER = TypeAdapter(ControlDefinition)
_TEMPLATE_CONTROL_INPUT_ADAPTER = TypeAdapter(TemplateControlInput)
_TEMPLATE_ONLY_CONTROL_FIELDS = frozenset({"template", "template_values"})
_RAW_CONTROL_INPUT_FIELDS = (
    frozenset(ControlDefinition.model_fields) - _TEMPLATE_ONLY_CONTROL_FIELDS
)
_RAW_CONTROL_INPUT_FIELDS = _RAW_CONTROL_INPUT_FIELDS.union(
    {
        # Legacy flat leaf fields still accepted for raw controls.
        "selector",
        "evaluator",
    }
)


def _parse_control_input(v: Any) -> Any:
    """Discriminate raw control inputs from template-backed inputs.

    A non-null ``template`` key means template-backed input and must be parsed
    strictly as ``TemplateControlInput`` so mixed payloads are rejected.
    """
    if isinstance(v, (ControlDefinition, TemplateControlInput)):
        return v
    if not isinstance(v, dict):
        return v

    if v.get("template") is not None:
        mixed_fields = sorted(field for field in v if field in _RAW_CONTROL_INPUT_FIELDS)
        if mixed_fields:
            raise ValueError(
                "Template-backed control input cannot mix template fields with rendered control "
                f"fields. Remove raw fields: {', '.join(mixed_fields)}."
            )
        return _TEMPLATE_CONTROL_INPUT_ADAPTER.validate_python(v)
    return _CONTROL_DEFINITION_ADAPTER.validate_python(v)


# Canonicalization at the API boundary: all SlugName fields are trimmed before
# validation. Server and SDKs use these request models; no client need pre-trim.
SlugName = Annotated[
    str,
    BeforeValidator(_strip_slug_name),
    StringConstraints(
        min_length=1,
        max_length=255,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$",
    ),
]

ControlInput = Annotated[
    ControlDefinition | TemplateControlInput,
    BeforeValidator(_parse_control_input),
]


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
    name: SlugName = Field(
        ...,
        description="Unique policy name (letters, numbers, hyphens, underscores)",
    )


class CreateControlRequest(BaseModel):
    name: SlugName = Field(
        ...,
        description="Unique control name (letters, numbers, hyphens, underscores)",
    )
    data: ControlInput = Field(
        ...,
        description="Control definition to validate and store during creation",
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
    target_type: Annotated[
        str | None, StringConstraints(min_length=1, max_length=255)
    ] = Field(
        default=None,
        description=(
            "Optional opaque target kind. When supplied with target_id, the "
            "returned controls include controls bound to that target via "
            "control bindings, in addition to the agent's direct and "
            "policy-derived controls."
        ),
    )
    target_id: Annotated[
        str | None, StringConstraints(min_length=1, max_length=255)
    ] = Field(
        default=None,
        description=(
            "Optional opaque target identifier. Required when target_type is "
            "supplied."
        ),
    )

    @model_validator(mode="after")
    def _check_target_pair(self) -> Self:
        if (self.target_type is None) != (self.target_id is None):
            raise ValueError(
                "target_type and target_id must be supplied together."
            )
        return self

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
        description=(
            "List of agent-associated controls matching the requested state filters "
            "(all associated controls by default, including disabled and unrendered controls)"
        )
    )


class CreateControlResponse(BaseModel):
    control_id: int = Field(description="Identifier of the created control")


class GetControlResponse(BaseModel):
    """Response containing control details."""

    id: int = Field(..., description="Control ID")
    name: str = Field(..., description="Control name")
    cloned_from_control_id: int | None = Field(
        None, description="Source control ID when this control is a clone."
    )
    data: ControlDefinition | UnrenderedTemplateControl = Field(
        description=(
            "Control configuration data. A ControlDefinition for raw/rendered "
            "controls or an UnrenderedTemplateControl for unrendered templates."
        ),
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
    data: ControlDefinition | UnrenderedTemplateControl = Field(
        description="Control data payload (rendered control or unrendered template)"
    )


class GetControlSchemaResponse(BaseModel):
    model_config = {"populate_by_name": True}

    schema_: dict[str, Any] = Field(
        alias="schema",
        serialization_alias="schema",
        description="JSON Schema for a full ControlDefinition payload",
    )


class SetControlDataRequest(BaseModel):
    """Request to update control configuration data."""
    data: ControlInput = Field(
        ...,
        description="Control configuration data (replaces existing)",
    )


class ValidateControlDataRequest(BaseModel):
    """Request to validate control configuration data without saving."""

    data: ControlInput = Field(
        ...,
        description="Control configuration data to validate",
    )


class SetControlDataResponse(BaseModel):
    success: bool = Field(description="Whether the control data was updated")


class ValidateControlDataResponse(BaseModel):
    success: bool = Field(description="Whether the control data is valid")


class RenderControlTemplateRequest(BaseModel):
    """Request to render a template-backed control without persisting it."""

    model_config = ConfigDict(extra="forbid")

    template: TemplateDefinition = Field(..., description="Template definition to render")
    template_values: dict[str, TemplateValue] = Field(
        default_factory=dict,
        description="Template parameter values used during rendering",
    )


class RenderControlTemplateResponse(BaseModel):
    """Rendered template preview response."""

    control: ControlDefinition = Field(
        ...,
        description="Rendered control definition including template metadata",
    )


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


class PolicyRef(BaseModel):
    """Reference to a policy attached to a control."""

    policy_id: int = Field(..., description="Policy ID")


class TargetAttachmentRef(BaseModel):
    """Reference to a target binding attached to a control."""

    binding_id: int = Field(..., description="Control binding ID")
    target_type: str = Field(..., description="Opaque target kind")
    target_id: str = Field(..., description="Opaque target identifier")
    enabled: bool = Field(..., description="Whether this target binding is enabled")


class ControlAttachments(BaseModel):
    """Attachments for a listed control."""

    agents: list[AgentRef] = Field(
        default_factory=list,
        description="Direct agent associations for this control",
    )
    policies: list[PolicyRef] = Field(
        default_factory=list,
        description="Policy associations for this control",
    )
    targets: list[TargetAttachmentRef] = Field(
        default_factory=list,
        description="Target bindings for this control",
    )
    targets_total: int = Field(
        default=0,
        description="Total target bindings matching the attachment filters",
    )
    targets_truncated: bool = Field(
        default=False,
        description="Whether the target bindings list was capped",
    )


class ControlSummary(BaseModel):
    """Summary of a control for list responses."""

    id: int = Field(..., description="Control ID")
    name: str = Field(..., description="Control name")
    cloned_from_control_id: int | None = Field(
        None, description="Source control ID when this control is a clone."
    )
    description: str | None = Field(None, description="Control description")
    enabled: bool = Field(True, description="Whether control is enabled")
    execution: str | None = Field(None, description="'server' or 'sdk'")
    action: ControlAction | None = Field(
        None, description="Action applied when the control matches."
    )
    step_types: list[str] | None = Field(None, description="Step types in scope")
    stages: list[str] | None = Field(None, description="Evaluation stages in scope")
    tags: list[str] = Field(default_factory=list, description="Control tags")
    template_backed: bool = Field(
        False,
        description="Whether the control was created from a template",
    )
    template_rendered: bool | None = Field(
        None,
        description=(
            "Whether a template-backed control has been rendered. "
            "True for rendered templates, False for unrendered templates, "
            "None for non-template controls."
        ),
    )
    used_by_agent: AgentRef | None = Field(None, description="Agent using this control")
    # TODO: Follow-up with full `used_by_agents` list for richer attribution.
    used_by_agents_count: int = Field(
        0, description="Number of unique agents using this control"
    )
    attachments: ControlAttachments | None = Field(
        None,
        description=(
            "Expanded attachment details. Present when list controls is called "
            "with include_attachments=true."
        ),
    )


class ListControlsResponse(BaseModel):
    """Response for listing controls."""

    controls: list[ControlSummary] = Field(..., description="List of control summaries")
    pagination: PaginationInfo = Field(..., description="Pagination metadata")


class ControlVersionSummary(BaseModel):
    """Summary of a single control version."""

    version_num: int = Field(..., description="Monotonic version number for the control")
    event_type: str = Field(..., description="Machine-readable event type for this version")
    note: str | None = Field(None, description="Human-readable note describing the change")
    created_at: str = Field(..., description="ISO 8601 timestamp when this version was created")


class ListControlVersionsResponse(BaseModel):
    """Response for listing control versions."""

    versions: list[ControlVersionSummary] = Field(
        ..., description="Control versions ordered newest-first"
    )
    pagination: PaginationInfo = Field(..., description="Pagination metadata")


class GetControlVersionResponse(BaseModel):
    """Response containing a full control version snapshot."""

    version_num: int = Field(..., description="Monotonic version number for the control")
    event_type: str = Field(..., description="Machine-readable event type for this version")
    note: str | None = Field(None, description="Human-readable note describing the change")
    created_at: str = Field(..., description="ISO 8601 timestamp when this version was created")
    snapshot: dict[str, Any] = Field(
        ...,
        description=(
            "Raw persisted snapshot of the control state at this version, including "
            "metadata such as name, deleted_at, and cloned_from_control_id."
        ),
    )


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
    detached_target_bindings: list[int] = Field(
        default_factory=list,
        description="Control binding IDs that were removed before deletion",
    )


class PatchControlRequest(BaseModel):
    """Request to update control metadata (name, enabled status)."""

    name: SlugName | None = Field(
        None,
        description="New control name (letters, numbers, hyphens, underscores)",
    )
    enabled: bool | None = Field(None, description="Enable or disable the control")


class PatchControlResponse(BaseModel):
    """Response from control metadata update."""

    success: bool = Field(..., description="Whether the update succeeded")
    name: str = Field(..., description="Current control name (may have changed)")
    enabled: bool | None = Field(
        None, description="Current enabled status (if control has data configured)"
    )


# Control binding requests / responses.

ControlBindingTargetField = Annotated[
    str,
    StringConstraints(min_length=1, max_length=255),
]


class CloneAndBindTargetBinding(BaseModel):
    """Target binding to create for a cloned control."""

    model_config = ConfigDict(extra="forbid")

    target_type: ControlBindingTargetField = Field(
        ...,
        description="Opaque attachment kind (caller-defined; e.g. 'environment', 'session').",
    )
    target_id: ControlBindingTargetField = Field(
        ..., description="Opaque external identifier within the target_type."
    )
    enabled: bool = Field(
        default=True,
        description="Whether the created binding is active.",
    )


class CloneAndBindControlRequest(BaseModel):
    """Request to clone a control and attach the clone to one target."""

    model_config = ConfigDict(extra="forbid")

    name: SlugName | None = Field(
        None,
        description=(
            "Optional unique name for the cloned control. If omitted, the server "
            "generates a name from the source control name."
        ),
    )
    target_binding: CloneAndBindTargetBinding = Field(
        ..., description="Target binding to create for the cloned control."
    )


class CloneAndBindControlResponse(BaseModel):
    """Response from cloning and binding a control."""

    id: int = Field(..., description="Identifier of the cloned control.")
    name: str = Field(..., description="Name of the cloned control.")
    cloned_from_control_id: int = Field(..., description="Source control ID.")
    binding_id: int = Field(..., description="Identifier of the created binding.")


class CreateControlBindingRequest(BaseModel):
    """Request to attach a control to an opaque external target."""

    target_type: ControlBindingTargetField = Field(
        ...,
        description="Opaque attachment kind (caller-defined; e.g. 'environment', 'session').",
    )
    target_id: ControlBindingTargetField = Field(
        ..., description="Opaque external identifier within the target_type."
    )
    control_id: int = Field(
        ..., gt=0, description="ID of the control to attach."
    )
    enabled: bool = Field(
        default=True,
        description=(
            "Whether the binding is active. Disabled bindings are preserved "
            "but excluded from the effective control set at runtime."
        ),
    )


class CreateControlBindingResponse(BaseModel):
    """Response from creating a control binding."""

    binding_id: int = Field(..., description="Identifier of the created binding.")


class GetControlBindingResponse(BaseModel):
    """Detail view of a single control binding."""

    id: int
    namespace_key: str
    target_type: str
    target_id: str
    control_id: int
    enabled: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class ListControlBindingsResponse(BaseModel):
    """Paginated/filtered list of control bindings."""

    bindings: list[GetControlBindingResponse] = Field(default_factory=list)
    pagination: PaginationInfo = Field(
        ...,
        description="Cursor-based pagination metadata.",
    )


class PatchControlBindingRequest(BaseModel):
    """Request to update a control binding's enabled flag."""

    enabled: bool = Field(..., description="New enabled value for the binding.")


class PatchControlBindingResponse(BaseModel):
    """Response from updating a control binding."""

    success: bool = Field(..., description="Whether the update succeeded.")
    enabled: bool = Field(..., description="Current enabled value.")


class DeleteControlBindingResponse(BaseModel):
    """Response from deleting a control binding."""

    success: bool = Field(..., description="Whether the deletion succeeded.")


class UpsertControlBindingRequest(BaseModel):
    """Request to attach (or update) a control binding by natural key.

    Idempotent: an existing binding with the same
    ``(target_type, target_id, control_id)`` is updated in-place;
    otherwise a new binding is created.
    """

    target_type: ControlBindingTargetField = Field(
        ..., description="Opaque attachment kind."
    )
    target_id: ControlBindingTargetField = Field(
        ..., description="Opaque external identifier within the target_type."
    )
    control_id: int = Field(
        ..., gt=0, description="ID of the control to attach."
    )
    enabled: bool = Field(
        default=True, description="Whether the binding is active."
    )


class UpsertControlBindingResponse(BaseModel):
    """Response from a natural-key upsert."""

    binding_id: int = Field(..., description="Identifier of the binding.")
    created: bool = Field(
        ...,
        description=(
            "True when a new binding was created; False when an existing "
            "binding was updated in place."
        ),
    )
    enabled: bool = Field(..., description="Current enabled value.")


class PatchControlBindingByKeyRequest(BaseModel):
    """Request to update an existing control binding by natural key."""

    target_type: ControlBindingTargetField = Field(
        ..., description="Opaque attachment kind."
    )
    target_id: ControlBindingTargetField = Field(
        ..., description="Opaque external identifier within the target_type."
    )
    control_id: int = Field(
        ..., gt=0, description="ID of the bound control."
    )
    enabled: bool = Field(..., description="New enabled value for the binding.")


class DeleteControlBindingByKeyRequest(BaseModel):
    """Request to detach a control binding by natural key (idempotent)."""

    target_type: ControlBindingTargetField = Field(...)
    target_id: ControlBindingTargetField = Field(...)
    control_id: int = Field(..., gt=0)


class DeleteControlBindingByKeyResponse(BaseModel):
    """Response from a natural-key detach."""

    deleted: bool = Field(
        ...,
        description=(
            "True when a binding was deleted; False when no matching "
            "binding existed."
        ),
    )
