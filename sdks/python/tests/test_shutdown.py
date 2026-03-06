"""Tests for agent_control.shutdown() and agent_control.ashutdown()."""

import threading
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
