from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_control_server import main as main_module
from agent_control_server.config import observability_settings, settings
from agent_control_server.main import lifespan
from agent_control_server.observability.sinks import (
    ResolvedControlEventBackend,
    register_control_event_sink_factory,
    unregister_control_event_sink_factory,
)


def test_lifespan_initializes_observability_when_enabled(monkeypatch) -> None:
    # Given: observability enabled
    monkeypatch.setattr(observability_settings, "enabled", True)
    monkeypatch.setattr(observability_settings, "sink_name", "default")

    app = FastAPI(lifespan=lifespan)

    # When: the app starts
    with TestClient(app):
        # Then: observability components are initialized
        assert hasattr(app.state, "event_store")
        assert hasattr(app.state, "event_ingestor")
        assert app.state.event_ingestor.sink.store is app.state.event_store


def test_lifespan_uses_custom_backend_store_for_custom_sink(monkeypatch) -> None:
    class DummyStore:
        def __init__(self) -> None:
            self.closed = False

        async def store(self, events, *, namespace_key: str):  # type: ignore[no-untyped-def]
            return len(events)

        async def query_stats(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        async def query_events(self, query, *, namespace_key: str):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        async def close(self) -> None:
            self.closed = True

    class DummySink:
        def __init__(self) -> None:
            self.flushed = False
            self.closed = False

        async def write_events(self, events):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        async def flush(self) -> None:
            self.flushed = True

        async def close(self) -> None:
            self.closed = True

    custom_store = DummyStore()
    custom_sink = DummySink()

    monkeypatch.setattr(observability_settings, "enabled", True)
    monkeypatch.setattr(observability_settings, "sink_name", "custom")
    monkeypatch.setattr(observability_settings, "sink_config", {"target": "demo"})
    monkeypatch.setattr(
        main_module,
        "PostgresEventStore",
        lambda session_maker: (_ for _ in ()).throw(
            AssertionError("default store should not be created")
        ),
    )
    register_control_event_sink_factory(
        "custom",
        lambda config: ResolvedControlEventBackend(
            sink=custom_sink,
            event_store=custom_store,
        ),
    )

    app = FastAPI(lifespan=lifespan)

    try:
        with TestClient(app):
            assert app.state.event_store is custom_store
            assert app.state.event_ingestor.sink is custom_sink
            assert app.state.event_sink is custom_sink
        assert custom_store.closed is True
        assert custom_sink.flushed is True
        assert custom_sink.closed is True
    finally:
        unregister_control_event_sink_factory("custom")


def test_lifespan_flushes_shared_sink_store_backend(monkeypatch) -> None:
    class SharedBackend:
        def __init__(self) -> None:
            self.flushed = False
            self.closed = 0

        async def write_events(self, events):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        async def store(self, events, *, namespace_key: str):  # type: ignore[no-untyped-def]
            return len(events)

        async def query_stats(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        async def query_events(self, query, *, namespace_key: str):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        async def flush(self) -> None:
            self.flushed = True

        async def close(self) -> None:
            self.closed += 1

    backend = SharedBackend()

    monkeypatch.setattr(observability_settings, "enabled", True)
    monkeypatch.setattr(observability_settings, "sink_name", "custom")
    monkeypatch.setattr(observability_settings, "sink_config", {"target": "demo"})
    register_control_event_sink_factory(
        "custom",
        lambda config: ResolvedControlEventBackend(
            sink=backend,
            event_store=backend,
        ),
    )

    app = FastAPI(lifespan=lifespan)

    try:
        with TestClient(app):
            assert app.state.event_store is backend
            assert app.state.event_sink is backend
            assert app.state.event_ingestor.sink is backend
        assert backend.flushed is True
        assert backend.closed == 1
    finally:
        unregister_control_event_sink_factory("custom")


def test_lifespan_skips_observability_when_disabled(monkeypatch) -> None:
    # Given: observability disabled
    monkeypatch.setattr(observability_settings, "enabled", False)

    app = FastAPI(lifespan=lifespan)

    # When: the app starts
    with TestClient(app):
        # Then: observability components are not initialized
        assert not hasattr(app.state, "event_store")
        assert not hasattr(app.state, "event_ingestor")


def test_custom_openapi_replaces_jsonvalue_variants(monkeypatch) -> None:
    # Given: a custom openapi generator that includes Pydantic JSONValue schemas
    json_value_schema_names = (
        "JSONValue",
        "JSONValue-Input",
        "JSONValue-Output",
        "JsonValue",
        "JsonValue-Input",
        "JsonValue-Output",
    )

    def fake_get_openapi(*, title, version, description, routes):
        return {
            "components": {
                "schemas": {name: {"type": "object"} for name in json_value_schema_names}
            },
            "info": {"title": title, "version": version, "description": description},
            "paths": {},
        }

    monkeypatch.setattr(main_module, "get_openapi", fake_get_openapi)
    main_module.app.openapi_schema = None

    # When: generating openapi
    schema = main_module.app.openapi()

    # Then: JSONValue schemas are replaced with a non-recursive schema
    schemas = schema["components"]["schemas"]
    for schema_name in json_value_schema_names:
        assert schemas[schema_name] == {"description": "Any JSON value"}


def test_custom_openapi_is_cached(monkeypatch) -> None:
    # Given: a custom openapi generator
    calls = {"count": 0}

    def fake_get_openapi(*, title, version, description, routes):
        calls["count"] += 1
        return {"components": {"schemas": {}}, "info": {"title": title, "version": version}}

    monkeypatch.setattr(main_module, "get_openapi", fake_get_openapi)
    main_module.app.openapi_schema = None

    # When: calling openapi twice
    first = main_module.app.openapi()
    second = main_module.app.openapi()

    # Then: result is cached and generator called once
    assert first is second
    assert calls["count"] == 1


def test_run_uses_settings(monkeypatch) -> None:
    # Given: patched settings and uvicorn.run
    called = {}

    def fake_run(app, host, port, log_level):
        called["host"] = host
        called["port"] = port
        called["log_level"] = log_level

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    monkeypatch.setattr(settings, "host", "127.0.0.1")
    monkeypatch.setattr(settings, "port", 9999)
    monkeypatch.setattr(settings, "debug", True)

    # When: running the server entrypoint
    main_module.run()

    # Then: uvicorn is called with expected settings
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 9999
    assert called["log_level"] == "debug"
