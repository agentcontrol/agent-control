"""Google ADK integration for Agent Control."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import AgentControlPlugin

__all__ = ["AgentControlPlugin"]


def __getattr__(name: str) -> type:
    """Lazy import to avoid import errors when google-adk is not installed."""
    if name == "AgentControlPlugin":
        from .plugin import AgentControlPlugin

        return AgentControlPlugin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
