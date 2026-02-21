"""Schema derivation helpers for agent step registration.

This module centralizes JSON schema derivation so registry code can focus on
bookkeeping (naming, metadata, and deduplication) rather than inference logic.

Derivation is best-effort:
- Prefer framework-provided ``args_schema`` for input if available.
- Otherwise infer schemas from function type hints using Pydantic.
- On inference failures, log a warning and return permissive fallback schemas.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_type_hints

from pydantic import TypeAdapter, create_model

logger = logging.getLogger(__name__)

_INPUT_FALLBACK_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": True}
_OUTPUT_FALLBACK_SCHEMA: dict[str, Any] = {}


@dataclass(frozen=True)
class DerivedSchemas:
    """Container for derived input/output JSON schemas."""

    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


def derive_schemas(func: Callable[..., Any]) -> DerivedSchemas:
    """Derive input/output JSON schemas for a function.

    Args:
        func: Function for schema derivation.

    Returns:
        DerivedSchemas containing input and output JSON schemas.
    """
    input_schema_override = _extract_args_schema_override(func)
    unwrapped = inspect.unwrap(func)

    try:
        hints = get_type_hints(unwrapped, include_extras=True)
    except Exception as exc:
        if input_schema_override is not None:
            _warn(
                func,
                phase="output",
                reason="failed to resolve type hints",
                exc=exc,
                fallback=_OUTPUT_FALLBACK_SCHEMA,
            )
            return DerivedSchemas(
                input_schema=input_schema_override,
                output_schema=_fallback_output_schema(),
            )

        _warn(
            func,
            phase="input/output",
            reason="failed to resolve type hints",
            exc=exc,
            fallback={
                "input": _INPUT_FALLBACK_SCHEMA,
                "output": _OUTPUT_FALLBACK_SCHEMA,
            },
        )
        return DerivedSchemas(
            input_schema=_fallback_input_schema(),
            output_schema=_fallback_output_schema(),
        )

    input_schema = input_schema_override
    if input_schema is None:
        input_schema = _infer_input_schema(func, unwrapped, hints)

    output_schema = _infer_output_schema(func, hints)
    return DerivedSchemas(input_schema=input_schema, output_schema=output_schema)


def _extract_args_schema_override(func: Callable[..., Any]) -> dict[str, Any] | None:
    """Extract framework-provided input schema from ``func.args_schema``."""
    args_schema = getattr(func, "args_schema", None)
    if args_schema is None:
        return None
    if not hasattr(args_schema, "model_json_schema"):
        return None

    try:
        schema = args_schema.model_json_schema()
    except Exception as exc:  # pragma: no cover - exercised via tests with caplog
        _warn(
            func,
            phase="input",
            reason="args_schema.model_json_schema() failed; using signature inference",
            exc=exc,
            fallback=_INPUT_FALLBACK_SCHEMA,
        )
        return None

    if not isinstance(schema, dict):
        _warn(
            func,
            phase="input",
            reason="args_schema.model_json_schema() returned non-dict; using signature inference",
            fallback=_INPUT_FALLBACK_SCHEMA,
        )
        return None

    return schema


def _infer_input_schema(
    func: Callable[..., Any],
    unwrapped: Callable[..., Any],
    hints: dict[str, Any],
) -> dict[str, Any]:
    """Infer input schema from signature + type hints using dynamic Pydantic model."""

    try:
        signature = inspect.signature(unwrapped)
    except Exception as exc:
        _warn(
            func,
            phase="input",
            reason="failed to inspect function signature",
            exc=exc,
            fallback=_INPUT_FALLBACK_SCHEMA,
        )
        return _fallback_input_schema()

    fields: dict[str, tuple[Any, Any]] = {}
    for name, param in signature.parameters.items():
        if name in {"self", "cls"}:
            continue
        if param.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}:
            continue

        annotation = hints.get(name, Any)
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (annotation, default)

    model_name = _build_model_name(unwrapped, suffix="Input")
    try:
        model = create_model(model_name, **fields)  # type: ignore[call-overload]
        schema = model.model_json_schema()
    except Exception as exc:
        _warn(
            func,
            phase="input",
            reason="failed to infer schema from signature",
            exc=exc,
            fallback=_INPUT_FALLBACK_SCHEMA,
        )
        return _fallback_input_schema()

    if not isinstance(schema, dict):
        _warn(
            func,
            phase="input",
            reason="inferred input schema is not a dict",
            fallback=_INPUT_FALLBACK_SCHEMA,
        )
        return _fallback_input_schema()

    return schema


def _infer_output_schema(func: Callable[..., Any], hints: dict[str, Any]) -> dict[str, Any]:
    """Infer output schema from return type annotation using ``TypeAdapter``."""
    if "return" not in hints:
        _warn(
            func,
            phase="output",
            reason="missing return type annotation",
            fallback=_OUTPUT_FALLBACK_SCHEMA,
        )
        return _fallback_output_schema()

    return_annotation = hints["return"]
    try:
        schema = TypeAdapter(return_annotation).json_schema()
    except Exception as exc:
        _warn(
            func,
            phase="output",
            reason="failed to infer output schema from return annotation",
            exc=exc,
            fallback=_OUTPUT_FALLBACK_SCHEMA,
        )
        return _fallback_output_schema()

    if not isinstance(schema, dict):
        _warn(
            func,
            phase="output",
            reason="inferred output schema is not a dict",
            fallback=_OUTPUT_FALLBACK_SCHEMA,
        )
        return _fallback_output_schema()

    return schema


def _build_model_name(func: Callable[..., Any], suffix: str) -> str:
    """Build a safe dynamic model name from function metadata."""
    raw = f"{func.__module__}_{func.__qualname__}_{suffix}"
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw)
    return safe or f"Derived_{suffix}"


def _fallback_input_schema() -> dict[str, Any]:
    """Return a permissive fallback input schema."""
    return dict(_INPUT_FALLBACK_SCHEMA)


def _fallback_output_schema() -> dict[str, Any]:
    """Return a permissive fallback output schema."""
    return dict(_OUTPUT_FALLBACK_SCHEMA)


def _warn(
    func: Callable[..., Any],
    *,
    phase: str,
    reason: str,
    fallback: dict[str, Any],
    exc: Exception | None = None,
) -> None:
    """Emit a structured warning for schema fallback paths."""
    function_name = f"{func.__module__}.{func.__qualname__}"
    if exc is None:
        logger.warning(
            "Using fallback %s schema for %s: %s. fallback=%s",
            phase,
            function_name,
            reason,
            fallback,
        )
        return

    logger.warning(
        "Using fallback %s schema for %s: %s (%s: %s). fallback=%s",
        phase,
        function_name,
        reason,
        exc.__class__.__name__,
        exc,
        fallback,
    )
