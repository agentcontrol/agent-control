"""Tests for the telemetry trace context provider contract."""

from typing import Any

import pytest

from agent_control_telemetry.trace_context import (
    clear_trace_context_provider,
    get_trace_context_from_provider,
    set_trace_context_provider,
)


def teardown_function() -> None:
    clear_trace_context_provider()


def test_get_trace_context_from_provider_returns_registered_context() -> None:
    # Given: a provider that returns valid trace and span identifiers
    set_trace_context_provider(
        lambda: {
            "trace_id": "trace-123",
            "span_id": "span-456",
        }
    )

    # When: reading the current trace context
    trace_context = get_trace_context_from_provider()

    # Then: the provider values are returned unchanged
    assert trace_context == {
        "trace_id": "trace-123",
        "span_id": "span-456",
    }


@pytest.mark.parametrize(
    ("provider_result"),
    [
        None,
        {"trace_id": "trace-123"},
        {"span_id": "span-456"},
        {"trace_id": 123, "span_id": "span-456"},
        {"trace_id": "trace-123", "span_id": object()},
        {"trace_id": "", "span_id": "span-456"},
        {"trace_id": "   ", "span_id": "span-456"},
        {"trace_id": "trace-123", "span_id": ""},
        {"trace_id": "trace-123", "span_id": "   "},
    ],
)
def test_get_trace_context_from_provider_rejects_invalid_results(
    provider_result: dict[str, Any] | None,
) -> None:
    # Given: a provider that returns an invalid trace-context payload
    set_trace_context_provider(lambda: provider_result)  # type: ignore[arg-type]

    # When: reading the current trace context
    trace_context = get_trace_context_from_provider()

    # Then: invalid provider output is ignored
    assert trace_context is None


def test_get_trace_context_from_provider_swallows_provider_failures() -> None:
    # Given: a provider that raises unexpectedly
    def _raising_provider() -> None:
        raise RuntimeError("boom")

    set_trace_context_provider(_raising_provider)

    # When: reading the current trace context
    trace_context = get_trace_context_from_provider()

    # Then: provider failures do not escape the helper
    assert trace_context is None
