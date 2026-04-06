"""Tests for agent_control.shutdown() and agent_control.ashutdown()."""

import asyncio
import os
import subprocess
import sys
import textwrap
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent_control
import agent_control.observability as obs_mod
from agent_control._state import state
from agent_control.observability import EventBatcher


def _make_started_batcher() -> EventBatcher:
    """Create a batcher with a mocked _send_batch and start it."""
    batcher = EventBatcher(batch_size=100, flush_interval=60.0)
    batcher._send_batch = AsyncMock(return_value=True)
    batcher.start()
    return batcher


class TestShutdownSync:
    """Tests for the synchronous shutdown() function."""

    def test_shutdown_flushes_batcher(self):
        batcher = _make_started_batcher()
        obs_mod._batcher = batcher

        mock_event = MagicMock()
        mock_event.model_dump = MagicMock(return_value={"test": True})
        for _ in range(3):
            batcher.add_event(mock_event)

        agent_control.shutdown()

        assert batcher._events_sent == 3
        assert len(batcher._events) == 0
        assert obs_mod._batcher is None

    def test_shutdown_stops_policy_refresh(self):
        stop_event = threading.Event()
        thread = threading.Thread(target=stop_event.wait, daemon=True)
        thread.start()

        agent_control._refresh_thread = thread
        agent_control._refresh_stop_event = stop_event
        agent_control._policy_refresh_interval_seconds = 60

        agent_control.shutdown()

        assert stop_event.is_set()
        assert agent_control._refresh_thread is None
        assert agent_control._refresh_stop_event is None

    def test_shutdown_resets_state(self):
        state.current_agent = MagicMock()
        state.control_engine = MagicMock()
        state.server_controls = [{"name": "test"}]
        state.server_url = "http://localhost:8000"
        state.api_key = "key"

        agent_control.shutdown()

        assert state.current_agent is None
        assert state.control_engine is None
        assert state.server_controls is None
        assert state.server_url is None
        assert state.api_key is None

    def test_shutdown_idempotent(self):
        agent_control.shutdown()
        agent_control.shutdown()

    def test_shutdown_without_init(self):
        """shutdown() should be safe to call even if init() was never called."""
        state.current_agent = None
        obs_mod._batcher = None
        agent_control._refresh_thread = None

        agent_control.shutdown()


class TestAshutdownAsync:
    """Tests for the async ashutdown() function."""

    @pytest.mark.asyncio
    async def test_ashutdown_flushes_batcher(self):
        batcher = _make_started_batcher()
        obs_mod._batcher = batcher

        mock_event = MagicMock()
        mock_event.model_dump = MagicMock(return_value={"test": True})
        for _ in range(3):
            batcher.add_event(mock_event)

        await agent_control.ashutdown()

        assert batcher._events_sent == 3
        assert obs_mod._batcher is None

    @pytest.mark.asyncio
    async def test_ashutdown_resets_state(self):
        state.current_agent = MagicMock()
        state.server_url = "http://localhost:8000"

        await agent_control.ashutdown()

        assert state.current_agent is None
        assert state.server_url is None

    @pytest.mark.asyncio
    async def test_ashutdown_idempotent(self):
        await agent_control.ashutdown()
        await agent_control.ashutdown()

    @pytest.mark.asyncio
    async def test_ashutdown_stops_policy_refresh_off_thread(self):
        with patch(
            "agent_control.asyncio.to_thread",
            new=AsyncMock(return_value=None),
        ) as to_thread_mock, patch(
            "agent_control.shutdown_observability",
            new=AsyncMock(return_value=None),
        ) as shutdown_observability_mock:
            await agent_control.ashutdown()

        to_thread_mock.assert_awaited_once_with(agent_control._stop_policy_refresh_loop)
        shutdown_observability_mock.assert_awaited_once()


class TestShutdownRefreshRace:
    """Regression tests: in-flight refresh must not publish after shutdown.

    These tests run _policy_refresh_worker directly (like the existing
    worker tests) with a gated _fetch_controls_async, so the actual
    post-fetch stop_event check in the worker is what prevents the
    zombie publish.
    """

    def test_sync_shutdown_prevents_zombie_publish(self):
        fetch_gate = threading.Event()
        fetch_entered = threading.Event()
        stop_event = threading.Event()

        async def slow_fetch() -> list[dict[str, Any]]:
            fetch_entered.set()
            await asyncio.to_thread(fetch_gate.wait)
            return [{"name": "zombie-control", "control": {}}]

        state.current_agent = None
        state.server_controls = None

        # Wire up module state so shutdown() can signal the stop event.
        agent_control._refresh_stop_event = stop_event

        with patch(
            "agent_control._fetch_controls_async",
            new=AsyncMock(side_effect=slow_fetch),
        ):
            # Run the real worker in a thread (interval=1 but the first
            # wait(1) returns False immediately since stop isn't set).
            worker_thread = threading.Thread(
                target=agent_control._policy_refresh_worker,
                args=(stop_event, 0),
                daemon=True,
            )
            agent_control._refresh_thread = worker_thread
            worker_thread.start()

            assert fetch_entered.wait(timeout=5), "worker never entered fetch"

            # Shutdown while fetch is in-flight.
            agent_control.shutdown()

            # Unblock the fetch - worker should see stop_event and discard.
            fetch_gate.set()
            worker_thread.join(timeout=5)

        assert state.server_controls is None

    @pytest.mark.asyncio
    async def test_async_shutdown_prevents_zombie_publish(self):
        fetch_gate = threading.Event()
        fetch_entered = threading.Event()
        stop_event = threading.Event()

        async def slow_fetch() -> list[dict[str, Any]]:
            fetch_entered.set()
            await asyncio.to_thread(fetch_gate.wait)
            return [{"name": "zombie-control", "control": {}}]

        state.current_agent = None
        state.server_controls = None

        agent_control._refresh_stop_event = stop_event

        with patch(
            "agent_control._fetch_controls_async",
            new=AsyncMock(side_effect=slow_fetch),
        ):
            worker_thread = threading.Thread(
                target=agent_control._policy_refresh_worker,
                args=(stop_event, 0),
                daemon=True,
            )
            agent_control._refresh_thread = worker_thread
            worker_thread.start()

            assert fetch_entered.wait(timeout=5), "worker never entered fetch"

            await agent_control.ashutdown()

            fetch_gate.set()
            worker_thread.join(timeout=5)

        assert state.server_controls is None


class TestManualRefreshLifecycleRace:
    """Regression tests for public refresh calls racing with lifecycle changes."""

    @pytest.mark.asyncio
    async def test_manual_refresh_discards_result_after_shutdown(self):
        fetch_gate = threading.Event()
        fetch_entered = threading.Event()

        async def slow_list_agent_controls(*args: Any, **kwargs: Any) -> dict[str, Any]:
            fetch_entered.set()
            await asyncio.to_thread(fetch_gate.wait)
            return {"controls": [{"name": "stale-control", "control": {}}]}

        with patch(
            "agent_control.__init__.AgentControlClient.health_check",
            new=AsyncMock(return_value={"status": "healthy"}),
        ), patch(
            "agent_control.__init__.agents.register_agent",
            new=AsyncMock(
                return_value={"created": True, "controls": [{"name": "initial", "control": {}}]}
            ),
        ), patch(
            "agent_control.__init__.agents.list_agent_controls",
            new=AsyncMock(side_effect=slow_list_agent_controls),
        ):
            agent_control.init(
                agent_name="manual-refresh-shutdown-agent",
                policy_refresh_interval_seconds=0,
            )
            refresh_task = asyncio.create_task(agent_control.refresh_controls_async())

            assert await asyncio.to_thread(fetch_entered.wait, 5), (
                "manual refresh never entered fetch"
            )

            agent_control.shutdown()
            fetch_gate.set()
            refreshed_snapshot = await refresh_task

        assert refreshed_snapshot is None
        assert state.server_controls is None


class TestAtexitShutdownFallback:
    """Regression tests for short-lived processes relying on atexit shutdown."""

    @pytest.mark.asyncio
    async def test_short_lived_process_flushes_sdk_events_on_exit(
        self,
        client: agent_control.AgentControlClient,
        test_agent: dict[str, Any],
        unique_name: str,
        server_url: str,
        api_key: str | None,
        tmp_path,
    ) -> None:
        """SDK-evaluated observability events should survive process exit."""
        control_name = f"sdk-shutdown-{unique_name}"
        control = await agent_control.controls.create_control(
            client,
            control_name,
            {
                "description": "Flush observability on short-lived script shutdown",
                "enabled": True,
                "execution": "sdk",
                "scope": {"stages": ["post"]},
                "condition": {
                    "selector": {"path": "output"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": r"\b123-45-6789\b"},
                    },
                },
                "action": {"decision": "deny"},
            },
        )

        await agent_control.agents.add_agent_control(
            client,
            agent_name=test_agent["agent_name"],
            control_id=control["control_id"],
        )

        script_path = tmp_path / "short_lived_agent.py"
        script_path.write_text(
            textwrap.dedent(
                f"""
                import asyncio
                import agent_control
                from agent_control import ControlViolationError, control


                @control()
                async def chat(message: str) -> str:
                    return "SSN 123-45-6789"


                agent_control.init(
                    agent_name={test_agent["agent_name"]!r},
                    agent_description="atexit shutdown flush regression",
                    observability_enabled=True,
                    policy_refresh_interval_seconds=0,
                )


                async def main() -> None:
                    try:
                        await chat("test")
                    except ControlViolationError:
                        pass


                if __name__ == "__main__":
                    asyncio.run(main())
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["AGENT_CONTROL_URL"] = server_url
        env["AGENT_CONTROL_OBSERVABILITY_ENABLED"] = "true"
        if api_key:
            env["AGENT_CONTROL_API_KEY"] = api_key
        else:
            env.pop("AGENT_CONTROL_API_KEY", None)

        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

        assert result.returncode == 0, (
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )

        events: list[dict[str, Any]] = []
        for _ in range(20):
            response = await client.http_client.post(
                "/api/v1/observability/events/query",
                json={
                    "agent_name": test_agent["agent_name"],
                    "control_ids": [control["control_id"]],
                    "limit": 10,
                    "offset": 0,
                },
            )
            response.raise_for_status()
            events = response.json()["events"]
            if events:
                break
            await asyncio.sleep(0.1)

        assert events, (
            "Expected at least one observability event from the short-lived process.\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
        assert events[0]["control_id"] == control["control_id"]
        assert events[0]["control_name"] == control_name
        assert events[0]["check_stage"] == "post"
        assert events[0]["matched"] is True
        assert events[0]["action"] == "deny"
