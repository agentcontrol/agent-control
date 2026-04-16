"""Tests for server-side observability sink resolution."""

import pytest
from agent_control_telemetry import (
    REGISTERED_CONTROL_EVENT_SINK_NAME,
    ControlEventSinkSelection,
)

from agent_control_server.observability.sinks import (
    ResolvedControlEventBackend,
    get_registered_control_event_sink_factory_names,
    register_control_event_sink_factory,
    resolve_control_event_backend,
    unregister_control_event_sink_factory,
)


class DummyAsyncSink:
    async def write_events(self, events):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class DummyStore:
    async def store(self, events):  # type: ignore[no-untyped-def]
        return len(events)

    async def query_stats(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def query_events(self, query):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    async def close(self) -> None:
        return None


def teardown_function() -> None:
    for name in get_registered_control_event_sink_factory_names():
        unregister_control_event_sink_factory(name)


def test_resolve_control_event_backend_uses_default_backend_for_default_selection() -> None:
    default_backend = ResolvedControlEventBackend(
        sink=DummyAsyncSink(),
        event_store=DummyStore(),
    )

    resolved = resolve_control_event_backend(
        ControlEventSinkSelection(name="default"),
        default_backend=default_backend,
    )

    assert resolved is default_backend


def test_resolve_control_event_backend_uses_named_factory() -> None:
    named_backend = ResolvedControlEventBackend(
        sink=DummyAsyncSink(),
        event_store=DummyStore(),
    )
    register_control_event_sink_factory("custom", lambda config: named_backend)

    resolved = resolve_control_event_backend(
        ControlEventSinkSelection(name="custom", config={"target": "x"}),
    )

    assert resolved is named_backend


def test_resolve_control_event_backend_rejects_registered_selection() -> None:
    with pytest.raises(RuntimeError, match="not supported on the server"):
        resolve_control_event_backend(
            ControlEventSinkSelection(name=REGISTERED_CONTROL_EVENT_SINK_NAME)
        )
