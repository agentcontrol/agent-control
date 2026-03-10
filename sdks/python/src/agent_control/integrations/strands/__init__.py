"""Strands integration for Agent Control."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plugin import AgentControlPlugin
    from .steering import AgentControlSteeringHandler

__all__ = ["AgentControlPlugin", "AgentControlSteeringHandler"]


def __getattr__(name: str) -> type:
    """Lazy import to avoid import errors when strands-agents is not installed."""
    if name == "AgentControlPlugin":
        from .plugin import AgentControlPlugin
        return AgentControlPlugin
    elif name == "AgentControlSteeringHandler":
        from .steering import AgentControlSteeringHandler
        return AgentControlSteeringHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
