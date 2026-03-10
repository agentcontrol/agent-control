"""Shared enforcement helpers for framework integrations."""

from __future__ import annotations

from typing import Any, Literal

from agent_control_models import EvaluationResult

import agent_control
from agent_control import ControlSteerError, ControlViolationError


def _action_error(result: EvaluationResult) -> tuple[str, Exception] | None:
    """Return the first blocking action from an evaluation result."""

    matches = result.matches or []
    deny_match = next((m for m in matches if m.action == "deny"), None)
    if deny_match:
        msg = getattr(getattr(deny_match, "result", None), "message", None) or result.reason
        msg = msg or f"Control '{deny_match.control_name}' triggered"
        deny_err = ControlViolationError(
            control_id=deny_match.control_id,
            control_name=deny_match.control_name,
            message=msg,
            metadata=getattr(deny_match.result, "metadata", None),
        )
        return "deny", deny_err

    steer_match = next((m for m in matches if m.action == "steer"), None)
    if not steer_match:
        return None

    msg = getattr(getattr(steer_match, "result", None), "message", None) or result.reason
    msg = msg or f"Control '{steer_match.control_name}' triggered"
    ctx = getattr(steer_match, "steering_context", None)
    ctx_msg = getattr(ctx, "message", None) if ctx else None
    steer_err = ControlSteerError(
        control_id=steer_match.control_id,
        control_name=steer_match.control_name,
        message=f"Steering required [{steer_match.control_name}]: {msg}",
        metadata=getattr(steer_match.result, "metadata", None),
        steering_context=ctx_msg or msg,
    )
    return "steer", steer_err


async def _evaluate_and_enforce(
    agent_name: str,
    step_name: str,
    *,
    input: Any | None = None,
    output: Any | None = None,
    context: dict[str, Any] | None = None,
    step_type: Literal["tool", "llm"] = "llm",
    stage: Literal["pre", "post"] = "pre",
) -> EvaluationResult:
    """Evaluate controls and enforce fail-closed blocking semantics."""

    result = await agent_control.evaluate_controls(
        step_name=step_name,
        input=input,
        output=output,
        context=context,
        step_type=step_type,
        stage=stage,
        agent_name=agent_name,
    )

    if result.errors:
        error_names = ", ".join(
            e.control_name for e in result.errors if getattr(e, "control_name", None)
        )
        raise RuntimeError(
            "Control evaluation failed; execution blocked for safety. "
            f"Errors: {error_names or 'unknown'}"
        )

    action = _action_error(result)
    if action:
        _, err = action
        raise err

    if not result.is_safe:
        control_name = "unknown"
        reason = result.reason
        match = None

        if result.matches:
            match = result.matches[0]
            control_name = match.control_name
            if not reason:
                match_result = getattr(match, "result", None)
                msg = getattr(match_result, "message", None) if match_result else None
                reason = msg or f"Control '{control_name}' triggered"

        raise ControlViolationError(
            control_id=(match.control_id if match is not None else None),
            control_name=control_name,
            message=reason or "Control violation",
            metadata=(getattr(match.result, "metadata", None) if match is not None else None),
        )

    return result
