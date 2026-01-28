"""Evaluator system base classes and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel

from .controls import EvaluatorResult

if TYPE_CHECKING:
    from typing import Self

logger = logging.getLogger(__name__)

ConfigT = TypeVar("ConfigT", bound=BaseModel)


@dataclass
class EvaluatorMetadata:
    """Metadata about an evaluator.

    Attributes:
        name: Unique evaluator name (e.g., "regex", "galileo-luna2")
        version: Evaluator version string
        description: Human-readable description
        requires_api_key: Whether the evaluator requires an API key
        timeout_ms: Default timeout in milliseconds
    """

    name: str
    version: str
    description: str
    requires_api_key: bool = False
    timeout_ms: int = 10000


class Evaluator(ABC, Generic[ConfigT]):  # noqa: UP046
    """Base class for all evaluators (built-in, external, or custom).

    All evaluators follow the same pattern:
        1. Define metadata and config_model as class variables
        2. Implement evaluate() method
        3. Register with @register_evaluator decorator

    IMPORTANT - Instance Caching & Thread Safety:
        Evaluator instances are cached and reused across multiple evaluate() calls
        when they have the same configuration. This means:

        - DO NOT store mutable request-scoped state on `self`
        - The evaluate() method may be called concurrently from multiple requests
        - Any state stored in __init__ should be immutable or thread-safe
        - Use local variables within evaluate() for request-specific state

        Good pattern:
            def __init__(self, config):
                super().__init__(config)
                self._compiled_regex = re.compile(config.pattern)  # OK: immutable

            async def evaluate(self, data):
                result = self._compiled_regex.search(data)  # OK: uses immutable state
                return EvaluatorResult(matched=result is not None, ...)

        Bad pattern:
            def __init__(self, config):
                super().__init__(config)
                self.call_count = 0  # BAD: mutable state shared across requests

            async def evaluate(self, data):
                self.call_count += 1  # BAD: race condition, leaks between requests

    Example:
        ```python
        from agent_control_models import Evaluator, EvaluatorMetadata, register_evaluator

        class MyConfig(BaseModel):
            threshold: float = 0.5

        @register_evaluator
        class MyEvaluator(Evaluator[MyConfig]):
            metadata = EvaluatorMetadata(
                name="my-evaluator",
                version="1.0.0",
                description="My custom evaluator",
            )
            config_model = MyConfig

            async def evaluate(self, data: Any) -> EvaluatorResult:
                return EvaluatorResult(
                    matched=len(str(data)) > self.config.threshold,
                    confidence=1.0,
                    message="Evaluation complete"
                )
        ```
    """

    metadata: ClassVar[EvaluatorMetadata]
    config_model: ClassVar[type[BaseModel]]

    def __init__(self, config: ConfigT) -> None:
        """Initialize evaluator with validated config.

        Args:
            config: Validated configuration (instance of config_model)
        """
        self.config: ConfigT = config

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Self:
        """Create evaluator instance from raw config dict.

        Validates config against config_model before creating instance.

        Args:
            config_dict: Raw configuration dictionary

        Returns:
            Evaluator instance with validated config
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

    @classmethod
    def is_available(cls) -> bool:
        """Check if evaluator dependencies are satisfied.

        Override this method for evaluators with optional dependencies.
        Return False to skip registration during discovery.

        Returns:
            True if evaluator can be used, False otherwise
        """
        return True


# =============================================================================
# Evaluator Registry
# =============================================================================

_EVALUATOR_REGISTRY: dict[str, type[Evaluator[Any]]] = {}


def register_evaluator(
    evaluator_class: type[Evaluator[Any]],
) -> type[Evaluator[Any]]:
    """Register an evaluator class by its metadata name.

    Can be used as a decorator or called directly. Respects the evaluator's
    is_available() method - evaluators with unavailable dependencies are
    silently skipped.

    Args:
        evaluator_class: Evaluator class to register

    Returns:
        The same evaluator class (for decorator usage)

    Raises:
        ValueError: If evaluator name already registered
    """
    name = evaluator_class.metadata.name

    # Check if evaluator dependencies are satisfied
    if not evaluator_class.is_available():
        logger.debug(f"Evaluator '{name}' not available (is_available=False), skipping")
        return evaluator_class

    if name in _EVALUATOR_REGISTRY:
        # Allow re-registration of same class (e.g., during hot reload)
        if _EVALUATOR_REGISTRY[name] is evaluator_class:
            return evaluator_class
        raise ValueError(f"Evaluator '{name}' is already registered")

    _EVALUATOR_REGISTRY[name] = evaluator_class
    logger.debug(f"Registered evaluator: {name} v{evaluator_class.metadata.version}")
    return evaluator_class


def get_evaluator(name: str) -> type[Evaluator[Any]] | None:
    """Get a registered evaluator by name.

    Args:
        name: Evaluator name to look up

    Returns:
        Evaluator class if found, None otherwise
    """
    return _EVALUATOR_REGISTRY.get(name)


def get_all_evaluators() -> dict[str, type[Evaluator[Any]]]:
    """Get all registered evaluators.

    Returns:
        Dictionary mapping evaluator names to evaluator classes
    """
    return dict(_EVALUATOR_REGISTRY)


def clear_evaluators() -> None:
    """Clear all registered evaluators. Useful for testing."""
    _EVALUATOR_REGISTRY.clear()
