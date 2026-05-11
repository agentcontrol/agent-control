"""
Global state management for Agent Control SDK.

This module holds global state in a container object to avoid circular imports
between __init__.py and other modules. Both modules can import and modify
the same state object.
"""

from typing import TYPE_CHECKING, Any

from .runtime_auth import RuntimeTokenCache

if TYPE_CHECKING:
    from agent_control_models import Agent

    from .client import AgentControlClient


class _StateContainer:
    """Container for global SDK state."""

    def __init__(self) -> None:
        self.current_agent: Agent | None = None
        self.control_engine: Any = None
        self.client: AgentControlClient | None = None
        self.server_controls: list[dict[str, Any]] | None = None
        self.server_url: str | None = None
        self.api_key: str | None = None
        self.api_key_header: str | None = None
        self.runtime_token_cache = RuntimeTokenCache()
        # Optional target context fixed at init() time; both fields are set
        # together or both remain None.
        self.target_type: str | None = None
        self.target_id: str | None = None


# Singleton state instance
state = _StateContainer()
