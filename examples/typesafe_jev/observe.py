"""Emit observability events for evaluations made over plain HTTP.

``POST /api/v1/evaluation`` is deliberately evaluation-only: it returns the
decision and writes no observability events. The SDK is what normally
reconstructs and sends them, so an application that calls the endpoint
directly shows nothing in Agent Control's Monitor tab.

These two web demos call the endpoint directly, because they need the full
response to show per-control detail. So they reconstruct the events the same
way the SDK does and queue them through the SDK's batcher.

Set AGENT_CONTROL_OBSERVE=0 to turn this off.
"""

from __future__ import annotations

import os
from typing import Any

import agent_control
from agent_control.evaluation_events import (
    build_control_execution_events,
    enqueue_observability_events,
)
from agent_control_models.controls import ControlDefinition
from agent_control_models.evaluation import EvaluationRequest, EvaluationResponse

ENABLED = os.getenv("AGENT_CONTROL_OBSERVE", "1") != "0"

_started = False


def start(agent_name: str, server_url: str, step_name: str, tool_name: str) -> bool:
    """Initialize the SDK so its observability batcher is running.

    Both steps are declared here. init() replaces the agent's step list, so
    leaving the tool step out would deregister it and the tool-stage control
    would have nothing to attach to.

    Args:
        agent_name: The agent to register.
        server_url: The Agent Control server.
        step_name: The chat step's name.
        tool_name: The lookup tool's step name.

    Returns:
        True when observability is on and initialization succeeded.
    """
    global _started
    if not ENABLED or _started:
        return _started
    try:
        agent_control.init(
            agent_name=agent_name,
            agent_description="TypeSafe Jev demo",
            server_url=server_url,
            steps=[
                {"type": "llm", "name": step_name, "description": "A chat turn."},
                {
                    "type": "tool",
                    "name": tool_name,
                    "description": "Read customer records from the bank's customer database.",
                },
            ],
            observability_enabled=True,
            policy_refresh_interval_seconds=0,
        )
        _started = True
    except Exception:  # a demo should still run when observability cannot start
        _started = False
    return _started


def _control_lookup(controls_payload: Any) -> dict[int, ControlDefinition]:
    """Parse the agent's controls into the typed models the builder needs."""
    items = (
        controls_payload.get("controls", controls_payload)
        if isinstance(controls_payload, dict)
        else controls_payload
    )
    lookup: dict[int, ControlDefinition] = {}
    for item in items or []:
        try:
            lookup[int(item["id"])] = ControlDefinition.model_validate(item["control"])
        except Exception:
            continue
    return lookup


def record(
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    controls_payload: Any,
) -> int:
    """Reconstruct and queue events for one evaluation.

    Args:
        request_payload: The body sent to /api/v1/evaluation.
        response_payload: The body it returned.
        controls_payload: The agent's controls, used to stamp selector and
            evaluator identity onto each event.

    Returns:
        How many events were queued. Zero when observability is off.
    """
    if not (ENABLED and _started):
        return 0
    try:
        request = EvaluationRequest.model_validate(request_payload)
        response = EvaluationResponse.model_validate(response_payload)
        events = build_control_execution_events(
            response=response,
            request=request,
            control_lookup=_control_lookup(controls_payload),
            trace_id=None,
            span_id=None,
            agent_name=request.agent_name,
        )
        enqueue_observability_events(events)
        return len(events)
    except Exception:  # never fail a request because observability failed
        return 0
