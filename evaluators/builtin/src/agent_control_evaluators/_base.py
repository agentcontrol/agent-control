"""Evaluator base classes and metadata."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from agent_control_models import EvaluatorResult
from agent_control_models.base import BaseModel

if TYPE_CHECKING:
    from typing import Self

logger = logging.getLogger(__name__)


class EvaluatorConfig(BaseModel):
    """Base class for typed evaluator configurations.

    Extends the project's BaseModel to ensure consistent behavior
    and enable type checking across all evaluator configs.

    Example:
        ```python
        from agent_control_evaluators import EvaluatorConfig

        class MyEvaluatorConfig(EvaluatorConfig):
            pattern: str
            threshold: float = 0.5
        ```
    """

    pass


ConfigT = TypeVar("ConfigT", bound=EvaluatorConfig)


@dataclass
class EvaluatorMetadata:
    """Metadata about an evaluator.

    Attributes:
        name: Unique evaluator name (e.g., "regex", "galileo.luna2")
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


class Evaluator(ABC, Generic[ConfigT]):  # noqa: UP046 - need Python 3.10 compat
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
        from agent_control_evaluators import (
            Evaluator,
            EvaluatorConfig,
            EvaluatorMetadata,
            register_evaluator,
        )
        from agent_control_models import EvaluatorResult

        class MyConfig(EvaluatorConfig):
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
    config_model: ClassVar[type[EvaluatorConfig]]

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
