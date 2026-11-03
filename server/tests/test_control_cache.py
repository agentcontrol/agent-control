"""Focused unit tests for the effective-control cache implementations."""

from __future__ import annotations

import asyncio
import sys
import time
import types

import pytest
from agent_control_models import ControlDefinitionRuntime
from agent_control_server import control_cache as cache_module
from agent_control_server.config import Settings
from agent_control_server.control_cache import (
    NoOpControlCache,
    RedisControlCache,
    _agent_generation_key,
    _agent_index_key,
    _stale_key,
    build_cache_key,
    get_control_cache_scopes,
    invalidate_control_agents,
    invalidate_control_cache_scopes,
    invalidate_namespace_agents,
    invalidate_policy_agents,
)
from agent_control_server.services.controls import RuntimeControl


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, tuple[str, float | None]] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, name: str) -> str | None:
        value = self.values.get(name)
        if value is None:
            return None
        payload, expires_at = value
        if expires_at is not None and expires_at <= time.monotonic():
            self.values.pop(name, None)
            return None
        return payload

    async def set(self, name: str, value: str, ex: int) -> None:
        self.values[name] = (value, time.monotonic() + ex)

    async def sadd(self, name: str, *values: str) -> None:
        self.sets.setdefault(name, set()).update(values)

    async def expire(self, name: str, seconds: int) -> None:
        del name, seconds

    async def smembers(self, name: str) -> set[str]:
        return self.sets.get(name, set()).copy()

    async def delete(self, *names: str) -> None:
        for name in names:
            self.values.pop(name, None)
            self.sets.pop(name, None)

    async def eval(
        self, script: str, numkeys: int, *keys_and_args: str | int
    ) -> str | int | None:
        keys = [str(value) for value in keys_and_args[:numkeys]]
        args = keys_and_args[numkeys:]
        if "INCR" in script:
            generation_key, index_key = keys
            current = self.values.get(generation_key, ("0", None))[0]
            self.values[generation_key] = (str(int(current) + 1), None)
            indexed = self.sets.get(index_key, set())
            ttl = int(args[0])
            for key in indexed:
                suffix = key.removeprefix("agent-control:effective-controls:v1:")
                stale_key = f"agent-control:effective-controls:stale:v1:{suffix}"
                await self.set(stale_key, "1", ttl)
            return len(indexed)
        if "EXISTS" in script:
            stale_key, snapshot_key = keys
            if await self.get(stale_key) is not None:
                return None
            return await self.get(snapshot_key)
        generation_key, snapshot_key, index_key, stale_key = keys
        expected_generation, payload, ttl = args
        current = self.values.get(generation_key, ("0", None))[0]
        if current != str(expected_generation):
            return 0
        await self.set(snapshot_key, str(payload), int(ttl))
        await self.sadd(index_key, snapshot_key)
        await self.delete(stale_key)
        return 1

    async def aclose(self) -> None:
        return None

    def expire_now(self, name: str) -> None:
        payload, _ = self.values[name]
        self.values[name] = (payload, time.monotonic() - 1)


class BrokenRedis(FakeRedis):
    async def get(self, name: str) -> str | None:
        del name
        raise ConnectionError("redis unavailable")


class FailingRedisCommands(FakeRedis):
    async def eval(
        self, script: str, numkeys: int, *keys_and_args: str | int
    ) -> str | int | None:
        del script, numkeys, keys_and_args
        raise ConnectionError("redis command failed")

    async def aclose(self) -> None:
        raise ConnectionError("redis close failed")


class NonStringSnapshotRedis(FakeRedis):
    async def eval(
        self, script: str, numkeys: int, *keys_and_args: str | int
    ) -> str | int | None:
        del script, numkeys, keys_and_args
        return 1


class FakeResult:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[str]]:
        return self.rows

    def first(self) -> tuple[str] | None:
        return self.rows[0] if self.rows else None


class FakeDatabase:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = iter(results)

    async def execute(self, statement: object) -> FakeResult:
        del statement
        return next(self.results)


class FailingDatabase:
    async def execute(self, statement: object) -> FakeResult:
        del statement
        raise RuntimeError("database scope lookup failed")


class MetricSpy:
    def __init__(self) -> None:
        self.calls = 0

    def inc(self) -> None:
        self.calls += 1


def test_postgres_only_defaults_to_no_op_cache() -> None:
    settings = Settings(_env_file=None)
    assert settings.control_cache_backend == "postgres"
    assert settings.redis_url is None
    assert settings.redis_mode == "standalone"
    assert asyncio.run(NoOpControlCache().get("ns", "agent", None, None)) is None


def test_configured_cache_uses_redis_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeRedis()
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(cache_module.settings, "control_cache_backend", "redis")
    monkeypatch.setattr(cache_module.settings, "redis_url", "redis://cache.example:6379")
    monkeypatch.setattr(cache_module.settings, "redis_mode", "cluster")
    monkeypatch.setattr(cache_module.settings, "control_cache_ttl_seconds", 17)

    def create_client(url: str, mode: str) -> FakeRedis:
        calls.append((url, mode))
        return client

    monkeypatch.setattr(cache_module, "_create_redis_client", create_client)
    cache_module._configured_control_cache.cache_clear()
    try:
        configured = cache_module.get_control_cache()
    finally:
        cache_module._configured_control_cache.cache_clear()

    assert isinstance(configured, RedisControlCache)
    assert configured._ttl_seconds == 17
    assert calls == [("redis://cache.example:6379", "cluster")]


def test_configured_cache_falls_back_when_redis_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache_module.settings, "control_cache_backend", "redis")
    monkeypatch.setattr(cache_module.settings, "redis_url", "redis://cache.example:6379")

    def fail_to_create_client(url: str, mode: str) -> FakeRedis:
        del url, mode
        raise ImportError("redis package is unavailable")

    monkeypatch.setattr(cache_module, "_create_redis_client", fail_to_create_client)
    cache_module._configured_control_cache.cache_clear()
    try:
        configured = cache_module.get_control_cache()
    finally:
        cache_module._configured_control_cache.cache_clear()

    assert isinstance(configured, NoOpControlCache)


def test_cache_key_includes_all_scope_dimensions() -> None:
    assert (
        build_cache_key("ns", "agent", None, None)
        == "agent-control:effective-controls:v1:{=bnM:=YWdlbnQ}:!:!"
    )
    base = build_cache_key("ns", "agent:other", "account", "42")
    assert base != build_cache_key("other", "agent", "account", "42")
    assert base != build_cache_key("ns", "agent", "other:account", "42")
    assert base != build_cache_key("ns", "agent:other", "workspace", "42")
    assert base != build_cache_key("ns", "agent:other", "account", "43")
    assert base != build_cache_key("ns:agent", "other", "account", "42")


def test_redis_script_keys_share_hash_tag_and_target_scope() -> None:
    key = build_cache_key("ns", "agent", "log_stream", "logstream-1")
    keys = [
        key,
        _agent_index_key("ns", "agent"),
        _agent_generation_key("ns", "agent"),
        _stale_key(key),
    ]
    hash_tags = [item[item.index("{") + 1 : item.index("}")] for item in keys]
    assert len(set(hash_tags)) == 1
    assert key != build_cache_key("ns", "agent", "log_stream", "logstream-2")
    assert key != build_cache_key("ns", "agent", "account", "logstream-1")


@pytest.mark.parametrize(
    "redis_mode,expected_client", [("standalone", "redis"), ("cluster", "cluster")]
)
def test_redis_client_factory_uses_selected_topology(
    monkeypatch: pytest.MonkeyPatch, redis_mode: str, expected_client: str
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class StandaloneRedis:
        @classmethod
        def from_url(cls, url: str, **options: object) -> object:
            calls.append(("redis", url, options))
            return cls()

    class ClusterRedis:
        @classmethod
        def from_url(cls, url: str, **options: object) -> object:
            calls.append(("cluster", url, options))
            return cls()

    redis_package = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")
    redis_asyncio.Redis = StandaloneRedis  # type: ignore[attr-defined]
    cluster_module = types.ModuleType("redis.asyncio.cluster")
    cluster_module.RedisCluster = ClusterRedis  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "redis", redis_package)
    monkeypatch.setitem(sys.modules, "redis.asyncio", redis_asyncio)
    monkeypatch.setitem(sys.modules, "redis.asyncio.cluster", cluster_module)

    client = cache_module._create_redis_client("rediss://cache.example:6380", redis_mode)

    assert isinstance(client, StandaloneRedis if expected_client == "redis" else ClusterRedis)
    assert calls == [
        (
            expected_client,
            "rediss://cache.example:6380",
            {
                "decode_responses": True,
                "socket_connect_timeout": 0.5,
                "socket_timeout": 0.5,
            },
        )
    ]


def test_redis_miss_hit_and_ttl_expiry() -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=1)
        assert await cache.get("ns", "agent", None, None) is None
        generation = await cache.get_generation("ns", "agent")
        await cache.set("ns", "agent", None, None, [], generation)
        assert await cache.get("ns", "agent", None, None) == []
        client.expire_now(build_cache_key("ns", "agent", None, None))
        assert await cache.get("ns", "agent", None, None) is None

    asyncio.run(run())


def test_redis_failure_falls_back_to_database() -> None:
    async def run() -> None:
        cache = RedisControlCache(BrokenRedis(), ttl_seconds=10)
        assert await cache.get("ns", "agent", None, None) is None
        assert await cache.get_generation("ns", "agent") is None
        await cache.set("ns", "agent", None, None, [])
        await cache.invalidate_agent("ns", "agent")
        await cache.close()

    asyncio.run(run())


def test_redis_corrupt_snapshot_is_treated_as_a_miss() -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=10)
        key = build_cache_key("ns", "agent", None, None)
        client.values[key] = ('{"schema_version":2,"controls":[]}', None)
        assert await cache.get("ns", "agent", None, None) is None

    asyncio.run(run())


def test_redis_non_string_snapshot_is_treated_as_a_miss() -> None:
    async def run() -> None:
        cache = RedisControlCache(NonStringSnapshotRedis(), ttl_seconds=10)
        assert await cache.get("ns", "agent", None, None) is None

    asyncio.run(run())


def test_redis_write_and_invalidation_failures_are_best_effort() -> None:
    async def run() -> None:
        cache = RedisControlCache(FailingRedisCommands(), ttl_seconds=10)
        await cache.set("ns", "agent", None, None, [], "0")
        await cache.invalidate_agent("ns", "agent")
        await cache.close()

    asyncio.run(run())


def test_invalidation_removes_all_target_snapshots_for_agent() -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        await cache.set("ns", "agent", None, None, [], await cache.get_generation("ns", "agent"))
        await cache.set(
            "ns", "agent", "account", "1", [], await cache.get_generation("ns", "agent")
        )
        await cache.set(
            "ns", "other-agent", None, None, [], await cache.get_generation("ns", "other-agent")
        )
        await cache.invalidate_agent("ns", "agent")
        assert await cache.get("ns", "agent", None, None) is None
        assert await cache.get("ns", "agent", "account", "1") is None
        assert await cache.get("ns", "other-agent", None, None) == []

    asyncio.run(run())


def test_control_mutation_invalidates_relationship_bound_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        await cache.set(
            "ns", "related-agent", None, None, [], await cache.get_generation("ns", "related-agent")
        )
        await cache.set(
            "ns",
            "unrelated-agent",
            None,
            None,
            [],
            await cache.get_generation("ns", "unrelated-agent"),
        )
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        db = FakeDatabase([FakeResult([("related-agent",)]), FakeResult([])])
        await invalidate_control_agents(db, "ns", 7)  # type: ignore[arg-type]
        assert await cache.get("ns", "related-agent", None, None) is None
        assert await cache.get("ns", "unrelated-agent", None, None) == []

    asyncio.run(run())


def test_control_target_binding_invalidates_namespace_after_relationship_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        generation = await cache.get_generation("ns", "agent")
        await cache.set("ns", "agent", "log_stream", "stream-1", [], generation)
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        db = FakeDatabase(
            [FakeResult([]), FakeResult([("binding-id",)]), FakeResult([("agent",)])]
        )

        await invalidate_control_agents(db, "ns", 7)  # type: ignore[arg-type]

        assert await cache.get("ns", "agent", "log_stream", "stream-1") is None

    asyncio.run(run())


def test_control_cache_scopes_capture_and_invalidate_related_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        generation = await cache.get_generation("ns", "related-agent")
        await cache.set("ns", "related-agent", None, None, [], generation)
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        db = FakeDatabase(
            [
                FakeResult([("related-agent",)]),
                FakeResult([("binding-id",)]),
                FakeResult([("related-agent",)]),
            ]
        )

        agents, has_target_bindings = await get_control_cache_scopes(
            db, "ns", 7  # type: ignore[arg-type]
        )
        assert agents == ["related-agent"]
        assert has_target_bindings
        await invalidate_control_cache_scopes(
            db, "ns", agents, has_target_bindings  # type: ignore[arg-type]
        )
        assert await cache.get("ns", "related-agent", None, None) is None

    asyncio.run(run())


def test_policy_mutation_invalidates_assigned_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        assigned_generation = await cache.get_generation("ns", "assigned-agent")
        await cache.set("ns", "assigned-agent", None, None, [], assigned_generation)
        await cache.set(
            "ns", "other-agent", None, None, [], await cache.get_generation("ns", "other-agent")
        )
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        db = FakeDatabase([FakeResult([("assigned-agent",)])])
        await invalidate_policy_agents(db, "ns", 4)  # type: ignore[arg-type]
        assert await cache.get("ns", "assigned-agent", None, None) is None
        assert await cache.get("ns", "other-agent", None, None) == []

    asyncio.run(run())


def test_target_binding_change_invalidates_namespace_agent_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        first_generation = await cache.get_generation("ns", "agent-one")
        second_generation = await cache.get_generation("ns", "agent-two")
        await cache.set("ns", "agent-one", "account", "a", [], first_generation)
        await cache.set("ns", "agent-two", None, None, [], second_generation)
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        db = FakeDatabase([FakeResult([("agent-one",), ("agent-two",)])])
        await invalidate_namespace_agents(db, "ns")  # type: ignore[arg-type]
        assert await cache.get("ns", "agent-one", "account", "a") is None
        assert await cache.get("ns", "agent-two", None, None) is None

    asyncio.run(run())


def test_post_commit_scope_lookup_failure_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        cache = RedisControlCache(FakeRedis(), ttl_seconds=30)
        failure_metric = MetricSpy()
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        monkeypatch.setattr(cache_module, "_CACHE_INVALIDATION_FAILURE", failure_metric)

        await invalidate_namespace_agents(FailingDatabase(), "ns")  # type: ignore[arg-type]

        assert failure_metric.calls == 1

    asyncio.run(run())


def test_control_scope_capture_failure_falls_back_to_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        cache = RedisControlCache(FakeRedis(), ttl_seconds=30)
        failure_metric = MetricSpy()
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        monkeypatch.setattr(cache_module, "_CACHE_INVALIDATION_FAILURE", failure_metric)

        agents, has_target_bindings = await get_control_cache_scopes(
            FailingDatabase(), "ns", 7  # type: ignore[arg-type]
        )

        assert agents == []
        assert has_target_bindings is False
        assert failure_metric.calls == 1

    asyncio.run(run())


def test_control_and_policy_scope_lookup_failures_are_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        cache = RedisControlCache(FakeRedis(), ttl_seconds=30)
        failure_metric = MetricSpy()
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        monkeypatch.setattr(cache_module, "_CACHE_INVALIDATION_FAILURE", failure_metric)

        await invalidate_control_agents(FailingDatabase(), "ns", 7)  # type: ignore[arg-type]
        await invalidate_policy_agents(FailingDatabase(), "ns", 7)  # type: ignore[arg-type]

        assert failure_metric.calls == 2

    asyncio.run(run())


def test_close_control_cache_closes_redis_client(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        cache = RedisControlCache(FakeRedis(), ttl_seconds=30)
        closed: list[bool] = []

        async def aclose() -> None:
            closed.append(True)

        monkeypatch.setattr(cache._client, "aclose", aclose)
        monkeypatch.setattr(cache_module, "get_control_cache", lambda: cache)
        await cache_module.close_control_cache()
        assert closed == [True]

    asyncio.run(run())


def test_runtime_control_snapshot_round_trip() -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        control = ControlDefinitionRuntime.model_validate(
            {
                "execution": "server",
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {"name": "regex", "config": {"pattern": "bad"}},
                },
                "action": {"decision": "deny"},
            }
        )
        snapshot = [RuntimeControl(id=21, name="block-bad", control=control)]
        generation = await cache.get_generation("ns", "agent")
        await cache.set("ns", "agent", None, None, snapshot, generation)
        restored = await cache.get("ns", "agent", None, None)
        assert restored == snapshot
        assert restored is not None
        assert restored[0].id == 21
        assert restored[0].name == "block-bad"
        assert restored[0].control == control

    asyncio.run(run())


def test_generation_prevents_stale_snapshot_repopulation() -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        generation = await cache.get_generation("ns", "agent")
        await cache.invalidate_agent("ns", "agent")
        await cache.set("ns", "agent", None, None, [], generation)
        assert await cache.get("ns", "agent", None, None) is None

    asyncio.run(run())


def test_stale_snapshot_is_bypassed_until_postgres_refresh() -> None:
    async def run() -> None:
        client = FakeRedis()
        cache = RedisControlCache(client, ttl_seconds=30)
        old = _runtime_control(1, "old-snapshot")
        fresh = _runtime_control(2, "fresh-snapshot")
        generation = await cache.get_generation("ns", "agent")
        await cache.set("ns", "agent", None, None, [old], generation)

        await cache.invalidate_agent("ns", "agent")
        assert await cache.get("ns", "agent", None, None) is None

        fresh_generation = await cache.get_generation("ns", "agent")
        await cache.set("ns", "agent", None, None, [fresh], fresh_generation)
        restored = await cache.get("ns", "agent", None, None)
        assert restored == [fresh]

    asyncio.run(run())


def _runtime_control(control_id: int, name: str) -> RuntimeControl:
    control = ControlDefinitionRuntime.model_validate(
        {
            "execution": "server",
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {"name": "regex", "config": {"pattern": "bad"}},
            },
            "action": {"decision": "deny"},
        }
    )
    return RuntimeControl(id=control_id, name=name, control=control)
