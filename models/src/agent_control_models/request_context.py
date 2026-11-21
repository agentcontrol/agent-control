"""Bounded request identity shared by the server and evaluator clients."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,200}")
_request_id: ContextVar[str | None] = ContextVar("agent_control_request_id", default=None)


def get_request_id() -> str | None:
    """Return the current parent request ID, if a caller established one."""
    return _request_id.get()


@contextmanager
def request_id_context(value: str | None) -> Iterator[str]:
    """Preserve a safe parent ID for this context and reset it on every exit."""
    request_id = value if value is not None and _REQUEST_ID.fullmatch(value) else str(uuid4())
    token = _request_id.set(request_id)
    try:
        yield request_id
    finally:
        _request_id.reset(token)
