"""Agent Control Server - Server component for agent protection system."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-server")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"
