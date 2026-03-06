from __future__ import annotations

from typing import Any


def is_typescript_agent_metadata(agent_metadata: dict[str, Any]) -> bool:
    """Return True when agent metadata identifies a TypeScript SDK agent.

    Contract: we store TypeScript SDK agents with a flat metadata shape where
    `sdk_language` lives at the top level of `agent_metadata`. We do not
    support nested `agent_metadata.agent_metadata` shapes; new code should
    always write the flat form.
    """
    sdk_language = agent_metadata.get("sdk_language")
    return isinstance(sdk_language, str) and sdk_language.lower() == "typescript"


def is_local_execution_control(control_data: dict[str, Any]) -> bool:
    """Return True when a control is configured for SDK-local execution."""
    execution = control_data.get("execution", "server")
    return isinstance(execution, str) and execution == "sdk"
