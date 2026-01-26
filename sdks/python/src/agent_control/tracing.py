"""
OpenTelemetry-compatible tracing for Agent Control.

This module provides trace and span ID management that is compatible with
OpenTelemetry. When OpenTelemetry is installed and in use, it will extract
IDs from the current context. Otherwise, it generates OTEL-compatible IDs.

Usage:
    from agent_control.tracing import get_trace_and_span_ids, with_trace

    # Get current trace and span IDs (auto-detects OTEL or generates)
    trace_id, span_id = get_trace_and_span_ids()

    # Use context manager for scoped tracing
    with with_trace() as (trace_id, span_id):
        # All operations within this block share the same trace/span
        result = await my_function()

    # Explicitly set trace ID for a block
    with with_trace(trace_id="abc123...") as (trace_id, span_id):
        # Uses provided trace_id, generates new span_id
        result = await my_function()

Environment Variables:
    OTEL_TRACE_ID_GENERATOR: Optional custom generator name
    OTEL_SERVICE_NAME: Used for context when OTEL is available
"""

import secrets
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token

# Context variables for trace/span propagation
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id_var: ContextVar[str | None] = ContextVar("span_id", default=None)


def _generate_trace_id() -> str:
    """
    Generate an OpenTelemetry-compatible trace ID.

    Returns:
        128-bit hex string (32 characters)
    """
    return secrets.token_hex(16)


def _generate_span_id() -> str:
    """
    Generate an OpenTelemetry-compatible span ID.

    Returns:
        64-bit hex string (16 characters)
    """
    return secrets.token_hex(8)


def _get_otel_ids() -> tuple[str | None, str | None]:
    """
    Extract trace and span IDs from the current OpenTelemetry context.

    Returns:
        Tuple of (trace_id, span_id) or (None, None) if OTEL not available
    """
    try:
        from opentelemetry.trace import (  # type: ignore[import-not-found]
            INVALID_SPAN_ID,
            INVALID_TRACE_ID,
            get_current_span,
        )

        span = get_current_span()
        ctx = span.get_span_context()

        # Check if we have valid IDs
        if ctx.trace_id == INVALID_TRACE_ID or ctx.span_id == INVALID_SPAN_ID:
            return None, None

        # Format as hex strings (OTEL uses int, we need hex)
        trace_id = format(ctx.trace_id, "032x")
        span_id = format(ctx.span_id, "016x")

        return trace_id, span_id
    except ImportError:
        return None, None
    except Exception:
        return None, None


def get_trace_and_span_ids() -> tuple[str, str]:
    """
    Get the current trace and span IDs.

    Priority:
    1. Context variable (set by with_trace or explicitly)
    2. OpenTelemetry context (if OTEL is installed and active)
    3. Generate new OTEL-compatible IDs

    Returns:
        Tuple of (trace_id, span_id) - both are hex strings
        - trace_id: 128-bit hex (32 characters)
        - span_id: 64-bit hex (16 characters)

    Example:
        trace_id, span_id = get_trace_and_span_ids()
        print(f"Trace: {trace_id}")  # e.g., "4bf92f3577b34da6a3ce929d0e0e4736"
        print(f"Span: {span_id}")    # e.g., "00f067aa0ba902b7"
    """
    # Check context variables first
    trace_id = _trace_id_var.get()
    span_id = _span_id_var.get()

    if trace_id is not None and span_id is not None:
        return trace_id, span_id

    # Try OpenTelemetry context
    otel_trace_id, otel_span_id = _get_otel_ids()

    if otel_trace_id is not None and otel_span_id is not None:
        return otel_trace_id, otel_span_id

    # Generate new IDs
    return _generate_trace_id(), _generate_span_id()


def get_current_trace_id() -> str | None:
    """
    Get the current trace ID from context.

    Returns:
        Trace ID if set, None otherwise
    """
    # Check context variable
    trace_id = _trace_id_var.get()
    if trace_id is not None:
        return trace_id

    # Try OpenTelemetry
    otel_trace_id, _ = _get_otel_ids()
    return otel_trace_id


def get_current_span_id() -> str | None:
    """
    Get the current span ID from context.

    Returns:
        Span ID if set, None otherwise
    """
    # Check context variable
    span_id = _span_id_var.get()
    if span_id is not None:
        return span_id

    # Try OpenTelemetry
    _, otel_span_id = _get_otel_ids()
    return otel_span_id


def set_trace_context(trace_id: str, span_id: str) -> tuple[Token[str | None], Token[str | None]]:
    """
    Set the trace context for the current async context.

    Args:
        trace_id: 128-bit hex trace ID
        span_id: 64-bit hex span ID

    Returns:
        Tuple of reset tokens for restoring previous context
    """
    trace_token = _trace_id_var.set(trace_id)
    span_token = _span_id_var.set(span_id)
    return trace_token, span_token


def reset_trace_context(trace_token: Token[str | None], span_token: Token[str | None]) -> None:
    """
    Reset the trace context to previous values.

    Args:
        trace_token: Token from set_trace_context
        span_token: Token from set_trace_context
    """
    _trace_id_var.reset(trace_token)
    _span_id_var.reset(span_token)


@contextmanager
def with_trace(
    trace_id: str | None = None,
    span_id: str | None = None,
) -> Generator[tuple[str, str], None, None]:
    """
    Context manager for scoped tracing.

    Sets trace and span IDs for the duration of the block.
    If IDs are not provided, generates new ones.

    Args:
        trace_id: Optional trace ID to use (generates if not provided)
        span_id: Optional span ID to use (generates if not provided)

    Yields:
        Tuple of (trace_id, span_id) being used

    Example:
        # Auto-generate IDs
        with with_trace() as (trace_id, span_id):
            result = await process_request()
            print(f"Request traced as {trace_id}")

        # Use existing trace, new span
        with with_trace(trace_id=incoming_trace_id) as (tid, sid):
            result = await nested_operation()
    """
    # Generate IDs if not provided
    final_trace_id = trace_id or _generate_trace_id()
    final_span_id = span_id or _generate_span_id()

    # Set context
    trace_token, span_token = set_trace_context(final_trace_id, final_span_id)

    try:
        yield final_trace_id, final_span_id
    finally:
        # Reset context
        reset_trace_context(trace_token, span_token)


def is_otel_available() -> bool:
    """
    Check if OpenTelemetry is available and can be used.

    Returns:
        True if OpenTelemetry is installed and importable
    """
    try:
        import opentelemetry.trace  # type: ignore[import-not-found] # noqa: F401

        return True
    except ImportError:
        return False


def validate_trace_id(trace_id: str) -> bool:
    """
    Validate that a trace ID is OTEL-compatible.

    Args:
        trace_id: String to validate

    Returns:
        True if valid 128-bit hex string (32 chars)
    """
    if not isinstance(trace_id, str):
        return False
    if len(trace_id) != 32:
        return False
    try:
        int(trace_id, 16)
        return True
    except ValueError:
        return False


def validate_span_id(span_id: str) -> bool:
    """
    Validate that a span ID is OTEL-compatible.

    Args:
        span_id: String to validate

    Returns:
        True if valid 64-bit hex string (16 chars)
    """
    if not isinstance(span_id, str):
        return False
    if len(span_id) != 16:
        return False
    try:
        int(span_id, 16)
        return True
    except ValueError:
        return False
