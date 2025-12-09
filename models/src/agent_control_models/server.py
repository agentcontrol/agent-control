from typing import Any

from pydantic import Field

from .agent import Agent, AgentTool
from .base import BaseModel
from .controls import ControlDefinition
from .policy import Control


class CreatePolicyRequest(BaseModel):
    name: str = Field(description="Unique policy name")


class CreateControlSetRequest(BaseModel):
    name: str = Field(description="Unique control set name")


class CreateControlRequest(BaseModel):
    name: str = Field(description="Unique control name")


class InitAgentRequest(BaseModel):
    """Request to initialize or update an agent registration."""
    agent: Agent = Field(
        ..., description="Agent metadata including ID, name, and version"
    )
    tools: list[AgentTool] = Field(
        default_factory=list, description="List of tools available to the agent"
    )
    policies: list[str] = Field(
        default_factory=list,
        description="List of policies required by the agent (auto-created if missing)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "agent": {
                        "agent_id": "550e8400-e29b-41d4-a716-446655440000",
                        "agent_name": "customer-service-bot",
                        "agent_description": "Handles customer inquiries",
                        "agent_version": "1.0.0"
                    },
                    "tools": [
                        {
                            "tool_name": "search_kb",
                            "arguments": {"query": {"type": "string"}},
                            "output_schema": {"results": {"type": "array"}}
                        }
                    ]
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
    """Response containing agent details and registered tools."""
    agent: Agent = Field(..., description="Agent metadata")
    tools: list[AgentTool] = Field(..., description="Tools registered with this agent")


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


class CreateControlSetResponse(BaseModel):
    control_set_id: int = Field(description="Identifier of the created control set")


class CreateControlResponse(BaseModel):
    control_id: int = Field(description="Identifier of the created control")


class GetPolicyControlSetsResponse(BaseModel):
    control_set_ids: list[int] = Field(
        description="List of control set ids associated with the policy"
    )


class GetControlSetControlsResponse(BaseModel):
    control_ids: list[int] = Field(
        description="List of control ids associated with the control set"
    )


class AssocResponse(BaseModel):
    success: bool = Field(description="Whether the association change succeeded")


class GetControlDataResponse(BaseModel):
    data: ControlDefinition | dict[str, Any] = Field(description="Control data payload")


class SetControlDataRequest(BaseModel):
    """Request to update control configuration data."""
    data: ControlDefinition = Field(
        ...,
        description="Control configuration data (replaces existing)",
    )


class SetControlDataResponse(BaseModel):
    success: bool = Field(description="Whether the control data was updated")
