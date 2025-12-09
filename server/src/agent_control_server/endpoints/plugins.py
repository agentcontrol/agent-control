"""Plugin discovery endpoints."""

from typing import Any

# Import plugins to ensure they are registered
import agent_control_plugins  # noqa: F401
from agent_control_models import list_plugins
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..services.evaluators import list_custom_evaluators

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginInfo(BaseModel):
    """Information about a registered plugin."""

    name: str = Field(..., description="Plugin name")
    version: str = Field(..., description="Plugin version")
    description: str = Field(..., description="Plugin description")
    requires_api_key: bool = Field(..., description="Whether plugin requires API key")
    timeout_ms: int = Field(..., description="Default timeout in milliseconds")
    config_schema: dict[str, Any] = Field(..., description="JSON Schema for config")
    is_custom: bool = Field(default=False, description="Whether this is a custom evaluator")


@router.get(
    "",
    response_model=dict[str, PluginInfo],
    summary="List available plugins",
    response_description="Dictionary of plugin name to plugin info",
)
async def get_plugins(
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, PluginInfo]:
    """List all available evaluator plugins.

    Returns metadata and JSON Schema for each available plugin,
    including both built-in plugins and custom evaluators.

    Built-in plugins:
    - **regex**: Regular expression pattern matching
    - **list**: List-based value matching with flexible logic

    Custom evaluators are registered via PUT /evaluators.
    """
    plugins = list_plugins()

    result: dict[str, PluginInfo] = {
        name: PluginInfo(
            name=plugin_cls.metadata.name,
            version=plugin_cls.metadata.version,
            description=plugin_cls.metadata.description,
            requires_api_key=plugin_cls.metadata.requires_api_key,
            timeout_ms=plugin_cls.metadata.timeout_ms,
            config_schema=plugin_cls.config_model.model_json_schema(),
            is_custom=False,
        )
        for name, plugin_cls in plugins.items()
    }

    # Add custom evaluators from database
    custom_evaluators = await list_custom_evaluators(db)
    for ce in custom_evaluators:
        result[ce.name] = PluginInfo(
            name=ce.name,
            version="1.0.0",
            description=ce.description or f"Custom evaluator: {ce.name}",
            requires_api_key=False,
            timeout_ms=ce.timeout_ms,
            config_schema=ce.config_schema,
            is_custom=True,
        )

    return result
