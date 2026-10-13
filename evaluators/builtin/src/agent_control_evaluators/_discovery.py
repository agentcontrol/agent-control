"""Evaluator discovery via entry points."""

from __future__ import annotations

import logging
import threading
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from agent_control_evaluators._registry import (
    get_all_evaluators,
    get_evaluator,
    register_evaluator,
)

if TYPE_CHECKING:
    from agent_control_evaluators._base import Evaluator

logger = logging.getLogger(__name__)

_DISCOVERY_COMPLETE = False
_DISCOVERY_LOCK = threading.Lock()


def discover_evaluators() -> int:
    """Discover and register evaluators via entry points.

    All evaluators (built-in and third-party) are discovered via the
    'agent_control.evaluators' entry point group. Evaluators are only registered
    if their `is_available()` method returns True.

    Safe to call multiple times - only runs discovery once.
    Thread-safe via lock.

    Returns:
        Number of evaluators discovered
    """
    global _DISCOVERY_COMPLETE

    # Fast path without lock
    if _DISCOVERY_COMPLETE:
        return 0

    with _DISCOVERY_LOCK:
        # Double-check after acquiring lock
        if _DISCOVERY_COMPLETE:
            return 0

        discovered = 0

        # Discover ALL evaluators (built-in and third-party) via entry points.
        # Only register evaluators where is_available() returns True.
        try:
            eps = entry_points(group="agent_control.evaluators")
            for ep in eps:
                try:
                    evaluator_class = ep.load()
                    name = evaluator_class.metadata.name

                    # Skip if already registered
                    if get_evaluator(name) is not None:
                        continue

                    # Check if evaluator dependencies are satisfied
                    if not evaluator_class.is_available():
                        logger.debug(f"Evaluator '{name}' not available, skipping")
                        continue

                    register_evaluator(evaluator_class)
                    logger.debug(f"Registered evaluator: {name}")
                    discovered += 1
                except Exception as e:
                    logger.warning(f"Failed to load evaluator '{ep.name}': {e}")
        except Exception as e:
            logger.debug(f"Entry point discovery not available: {e}")

        _DISCOVERY_COMPLETE = True
        logger.debug(f"Evaluator discovery complete: {discovered} new evaluators")
        return discovered


def ensure_evaluators_discovered() -> None:
    """Ensure evaluator discovery has run. Call this before using evaluators."""
    if not _DISCOVERY_COMPLETE:
        discover_evaluators()


def reset_evaluator_discovery() -> None:
    """Reset discovery state. Useful for testing."""
    global _DISCOVERY_COMPLETE
    with _DISCOVERY_LOCK:
        _DISCOVERY_COMPLETE = False


# =============================================================================
# Public evaluator API
# =============================================================================


def list_evaluators() -> dict[str, type[Evaluator[Any]]]:
    """List all registered evaluators.

    This function ensures evaluator discovery has run before returning results.

    Returns:
        Dictionary mapping evaluator names to evaluator classes
    """
    ensure_evaluators_discovered()
    return get_all_evaluators()


def is_evaluator_disabled(name: str) -> bool:
    """Return True if an evaluator exists in entry points but is disabled by a feature flag.

    An evaluator is considered disabled (not merely unknown) when it is present
    in the ``agent_control.evaluators`` entry point group but its ``is_available()``
    method returns ``False``.  A genuinely unrecognised name returns ``False``.

    Args:
        name: The evaluator metadata name to check (e.g. ``"galileo.llm"``).

    Returns:
        ``True`` if the evaluator is known but currently unavailable, ``False``
        if it is either registered/available or completely unknown.
    """
    if name in get_all_evaluators():
        return False
    try:
        eps = entry_points(group="agent_control.evaluators")
        for ep in eps:
            try:
                evaluator_class = ep.load()
                if evaluator_class.metadata.name == name:
                    return not evaluator_class.is_available()
            except Exception:
                pass
    except Exception:
        pass
    return False
