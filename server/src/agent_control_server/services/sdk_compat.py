from __future__ import annotations

from typing import Any


def is_typescript_agent_metadata(agent_metadata: dict[str, Any]) -> bool:
    """Return True when agent metadata identifies a TypeScript SDK agent.

    ``AgentData.agent_metadata`` stores the full ``APIAgent.model_dump()`` payload
    (see ``initAgent`` endpoint), so the user-supplied metadata dict is nested under
    the ``"agent_metadata"`` key — i.e. ``agent_metadata["agent_metadata"]["sdk_language"]``.
    """
    nested = agent_metadata.get("agent_metadata")
    if not isinstance(nested, dict):
        return False
    return str(nested.get("sdk_language", "")).lower() == "typescript"


def is_local_execution_control(control_data: dict[str, Any]) -> bool:
    """Return True when a control is configured for SDK-local execution."""
    execution = control_data.get("execution", "server")
    return isinstance(execution, str) and execution == "sdk"
