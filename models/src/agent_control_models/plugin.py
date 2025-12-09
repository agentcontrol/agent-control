"""Plugin system base classes and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

from .controls import EvaluatorResult

if TYPE_CHECKING:
    from typing import Self

logger = logging.getLogger(__name__)

ConfigT = TypeVar("ConfigT", bound=BaseModel)


@dataclass
class PluginMetadata:
    """Metadata about a plugin.

    Attributes:
        name: Unique plugin name (e.g., "regex", "galileo-luna2")
        version: Plugin version string
        description: Human-readable description
        requires_api_key: Whether the plugin requires an API key
        timeout_ms: Default timeout in milliseconds
        config_schema: JSON Schema for plugin configuration (auto-generated from config_model)
    """

    name: str
    version: str
    description: str
    requires_api_key: bool = False
    timeout_ms: int = 10000
    config_schema: dict[str, Any] | None = field(default=None, repr=False)


class PluginEvaluator(ABC, Generic[ConfigT]):  # noqa: UP046
    """Base class for all evaluators (built-in, external, or custom).

    All evaluators follow the same pattern:
        1. Define metadata and config_model as class variables
        2. Implement evaluate() method
        3. Register with @register_plugin decorator

    Example:
        ```python
        from agent_control_models import PluginEvaluator, PluginMetadata, register_plugin

        class MyConfig(BaseModel):
            threshold: float = 0.5

        @register_plugin
        class MyPlugin(PluginEvaluator[MyConfig]):
            metadata = PluginMetadata(
                name="my-plugin",
                version="1.0.0",
                description="My custom evaluator",
            )
            config_model = MyConfig

            def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(
                    matched=len(str(data)) > self.config.threshold,
                    confidence=1.0,
                    message="Evaluation complete"
                )
        ```
    """

    metadata: ClassVar[PluginMetadata]
    config_model: ClassVar[type[BaseModel]]

    def __init__(self, config: ConfigT) -> None:
        """Initialize plugin with validated config.

        Args:
            config: Validated configuration (instance of config_model)
        """
        self.config: ConfigT = config

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Self:
        """Create plugin instance from raw config dict.

        Validates config against config_model before creating instance.

        Args:
            config_dict: Raw configuration dictionary

        Returns:
            Plugin instance with validated config
        """
        validated = cls.config_model(**config_dict)
        return cls(validated)  # type: ignore[arg-type]

    @abstractmethod
    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate data and return result.

        Args:
            data: Data extracted by selector from the payload

        Returns:
            EvaluatorResult with matched status, confidence, and message
        """
        pass

    def get_timeout_seconds(self) -> float:
        """Get timeout in seconds from config or metadata default."""
        timeout_ms: int = getattr(self.config, "timeout_ms", self.metadata.timeout_ms)
        return float(timeout_ms) / 1000.0


# =============================================================================
# Plugin Registry
# =============================================================================

_PLUGIN_REGISTRY: dict[str, type[PluginEvaluator[Any]]] = {}


def register_plugin(
    plugin_class: type[PluginEvaluator[Any]],
) -> type[PluginEvaluator[Any]]:
    """Register a plugin class by its metadata name.

    Can be used as a decorator or called directly.

    Args:
        plugin_class: Plugin class to register

    Returns:
        The same plugin class (for decorator usage)

    Raises:
        ValueError: If plugin name already registered
    """
    name = plugin_class.metadata.name
    if name in _PLUGIN_REGISTRY:
        # Allow re-registration of same class (e.g., during hot reload)
        if _PLUGIN_REGISTRY[name] is plugin_class:
            return plugin_class
        raise ValueError(f"Plugin '{name}' is already registered")

    _PLUGIN_REGISTRY[name] = plugin_class
    logger.debug(f"Registered plugin: {name} v{plugin_class.metadata.version}")
    return plugin_class


def get_plugin(name: str) -> type[PluginEvaluator[Any]] | None:
    """Get a plugin class by name.

    Args:
        name: Plugin name (e.g., "regex", "galileo-luna2")

    Returns:
        Plugin class or None if not found
    """
    return _PLUGIN_REGISTRY.get(name)


def list_plugins() -> dict[str, type[PluginEvaluator[Any]]]:
    """List all registered plugins.

    Returns:
        Dictionary mapping plugin names to plugin classes
    """
    return dict(_PLUGIN_REGISTRY)


def clear_plugins() -> None:
    """Clear all registered plugins. Useful for testing."""
    _PLUGIN_REGISTRY.clear()
