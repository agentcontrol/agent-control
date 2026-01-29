"""Evaluator registry for registration and lookup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_control_evaluators._base import Evaluator

logger = logging.getLogger(__name__)

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
        ValueError: If evaluator name already registered with different class

    Example:
        ```python
        @register_evaluator
        class MyEvaluator(Evaluator[MyConfig]):
            metadata = EvaluatorMetadata(name="my-evaluator", ...)
            ...
        ```
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
