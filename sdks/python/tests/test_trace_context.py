"""Tests for the telemetry trace context provider interface."""

from agent_control.telemetry.trace_context import (
    clear_trace_context_provider,
    get_trace_context_from_provider,
    set_trace_context_provider,
)


def teardown_function() -> None:
    clear_trace_context_provider()


def test_get_trace_context_from_provider_returns_registered_context() -> None:
    set_trace_context_provider(
        lambda: {
            "trace_id": "a" * 32,
            "span_id": "b" * 16,
        }
    )

    assert get_trace_context_from_provider() == {
        "trace_id": "a" * 32,
        "span_id": "b" * 16,
    }


def test_get_trace_context_from_provider_returns_none_when_unset() -> None:
    assert get_trace_context_from_provider() is None


def test_get_trace_context_from_provider_returns_none_when_provider_returns_none() -> None:
    set_trace_context_provider(lambda: None)

    assert get_trace_context_from_provider() is None


def test_get_trace_context_from_provider_swallows_provider_failures() -> None:
    def _raising_provider():
        raise RuntimeError("boom")

    set_trace_context_provider(_raising_provider)

    assert get_trace_context_from_provider() is None


def test_get_trace_context_from_provider_returns_none_for_invalid_shape() -> None:
    set_trace_context_provider(  # type: ignore[arg-type]
        lambda: {
            "trace_id": "a" * 32,
        }
    )

    assert get_trace_context_from_provider() is None


def test_get_trace_context_from_provider_returns_none_for_empty_ids() -> None:
    set_trace_context_provider(
        lambda: {
            "trace_id": "",
            "span_id": "",
        }
    )

    assert get_trace_context_from_provider() is None
