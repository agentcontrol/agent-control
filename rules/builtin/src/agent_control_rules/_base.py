"""Rule base classes and metadata."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from agent_control_models import RuleResult
from agent_control_models.base import BaseModel

if TYPE_CHECKING:
    from typing import Self

logger = logging.getLogger(__name__)


class RuleConfig(BaseModel):
    """Base class for typed rule configurations.

    Extends the project's BaseModel to ensure consistent behavior
    and enable type checking across all rule configs.

    Example:
        ```python
        from agent_control_rules import RuleConfig

        class MyRuleConfig(RuleConfig):
            pattern: str
            threshold: float = 0.5
        ```
    """

    pass


ConfigT = TypeVar("ConfigT", bound=RuleConfig)


@dataclass
class RuleMetadata:
    """Metadata about a rule.

    Attributes:
        name: Unique rule name (e.g., "regex", "galileo.luna")
        version: Rule version string
        description: Human-readable description
        requires_api_key: Whether the rule requires an API key
        timeout_ms: Default timeout in milliseconds
    """

    name: str
    version: str
    description: str
    requires_api_key: bool = False
    timeout_ms: int = 10000


class Rule(ABC, Generic[ConfigT]):  # noqa: UP046 - need Python 3.10 compat
    """Base class for all rules (built-in, external, or custom).

    All rules follow the same pattern:
        1. Define metadata and config_model as class variables
        2. Implement evaluate() method
        3. Register with @register_rule decorator

    IMPORTANT - Instance Caching & Thread Safety:
        Rule instances are cached and reused across multiple evaluate() calls
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
                return RuleResult(matched=result is not None, ...)

        Bad pattern:
            def __init__(self, config):
                super().__init__(config)
                self.call_count = 0  # BAD: mutable state shared across requests

            async def evaluate(self, data):
                self.call_count += 1  # BAD: race condition, leaks between requests

    Example:
        ```python
        from agent_control_rules import (
            Rule,
            RuleConfig,
            RuleMetadata,
            register_rule,
        )
        from agent_control_models import RuleResult

        class MyConfig(RuleConfig):
            threshold: float = 0.5

        @register_rule
        class MyRule(Rule[MyConfig]):
            metadata = RuleMetadata(
                name="my-rule",
                version="1.0.0",
                description="My custom rule",
            )
            config_model = MyConfig

            async def evaluate(self, data: Any) -> RuleResult:
                return RuleResult(
                    matched=len(str(data)) > self.config.threshold,
                    confidence=1.0,
                    message="Evaluation complete"
                )
        ```

    """

    metadata: ClassVar[RuleMetadata]
    config_model: ClassVar[type[RuleConfig]]

    def __init__(self, config: ConfigT) -> None:
        """Initialize rule with validated config.

        Args:
            config: Validated configuration (instance of config_model)
        """
        self.config: ConfigT = config

    @classmethod
    def from_dict(cls, config_dict: dict[str, Any]) -> Self:
        """Create rule instance from raw config dict.

        Validates config against config_model before creating instance.

        Args:
            config_dict: Raw configuration dictionary

        Returns:
            Rule instance with validated config
        """
        validated = cls.config_model(**config_dict)
        return cls(validated)  # type: ignore[arg-type]

    @abstractmethod
    async def evaluate(self, data: Any) -> RuleResult:
        """Evaluate data and return result.

        Args:
            data: Data extracted by selector from the payload

        Returns:
            RuleResult with matched status, confidence, and message
        """
        pass

    def get_timeout_seconds(self) -> float:
        """Get timeout in seconds from config or metadata default."""
        timeout_ms: int = getattr(self.config, "timeout_ms", self.metadata.timeout_ms)
        return float(timeout_ms) / 1000.0

    @classmethod
    def is_available(cls) -> bool:
        """Check if rule dependencies are satisfied.

        Override this method for rules with optional dependencies.
        Return False to skip registration during discovery.

        Returns:
            True if rule can be used, False otherwise
        """
        return True
