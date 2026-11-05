"""Reuse synchronous input preparation within one engine evaluation.

This holds no evaluation results, credentials or state across requests. Inputs
are treated as read-only for the duration of an evaluation, as they already are
when the engine passes the same Step to concurrent evaluators.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import cast


@dataclass
class _Preparation:
    # Retain inputs to prevent object-ID reuse during the evaluation.
    entries: dict[tuple[str, tuple[int, ...]], tuple[tuple[object, ...], object]] = field(
        default_factory=dict
    )
    active: bool = True


_CURRENT: ContextVar[_Preparation | None] = ContextVar("evaluation_preparation", default=None)


@contextmanager
def evaluation_preparation_scope() -> Iterator[None]:
    """Isolate preparation for one evaluation, including its child tasks.

    Nested and concurrent evaluations get separate scopes. Clearing and marking
    the scope inactive also prevents inherited background contexts retaining or
    repopulating request data after the evaluation exits.
    """
    preparation = _Preparation()
    token = _CURRENT.set(preparation)
    try:
        yield
    finally:
        preparation.active = False
        preparation.entries.clear()
        _CURRENT.reset(token)


def prepare_once[T](namespace: str, inputs: tuple[object, ...], build: Callable[[], T]) -> T:
    """Reuse preparation for identical input objects in the active evaluation.

    The namespace must identify the preparation and all non-object options.
    Builders must be synchronous, side-effect-free and return read-only values.
    Outside an engine evaluation, build normally without retaining anything.
    Failed builds are not cached. No hashing or serialization of content is
    needed to look up a prepared value.
    """
    preparation = _CURRENT.get()
    if preparation is None or not preparation.active:
        return build()
    key = namespace, tuple(id(value) for value in inputs)
    entry = preparation.entries.get(key)
    if entry is not None:
        return cast(T, entry[1])
    value = build()
    preparation.entries[key] = inputs, value
    return value
