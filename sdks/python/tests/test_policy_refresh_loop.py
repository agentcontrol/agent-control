"""Tests for SDK policy refresh loop lifecycle and cache publication semantics."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Generator
from unittest.mock import AsyncMock, call, patch

import pytest

import agent_control
from agent_control._state import state


@pytest.fixture(autouse=True)
def _reset_policy_refresh_state() -> Generator[None, None, None]:
    """Ensure refresh loop and cache globals do not leak across tests."""
    agent_control._stop_policy_refresh_loop()
    agent_control._reset_state()
    yield
    agent_control._stop_policy_refresh_loop()
    agent_control._reset_state()


def test_init_starts_policy_refresh_loop_by_default() -> None:
    # Given: init dependencies are mocked and no explicit refresh interval is passed.
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})

    # When: init() is called.
    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control._start_policy_refresh_loop",
    ) as start_loop_mock:
        agent_control.init(
            agent_name="default-refresh-agent",
        )

    # Then: the loop starts with the default interval (60s).
    start_loop_mock.assert_called_once_with(60)


def test_init_disables_policy_refresh_loop_when_interval_is_zero() -> None:
    # Given: init dependencies are mocked.
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})

    # When: init() is called with interval=0.
    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control._start_policy_refresh_loop",
    ) as start_loop_mock:
        agent_control.init(
            agent_name="disabled-refresh-agent",
            policy_refresh_interval_seconds=0,
        )

    # Then: no background loop is started.
    start_loop_mock.assert_not_called()


def test_reinit_stops_and_restarts_policy_refresh_loop() -> None:
    # Given: init dependencies are mocked.
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})

    # When: init() is called twice with different intervals.
    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control._stop_policy_refresh_loop",
    ) as stop_loop_mock, patch(
        "agent_control._start_policy_refresh_loop",
    ) as start_loop_mock:
        agent_control.init(
            agent_name="reinit-agent",
            policy_refresh_interval_seconds=60,
        )
        agent_control.init(
            agent_name="reinit-agent",
            policy_refresh_interval_seconds=5,
        )

    # Then: each init stops the old loop first and starts with the new interval.
    assert stop_loop_mock.call_count == 2
    assert start_loop_mock.call_args_list == [call(60), call(5)]


def test_policy_refresh_worker_runs_multiple_iterations() -> None:
    # Given: a stop event that is set after the second fetch call.
    stop_event = threading.Event()
    call_count = 0

    async def mock_fetch() -> list[dict[str, int]]:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        return [{"id": call_count}]

    # When: the worker loop runs with zero wait interval for deterministic test speed.
    with patch(
        "agent_control._fetch_controls_async",
        new=AsyncMock(side_effect=mock_fetch),
    ):
        agent_control._policy_refresh_worker(stop_event, interval_seconds=0)

    # Then: periodic refresh behavior is observed (more than one iteration).
    assert call_count >= 2


def test_publish_server_controls_clears_cache_on_none() -> None:
    # GIVEN: an existing cached controls snapshot.
    state.server_controls = [{"id": 1, "name": "cached"}]

    # WHEN: the publisher receives None.
    published = agent_control._publish_server_controls(None)

    # THEN: the cache is cleared and None is returned.
    assert published is None
    assert agent_control.get_server_controls() is None


def test_start_policy_refresh_loop_ignores_non_positive_interval() -> None:
    # GIVEN: no background refresh loop is running.
    assert agent_control._refresh_thread is None
    assert agent_control._refresh_stop_event is None

    # WHEN: loop start is requested with interval=0.
    agent_control._start_policy_refresh_loop(0)

    # THEN: no thread or stop event is created.
    assert agent_control._refresh_thread is None
    assert agent_control._refresh_stop_event is None
    assert agent_control._policy_refresh_interval_seconds is None


def test_start_and_stop_policy_refresh_loop_manage_lifecycle_state() -> None:
    # GIVEN: no background refresh loop is running.
    assert agent_control._refresh_thread is None
    assert agent_control._refresh_stop_event is None

    # WHEN: the refresh loop is started.
    agent_control._start_policy_refresh_loop(interval_seconds=60)
    refresh_thread = agent_control._refresh_thread
    stop_event = agent_control._refresh_stop_event

    for _ in range(20):
        if refresh_thread is not None and refresh_thread.is_alive():
            break
        time.sleep(0.01)

    # THEN: lifecycle globals reflect a running loop.
    assert agent_control._policy_refresh_interval_seconds == 60
    assert refresh_thread is not None
    assert stop_event is not None
    assert refresh_thread.is_alive()
    assert not stop_event.is_set()

    # WHEN: the loop is stopped.
    agent_control._stop_policy_refresh_loop()

    # THEN: thread/event are torn down and previous stop event is signaled.
    assert stop_event.is_set()
    assert agent_control._refresh_thread is None
    assert agent_control._refresh_stop_event is None
    assert agent_control._policy_refresh_interval_seconds is None
    assert not refresh_thread.is_alive()


def test_stop_policy_refresh_loop_logs_warning_if_thread_does_not_stop() -> None:
    # GIVEN: a loop state with a non-stopping thread.
    class NonStoppingThread:
        def __init__(self) -> None:
            self.join_calls = 0

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            self.join_calls += 1

    stop_event = threading.Event()
    stuck_thread = NonStoppingThread()
    agent_control._policy_refresh_interval_seconds = 60
    agent_control._refresh_stop_event = stop_event
    agent_control._refresh_thread = stuck_thread  # type: ignore[assignment]

    # WHEN: stop is requested.
    with patch("agent_control.logger.warning") as warning_mock:
        agent_control._stop_policy_refresh_loop()

    # THEN: stop is signaled and a timeout warning is emitted.
    assert stop_event.is_set()
    assert stuck_thread.join_calls == 1
    warning_mock.assert_called_once()


def test_policy_refresh_worker_logs_and_continues_after_refresh_error() -> None:
    # GIVEN: fetch fails once, then succeeds and signals stop.
    stop_event = threading.Event()
    call_count = 0

    async def flaky_fetch() -> list[dict[str, int]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient refresh failure")
        stop_event.set()
        return [{"id": call_count}]

    # WHEN: the worker loop runs.
    with patch(
        "agent_control._fetch_controls_async",
        new=AsyncMock(side_effect=flaky_fetch),
    ), patch("agent_control.logger.error") as error_log_mock:
        agent_control._policy_refresh_worker(stop_event, interval_seconds=0)

    # THEN: the error is logged and a subsequent iteration still executes.
    assert call_count >= 2
    error_log_mock.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_controls_async_without_init_raises_runtime_error() -> None:
    # GIVEN: no initialized SDK session.
    agent_control._stop_policy_refresh_loop()
    agent_control._reset_state()

    # WHEN / THEN: refresh surfaces the lifecycle misuse.
    with pytest.raises(RuntimeError, match="Agent not initialized"):
        await agent_control.refresh_controls_async()


def test_refresh_controls_after_shutdown_raises_runtime_error() -> None:
    # GIVEN: an initialized session that is then shut down.
    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=AsyncMock(return_value={"status": "healthy"}),
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=AsyncMock(return_value={"created": True, "controls": []}),
    ):
        agent_control.init(
            agent_name="refresh-after-shutdown-agent",
            policy_refresh_interval_seconds=0,
        )

    agent_control.shutdown()

    # WHEN / THEN: sync refresh also surfaces the lifecycle misuse.
    with pytest.raises(RuntimeError, match="Agent not initialized"):
        agent_control.refresh_controls()


def test_refresh_controls_sync_without_running_loop_uses_refresh_endpoint() -> None:
    # GIVEN: initialized SDK state and a successful controls refresh response.
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})
    refreshed_controls = [{"id": 9, "name": "sync", "control": {"execution": "server"}}]
    list_agent_controls_mock = AsyncMock(return_value={"controls": refreshed_controls})

    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control.__init__.agents.list_agent_controls",
        new=list_agent_controls_mock,
    ):
        agent_control.init(
            agent_name="sync-refresh-agent",
            policy_refresh_interval_seconds=0,
        )

        # WHEN: refresh_controls() is called from a synchronous context.
        refreshed_snapshot = agent_control.refresh_controls()

    # THEN: the endpoint is called and refreshed snapshot is returned.
    assert refreshed_snapshot == refreshed_controls
    assert list_agent_controls_mock.await_count == 1


@pytest.mark.asyncio
async def test_refresh_controls_sync_with_running_loop_uses_worker_thread() -> None:
    # GIVEN: initialized SDK state and a successful controls refresh response.
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": []})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})
    refreshed_controls = [{"id": 11, "name": "async", "control": {"execution": "server"}}]
    list_agent_controls_mock = AsyncMock(return_value={"controls": refreshed_controls})

    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control.__init__.agents.list_agent_controls",
        new=list_agent_controls_mock,
    ):
        agent_control.init(
            agent_name="async-refresh-agent",
            policy_refresh_interval_seconds=0,
        )

        # WHEN: refresh_controls() is called while an event loop is already running.
        refreshed_snapshot = agent_control.refresh_controls()

    # THEN: refresh still succeeds and returns the server snapshot.
    assert refreshed_snapshot == refreshed_controls
    assert list_agent_controls_mock.await_count == 1


@pytest.mark.asyncio
async def test_refresh_fail_open_retains_previous_controls() -> None:
    # Given: initialized controls cache and a failing refresh endpoint call.
    initial_controls = [{"id": 1, "name": "old", "control": {"execution": "server"}}]
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": initial_controls})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})
    list_agent_controls_mock = AsyncMock(side_effect=RuntimeError("network failure"))

    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control.__init__.agents.list_agent_controls",
        new=list_agent_controls_mock,
    ):
        agent_control.init(
            agent_name="fail-open-agent",
            policy_refresh_interval_seconds=0,
        )
        previous_snapshot = agent_control.get_server_controls()

        # When: refresh fails.
        refreshed_snapshot = await agent_control.refresh_controls_async()

    # Then: existing cache is retained.
    assert previous_snapshot is not None
    assert refreshed_snapshot is previous_snapshot
    assert agent_control.get_server_controls() is previous_snapshot


@pytest.mark.asyncio
async def test_refresh_uses_swap_only_cache_publication() -> None:
    # Given: initialized cache and a successful refresh with different controls.
    initial_controls = [{"id": 1, "name": "old", "control": {"execution": "server"}}]
    updated_controls = [{"id": 2, "name": "new", "control": {"execution": "sdk"}}]
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": initial_controls})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})
    list_agent_controls_mock = AsyncMock(return_value={"controls": updated_controls})

    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control.__init__.agents.list_agent_controls",
        new=list_agent_controls_mock,
    ):
        agent_control.init(
            agent_name="swap-only-agent",
            policy_refresh_interval_seconds=0,
        )
        old_snapshot = agent_control.get_server_controls()

        # When: refresh succeeds with a new payload.
        new_snapshot = await agent_control.refresh_controls_async()

    # Then: cache publication swaps object identity instead of mutating old list in place.
    assert old_snapshot is not None
    assert new_snapshot is not None
    assert new_snapshot is not old_snapshot
    assert old_snapshot[0]["id"] == 1
    assert new_snapshot[0]["id"] == 2
    assert agent_control.get_server_controls() is new_snapshot


@pytest.mark.asyncio
async def test_manual_refresh_does_not_overwrite_reinitialized_session() -> None:
    # Given: a refresh for the old session is blocked while init() creates a new session.
    fetch_gate = threading.Event()
    fetch_entered = threading.Event()
    initial_controls = [{"id": 1, "name": "old-init", "control": {"execution": "server"}}]
    new_session_controls = [{"id": 2, "name": "new-init", "control": {"execution": "server"}}]
    stale_refresh_controls = [
        {"id": 99, "name": "stale-refresh", "control": {"execution": "server"}}
    ]
    register_agent_mock = AsyncMock(
        side_effect=[
            {"created": True, "controls": initial_controls},
            {"created": True, "controls": new_session_controls},
        ]
    )
    health_check_mock = AsyncMock(return_value={"status": "healthy"})

    async def slow_list_agent_controls(*args: object, **kwargs: object) -> dict[str, object]:
        fetch_entered.set()
        await asyncio.to_thread(fetch_gate.wait)
        return {"controls": stale_refresh_controls}

    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control.__init__.agents.list_agent_controls",
        new=AsyncMock(side_effect=slow_list_agent_controls),
    ):
        agent_control.init(
            agent_name="old-session-agent",
            policy_refresh_interval_seconds=0,
        )
        refresh_task = asyncio.create_task(agent_control.refresh_controls_async())

        assert await asyncio.to_thread(fetch_entered.wait, 5), (
            "manual refresh never entered fetch"
        )

        agent_control.init(
            agent_name="new-session-agent",
            policy_refresh_interval_seconds=0,
        )
        fetch_gate.set()
        refreshed_snapshot = await refresh_task

    assert refreshed_snapshot == new_session_controls
    assert agent_control.get_server_controls() == new_session_controls
    assert agent_control.get_server_controls() != stale_refresh_controls


@pytest.mark.asyncio
async def test_concurrent_reads_and_refresh_updates_do_not_raise() -> None:
    # Given: initialized cache and many refresh payloads.
    initial_controls = [{"id": 1, "name": "c1", "control": {"execution": "server"}}]
    refresh_payloads = [
        {"controls": [{"id": idx, "name": f"c{idx}", "control": {"execution": "server"}}]}
        for idx in range(2, 32)
    ]
    register_agent_mock = AsyncMock(return_value={"created": True, "controls": initial_controls})
    health_check_mock = AsyncMock(return_value={"status": "healthy"})
    list_agent_controls_mock = AsyncMock(side_effect=refresh_payloads)
    reader_errors: list[Exception] = []
    stop_reader = threading.Event()

    def reader() -> None:
        try:
            while not stop_reader.is_set():
                controls = agent_control.get_server_controls()
                if controls:
                    _ = [ctrl["name"] for ctrl in controls]
        except Exception as exc:
            reader_errors.append(exc)

    with patch(
        "agent_control.__init__.AgentControlClient.health_check",
        new=health_check_mock,
    ), patch(
        "agent_control.__init__.agents.register_agent",
        new=register_agent_mock,
    ), patch(
        "agent_control.__init__.agents.list_agent_controls",
        new=list_agent_controls_mock,
    ):
        agent_control.init(
            agent_name="concurrent-refresh-agent",
            policy_refresh_interval_seconds=0,
        )
        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        # When: many refresh updates happen while reads are in flight.
        for _ in refresh_payloads:
            await agent_control.refresh_controls_async()

        stop_reader.set()
        reader_thread.join(timeout=2)

    # Then: no reader errors occur and latest snapshot is available.
    assert not reader_errors
    latest = agent_control.get_server_controls()
    assert latest is not None
    assert latest[0]["id"] == 31
