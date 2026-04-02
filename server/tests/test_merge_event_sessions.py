from agent_control_server.auth import AuthLevel, AuthenticatedClient
from agent_control_server.merge_event_sessions import (
    is_merge_events_enabled,
    set_merge_events_enabled,
)


def _client(api_key: str) -> AuthenticatedClient:
    return AuthenticatedClient(
        api_key=api_key,
        is_admin=False,
        auth_level=AuthLevel.API_KEY,
    )


def test_merge_event_session_enable_disable_is_scoped_by_client_and_agent() -> None:
    client_a = _client("key-a")
    client_b = _client("key-b")

    set_merge_events_enabled(client_a, "agent-a", enabled=False)
    set_merge_events_enabled(client_b, "agent-a", enabled=False)

    assert is_merge_events_enabled(client_a, "agent-a") is False
    assert is_merge_events_enabled(client_b, "agent-a") is False

    set_merge_events_enabled(client_a, "agent-a", enabled=True)

    assert is_merge_events_enabled(client_a, "agent-a") is True
    assert is_merge_events_enabled(client_a, "agent-b") is False
    assert is_merge_events_enabled(client_b, "agent-a") is False

    set_merge_events_enabled(client_a, "agent-a", enabled=False)

    assert is_merge_events_enabled(client_a, "agent-a") is False
