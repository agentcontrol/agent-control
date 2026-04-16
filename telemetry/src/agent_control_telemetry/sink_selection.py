"""Shared sink-selection models and registries for control-event delivery."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import TypeVar

from agent_control_models import JSONObject
from pydantic import BaseModel, Field

DEFAULT_CONTROL_EVENT_SINK_NAME = "default"
REGISTERED_CONTROL_EVENT_SINK_NAME = "registered"

SinkT = TypeVar("SinkT")
type ControlEventSinkFactory[SinkT] = Callable[[JSONObject], SinkT]


class SinkSelectionError(LookupError):
    """Raised when a configured sink cannot be resolved."""


class ControlEventSinkSelection(BaseModel):
    """Configuration for choosing a control-event sink."""

    name: str = Field(default=DEFAULT_CONTROL_EVENT_SINK_NAME, min_length=1)
    config: JSONObject = Field(default_factory=dict)


class ControlEventSinkFactoryRegistry[SinkT]:
    """Thread-safe registry for named control-event sink factories."""

    def __init__(self) -> None:
        self._factories: dict[str, ControlEventSinkFactory[SinkT]] = {}
        self._lock = Lock()

    def register(self, name: str, factory: ControlEventSinkFactory[SinkT]) -> None:
        """Register a named sink factory."""
        if name in {
            DEFAULT_CONTROL_EVENT_SINK_NAME,
            REGISTERED_CONTROL_EVENT_SINK_NAME,
        }:
            raise ValueError(f"'{name}' is reserved and cannot be registered as a custom sink")

        with self._lock:
            self._factories[name] = factory

    def unregister(self, name: str) -> None:
        """Unregister a previously registered named sink factory."""
        with self._lock:
            self._factories.pop(name, None)

    def registered_names(self) -> tuple[str, ...]:
        """Return the registered sink names."""
        with self._lock:
            return tuple(sorted(self._factories))

    def resolve(self, selection: ControlEventSinkSelection) -> SinkT:
        """Resolve a configured named sink."""
        if selection.name in {
            DEFAULT_CONTROL_EVENT_SINK_NAME,
            REGISTERED_CONTROL_EVENT_SINK_NAME,
        }:
            raise SinkSelectionError(
                f"'{selection.name}' must be resolved by the caller as a built-in sink"
            )

        with self._lock:
            factory = self._factories.get(selection.name)

        if factory is None:
            raise SinkSelectionError(f"No control-event sink registered for '{selection.name}'")

        return factory(dict(selection.config))
