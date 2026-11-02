"""Focused unit tests for the effective-control cache implementations."""

from __future__ import annotations

import asyncio
import time

import pytest
from agent_control_models import ControlDefinitionRuntime

from agent_control_server import control_cache as cache_module
from agent_control_server.config import Settings
from agent_control_server.control_cache import (
    NoOpControlCache,
    RedisControlCache,
    build_cache_key,
    invalidate_control_agents,
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
    assert asyncio.run(NoOpControlCache().get("ns", "agent", None, None)) is None


def test_cache_key_includes_all_scope_dimensions() -> None:
    assert (
        build_cache_key("ns", "agent", None, None)
        == "agent-control:effective-controls:v1:=bnM:=YWdlbnQ:!:!"
    )
    base = build_cache_key("ns", "agent:other", "account", "42")
    assert base != build_cache_key("other", "agent", "account", "42")
    assert base != build_cache_key("ns", "agent", "other:account", "42")
    assert base != build_cache_key("ns", "agent:other", "workspace", "42")
    assert base != build_cache_key("ns", "agent:other", "account", "43")
    assert base != build_cache_key("ns:agent", "other", "account", "42")


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
        await cache.set("ns", "agent", None, None, [])
        await cache.invalidate_agent("ns", "agent")

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
