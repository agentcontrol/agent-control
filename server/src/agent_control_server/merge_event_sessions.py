"""Server-side trust state for merged event creation.

Merged event creation is an SDK-owned flow where the SDK reconstructs and
enqueues the final batch of control-execution events after combining local and
server evaluation results. In that mode the server must skip its normal
observability ingestion step, otherwise both the server and SDK would emit
events for the same evaluation.

The merge request header on ``/evaluation`` is caller-controlled, so the server
cannot safely trust that header on its own. This module stores a small amount
of init-scoped session state so the server can distinguish:

- callers that previously initialized a given agent with ``merge_events=True``
- callers that merely send the merge header directly

Only the first case is allowed to suppress server-side observability
ingestion. All other callers stay on the default server-ingestion path.
"""

from __future__ import annotations

from threading import Lock

from .auth import AuthenticatedClient

_merge_enabled_sessions: set[tuple[str, str]] = set()
_lock = Lock()


def _session_key(client: AuthenticatedClient, agent_name: str) -> tuple[str, str]:
    """Return the in-memory lookup key for one merge-enabled SDK session.

    Args:
        client: Authenticated caller identity resolved by the server.
        agent_name: Normalized agent name for the initialized SDK session.

    Returns:
        A stable ``(client, agent)`` key used for merge-session tracking.
    """
    return (client.api_key, agent_name)


def set_merge_events_enabled(
    client: AuthenticatedClient,
    agent_name: str,
    enabled: bool,
) -> None:
    """Record whether merged event creation is enabled for a client/agent pair.

    This is called from the agent-init flow so later evaluation requests can be
    checked against the server's trusted SDK session state instead of relying on
    request headers alone.

    Args:
        client: Authenticated caller identity resolved by the server.
        agent_name: Normalized agent name whose session state is being updated.
        enabled: Whether merged event creation is enabled for this session.

    Returns:
        None.
    """
    key = _session_key(client, agent_name)
    with _lock:
        if enabled:
            _merge_enabled_sessions.add(key)
        else:
            _merge_enabled_sessions.discard(key)


def is_merge_events_enabled(
    client: AuthenticatedClient,
    agent_name: str,
) -> bool:
    """Return whether merged event creation is enabled for this SDK session.

    Args:
        client: Authenticated caller identity resolved by the server.
        agent_name: Normalized agent name for the evaluation request.

    Returns:
        ``True`` when the caller previously initialized the same agent with
        merged event creation enabled; otherwise ``False``.
    """
    key = _session_key(client, agent_name)
    with _lock:
        return key in _merge_enabled_sessions
