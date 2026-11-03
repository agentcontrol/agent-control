"""Provider-neutral cache for serialized effective-control snapshots."""

from __future__ import annotations

import base64
import builtins
import json
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol, cast

from agent_control_models import ControlDefinitionRuntime
from prometheus_client import Counter, Histogram
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Agent, ControlBinding, agent_controls, agent_policies, policy_controls
from .services.controls import RuntimeControl

_logger = logging.getLogger(__name__)
_CACHE_HIT = Counter("agent_control_control_cache_hit_total", "Effective control cache hits")
_CACHE_MISS = Counter("agent_control_control_cache_miss_total", "Effective control cache misses")
_CACHE_FAILURE = Counter("agent_control_control_cache_redis_failure_total", "Redis cache failures")
_CACHE_INVALIDATION = Counter(
    "agent_control_control_cache_invalidation_total", "Effective control cache invalidations"
)
_CACHE_INVALIDATION_FAILURE = Counter(
    "agent_control_control_cache_invalidation_failure_total",
    "Effective control cache invalidation failures",
)
_SNAPSHOT_LOAD = Histogram(
    "agent_control_control_cache_snapshot_load_seconds", "Effective control snapshot load time"
)
_SNAPSHOT_SIZE = Histogram(
    "agent_control_control_cache_snapshot_size_bytes", "Serialized snapshot size"
)


class ControlCache(Protocol):
    """Storage interface for effective-control snapshots."""

    async def get(
        self, namespace: str, agent: str, target_type: str | None, target_id: str | None
    ) -> list[RuntimeControl] | None: ...

    async def set(
        self,
        namespace: str,
        agent: str,
        target_type: str | None,
        target_id: str | None,
        controls: Sequence[RuntimeControl],
        generation: str | None,
    ) -> None: ...

    async def get_generation(self, namespace: str, agent: str) -> str | None: ...

    async def invalidate_agent(self, namespace: str, agent: str) -> None: ...


class NoOpControlCache:
    """Cache implementation that always uses PostgreSQL."""

    async def get(
        self, namespace: str, agent: str, target_type: str | None, target_id: str | None
    ) -> None:
        del namespace, agent, target_type, target_id
        _CACHE_MISS.inc()
        return None

    async def set(
        self,
        namespace: str,
        agent: str,
        target_type: str | None,
        target_id: str | None,
        controls: Sequence[RuntimeControl],
        generation: str | None = None,
    ) -> None:
        del namespace, agent, target_type, target_id, controls, generation

    async def get_generation(self, namespace: str, agent: str) -> None:
        del namespace, agent
        return None

    async def invalidate_agent(self, namespace: str, agent: str) -> None:
        del namespace, agent


class RedisCommands(Protocol):
    """Minimal asynchronous Redis command surface used by this cache."""

    async def get(self, name: str) -> str | bytes | None: ...

    async def set(self, name: str, value: str, ex: int) -> object: ...

    async def sadd(self, name: str, *values: str) -> object: ...

    async def expire(self, name: str, seconds: int) -> object: ...

    async def smembers(self, name: str) -> builtins.set[str | bytes]: ...

    async def delete(self, *names: str) -> object: ...

    async def eval(
        self, script: str, numkeys: int, *keys_and_args: str | int
    ) -> str | bytes | int | None: ...

    async def aclose(self) -> None: ...


def build_cache_key(
    namespace: str, agent: str, target_type: str | None, target_id: str | None
) -> str:
    """Build the versioned snapshot key, preserving all effective-control scope dimensions."""
    return (
        f"agent-control:effective-controls:v1:{{{_agent_hash_tag(namespace, agent)}}}:"
        f"{_encode_key_component(target_type)}:{_encode_key_component(target_id)}"
    )


def _encode_key_component(value: str | None) -> str:
    if value is None:
        return "!"
    return "=" + base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _agent_index_key(namespace: str, agent: str) -> str:
    return f"agent-control:effective-controls:index:v1:{{{_agent_hash_tag(namespace, agent)}}}"


def _agent_generation_key(namespace: str, agent: str) -> str:
    return f"agent-control:effective-controls:generation:v1:{{{_agent_hash_tag(namespace, agent)}}}"


def _agent_hash_tag(namespace: str, agent: str) -> str:
    return f"{_encode_key_component(namespace)}:{_encode_key_component(agent)}"


def _stale_key(snapshot_key: str) -> str:
    suffix = snapshot_key.removeprefix("agent-control:effective-controls:v1:")
    return f"agent-control:effective-controls:stale:v1:{suffix}"


class RedisControlCache:
    """Redis implementation storing JSON snapshots and a per-agent key index."""

    def __init__(self, client: RedisCommands, ttl_seconds: int = 60) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def get_generation(self, namespace: str, agent: str) -> str | None:
        """Read the version used to guard a subsequent snapshot write."""
        try:
            raw = await self._client.get(_agent_generation_key(namespace, agent))
            return raw.decode() if isinstance(raw, bytes) else raw or "0"
        except Exception:
            _CACHE_FAILURE.inc()
            _logger.warning("Effective-control cache generation read failed", exc_info=True)
            return None

    async def get(
        self, namespace: str, agent: str, target_type: str | None, target_id: str | None
    ) -> list[RuntimeControl] | None:
        try:
            key = build_cache_key(namespace, agent, target_type, target_id)
            script = """
            if redis.call('EXISTS', KEYS[1]) == 1 then return nil end
            return redis.call('GET', KEYS[2])
            """
            raw = await self._client.eval(script, 2, _stale_key(key), key)
            if raw is None:
                _CACHE_MISS.inc()
                return None
            if not isinstance(raw, (str, bytes)):
                raise TypeError("Redis returned a non-string effective-control snapshot")
            payload = json.loads(raw)
            if payload.get("schema_version") != 1 or not isinstance(payload.get("controls"), list):
                _CACHE_MISS.inc()
                return None
            controls = [
                RuntimeControl(
                    id=item["id"],
                    name=item["name"],
                    control=ControlDefinitionRuntime.model_validate(item["control"]),
                )
                for item in payload["controls"]
            ]
            _CACHE_HIT.inc()
            return controls
        except Exception:  # Redis and corrupt cache data must not block evaluation.
            _CACHE_FAILURE.inc()
            _CACHE_MISS.inc()
            _logger.warning(
                "Effective-control cache read failed; loading from PostgreSQL", exc_info=True
            )
            return None

    async def set(
        self,
        namespace: str,
        agent: str,
        target_type: str | None,
        target_id: str | None,
        controls: Sequence[RuntimeControl],
        generation: str | None = None,
    ) -> None:
        key = build_cache_key(namespace, agent, target_type, target_id)
        payload = {
            "schema_version": 1,
            "controls": [
                {"id": item.id, "name": item.name, "control": item.control.model_dump(mode="json")}
                for item in controls
            ],
            "loaded_at": datetime.now(UTC).isoformat(),
        }
        serialized = json.dumps(payload, separators=(",", ":"))
        _SNAPSHOT_SIZE.observe(len(serialized.encode("utf-8")))
        try:
            if generation is None:
                return
            index_key = _agent_index_key(namespace, agent)
            generation_key = _agent_generation_key(namespace, agent)
            stale_key = _stale_key(key)
            script = """
            local current = redis.call('GET', KEYS[1]) or '0'
            if current ~= ARGV[1] then return 0 end
            redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
            redis.call('SADD', KEYS[3], KEYS[2])
            redis.call('EXPIRE', KEYS[3], ARGV[3] * 2)
            redis.call('DEL', KEYS[4])
            return 1
            """
            await self._client.eval(
                script,
                4,
                generation_key,
                key,
                index_key,
                stale_key,
                generation,
                serialized,
                self._ttl_seconds,
            )
        except Exception:
            _CACHE_FAILURE.inc()
            _logger.warning("Effective-control cache write failed", exc_info=True)

    async def invalidate_agent(self, namespace: str, agent: str) -> None:
        index_key = _agent_index_key(namespace, agent)
        generation_key = _agent_generation_key(namespace, agent)
        try:
            script = """
            redis.call('INCR', KEYS[1])
            local keys = redis.call('SMEMBERS', KEYS[2])
            local prefix = 'agent-control:effective-controls:v1:'
            for _, key in ipairs(keys) do
                local suffix = string.sub(key, string.len(prefix) + 1)
                local stale = 'agent-control:effective-controls:stale:v1:' .. suffix
                redis.call('SET', stale, '1', 'EX', ARGV[1])
            end
            return #keys
            """
            await self._client.eval(
                script, 2, generation_key, index_key, self._ttl_seconds * 2
            )
            _CACHE_INVALIDATION.inc()
        except Exception:
            _CACHE_FAILURE.inc()
            _logger.warning("Effective-control cache invalidation failed", exc_info=True)

    async def close(self) -> None:
        """Close the shared Redis connection pool."""
        try:
            await self._client.aclose()
        except Exception:
            _CACHE_FAILURE.inc()
            _logger.warning("Effective-control cache shutdown failed", exc_info=True)


def get_control_cache() -> ControlCache:
    """Construct the configured cache; PostgreSQL-only remains the default."""
    return _configured_control_cache()


@lru_cache(maxsize=1)
def _configured_control_cache() -> ControlCache:
    if settings.control_cache_backend.lower() != "redis" or not settings.redis_url:
        return NoOpControlCache()
    try:
        client = _create_redis_client(settings.redis_url, settings.redis_mode)
        return RedisControlCache(client, settings.control_cache_ttl_seconds)
    except Exception:
        _CACHE_FAILURE.inc()
        _logger.warning("Redis cache initialization failed; using PostgreSQL", exc_info=True)
        return NoOpControlCache()


def _create_redis_client(redis_url: str, redis_mode: str) -> RedisCommands:
    """Build a redis-py client using a standard redis/rediss URL."""
    from redis.asyncio import Redis  # type: ignore[import-not-found]

    options = {
        "decode_responses": True,
        "socket_connect_timeout": 0.5,
        "socket_timeout": 0.5,
    }
    if redis_mode == "cluster":
        from redis.asyncio.cluster import RedisCluster  # type: ignore[import-not-found]

        client_factory = cast(Any, RedisCluster)
    else:
        client_factory = cast(Any, Redis)
    return cast(RedisCommands, client_factory.from_url(redis_url, **options))


def observe_snapshot_load(started_at: float) -> None:
    """Record database snapshot load duration."""
    _SNAPSHOT_LOAD.observe(time.perf_counter() - started_at)


async def close_control_cache() -> None:
    """Close the shared Redis client during application shutdown."""
    cache = get_control_cache()
    if isinstance(cache, RedisControlCache):
        await cache.close()


async def invalidate_namespace_agents(db: AsyncSession, namespace: str) -> None:
    """Invalidate every agent scope in a namespace after a namespace-wide mutation."""
    cache = get_control_cache()
    if isinstance(cache, NoOpControlCache):
        return
    try:
        result = await db.execute(select(Agent.name).where(Agent.namespace_key == namespace))
        for (agent_name,) in result.all():
            await cache.invalidate_agent(namespace, agent_name)
    except Exception:
        _CACHE_INVALIDATION_FAILURE.inc()
        _logger.warning(
            "Unable to discover namespace cache scopes after commit; relying on TTL",
            exc_info=True,
        )


async def invalidate_agent_scope(namespace: str, agent: str) -> None:
    """Invalidate all target variants for one agent scope."""
    await get_control_cache().invalidate_agent(namespace, agent)


async def invalidate_control_agents(
    db: AsyncSession, namespace: str, control_id: int
) -> None:
    """Invalidate agents related to a changed control through direct or policy bindings."""
    cache = get_control_cache()
    if isinstance(cache, NoOpControlCache):
        return
    direct_agents = select(agent_controls.c.agent_name).where(
        agent_controls.c.namespace_key == namespace,
        agent_controls.c.control_id == control_id,
    )
    policy_agents = (
        select(agent_policies.c.agent_name)
        .join(
            policy_controls,
            (policy_controls.c.namespace_key == agent_policies.c.namespace_key)
            & (policy_controls.c.policy_id == agent_policies.c.policy_id),
        )
        .where(
            agent_policies.c.namespace_key == namespace,
            policy_controls.c.control_id == control_id,
        )
    )
    try:
        result = await db.execute(direct_agents.union(policy_agents))
        for (agent_name,) in result.all():
            await cache.invalidate_agent(namespace, agent_name)

        target_binding = await db.execute(
            select(ControlBinding.id).where(
                ControlBinding.namespace_key == namespace,
                ControlBinding.control_id == control_id,
            ).limit(1)
        )
        if target_binding.first() is not None:
            await invalidate_namespace_agents(db, namespace)
    except Exception:
        _CACHE_INVALIDATION_FAILURE.inc()
        _logger.warning(
            "Unable to discover control cache scopes after commit; relying on TTL",
            exc_info=True,
        )


async def get_control_cache_scopes(
    db: AsyncSession, namespace: str, control_id: int
) -> tuple[list[str], bool]:
    """Capture related agent scopes before a mutation removes association rows."""
    if isinstance(get_control_cache(), NoOpControlCache):
        return [], False
    direct_agents = select(agent_controls.c.agent_name).where(
        agent_controls.c.namespace_key == namespace,
        agent_controls.c.control_id == control_id,
    )
    policy_agents = (
        select(agent_policies.c.agent_name)
        .join(
            policy_controls,
            (policy_controls.c.namespace_key == agent_policies.c.namespace_key)
            & (policy_controls.c.policy_id == agent_policies.c.policy_id),
        )
        .where(
            agent_policies.c.namespace_key == namespace,
            policy_controls.c.control_id == control_id,
        )
    )
    agents_result = await db.execute(direct_agents.union(policy_agents))
    target_result = await db.execute(
        select(ControlBinding.id).where(
            ControlBinding.namespace_key == namespace,
            ControlBinding.control_id == control_id,
        ).limit(1)
    )
    return [name for (name,) in agents_result.all()], target_result.first() is not None


async def invalidate_control_cache_scopes(
    db: AsyncSession, namespace: str, agents: Sequence[str], has_target_bindings: bool
) -> None:
    """Invalidate captured control scopes after commit."""
    cache = get_control_cache()
    for agent_name in agents:
        await cache.invalidate_agent(namespace, agent_name)
    if has_target_bindings:
        await invalidate_namespace_agents(db, namespace)


async def invalidate_policy_agents(db: AsyncSession, namespace: str, policy_id: int) -> None:
    """Invalidate agents assigned to a changed policy."""
    cache = get_control_cache()
    if isinstance(cache, NoOpControlCache):
        return
    try:
        result = await db.execute(
            select(agent_policies.c.agent_name).where(
                agent_policies.c.namespace_key == namespace,
                agent_policies.c.policy_id == policy_id,
            )
        )
        for (agent_name,) in result.all():
            await cache.invalidate_agent(namespace, agent_name)
    except Exception:
        _CACHE_INVALIDATION_FAILURE.inc()
        _logger.warning(
            "Unable to discover policy cache scopes after commit; relying on TTL",
            exc_info=True,
        )
