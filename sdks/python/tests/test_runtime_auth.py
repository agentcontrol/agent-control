"""Tests for Agent Control SDK runtime auth helpers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from agent_control.runtime_auth import (
    RuntimeToken,
    RuntimeTokenCache,
    normalize_runtime_auth_mode,
    parse_runtime_token_exchange_response,
)


def _runtime_token(
    *,
    token: str = "token",
    server_url: str = "https://server-a.test",
    target_type: str = "log_stream",
    target_id: str = "ls-1",
    expires_at: datetime | None = None,
) -> RuntimeToken:
    return RuntimeToken(
        token=token,
        expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=5),
        server_url=server_url,
        target_type=target_type,
        target_id=target_id,
        scopes=("runtime.use",),
    )


def test_runtime_token_cache_is_keyed_by_server_and_target() -> None:
    cache = RuntimeTokenCache()
    token = _runtime_token()

    cache.set(token)

    assert (
        cache.get("https://server-a.test", "log_stream", "ls-1", refresh_margin_seconds=0) == token
    )
    assert (
        cache.get("https://server-b.test", "log_stream", "ls-1", refresh_margin_seconds=0) is None
    )
    assert (
        cache.get("https://server-a.test", "log_stream", "ls-2", refresh_margin_seconds=0) is None
    )


def test_runtime_token_cache_is_keyed_by_client_identity() -> None:
    cache = RuntimeTokenCache()
    token = _runtime_token()

    cache.set(token, cache_identity="client-a")

    assert (
        cache.get(
            "https://server-a.test",
            "log_stream",
            "ls-1",
            cache_identity="client-a",
            refresh_margin_seconds=0,
        )
        == token
    )
    assert (
        cache.get(
            "https://server-a.test",
            "log_stream",
            "ls-1",
            cache_identity="client-b",
            refresh_margin_seconds=0,
        )
        is None
    )

    cache.mark_jwt_unavailable(
        server_url="https://server-a.test",
        target_type="log_stream",
        target_id="ls-1",
        cache_identity="client-b",
    )

    assert not cache.is_jwt_unavailable(
        "https://server-a.test",
        "log_stream",
        "ls-1",
        cache_identity="client-a",
    )
    assert cache.is_jwt_unavailable(
        "https://server-a.test",
        "log_stream",
        "ls-1",
        cache_identity="client-b",
    )


def test_runtime_token_repr_redacts_jwt() -> None:
    token = _runtime_token(token="raw-jwt-value")

    assert "raw-jwt-value" not in repr(token)


def test_runtime_token_cache_drops_stale_tokens() -> None:
    cache = RuntimeTokenCache()
    cache.set(_runtime_token(expires_at=datetime.now(UTC) + timedelta(seconds=5)))

    assert (
        cache.get("https://server-a.test", "log_stream", "ls-1", refresh_margin_seconds=30) is None
    )
    assert (
        cache.get("https://server-a.test", "log_stream", "ls-1", refresh_margin_seconds=0) is None
    )


def test_runtime_token_cache_tracks_jwt_unavailable_by_server_and_target() -> None:
    cache = RuntimeTokenCache()

    cache.mark_jwt_unavailable(
        server_url="https://server-a.test",
        target_type="log_stream",
        target_id="ls-1",
    )

    assert cache.is_jwt_unavailable("https://server-a.test", "log_stream", "ls-1")
    assert not cache.is_jwt_unavailable("https://server-b.test", "log_stream", "ls-1")

    cache.set(_runtime_token())

    assert not cache.is_jwt_unavailable("https://server-a.test", "log_stream", "ls-1")


def test_runtime_token_cache_target_unavailable_marker_expires() -> None:
    cache = RuntimeTokenCache()

    cache.mark_jwt_unavailable(
        server_url="https://server-a.test",
        target_type="log_stream",
        target_id="ls-1",
        ttl_seconds=0,
    )

    assert not cache.is_jwt_unavailable("https://server-a.test", "log_stream", "ls-1")


def test_runtime_token_cache_server_unavailable_clears_server_cache() -> None:
    cache = RuntimeTokenCache()
    cache.set(_runtime_token())
    token_2 = _runtime_token(
        token="token-2",
        server_url="https://server-b.test",
        target_id="ls-2",
    )
    cache.set(token_2)

    cache.mark_jwt_unavailable(server_url="https://server-a.test", globally=True)

    assert cache.is_jwt_unavailable("https://server-a.test", "log_stream", "ls-1")
    assert not cache.is_jwt_unavailable("https://server-b.test", "log_stream", "ls-2")
    assert (
        cache.get("https://server-a.test", "log_stream", "ls-1", refresh_margin_seconds=0) is None
    )
    assert (
        cache.get("https://server-b.test", "log_stream", "ls-2", refresh_margin_seconds=0)
        == token_2
    )

    cache.clear()

    assert not cache.is_jwt_unavailable("https://server-a.test", "log_stream", "ls-1")


def test_runtime_token_cache_server_unavailable_marker_expires() -> None:
    cache = RuntimeTokenCache(jwt_unavailable_ttl_seconds=0)

    cache.mark_jwt_unavailable(server_url="https://server-a.test", globally=True)

    assert not cache.is_jwt_unavailable("https://server-a.test", "log_stream", "ls-1")


def test_runtime_token_cache_remove_drops_one_token() -> None:
    cache = RuntimeTokenCache()
    cache.set(_runtime_token(target_id="ls-1"))
    token_2 = _runtime_token(token="token-2", target_id="ls-2")
    cache.set(token_2)

    cache.remove("https://server-a.test", "log_stream", "ls-1")

    assert (
        cache.get("https://server-a.test", "log_stream", "ls-1", refresh_margin_seconds=0) is None
    )
    assert (
        cache.get("https://server-a.test", "log_stream", "ls-2", refresh_margin_seconds=0)
        == token_2
    )


def test_runtime_token_cache_evicts_oldest_token_when_full() -> None:
    cache = RuntimeTokenCache(max_entries=1)
    token_1 = _runtime_token(target_id="ls-1")
    token_2 = _runtime_token(token="token-2", target_id="ls-2")

    cache.set(token_1)
    cache.set(token_2)

    assert (
        cache.get("https://server-a.test", "log_stream", "ls-1", refresh_margin_seconds=0) is None
    )
    assert (
        cache.get("https://server-a.test", "log_stream", "ls-2", refresh_margin_seconds=0)
        == token_2
    )


@pytest.mark.asyncio
async def test_runtime_token_cache_token_eviction_preserves_exchange_lock() -> None:
    cache = RuntimeTokenCache(max_entries=1)
    lock = cache.exchange_lock("https://server-a.test", "log_stream", "ls-1")

    cache.set(_runtime_token(target_id="ls-1"))
    cache.set(_runtime_token(token="token-2", target_id="ls-2"))

    assert cache.exchange_lock("https://server-a.test", "log_stream", "ls-1") is lock


@pytest.mark.asyncio
async def test_runtime_token_cache_evicts_idle_exchange_locks() -> None:
    cache = RuntimeTokenCache(max_entries=1)
    first = cache.exchange_lock("https://server-a.test", "log_stream", "ls-1")

    cache.exchange_lock("https://server-a.test", "log_stream", "ls-2")

    assert cache.exchange_lock("https://server-a.test", "log_stream", "ls-1") is not first


def test_runtime_token_cache_exchange_locks_are_loop_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = RuntimeTokenCache()
    loop_1 = object()
    loop_2 = object()

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop_1)
    first = cache.exchange_lock("https://server-a.test", "log_stream", "ls-1")

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop_2)
    second = cache.exchange_lock("https://server-a.test", "log_stream", "ls-1")

    assert first != second


def test_runtime_token_cache_rejects_empty_capacity() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        RuntimeTokenCache(max_entries=0)


def test_runtime_token_cache_rejects_negative_unavailable_ttl() -> None:
    with pytest.raises(ValueError, match="jwt_unavailable_ttl_seconds"):
        RuntimeTokenCache(jwt_unavailable_ttl_seconds=-1)


def test_runtime_token_cache_rejects_negative_marker_ttl() -> None:
    cache = RuntimeTokenCache()

    with pytest.raises(ValueError, match="ttl_seconds"):
        cache.mark_jwt_unavailable(ttl_seconds=-1)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "auto"),
        ("", "auto"),
        (" NO_AUTH ", "none"),
        ("header", "api_key"),
        ("api_key", "api_key"),
        ("jwt", "jwt"),
    ],
)
def test_normalize_runtime_auth_mode(raw: str | None, expected: str) -> None:
    assert normalize_runtime_auth_mode(raw) == expected


def test_normalize_runtime_auth_mode_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="runtime_auth_mode must be one of"):
        normalize_runtime_auth_mode("cookie")


def test_parse_runtime_token_exchange_response_normalizes_zulu_expiry() -> None:
    token = parse_runtime_token_exchange_response(
        {
            "token": "runtime-token",
            "expires_at": "2026-05-07T15:00:00Z",
            "target_type": "log_stream",
            "target_id": "ls-1",
            "scopes": ["runtime.use"],
        },
        server_url="https://server-a.test",
    )

    assert token.token == "runtime-token"
    assert token.expires_at == datetime(2026, 5, 7, 15, 0, tzinfo=UTC)
    assert token.server_url == "https://server-a.test"
    assert token.target_type == "log_stream"
    assert token.target_id == "ls-1"
    assert token.scopes == ("runtime.use",)


def test_parse_runtime_token_exchange_response_treats_naive_expiry_as_utc() -> None:
    token = parse_runtime_token_exchange_response(
        {
            "token": "runtime-token",
            "expires_at": "2026-05-07T15:00:00",
            "target_type": "log_stream",
            "target_id": "ls-1",
            "scopes": ["runtime.use"],
        },
        server_url="https://server-a.test",
    )

    assert token.expires_at == datetime(2026, 5, 7, 15, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({}, "token"),
        ({"token": "runtime-token"}, "expires_at"),
        ({"token": "runtime-token", "expires_at": "2026-05-07T15:00:00Z"}, "target_type"),
        (
            {
                "token": "runtime-token",
                "expires_at": "2026-05-07T15:00:00Z",
                "target_type": "log_stream",
            },
            "target_id",
        ),
        (
            {
                "token": "runtime-token",
                "expires_at": "2026-05-07T15:00:00Z",
                "target_type": "log_stream",
                "target_id": "ls-1",
                "scopes": "runtime.use",
            },
            "scopes",
        ),
        (
            {
                "token": "runtime-token",
                "expires_at": "2026-05-07T15:00:00Z",
                "target_type": "log_stream",
                "target_id": "ls-1",
                "scopes": ["runtime.use", 1],
            },
            "non-string scope",
        ),
    ],
)
def test_parse_runtime_token_exchange_response_rejects_invalid_payloads(
    payload: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(RuntimeError, match=match):
        parse_runtime_token_exchange_response(payload, server_url="https://server-a.test")
