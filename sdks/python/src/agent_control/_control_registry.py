"""Registry for @control()-decorated functions.

Tracks step schemas (name, type, input/output schema) from decorated functions
so they can be auto-populated into ``init(steps=...)`` without the user having
to specify them manually.

Registration happens at **decoration time** (import time), so all decorated
functions are captured before ``init()`` is called -- as long as ``init()``
is called after the module containing the decorated functions has been imported.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ._schema_derivation import derive_schemas

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal registry
# ---------------------------------------------------------------------------

_registered_steps: dict[str, dict[str, Any]] = {}
"""Maps step name -> step schema dict.  Keyed by name to deduplicate."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register(func: Callable[..., Any], policy: str | None = None) -> None:
    """Register a decorated function's step schema in the registry.

    Extracts name, type (tool vs llm), description, and input/output schemas
    from the function and stores them for later retrieval via
    ``get_registered_steps()``.

    Args:
        func: The original (unwrapped) function being decorated.
        policy: Optional policy name (stored as metadata).
    """
    # Determine step name -- tools typically have .name or .tool_name
    tool_name = getattr(func, "name", None) or getattr(func, "tool_name", None)
    step_name: str = tool_name if isinstance(tool_name, str) else func.__name__
    step_type: str = "tool" if isinstance(tool_name, str) else "llm"

    # Extract description from docstring (first line only)
    description: str | None = None
    if func.__doc__:
        first_line = func.__doc__.strip().split("\n")[0].strip()
        if first_line:
            description = first_line

    schemas = derive_schemas(func)

    step: dict[str, Any] = {
        "type": step_type,
        "name": step_name,
        "input_schema": schemas.input_schema,
        "output_schema": schemas.output_schema,
    }
    if description is not None:
        step["description"] = description

    metadata: dict[str, Any] = {}
    if policy is not None:
        metadata["policy"] = policy
    if metadata:
        step["metadata"] = metadata

    # Store (last-write-wins for duplicate names)
    if step_name in _registered_steps:
        logger.debug("Overwriting previously registered step '%s'", step_name)
    _registered_steps[step_name] = step
    logger.debug("Registered step schema: %s (type=%s)", step_name, step_type)


def get_registered_steps() -> list[dict[str, Any]]:
    """Return all registered step schemas as a list of dicts.

    The returned dicts conform to the ``StepSchema`` model format expected
    by ``init(steps=...)``.
    """
    return list(_registered_steps.values())


def clear() -> None:
    """Clear all registered steps.  Useful for testing."""
    _registered_steps.clear()
