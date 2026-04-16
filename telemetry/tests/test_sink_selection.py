"""Tests for shared control-event sink selection helpers."""

from agent_control_telemetry import (
    DEFAULT_CONTROL_EVENT_SINK_NAME,
    REGISTERED_CONTROL_EVENT_SINK_NAME,
    ControlEventSinkFactoryRegistry,
    ControlEventSinkSelection,
    SinkSelectionError,
)


def test_control_event_sink_selection_defaults_to_builtin_sink() -> None:
    selection = ControlEventSinkSelection()

    assert selection.name == DEFAULT_CONTROL_EVENT_SINK_NAME
    assert selection.config == {}


def test_sink_factory_registry_resolves_registered_factory() -> None:
    registry: ControlEventSinkFactoryRegistry[str] = ControlEventSinkFactoryRegistry()
    registry.register("custom", lambda config: f"sink:{config['target']}")

    resolved = registry.resolve(
        ControlEventSinkSelection(name="custom", config={"target": "demo"})
    )

    assert resolved == "sink:demo"


def test_sink_factory_registry_rejects_reserved_names() -> None:
    registry: ControlEventSinkFactoryRegistry[str] = ControlEventSinkFactoryRegistry()

    for reserved_name in (DEFAULT_CONTROL_EVENT_SINK_NAME, REGISTERED_CONTROL_EVENT_SINK_NAME):
        try:
            registry.register(reserved_name, lambda config: "x")
        except ValueError as exc:
            assert reserved_name in str(exc)
        else:
            raise AssertionError(f"Expected ValueError for reserved name {reserved_name}")


def test_sink_factory_registry_raises_for_unknown_name() -> None:
    registry: ControlEventSinkFactoryRegistry[str] = ControlEventSinkFactoryRegistry()

    try:
        registry.resolve(ControlEventSinkSelection(name="missing"))
    except SinkSelectionError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("Expected SinkSelectionError for unknown sink name")
