"""Rule discovery endpoints."""

from typing import Any

from agent_control_engine import list_rules
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth_framework import Operation, require_operation

router = APIRouter(prefix="/rules", tags=["rules"])


class RuleInfo(BaseModel):
    """Information about a registered rule."""

    name: str = Field(..., description="Rule name")
    version: str = Field(..., description="Rule version")
    description: str = Field(..., description="Rule description")
    requires_api_key: bool = Field(..., description="Whether rule requires API key")
    timeout_ms: int = Field(..., description="Default timeout in milliseconds")
    config_schema: dict[str, Any] = Field(..., description="JSON Schema for config")


@router.get(
    "",
    response_model=dict[str, RuleInfo],
    summary="List available rules",
    response_description="Dictionary of rule name to rule info",
    dependencies=[Depends(require_operation(Operation.RULES_READ))],
)
async def get_rules() -> dict[str, RuleInfo]:
    """List all available rules.

    Returns metadata and JSON Schema for each built-in rule.

    Built-in rules:
    - **regex**: Regular expression pattern matching
    - **list**: List-based value matching with flexible logic
    - **json**: JSON validation with schema, types, constraints
    - **sql**: SQL query validation

    Custom rules are registered per-agent via initAgent.
    Use GET /agents/{agent_name}/rules to list agent-specific schemas.
    """
    rules = list_rules()

    return {
        name: RuleInfo(
            name=rule_cls.metadata.name,
            version=rule_cls.metadata.version,
            description=rule_cls.metadata.description,
            requires_api_key=rule_cls.metadata.requires_api_key,
            timeout_ms=rule_cls.metadata.timeout_ms,
            config_schema=rule_cls.config_model.model_json_schema(),
        )
        for name, rule_cls in rules.items()
    }
