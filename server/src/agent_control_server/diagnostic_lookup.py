"""Opt-in lookup-cache experiment for explicitly frozen, expiring LT fixtures.

Not production invalidation: the controller must prohibit all fixture writes until
restoration. Authorization always precedes this module. No ORM object is retained.
"""

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from agent_control_models import ControlDefinitionRuntime
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .diagnostic_metrics import _EVENTS, _SNAPSHOT_AGE, measured
from .services.controls import RuntimeControl


class FrozenFixture(BaseModel):
    """Exact frozen fixture and expected digest of its ordered runtime definitions."""

    namespace: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    generation: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    controls_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DiagnosticSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_CONTROL_LOOKUP_DIAGNOSTIC_", extra="ignore")
    enabled: bool = False
    fixtures: list[FrozenFixture] = Field(default_factory=list, max_length=32)
    expires_at: datetime | None = None
    ttl_seconds: float = Field(default=300, gt=0, le=600)
    redis_timeout_seconds: float = Field(default=0.05, gt=0, le=0.25)
    max_value_bytes: int = Field(default=1048576, ge=1024, le=1048576)

    def fixture(
        self,
        namespace: str,
        agent: str,
        target_type: str | None,
        target_id: str | None,
        generation: str | None = None,
    ) -> FrozenFixture | None:
        expiry = self.expires_at
        if (
            not self.enabled
            or expiry is None
            or expiry.tzinfo is None
            or expiry <= datetime.now(UTC)
        ):
            return None
        return next(
            (
                f
                for f in self.fixtures
                if (f.namespace, f.agent, f.target_type, f.target_id)
                == (namespace, agent, target_type, target_id)
                and (generation is None or f.generation == generation)
            ),
            None,
        )


settings = DiagnosticSettings()


def definition_digest(controls: list[RuntimeControl]) -> str:
    """Stable ordered digest; output is a hash, never persisted control contents."""
    data = [(c.id, c.name, c.control.model_dump(mode="json")) for c in controls]
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    namespace: str
    agent: str
    target_type: str
    target_id: str
    generation: str
    digest: str


class RedisClient(Protocol):
    """Small async transport seam; Orbit supplies RedisConfig's async client."""

    async def get(self, name: str) -> bytes | str | None: ...
    async def set(self, name: str, value: str, *, ex: int) -> object: ...
    async def aclose(self) -> None: ...


class CachedControl(BaseModel):
    id: int
    name: str
    control: ControlDefinitionRuntime


class CachedDefinitions(BaseModel):
    format_version: Literal[1] = 1
    controls: list[CachedControl]
    loaded_at_unix: float = Field(gt=0, allow_inf_nan=False)


def redis_key(key: CacheKey) -> str:
    """Hash identifiers so keys expose no fixture identity and remain bounded."""
    identity = json.dumps(
        [key.namespace, key.agent, key.target_type, key.target_id, key.generation, key.digest],
        separators=(",", ":"),
    )
    return "galileo:ac:lt-lookup:v1:" + hashlib.sha256(identity.encode()).hexdigest()


class LookupCache:
    """Redis shared cache restricted to a bounded, explicitly frozen fixture set.

    No local results cache. Every ON request measures a Redis GET. Parse cached JSON
    into independent runtime models. Failed, timed-out or corrupt Redis data falls
    back to the authorized DB loader, never to stale local definitions. Generation
    changes address a new key and TTL bounds old keys; fixture writes are forbidden
    throughout this diagnostic. This is not production write-event invalidation.
    """

    def __init__(self, factory: Callable[[], RedisClient] | None = None) -> None:
        self._factory = factory
        self._client: RedisClient | None = None
        self._locks = [asyncio.Lock() for _ in range(64)]

    def _redis(self) -> RedisClient:
        if self._client is None:
            if self._factory is None:
                raise RuntimeError("Redis diagnostic client not configured")
            self._client = self._factory()
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def _read(self, key: CacheKey) -> list[RuntimeControl] | None:
        with measured("redis_get"):
            async with asyncio.timeout(settings.redis_timeout_seconds):
                value = await self._redis().get(redis_key(key))
        if value is None:
            return None
        if len(value) > settings.max_value_bytes:
            raise ValueError("Redis diagnostic value exceeds bound")
        with measured("cache_decode"):
            parsed = CachedDefinitions.model_validate_json(value)
            controls = [RuntimeControl(c.id, c.name, c.control) for c in parsed.controls]
            if definition_digest(controls) != key.digest:
                raise ValueError("Redis diagnostic digest mismatch")
        age = time.time() - parsed.loaded_at_unix
        if age < -1 or age > 600:
            raise ValueError("Redis diagnostic snapshot timestamp outside bound")
        _SNAPSHOT_AGE.labels("on").observe(max(0, age))
        return controls

    async def load(
        self,
        key: CacheKey,
        loader: Callable[[], Awaitable[list[RuntimeControl]]],
        *,
        ttl: float,
    ) -> list[RuntimeControl]:
        # Hits must not queue behind a process-local lock. Only coalesce misses.
        try:
            controls = await self._read(key)
        except Exception:
            _EVENTS.labels("on", "redis_read_fallback").inc()
            return await loader()
        if controls is not None:
            _EVENTS.labels("on", "hit").inc()
            return controls
        lock = self._locks[hash(key) % len(self._locks)]
        with measured("miss_wait"):
            await lock.acquire()
        try:
            try:
                controls = await self._read(key)
            except Exception:
                _EVENTS.labels("on", "redis_read_fallback").inc()
                return await loader()
            if controls is not None:
                _EVENTS.labels("on", "hit").inc()
                return controls
            _EVENTS.labels("on", "miss").inc()
            controls = await loader()
            if definition_digest(controls) != key.digest:
                _EVENTS.labels("on", "fixture_mismatch").inc()
                raise ValueError("Frozen diagnostic fixture digest mismatch")
            with measured("cache_encode"):
                value = CachedDefinitions(
                    loaded_at_unix=time.time(),
                    controls=[
                        CachedControl(id=c.id, name=c.name, control=c.control) for c in controls
                    ],
                ).model_dump_json()
            if len(value.encode()) > settings.max_value_bytes:
                _EVENTS.labels("on", "oversize_fallback").inc()
                return controls
            try:
                with measured("redis_set"):
                    async with asyncio.timeout(settings.redis_timeout_seconds):
                        await self._redis().set(redis_key(key), value, ex=max(1, int(ttl)))
            except Exception:
                _EVENTS.labels("on", "redis_write_fallback").inc()
            return controls
        finally:
            lock.release()


cache = LookupCache()


def configure_redis_factory(factory: Callable[[], RedisClient]) -> None:
    """Wire the deployed service's existing RedisConfig without importing Orbit."""
    global cache
    cache = LookupCache(factory)
