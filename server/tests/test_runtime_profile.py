"""Bounded profiling must be opt-in and must never collect application locals."""

import json
import threading
import time

from agent_control_server.runtime_profile import RuntimeProfiler, start_runtime_profiler


def test_disabled_profiler_creates_no_thread(monkeypatch):
    # Given ordinary startup, no sampling thread is created.
    monkeypatch.delenv("GALILEO_RUNTIME_PROFILE_ENABLED", raising=False)
    before = {thread.ident for thread in threading.enumerate()}
    assert start_runtime_profiler() is None
    assert {thread.ident for thread in threading.enumerate()} == before


def test_one_shot_profile_is_bounded_and_records_only_stack_metadata(tmp_path, monkeypatch):
    # Given a one-second opt-in profile and a main thread with a secret local.
    monkeypatch.setenv("GALILEO_RUNTIME_PROFILE_SECONDS", "1")
    secret_payload = "DO-NOT-CAPTURE-THIS-LOCAL"
    trigger = tmp_path / "trigger"
    output = tmp_path / "profile.json"
    profiler = RuntimeProfiler(trigger, output)
    profiler.start()
    try:
        # When the operator triggers collection, a bounded one-shot report is saved.
        trigger.touch()
        deadline = time.monotonic() + 4
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        result = json.loads(output.read_text())
        assert 1 <= result["sample_count"] <= 60
        assert result["duration_seconds"] < 2
        assert len(result["wall_stacks"]) <= 4096
        assert all(len(item["stack"]) <= 32 for item in result["wall_stacks"])
        assert secret_payload not in output.read_text()
        assert output.stat().st_mode & 0o777 == 0o600
        assert any("test_one_shot_profile" in line
                   for item in result["wall_stacks"] for line in item["stack"])
    finally:
        profiler.stop()
    assert not profiler._thread.is_alive()
