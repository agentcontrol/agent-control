"""Opt-in, one-shot LT stack sampler. No locals, arguments, or network endpoint."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from types import FrameType

TRIGGER = Path("/tmp/ac-runtime-profile.trigger")
OUTPUT = Path("/tmp/ac-runtime-profile.json")
_MAX_STACKS = 4096


def _stack(frame: FrameType) -> tuple[str, ...]:
    result: list[str] = []
    current: FrameType | None = frame
    while current is not None and len(result) < 32:
        result.append(
            f"{current.f_code.co_filename}:{current.f_lineno}:{current.f_code.co_name}"
        )
        current = current.f_back
    return tuple(reversed(result))


class RuntimeProfiler:
    """Bounded wall samples and approximate CPU-weighted main-thread stacks.

    CPU weights describe CPU consumed between samples, attributed to the sampled
    Python stack. They cannot attribute native frames or identify all short calls.
    The main thread stays alive for the server lifespan (required for its clock).
    """

    def __init__(self, trigger: Path = TRIGGER, output: Path = OUTPUT) -> None:
        self.trigger = trigger
        self.output = output
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="lt-stack-sampler", daemon=True)
        self._main_ident = threading.main_thread().ident

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _watch(self) -> None:
        while not self._stop.wait(0.25):
            if self.trigger.exists():
                self.trigger.unlink(missing_ok=True)
                # One profile per process. Restarting requires a fresh pod.
                self._capture()
                return

    def _capture(self) -> None:
        duration = min(90.0, max(1.0, float(os.getenv("GALILEO_RUNTIME_PROFILE_SECONDS", "60"))))
        period = 0.02  # 50 Hz; bounded counters, no per-sample output.
        samples: Counter[tuple[str, tuple[str, ...]]] = Counter()
        cpu: Counter[tuple[str, ...]] = Counter()
        started = time.monotonic()
        started_wall = time.time_ns()
        cpu_clock: int | None = None
        if self._main_ident is not None and hasattr(time, "pthread_getcpuclockid"):
            cpu_clock = time.pthread_getcpuclockid(self._main_ident)
        previous_cpu = time.clock_gettime_ns(cpu_clock) if cpu_clock is not None else 0
        total_cpu = 0
        count = 0
        dropped = 0
        max_wake_delay = 0.0
        deadline = started
        while not self._stop.is_set() and time.monotonic() - started < duration:
            now = time.monotonic()
            max_wake_delay = max(max_wake_delay, now - deadline)
            names = {thread.ident: thread.name for thread in threading.enumerate()}
            frames = sys._current_frames()
            current_cpu = time.clock_gettime_ns(cpu_clock) if cpu_clock is not None else 0
            delta = max(0, current_cpu - previous_cpu)
            previous_cpu = current_cpu
            total_cpu += delta
            for ident, frame in frames.items():
                if ident == self._thread.ident:
                    continue
                stack = _stack(frame)
                key = (names.get(ident, "unnamed"), stack)
                if key in samples or len(samples) < _MAX_STACKS:
                    samples[key] += 1
                else:
                    dropped += 1
                if ident == self._main_ident and (stack in cpu or len(cpu) < _MAX_STACKS):
                    cpu[stack] += delta
            del frames
            count += 1
            deadline += period
            if deadline < time.monotonic():
                deadline = time.monotonic()
            self._stop.wait(max(0, deadline - time.monotonic()))
        result = {
            "format": "lt-python-stack-samples-v1",
            "started_unix_ns": started_wall,
            "ended_unix_ns": time.time_ns(),
            "duration_seconds": time.monotonic() - started,
            "period_seconds": period,
            "sample_count": count,
            "max_wake_delay_seconds": max_wake_delay,
            "dropped_unique_stack_samples": dropped,
            "main_cpu_ns": total_cpu,
            "cpu_clock_available": cpu_clock is not None,
            "cpu_weighting": (
                "approximate interval CPU attributed to sampled Python stack; no native frames"
            ),
            "wall_stacks": [
                {"thread": name, "stack": list(stack), "samples": n}
                for (name, stack), n in samples.most_common()
            ],
            "main_cpu_stacks": [
                {"stack": list(stack), "cpu_ns": n} for stack, n in cpu.most_common()
            ],
        }
        temporary = self.output.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(result, stream)
        temporary.replace(self.output)


def start_runtime_profiler() -> RuntimeProfiler | None:
    """Normal server startups create no sampler thread."""
    if os.getenv("GALILEO_RUNTIME_PROFILE_ENABLED", "").lower() not in {"true", "1"}:
        return None
    profiler = RuntimeProfiler()
    profiler.start()
    return profiler
