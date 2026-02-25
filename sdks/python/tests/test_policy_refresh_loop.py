"""Tests for SDK policy refresh loop lifecycle and cache publication semantics."""

from __future__ import annotations

import threading
from collections.abc import Generator
from unittest.mock import AsyncMock, call, patch
from uuid import uuid4

import agent_control
import pytest


@pytest.fixture(autouse=True)
def _reset_policy_refresh_state() -> Generator[None, None, None]:
    """Ensure refresh loop and cache globals do not leak across tests."""
    agent_control._stop_policy_refresh_loop()
    agent_control._server_controls = None
    agent_control._current_agent = None
    agent_control._server_url = None
    agent_control._api_key = None
    yield
    agent_control._stop_policy_refresh_loop()
    agent_control._server_controls = None
    agent_control._current_agent = None
    agent_control._server_url = None
    agent_control._api_key = None


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
            agent_name="Default Refresh Agent",
            agent_id=str(uuid4()),
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
            agent_name="Disabled Refresh Agent",
            agent_id=str(uuid4()),
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
            agent_name="Reinit Agent",
            agent_id=str(uuid4()),
            policy_refresh_interval_seconds=60,
        )
        agent_control.init(
            agent_name="Reinit Agent",
            agent_id=str(uuid4()),
            policy_refresh_interval_seconds=5,
        )

    # Then: each init stops the old loop first and starts with the new interval.
    assert stop_loop_mock.call_count == 2
    assert start_loop_mock.call_args_list == [call(60), call(5)]


def test_policy_refresh_worker_runs_multiple_iterations() -> None:
    # Given: a stop event that is set after the second refresh call.
    stop_event = threading.Event()
    call_count = 0

    async def mock_refresh_controls_async() -> list[dict[str, int]]:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        return [{"id": call_count}]

    # When: the worker loop runs with zero wait interval for deterministic test speed.
    with patch(
        "agent_control.refresh_controls_async",
        new=AsyncMock(side_effect=mock_refresh_controls_async),
    ):
        agent_control._policy_refresh_worker(stop_event, interval_seconds=0)

    # Then: periodic refresh behavior is observed (more than one iteration).
    assert call_count >= 2


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
            agent_name="Fail Open Agent",
            agent_id=str(uuid4()),
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
            agent_name="Swap Only Agent",
            agent_id=str(uuid4()),
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
            agent_name="Concurrent Refresh Agent",
            agent_id=str(uuid4()),
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
