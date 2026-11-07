"""Optional tracing hooks without a tracing SDK dependency in the engine."""

from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar

Attributes = Mapping[str, str | int]
SpanFactory = Callable[[str, Attributes], AbstractContextManager[None]]
HeaderInjector = Callable[[dict[str, str]], None]
IntervalObserver = Callable[[str, int, int], None]
_span_factory: SpanFactory | None = None
_header_injector: HeaderInjector | None = None
_interval_observer: IntervalObserver | None = None
_control: ContextVar[tuple[int, int] | None] = ContextVar("ac_trace_control", default=None)


def configure_runtime_tracing(
    span_factory: SpanFactory | None,
    header_injector: HeaderInjector | None = None,
    interval_observer: IntervalObserver | None = None,
) -> None:
    """Install process-local hooks. Unconfigured libraries emit no spans or headers."""
    global _span_factory, _header_injector, _interval_observer
    _span_factory = span_factory
    _header_injector = header_injector
    _interval_observer = interval_observer


@contextmanager
def runtime_span(name: str, attributes: Attributes | None = None) -> Iterator[None]:
    if _span_factory is None:
        yield
    else:
        with _span_factory(name, attributes or {}):
            yield


@contextmanager
def control_span(control_id: int, index: int) -> Iterator[None]:
    """Keep each parallel control's identity local to its async task."""
    token = _control.set((control_id, index))
    try:
        with runtime_span(
            "agentcontrol.control",
            {"galileo.control.id": control_id, "galileo.control.index": index},
        ):
            yield
    finally:
        _control.reset(token)


def inject_runtime_trace_headers(headers: dict[str, str]) -> None:
    if _header_injector is None:
        return
    for key in list(headers):
        if key.lower() in {
            "traceparent",
            "tracestate",
            "baggage",
            "x-galileo-control-id",
            "x-galileo-control-index",
        }:
            del headers[key]
    _header_injector(headers)
    control = _control.get()
    if control is not None and "traceparent" in headers:
        headers["x-galileo-control-id"] = str(control[0])
        headers["x-galileo-control-index"] = str(control[1])


def observe_runtime_interval(name: str, started_ns: int, ended_ns: int) -> None:
    """Record a completed transport interval under the active HTTP span."""
    if _interval_observer is not None:
        _interval_observer(name, started_ns, ended_ns)
