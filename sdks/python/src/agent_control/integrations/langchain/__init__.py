"""LangChain integration for Agent Control."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .middleware import AgentControlMiddleware

__all__ = ["AgentControlMiddleware"]


def __getattr__(name: str) -> Any:
    """Lazy import to avoid import errors when langchain is not installed."""
    if name == "AgentControlMiddleware":
        from .middleware import AgentControlMiddleware

        return AgentControlMiddleware
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
