"""LangGraph integration for Agent Control."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tool_node import create_controlled_tool_node

__all__ = ["create_controlled_tool_node"]


def __getattr__(name: str) -> Any:
    """Lazy import to avoid import errors when langgraph is not installed."""
    if name == "create_controlled_tool_node":
        from .tool_node import create_controlled_tool_node

        return create_controlled_tool_node
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
