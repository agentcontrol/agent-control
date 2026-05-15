"""Runtime-token cache helpers for the Agent Control SDK."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

RuntimeAuthMode = Literal["auto", "none", "api_key", "jwt"]

_TokenKey = tuple[str, str, str, str]
_LockKey = tuple[str, str, str, str, asyncio.AbstractEventLoop]
_DEFAULT_MAX_CACHE_ENTRIES = 256
_DEFAULT_JWT_UNAVAILABLE_TTL_SECONDS = 30


@dataclass(frozen=True)
class RuntimeToken:
    """Short-lived runtime token bound to one target."""

    token: str = field(repr=False)
    expires_at: datetime
    server_url: str
    target_type: str
    target_id: str
    scopes: tuple[str, ...]

    def is_fresh(self, *, refresh_margin_seconds: int) -> bool:
        """Return whether the token is usable beyond the refresh margin."""
        refresh_at = datetime.now(UTC) + timedelta(seconds=refresh_margin_seconds)
        return self.expires_at > refresh_at


class RuntimeTokenCache:
    """Thread-safe runtime token cache keyed by server and target."""

    def __init__(
        self,
        *,
        max_entries: int = _DEFAULT_MAX_CACHE_ENTRIES,
        jwt_unavailable_ttl_seconds: int = _DEFAULT_JWT_UNAVAILABLE_TTL_SECONDS,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1.")
        if jwt_unavailable_ttl_seconds < 0:
            raise ValueError("jwt_unavailable_ttl_seconds must be >= 0.")
        self._max_entries = max_entries
        self._jwt_unavailable_ttl_seconds = jwt_unavailable_ttl_seconds
        self._tokens: dict[_TokenKey, RuntimeToken] = {}
        self._jwt_unavailable_until: datetime | None = None
        self._jwt_unavailable_servers: dict[str, datetime] = {}
        self._jwt_unavailable_targets: dict[_TokenKey, datetime] = {}
        self._exchange_locks: dict[_LockKey, asyncio.Lock] = {}
        self._lock = threading.Lock()

    def get(
        self,
        server_url: str,
        target_type: str,
        target_id: str,
        *,
        cache_identity: str = "",
        refresh_margin_seconds: int,
    ) -> RuntimeToken | None:
        """Return a fresh cached token for the target, if present."""
        key = (server_url, cache_identity, target_type, target_id)
        with self._lock:
            token = self._tokens.get(key)
            if token is None:
                return None
            if token.is_fresh(refresh_margin_seconds=refresh_margin_seconds):
                return token
            self._tokens.pop(key, None)
            return None

    def set(self, token: RuntimeToken, *, cache_identity: str = "") -> None:
        """Store a token and clear any fallback marker for its target."""
        key = (token.server_url, cache_identity, token.target_type, token.target_id)
        with self._lock:
            if key not in self._tokens and len(self._tokens) >= self._max_entries:
                oldest_key = next(iter(self._tokens))
                self._tokens.pop(oldest_key, None)
                self._jwt_unavailable_targets.pop(oldest_key, None)
            self._tokens[key] = token
            self._jwt_unavailable_servers.pop(token.server_url, None)
            self._jwt_unavailable_targets.pop(key, None)

    def remove(
        self,
        server_url: str,
        target_type: str,
        target_id: str,
        *,
        cache_identity: str = "",
    ) -> None:
        """Drop the cached token for one target."""
        with self._lock:
            self._tokens.pop((server_url, cache_identity, target_type, target_id), None)

    def mark_jwt_unavailable(
        self,
        *,
        server_url: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        cache_identity: str = "",
        globally: bool = False,
        ttl_seconds: int | None = None,
    ) -> None:
        """Record that JWT runtime auth should not be attempted."""
        ttl = self._jwt_unavailable_ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl < 0:
            raise ValueError("ttl_seconds must be >= 0.")
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        with self._lock:
            self._prune_expired_unavailable_markers_locked()
            if globally:
                if server_url is None:
                    self._jwt_unavailable_until = expires_at
                    self._tokens.clear()
                    self._jwt_unavailable_servers.clear()
                    self._jwt_unavailable_targets.clear()
                    return

                if (
                    server_url not in self._jwt_unavailable_servers
                    and len(self._jwt_unavailable_servers) >= self._max_entries
                ):
                    self._jwt_unavailable_servers.pop(next(iter(self._jwt_unavailable_servers)))
                self._jwt_unavailable_servers[server_url] = expires_at
                self._drop_server_entries_locked(server_url)
                return
            if server_url is not None and target_type is not None and target_id is not None:
                key = (server_url, cache_identity, target_type, target_id)
                if (
                    key not in self._jwt_unavailable_targets
                    and len(self._jwt_unavailable_targets) >= self._max_entries
                ):
                    self._jwt_unavailable_targets.pop(next(iter(self._jwt_unavailable_targets)))
                self._jwt_unavailable_targets[key] = expires_at
                self._tokens.pop(key, None)

    def is_jwt_unavailable(
        self,
        server_url: str,
        target_type: str,
        target_id: str,
        *,
        cache_identity: str = "",
    ) -> bool:
        """Return whether JWT exchange is known unavailable for the target."""
        key = (server_url, cache_identity, target_type, target_id)
        with self._lock:
            self._prune_expired_unavailable_markers_locked()
            if self._jwt_unavailable_until is not None:
                return True
            if server_url in self._jwt_unavailable_servers:
                return True
            expires_at = self._jwt_unavailable_targets.get(key)
            return expires_at is not None

    def clear(self) -> None:
        """Clear every cached token and fallback marker."""
        with self._lock:
            self._tokens.clear()
            self._jwt_unavailable_until = None
            self._jwt_unavailable_servers.clear()
            self._jwt_unavailable_targets.clear()

    def exchange_lock(
        self,
        server_url: str,
        target_type: str,
        target_id: str,
        *,
        cache_identity: str = "",
    ) -> asyncio.Lock:
        """Return the async exchange lock for one server and target."""
        key = (server_url, cache_identity, target_type, target_id, asyncio.get_running_loop())
        with self._lock:
            lock = self._exchange_locks.get(key)
            if lock is None:
                if len(self._exchange_locks) >= self._max_entries:
                    self._evict_idle_exchange_lock_locked()
                lock = asyncio.Lock()
                self._exchange_locks[key] = lock
            else:
                # Preserve insertion order as a simple LRU for idle-lock eviction.
                self._exchange_locks.pop(key)
                self._exchange_locks[key] = lock
            return lock

    def _drop_server_entries_locked(self, server_url: str) -> None:
        for key in list(self._tokens):
            if key[0] == server_url:
                self._tokens.pop(key, None)
        for key in list(self._jwt_unavailable_targets):
            if key[0] == server_url:
                self._jwt_unavailable_targets.pop(key, None)

    def _prune_expired_unavailable_markers_locked(self) -> None:
        now = datetime.now(UTC)
        if self._jwt_unavailable_until is not None and self._jwt_unavailable_until <= now:
            self._jwt_unavailable_until = None
        for server_url, expires_at in list(self._jwt_unavailable_servers.items()):
            if expires_at <= now:
                self._jwt_unavailable_servers.pop(server_url, None)
        for key, expires_at in list(self._jwt_unavailable_targets.items()):
            if expires_at <= now:
                self._jwt_unavailable_targets.pop(key, None)

    def _evict_idle_exchange_lock_locked(self) -> None:
        for key, lock in list(self._exchange_locks.items()):
            if not lock.locked():
                self._exchange_locks.pop(key, None)
                return


def normalize_runtime_auth_mode(raw: str | None) -> RuntimeAuthMode:
    """Normalize configured SDK runtime auth mode."""
    if raw is None or not raw.strip():
        return "auto"

    mode = raw.strip().lower()
    if mode in {"none", "no_auth"}:
        return "none"
    if mode in {"api_key", "header"}:
        return "api_key"
    if mode == "auto":
        return "auto"
    if mode == "jwt":
        return "jwt"
    raise ValueError("runtime_auth_mode must be one of 'auto', 'none', 'api_key', or 'jwt'.")


def parse_runtime_token_exchange_response(
    payload: Mapping[str, object],
    *,
    server_url: str,
) -> RuntimeToken:
    """Parse the runtime token exchange response payload."""
    token = payload.get("token")
    expires_at = payload.get("expires_at")
    target_type = payload.get("target_type")
    target_id = payload.get("target_id")
    scopes = payload.get("scopes")

    if not isinstance(token, str) or not token:
        raise RuntimeError("Runtime token exchange response did not include a token.")
    if not isinstance(expires_at, str) or not expires_at:
        raise RuntimeError("Runtime token exchange response did not include expires_at.")
    if not isinstance(target_type, str) or not target_type:
        raise RuntimeError("Runtime token exchange response did not include target_type.")
    if not isinstance(target_id, str) or not target_id:
        raise RuntimeError("Runtime token exchange response did not include target_id.")
    if not isinstance(scopes, Sequence) or isinstance(scopes, str):
        raise RuntimeError("Runtime token exchange response did not include scopes.")

    parsed_scopes: list[str] = []
    for scope in scopes:
        if not isinstance(scope, str):
            raise RuntimeError("Runtime token exchange response included a non-string scope.")
        parsed_scopes.append(scope)

    normalized_expires_at = expires_at
    if normalized_expires_at.endswith("Z"):
        normalized_expires_at = f"{normalized_expires_at[:-1]}+00:00"
    parsed_expires_at = datetime.fromisoformat(normalized_expires_at)
    if parsed_expires_at.tzinfo is None:
        parsed_expires_at = parsed_expires_at.replace(tzinfo=UTC)

    return RuntimeToken(
        token=token,
        expires_at=parsed_expires_at.astimezone(UTC),
        server_url=server_url,
        target_type=target_type,
        target_id=target_id,
        scopes=tuple(parsed_scopes),
    )
