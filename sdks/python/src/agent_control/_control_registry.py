"""Registry for @control()-decorated functions.

Tracks step schemas (name, type, input/output schema) from decorated functions
so they can be auto-populated into ``init(steps=...)`` without the user having
to specify them manually.

Registration happens at **decoration time** (import time), so all decorated
functions are captured before ``init()`` is called -- as long as ``init()``
is called after the module containing the decorated functions has been imported.
"""

from __future__ import annotations

import inspect
import logging
import typing
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal registry
# ---------------------------------------------------------------------------

_registered_steps: dict[str, dict[str, Any]] = {}
"""Maps step name -> step schema dict.  Keyed by name to deduplicate."""


# ---------------------------------------------------------------------------
# Schema extraction helpers
# ---------------------------------------------------------------------------

# Mapping from Python primitive types to JSON Schema type strings.
_PRIMITIVE_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _type_to_json_schema(annotation: Any) -> dict[str, Any] | None:
    """Convert a Python type annotation to a JSON Schema dict.

    Supports:
    - Pydantic models (via ``model_json_schema()``)
    - Primitive types (str, int, float, bool)
    - Framework-specific ``args_schema`` on the function (checked separately)

    Returns ``None`` for complex or unrecognised types so callers can
    gracefully degrade.
    """
    if annotation is None or annotation is inspect.Parameter.empty:
        return None

    # Pydantic v2 models expose model_json_schema()
    if hasattr(annotation, "model_json_schema"):
        try:
            result: dict[str, Any] = annotation.model_json_schema()
            return result
        except Exception:
            logger.debug("Failed to extract JSON schema from Pydantic model %s", annotation)
            return None

    # Primitive types
    type_str = _PRIMITIVE_TYPE_MAP.get(annotation)  # type: ignore[arg-type]
    if type_str is not None:
        return {"type": type_str}

    return None


def _extract_input_schema(func: Callable[..., Any]) -> dict[str, Any] | None:
    """Build a JSON Schema ``object`` from the function's parameter type hints.

    Skips ``self`` and ``cls`` parameters.  Returns ``None`` when no useful
    schema can be derived (e.g. no type hints at all).
    """
    # Framework tools (e.g. LangChain) may expose a Pydantic args_schema
    args_schema = getattr(func, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_json_schema"):
        try:
            result: dict[str, Any] = args_schema.model_json_schema()
            return result
        except Exception:
            logger.debug("Failed to extract args_schema from %s", func)

    try:
        hints = typing.get_type_hints(func)
    except Exception:
        # get_type_hints can fail on some decorated / wrapped functions
        return None

    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    for name, _param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        hint = hints.get(name)
        if hint is None:
            continue
        schema = _type_to_json_schema(hint)
        if schema is not None:
            properties[name] = schema

    if not properties:
        return None
    return {"type": "object", "properties": properties}


def _extract_output_schema(func: Callable[..., Any]) -> dict[str, Any] | None:
    """Derive output schema from the function's return type annotation."""
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        return None

    return_hint = hints.get("return")
    if return_hint is None:
        return None
    return _type_to_json_schema(return_hint)


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

    input_schema = _extract_input_schema(func)
    output_schema = _extract_output_schema(func)

    step: dict[str, Any] = {
        "type": step_type,
        "name": step_name,
    }
    if description is not None:
        step["description"] = description
    if input_schema is not None:
        step["input_schema"] = input_schema
    if output_schema is not None:
        step["output_schema"] = output_schema

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
