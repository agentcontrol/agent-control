"""SDK caller-visible timing for one control-check invocation."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import uuid4

from agent_control_models import ControlCheckEvent, EvaluationResult

from .observability import is_observability_enabled, write_control_check_events

logger = logging.getLogger(__name__)

async def measure_control_check[CheckResult: (EvaluationResult, dict[str, Any])](
    evaluate: Callable[[], Awaitable[CheckResult]],
    *,
    agent_name: str,
    stage: Literal["pre", "post"],
    trace_id: str | None,
    span_id: str | None,
) -> CheckResult:
    """Measure the actual local-plus-remote check, retaining exceptions/cancellation.

    The monotonic clock measures evaluation-helper work, including preparation
    and existing per-control event handling. Check-event construction/export is
    outside the elapsed boundary. Epoch time is captured only for observability;
    its span end is the captured start plus measured monotonic nanoseconds.
    """
    emit_event = is_observability_enabled()
    start_unix_nano = time.time_ns() if emit_event else 0
    started = time.perf_counter_ns()
    result: CheckResult | None = None
    status: Literal["completed", "error", "cancelled"] = "error"
    try:
        result = await evaluate()
        status = "completed"
        return result
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        elapsed_ns = time.perf_counter_ns() - started
        elapsed_ms = elapsed_ns / 1_000_000
        check_id = str(uuid4()) if result is not None or emit_event else ""
        is_safe: bool | None = None
        if isinstance(result, EvaluationResult):
            result.control_check_id = check_id
            result.control_check_elapsed_ms = elapsed_ms
            is_safe = result.is_safe
        elif result is not None:
            # Preserve the decorator's raw server response, including extensions.
            result["control_check_id"] = check_id
            result["control_check_elapsed_ms"] = elapsed_ms
            if isinstance(result.get("is_safe"), bool):
                is_safe = result["is_safe"]
        if emit_event:
            try:
                event = ControlCheckEvent(
                    control_check_id=check_id,
                    trace_id=trace_id or "0" * 32,
                    span_id=span_id or "0" * 16,
                    agent_name=str(agent_name),
                    check_stage=stage,
                    status=status,
                    elapsed_ms=elapsed_ms,
                    start_time_unix_nano=start_unix_nano,
                    end_time_unix_nano=start_unix_nano + elapsed_ns,
                    is_safe=is_safe,
                )
                write_control_check_events([event])
            except Exception:
                logger.warning("Control-check telemetry failed", exc_info=True)
