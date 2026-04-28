"""Tests for the SDK's target-controls refresh + invalidate APIs."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent_control
from agent_control._state import state
from agent_control._target_controls_cache import get_target_controls_cache


def _ctrl(name: str) -> dict[str, object]:
    return {"id": 1, "name": name, "control": {}}


class _GetResponse:
    """Minimal stand-in for httpx.Response used by ``client.http_client.get``."""

    def __init__(self, controls: list[dict[str, object]]) -> None:
        self._controls = controls

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None

    def json(self) -> dict[str, object]:
        return {"controls": self._controls}


def _patch_session(server_url: str = "http://server-a", api_key: str | None = "k"):
    """Helper to set state.server_url/api_key for the duration of the patch."""
    return patch.multiple(state, server_url=server_url, api_key=api_key)


# ---------------------------------------------------------------------------
# invalidate_target_controls_cache
# ---------------------------------------------------------------------------


def test_invalidate_one_drops_only_that_entry():
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("ca")], epoch=epoch)
    cache.put("env", "b", [_ctrl("cb")], epoch=epoch)

    agent_control.invalidate_target_controls_cache("env", "a")

    assert cache.get("env", "a") is None
    assert cache.get("env", "b") == [_ctrl("cb")]


def test_invalidate_with_no_args_clears_everything():
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("ca")], epoch=epoch)
    cache.put("env", "b", [_ctrl("cb")], epoch=epoch)

    agent_control.invalidate_target_controls_cache()

    assert len(cache) == 0


def test_invalidate_partial_args_clears_everything():
    """Either both args or none — partial args should clear all (per docstring)."""
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("ca")], epoch=epoch)

    agent_control.invalidate_target_controls_cache(target_type="env")
    assert len(cache) == 0


# ---------------------------------------------------------------------------
# refresh_target_controls_async / refresh_target_controls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_async_returns_zero_when_cache_empty():
    """Nothing to refresh: function short-circuits without snapshotting context."""
    cache = get_target_controls_cache()
    cache.clear()
    refreshed = await agent_control.refresh_target_controls_async()
    assert refreshed == 0


@pytest.mark.asyncio
async def test_refresh_async_refetches_each_cached_target():
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("stale-a")], epoch=epoch)
    cache.put("env", "b", [_ctrl("stale-b")], epoch=epoch)

    fresh: dict[tuple[str, str], list[dict[str, object]]] = {
        ("env", "a"): [_ctrl("fresh-a")],
        ("env", "b"): [_ctrl("fresh-b")],
    }
    captured_calls: list[dict[str, str]] = []

    async def fake_get(path: str, *, params: dict[str, str], **_: object):
        captured_calls.append(params)
        key = (params["target_type"], params["target_id"])
        return _GetResponse(fresh[key])

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock(side_effect=fake_get)

    state.current_agent = MagicMock(agent_name="agent-x")
    with _patch_session(), patch(
        "agent_control.AgentControlClient", return_value=fake_client
    ):
        refreshed = await agent_control.refresh_target_controls_async()

    assert refreshed == 2
    assert cache.get("env", "a") == [_ctrl("fresh-a")]
    assert cache.get("env", "b") == [_ctrl("fresh-b")]
    assert {(c["target_type"], c["target_id"]) for c in captured_calls} == {
        ("env", "a"),
        ("env", "b"),
    }


@pytest.mark.asyncio
async def test_refresh_async_logs_and_continues_on_per_target_error(caplog):
    """A failed fetch on one target must not stop the rest."""
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "good", [_ctrl("stale")], epoch=epoch)
    cache.put("env", "bad", [_ctrl("stale")], epoch=epoch)

    async def fake_get(path: str, *, params: dict[str, str], **_: object):
        if params["target_id"] == "bad":
            raise RuntimeError("boom")
        return _GetResponse([_ctrl("fresh")])

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock(side_effect=fake_get)

    state.current_agent = MagicMock(agent_name="agent-x")
    with _patch_session(), patch(
        "agent_control.AgentControlClient", return_value=fake_client
    ), caplog.at_level("WARNING"):
        refreshed = await agent_control.refresh_target_controls_async()

    assert refreshed == 1  # only the good one
    assert cache.get("env", "good") == [_ctrl("fresh")]
    assert any("Failed to refresh" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_refresh_async_drops_stale_writes_after_reset():
    """A reset between fetch and put must reject the in-flight refresh."""
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("stale")], epoch=epoch)

    class _ResetMidJson:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            cache.reset()  # advances the epoch between get() and put()
            return {"controls": [_ctrl("late")]}

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock(return_value=_ResetMidJson())

    state.current_agent = MagicMock(agent_name="agent-x")
    with _patch_session(), patch(
        "agent_control.AgentControlClient", return_value=fake_client
    ):
        refreshed = await agent_control.refresh_target_controls_async()

    assert refreshed == 0
    assert cache.get("env", "a") is None  # reset emptied the cache


def test_refresh_sync_wraps_async_in_sync_context():
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("stale")], epoch=epoch)

    async def fake_get(path: str, *, params: dict[str, str], **_: object):
        return _GetResponse([_ctrl("fresh")])

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock(side_effect=fake_get)

    state.current_agent = MagicMock(agent_name="agent-x")
    with _patch_session(), patch(
        "agent_control.AgentControlClient", return_value=fake_client
    ):
        refreshed = agent_control.refresh_target_controls()

    assert refreshed == 1
    assert cache.get("env", "a") == [_ctrl("fresh")]


# ---------------------------------------------------------------------------
# Background refresh worker lifecycle
# ---------------------------------------------------------------------------


def test_start_then_stop_target_controls_refresh_loop():
    """Round-trip the worker lifecycle without blocking on the interval."""
    agent_control._start_target_controls_refresh_loop(interval_seconds=60)
    assert agent_control._target_refresh_thread is not None
    assert agent_control._target_refresh_thread.is_alive()

    agent_control._stop_target_controls_refresh_loop()
    assert agent_control._target_refresh_thread is None
    assert agent_control._target_refresh_stop_event is None


def test_start_target_controls_refresh_loop_zero_interval_is_noop():
    agent_control._start_target_controls_refresh_loop(interval_seconds=0)
    assert agent_control._target_refresh_thread is None


def test_target_controls_refresh_worker_skips_when_cache_empty():
    """Empty cache → worker iteration is a no-op (no upstream call attempted)."""
    cache = get_target_controls_cache()
    cache.clear()

    stop_event = threading.Event()

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock()

    # Fire one tick: stop the loop after the first sleep returns.
    def _fire_once_then_stop():
        # Set the stop_event so wait() returns True after the interval.
        stop_event.set()

    threading.Timer(0.0, _fire_once_then_stop).start()

    state.current_agent = MagicMock(agent_name="agent-x")
    with _patch_session(), patch(
        "agent_control.AgentControlClient", return_value=fake_client
    ):
        agent_control._target_controls_refresh_worker(stop_event, interval_seconds=0)

    fake_client.http_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_target_controls_refresh_worker_refreshes_known_keys():
    """When the cache has entries, the worker refreshes them on each tick."""
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("stale")], epoch=epoch)

    stop_event = threading.Event()

    async def fake_get(path: str, *, params: dict[str, str], **_: object):
        return _GetResponse([_ctrl("fresh-a")])

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock(side_effect=fake_get)

    # Run the worker in a thread, let it execute one iteration, then stop it.
    state.current_agent = MagicMock(agent_name="agent-x")

    async def _drive():
        with _patch_session(), patch(
            "agent_control.AgentControlClient", return_value=fake_client
        ):
            t = threading.Thread(
                target=agent_control._target_controls_refresh_worker,
                args=(stop_event, 0),
                daemon=True,
            )
            t.start()
            # Yield so the worker can run one iteration.
            await asyncio.sleep(0.05)
            stop_event.set()
            t.join(timeout=2)

    await _drive()

    assert cache.get("env", "a") == [_ctrl("fresh-a")]


def test_target_controls_refresh_worker_skips_when_session_unset():
    """Worker that can't snapshot context (no current_agent) just continues."""
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("stale")], epoch=epoch)

    stop_event = threading.Event()

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock()

    threading.Timer(0.0, stop_event.set).start()

    # No current_agent → _snapshot_refresh_context raises RuntimeError
    state.current_agent = None
    with _patch_session(server_url=None, api_key=None), patch(
        "agent_control.AgentControlClient", return_value=fake_client
    ):
        agent_control._target_controls_refresh_worker(stop_event, interval_seconds=0)

    fake_client.http_client.get.assert_not_called()


def test_target_controls_refresh_worker_logs_and_continues_on_iteration_failure(
    caplog,
):
    """An exception in the per-tick coroutine is logged, not re-raised."""
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("stale")], epoch=epoch)

    stop_event = threading.Event()

    def boom(*_args, **_kwargs):
        stop_event.set()  # also stop after the first iteration
        raise RuntimeError("network down")

    state.current_agent = MagicMock(agent_name="agent-x")
    with _patch_session(), patch(
        "agent_control._run_coro_in_new_loop", side_effect=boom
    ), caplog.at_level("ERROR"):
        agent_control._target_controls_refresh_worker(stop_event, interval_seconds=0)

    assert any(
        "Background target controls refresh loop iteration failed" in rec.message
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# refresh_target_controls (sync) called from inside an async context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_sync_called_from_async_context_runs_in_thread():
    """When the sync wrapper is called inside a running event loop, it
    delegates to a worker thread instead of blocking the loop."""
    cache = get_target_controls_cache()
    epoch = cache.current_epoch()
    cache.put("env", "a", [_ctrl("stale")], epoch=epoch)

    async def fake_get(path: str, *, params: dict[str, str], **_: object):
        return _GetResponse([_ctrl("fresh")])

    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None
    fake_client.http_client = MagicMock()
    fake_client.http_client.get = AsyncMock(side_effect=fake_get)

    state.current_agent = MagicMock(agent_name="agent-x")
    # We are inside an async test → asyncio.get_running_loop() succeeds in
    # refresh_target_controls() and it dispatches via a worker thread.
    with _patch_session(), patch(
        "agent_control.AgentControlClient", return_value=fake_client
    ):
        refreshed = await asyncio.to_thread(agent_control.refresh_target_controls)

    assert refreshed == 1
    assert cache.get("env", "a") == [_ctrl("fresh")]
