"""Controlled lookup diagnostic: isolation, coalescing, expiry and authorization."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from agent_control_models import ControlDefinitionRuntime, EvaluationRequest, Step
from fastapi.testclient import TestClient

from agent_control_server import diagnostic_lookup as diagnostic
from agent_control_server.auth_framework import Principal
from agent_control_server.endpoints import evaluation
from agent_control_server.models import DEFAULT_NAMESPACE_KEY
from agent_control_server.services.controls import RuntimeControl

from .utils import VALID_CONTROL_PAYLOAD, create_and_assign_policy


def sample() -> list[RuntimeControl]:
    return [
        RuntimeControl(
            1, "synthetic", ControlDefinitionRuntime.model_validate(VALID_CONTROL_PAYLOAD)
        )
    ]


def key() -> diagnostic.CacheKey:
    return diagnostic.CacheKey(
        "namespace", "agent", "log_stream", "target", "v1", diagnostic.definition_digest(sample())
    )


class FakeRedis:
    """Deterministic transport boundary; integration must still verify real Redis."""

    def __init__(self) -> None:
        self.now = 0.0
        self.values: dict[str, tuple[str, float]] = {}
        self.reads = 0
        self.writes = 0
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None

    async def aclose(self) -> None:
        pass

    async def get(self, name: str) -> str | None:
        self.reads += 1
        if self.read_error:
            raise self.read_error
        item = self.values.get(name)
        return item[0] if item is not None and item[1] > self.now else None

    async def set(self, name: str, value: str, *, ex: int) -> None:
        self.writes += 1
        if self.write_error:
            raise self.write_error
        self.values[name] = (value, self.now + ex)


@pytest.mark.asyncio
async def test_redis_shared_across_instances_and_results_are_isolated() -> None:
    # Given: two server cache instances use one Redis transport.
    redis = FakeRedis()
    first = diagnostic.LookupCache(lambda: redis)
    second = diagnostic.LookupCache(lambda: redis)
    loader = AsyncMock(side_effect=lambda: sample())
    # When: a second instance evaluates after the first fills Redis.
    initial = await first.load(key(), loader, ttl=30)
    initial[0].control.condition.evaluator.config["pattern"] = "mutated"
    actual = await second.load(key(), loader, ttl=30)
    # Then: shared Redis avoids another database load and does not share mutable objects.
    assert loader.await_count == 1
    assert redis.reads == 3 and redis.writes == 1
    assert actual[0].control.condition.evaluator.config["pattern"] == "x"


@pytest.mark.asyncio
async def test_redis_expiry_namespace_target_and_generation_separation() -> None:
    # Given: a deterministic Redis TTL, no local result cache.
    redis = FakeRedis()
    cache = diagnostic.LookupCache(lambda: redis)
    loader = AsyncMock(side_effect=lambda: sample())
    first = key()
    # When: namespace/target/generation changes and an old key expires.
    for other in (
        first,
        replace(first, namespace="other"),
        replace(first, target_id="other"),
        replace(first, generation="v2"),
        first,
    ):
        await cache.load(other, loader, ttl=30)
    redis.now = 30
    await cache.load(first, loader, ttl=30)
    # Then: exact identities share only their own unexpired definition.
    assert loader.await_count == 5
    # Five misses recheck under the miss lock; the one warm hit reads once.
    assert redis.reads == 11


@pytest.mark.asyncio
async def test_redis_corrupt_read_and_unavailability_fall_back_without_stale_data() -> None:
    # Given: a known cache entry followed by corrupt or unavailable Redis.
    redis = FakeRedis()
    cache = diagnostic.LookupCache(lambda: redis)
    loader = AsyncMock(side_effect=lambda: sample())
    await cache.load(key(), loader, ttl=30)
    redis.values[diagnostic.redis_key(key())] = ("invalid-json", 30)
    # When: corrupt data then a connection error occurs.
    corrupt = await cache.load(key(), loader, ttl=30)
    redis.read_error = ConnectionError("synthetic")
    unavailable = await cache.load(key(), loader, ttl=30)
    # Then: both use the database loader, never stale or corrupt cached controls.
    assert loader.await_count == 3
    assert corrupt == unavailable == sample()


@pytest.mark.asyncio
async def test_redis_write_failure_does_not_break_evaluation() -> None:
    # Given: Redis accepts reads but rejects writes.
    redis = FakeRedis()
    redis.write_error = ConnectionError("synthetic")
    cache = diagnostic.LookupCache(lambda: redis)
    loader = AsyncMock(side_effect=lambda: sample())
    # When: two requests encounter a cold cache.
    actual = [await cache.load(key(), loader, ttl=30) for _ in range(2)]
    # Then: every evaluation uses valid DB data and the cache remains cold.
    assert loader.await_count == 2
    assert actual == [sample(), sample()]


@pytest.mark.asyncio
async def test_cancelled_failed_and_mismatched_db_loads_never_reach_redis() -> None:
    # Given: the internal loader seam yields controlled database failures.
    redis = FakeRedis()
    cache = diagnostic.LookupCache(lambda: redis)
    loader = AsyncMock(
        side_effect=[RuntimeError("synthetic"), asyncio.CancelledError(), [], sample()]
    )
    # When: each failed load precedes one valid load.
    for error in (RuntimeError, asyncio.CancelledError, ValueError):
        with pytest.raises(error):
            await cache.load(key(), loader, ttl=30)
    result = await cache.load(key(), loader, ttl=30)
    # Then: Redis receives only the valid serialized definitions.
    assert result == sample()
    assert redis.writes == 1


def test_default_off_expiry_and_allowlist() -> None:
    # Given: exact frozen fixture plus an explicit expiry.
    fixture = diagnostic.FrozenFixture(
        namespace="n",
        agent="synthetic-agent",
        target_type="t",
        target_id="id",
        generation="v1",
        controls_sha256=key().digest,
    )
    default = diagnostic.DiagnosticSettings(_env_file=None)
    config = diagnostic.DiagnosticSettings(
        enabled=True, fixtures=[fixture], expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    # When/Then: disabled, expired, foreign namespace/target and naive time cannot opt in.
    assert default.fixture("n", "synthetic-agent", "t", "id") is None
    assert config.fixture("n", "synthetic-agent", "t", "id") == fixture
    assert config.fixture("foreign", "synthetic-agent", "t", "id") is None
    assert config.fixture("n", "synthetic-agent", "t", "foreign") is None
    config.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert config.fixture("n", "synthetic-agent", "t", "id") is None
    config.expires_at = datetime(2099, 1, 1)
    assert config.fixture("n", "synthetic-agent", "t", "id") is None


@pytest.mark.asyncio
async def test_off_always_loads_and_on_reuses_parsed_controls(monkeypatch) -> None:
    # Given: explicit internal loader seam avoids an unrelated engine/model call.
    controls = sample()
    fixture = diagnostic.FrozenFixture(
        namespace="n",
        agent="synthetic-agent",
        target_type="t",
        target_id="id",
        generation="v1",
        controls_sha256=diagnostic.definition_digest(controls),
    )
    config = diagnostic.DiagnosticSettings(
        enabled=True, fixtures=[fixture], expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    monkeypatch.setattr(diagnostic, "settings", config)
    redis = FakeRedis()
    monkeypatch.setattr(diagnostic, "cache", diagnostic.LookupCache(lambda: redis))
    loader = AsyncMock(
        side_effect=lambda *_: [
            evaluation.ControlAdapter(c.id, c.name, c.control) for c in sample()
        ]
    )
    monkeypatch.setattr(evaluation, "_load_engine_controls", loader)
    request = EvaluationRequest(
        agent_name="synthetic-agent",
        target_type="t",
        target_id="id",
        stage="pre",
        step=Step(type="llm", name="s", input="x"),
    )
    principal = Principal(namespace_key="n")
    # When: each mode receives two identical requests.
    off = [await evaluation._load_with_diagnostic(request, principal, "off") for _ in range(2)]
    on = [await evaluation._load_with_diagnostic(request, principal, "on") for _ in range(2)]
    # Then: only ON reuses a load; semantic definitions are identical.
    assert loader.await_count == 3
    assert off == on


def test_cached_http_evaluation_still_authorizes_every_call(
    client: TestClient, monkeypatch
) -> None:
    # Given: real HTTP-created fixture, then freeze its exact resolved definition digest.
    agent, _ = create_and_assign_policy(client)
    request = EvaluationRequest(
        agent_name=agent,
        target_type="log_stream",
        target_id="synthetic",
        stage="pre",
        step=Step(type="llm", name="s", input="x"),
    )
    principal = Principal(namespace_key=DEFAULT_NAMESPACE_KEY)
    controls = asyncio.run(evaluation._load_engine_controls(request, principal))
    runtime = [RuntimeControl(c.id, c.name, c.control) for c in controls]
    fixture = diagnostic.FrozenFixture(
        namespace=DEFAULT_NAMESPACE_KEY,
        agent=agent,
        target_type="log_stream",
        target_id="synthetic",
        generation="v1",
        controls_sha256=diagnostic.definition_digest(runtime),
    )
    monkeypatch.setattr(
        diagnostic,
        "settings",
        diagnostic.DiagnosticSettings(
            enabled=True, fixtures=[fixture], expires_at=datetime.now(UTC) + timedelta(hours=1)
        ),
    )
    redis = FakeRedis()
    monkeypatch.setattr(diagnostic, "cache", diagnostic.LookupCache(lambda: redis))
    headers = {"X-LT-Control-Lookup-Cache": "on", "X-LT-Control-Lookup-Generation": "v1"}
    body = request.model_dump(mode="json")
    # When: warm the cache, then use an invalid credential on that identical request.
    first = client.post("/api/v1/evaluation", json=body, headers=headers)
    second = client.post("/api/v1/evaluation", json=body, headers=headers)
    denied = client.post(
        "/api/v1/evaluation", json=body, headers={**headers, "X-API-Key": "invalid-synthetic"}
    )
    # Then: valid requests agree but a cache hit never bypasses authorization.
    assert first.status_code == second.status_code == 200
    assert first.json()["is_safe"] == second.json()["is_safe"] is False
    assert denied.status_code in (401, 403)


def test_diagnostic_header_without_allowlist_is_rejected(client: TestClient) -> None:
    # Given: the default-OFF configuration and an otherwise valid authenticated request.
    body = {
        "agent_name": "not-registered",
        "stage": "pre",
        "step": {"type": "llm", "name": "s", "input": "x"},
    }
    # When: attempting to opt in without server-side fixture authorization.
    response = client.post(
        "/api/v1/evaluation", json=body, headers={"X-LT-Control-Lookup-Cache": "on"}
    )
    # Then: reject rather than pretending the request was a cache trial.
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_redis_timeout_uses_database_and_is_counted(monkeypatch) -> None:
    # Given: a transport waits forever, bounded by the diagnostic's request deadline.
    from agent_control_server import diagnostic_metrics as metrics

    class SlowRedis(FakeRedis):
        async def get(self, name: str) -> str | None:
            await asyncio.Event().wait()
            return None

    slow = SlowRedis()
    cache = diagnostic.LookupCache(lambda: slow)
    loader = AsyncMock(side_effect=lambda: sample())
    monkeypatch.setattr(diagnostic.settings, "redis_timeout_seconds", 0.001)
    before = metrics._EVENTS.labels("on", "redis_read_fallback")._value.get()
    # When: the Redis read exceeds its own deadline.
    result = await cache.load(key(), loader, ttl=30)
    # Then: the evaluation keeps valid DB semantics and exposes the fallback.
    assert result == sample()
    assert loader.await_count == 1
    assert metrics._EVENTS.labels("on", "redis_read_fallback")._value.get() == before + 1


@pytest.mark.asyncio
async def test_redis_stages_have_numeric_metrics_without_identifiers() -> None:
    # Given: an opted-in diagnostic request and an isolated fixed transport.
    from agent_control_server import diagnostic_metrics as metrics

    redis = FakeRedis()
    cache = diagnostic.LookupCache(lambda: redis)
    loader = AsyncMock(side_effect=lambda: sample())
    mode = metrics._active_mode.set("on")
    # When: the request first fills, then reads Redis.
    try:
        await cache.load(key(), loader, ttl=30)
        await cache.load(key(), loader, ttl=30)
    finally:
        metrics._active_mode.reset(mode)
    # Then: all stages use bounded mode/stage labels, with no fixture identifiers.
    samples = [s for family in metrics._DURATION.collect() for s in family.samples]
    assert {"redis_get", "redis_set", "cache_encode", "cache_decode"} <= {
        s.labels["stage"] for s in samples
    }
    assert all(set(s.labels) <= {"mode", "stage", "le"} for s in samples)


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/v1/controls", "PUT"),
        ("/api/v1/controls/1", "DELETE"),
        ("/api/v1/control-bindings/1", "PATCH"),
        ("/api/v1/policies", "PUT"),
        ("/api/v1/agents/initAgent", "POST"),
    ],
)
def test_diagnostic_freezes_configuration_writes_until_disabled(
    client: TestClient,
    monkeypatch,
    path: str,
    method: str,
) -> None:
    # Given: the owned dedicated app is explicitly frozen, even after cache expiry.
    monkeypatch.setattr(diagnostic.settings, "enabled", True)
    monkeypatch.setattr(diagnostic.settings, "expires_at", datetime(2000, 1, 1, tzinfo=UTC))
    # When: a configuration mutation is attempted through any management surface.
    response = client.request(method, path, json={})
    # Then: reject it without writing, and leave read/health routes available.
    assert response.status_code == 409
    assert "frozen" in response.json()["detail"]
    assert client.get("/health").status_code == 200


def test_missing_pair_generation_rejected(client: TestClient) -> None:
    # Given: a cache-mode header without an explicit cold-start pair identity.
    body = {
        "agent_name": "not-registered",
        "stage": "pre",
        "step": {"type": "llm", "name": "s", "input": "x"},
    }
    # When: evaluation attempts diagnostic mode without the paired generation.
    response = client.post(
        "/api/v1/evaluation", json=body, headers={"X-LT-Control-Lookup-Cache": "on"}
    )
    # Then: no silently reused generation is accepted.
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cache_hits_do_not_serialize_behind_fixture_lock() -> None:
    redis = FakeRedis()
    cache = diagnostic.LookupCache(lambda: redis)
    loader = AsyncMock(side_effect=lambda: sample())
    await cache.load(key(), loader, ttl=30)
    original = redis.get
    entered = 0
    both_started = asyncio.Event()

    async def overlapping_get(name: str) -> str | None:
        nonlocal entered
        entered += 1
        if entered == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return await original(name)

    redis.get = overlapping_get  # type: ignore[method-assign]
    results = await asyncio.gather(*(cache.load(key(), loader, ttl=30) for _ in range(2)))
    assert entered == 2
    assert len(results) == 2
    assert loader.await_count == 1
