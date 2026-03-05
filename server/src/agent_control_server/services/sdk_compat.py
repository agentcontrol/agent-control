from __future__ import annotations

from typing import Any


def is_typescript_agent_metadata(agent_metadata: dict[str, Any]) -> bool:
    """Return True when agent metadata identifies a TypeScript SDK agent."""
    sdk_language = agent_metadata.get("sdk_language")
    if not isinstance(sdk_language, str):
        nested_metadata = agent_metadata.get("agent_metadata")
        if isinstance(nested_metadata, dict):
            sdk_language = nested_metadata.get("sdk_language")
    return isinstance(sdk_language, str) and sdk_language.lower() == "typescript"


def is_local_execution_control(control_data: dict[str, Any]) -> bool:
    """Return True when a control is configured for SDK-local execution."""
    execution = control_data.get("execution", "server")
    return isinstance(execution, str) and execution == "sdk"
