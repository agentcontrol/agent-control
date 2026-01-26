"""Agent Control Engine - Rule execution logic and plugin system."""

from .discovery import (
    discover_plugins,
    ensure_plugins_discovered,
    list_plugins,
    reset_discovery,
)

__version__ = "0.1.0"

__all__ = [
    "discover_plugins",
    "ensure_plugins_discovered",
    "list_plugins",
    "reset_discovery",
]
