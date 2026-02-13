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
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from ._schema_derivation import derive_schemas

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step schema types
# ---------------------------------------------------------------------------

type StepKey = tuple[str, str]


class StepSchemaDict(TypedDict):
    """Runtime representation of a step schema payload."""

    type: str
    name: str
    description: NotRequired[str]
    input_schema: NotRequired[dict[str, Any] | None]
    output_schema: NotRequired[dict[str, Any] | None]
    metadata: NotRequired[dict[str, Any]]


@dataclass(frozen=True)
class StepMergeResult:
    """Result of merging explicit and auto-discovered step schemas."""

    steps: list[StepSchemaDict]
    overridden_keys: list[StepKey]


# ---------------------------------------------------------------------------
# Internal registry
# ---------------------------------------------------------------------------

_registered_steps: dict[StepKey, StepSchemaDict] = {}
"""Maps ``(type, name)`` -> step schema dict. Keyed by type+name to deduplicate."""


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

    step: StepSchemaDict = {
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

    key = _step_key(step_type, step_name)

    # Store (last-write-wins for duplicate type+name pairs).
    if key in _registered_steps:
        logger.debug(
            "Overwriting previously registered step '%s' (type=%s)",
            step_name,
            step_type,
        )
    _registered_steps[key] = step
    logger.debug("Registered step schema: %s (type=%s)", step_name, step_type)


def get_registered_steps() -> list[StepSchemaDict]:
    """Return all registered step schemas as a list of dicts.

    The returned dicts conform to the ``StepSchema`` model format expected
    by ``init(steps=...)``.
    """
    return list(_registered_steps.values())


def merge_explicit_and_auto_steps(
    explicit_steps: list[StepSchemaDict] | None,
    auto_steps: list[StepSchemaDict],
) -> StepMergeResult:
    """Merge explicit and auto-discovered steps.

    Explicit steps win on exact ``(type, name)`` collisions.

    Args:
        explicit_steps: Steps provided explicitly to ``init(steps=...)``.
        auto_steps: Steps auto-discovered from ``@control()`` registration.

    Returns:
        Merge result containing final merged steps and the overridden auto keys.
    """
    explicit = list(explicit_steps or [])
    if not auto_steps:
        return StepMergeResult(steps=explicit, overridden_keys=[])

    explicit_keys = {_step_key(step["type"], step["name"]) for step in explicit}
    merged_auto_steps: list[StepSchemaDict] = []
    overridden_keys: list[StepKey] = []

    for auto_step in auto_steps:
        key = _step_key(auto_step["type"], auto_step["name"])
        if key in explicit_keys:
            overridden_keys.append(key)
            continue
        merged_auto_steps.append(auto_step)

    return StepMergeResult(
        steps=explicit + merged_auto_steps,
        overridden_keys=overridden_keys,
    )


def clear() -> None:
    """Clear all registered steps.  Useful for testing."""
    _registered_steps.clear()


def _step_key(step_type: str, step_name: str) -> StepKey:
    """Create a canonical deduplication key for step schemas."""
    return (step_type, step_name)
