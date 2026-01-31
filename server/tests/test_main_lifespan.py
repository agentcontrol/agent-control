from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_control_server.config import observability_settings, settings
from agent_control_server import main as main_module
from agent_control_server.main import lifespan


def test_lifespan_initializes_observability_when_enabled(monkeypatch) -> None:
    # Given: observability enabled
    monkeypatch.setattr(observability_settings, "enabled", True)

    app = FastAPI(lifespan=lifespan)

    # When: the app starts
    with TestClient(app):
        # Then: observability components are initialized
        assert hasattr(app.state, "event_store")
        assert hasattr(app.state, "event_ingestor")


def test_lifespan_skips_observability_when_disabled(monkeypatch) -> None:
    # Given: observability disabled
    monkeypatch.setattr(observability_settings, "enabled", False)

    app = FastAPI(lifespan=lifespan)

    # When: the app starts
    with TestClient(app):
        # Then: observability components are not initialized
        assert not hasattr(app.state, "event_store")
        assert not hasattr(app.state, "event_ingestor")


def test_custom_openapi_replaces_jsonvalue(monkeypatch) -> None:
    # Given: a custom openapi generator that includes JSONValue
    def fake_get_openapi(*, title, version, description, routes):
        return {
            "components": {"schemas": {"JSONValue": {"type": "object"}}},
            "info": {"title": title, "version": version, "description": description},
            "paths": {},
        }

    monkeypatch.setattr(main_module, "get_openapi", fake_get_openapi)
    main_module.app.openapi_schema = None

    # When: generating openapi
    schema = main_module.app.openapi()

    # Then: JSONValue is replaced with safe description
    assert schema["components"]["schemas"]["JSONValue"]["description"] == "Any JSON value"


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
