"""Optional Prometheus metrics for Luna scorer client timing."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import Protocol, cast

try:
    from prometheus_client import Histogram  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised when embedded without Prometheus.
    Histogram = None  # type: ignore[assignment]


class _HistogramChild(Protocol):
    def observe(self, amount: float) -> None: ...


class _Histogram(Protocol):
    def labels(self, **labels: str) -> _HistogramChild: ...


if Histogram is None:
    _CLIENT_STAGE_DURATION: _Histogram | None = None
    _HTTPCORE_PHASE_DURATION: _Histogram | None = None
else:
    _CLIENT_STAGE_DURATION = cast(
        _Histogram,
        Histogram(
            "agent_control_luna_client_stage_duration_seconds",
            "Duration of Luna scorer client stages.",
            ("stage", "outcome", "auth_mode", "endpoint_path", "scorer_identifier_kind"),
        ),
    )
    _HTTPCORE_PHASE_DURATION = cast(
        _Histogram,
        Histogram(
            "agent_control_luna_httpcore_phase_duration_seconds",
            "Duration of Luna scorer HTTP transport phases.",
            ("phase", "outcome"),
        ),
    )


def _stage_outcome(error: BaseException | None) -> str:
    if error is None:
        return "success"
    if error.__class__.__name__ == "HTTPStatusError":
        return "http_status_error"
    if error.__class__.__name__.endswith("RequestError"):
        return "request_error"
    return "error"


def observe_luna_httpcore_phase(
    *,
    phase: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    """Record an HTTP transport phase duration when Prometheus is available."""
    if _HTTPCORE_PHASE_DURATION is None:
        return
    _HTTPCORE_PHASE_DURATION.labels(phase=phase, outcome=outcome).observe(duration_seconds)


@contextmanager
def observe_luna_client_stage(
    *,
    stage: str,
    auth_mode: str,
    endpoint_path: str,
    scorer_identifier_kind: str,
) -> Iterator[None]:
    """Record a Luna client stage duration when Prometheus is available."""
    started_at = perf_counter()
    error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        if _CLIENT_STAGE_DURATION is not None:
            _CLIENT_STAGE_DURATION.labels(
                stage=stage,
                outcome=_stage_outcome(error),
                auth_mode=auth_mode,
                endpoint_path=endpoint_path,
                scorer_identifier_kind=scorer_identifier_kind,
            ).observe(perf_counter() - started_at)
