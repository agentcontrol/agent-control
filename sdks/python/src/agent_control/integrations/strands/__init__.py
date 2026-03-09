"""Strands integration for Agent Control."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .hook import AgentControlHook
    from .steering import AgentControlSteeringHandler

__all__ = ["AgentControlHook", "AgentControlSteeringHandler"]


def __getattr__(name: str) -> type:
    """Lazy import to avoid import errors when strands-agents is not installed."""
    if name == "AgentControlHook":
        from .hook import AgentControlHook
        return AgentControlHook
    elif name == "AgentControlSteeringHandler":
        from .steering import AgentControlSteeringHandler
        return AgentControlSteeringHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
