"""Evaluation check operations for Agent Control SDK."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from agent_control_engine import list_evaluators
from agent_control_engine.core import ControlEngine
from agent_control_models import (
    ControlDefinition,
    ControlExecutionEvent,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationResult,
    EvaluatorResult,
    Step,
)

from ._state import state
from .client import AgentControlClient
from .observability import add_event, get_logger, is_observability_enabled
from .validation import ensure_agent_name

_logger = get_logger(__name__)

# Fallback IDs used when trace context is missing.
# All-zero values are invalid trace/span IDs per OpenTelemetry.
_FALLBACK_TRACE_ID = "0" * 32
_FALLBACK_SPAN_ID = "0" * 16
_trace_warning_logged = False

def _map_applies_to(step_type: str) -> Literal["llm_call", "tool_call"]:
    return "tool_call" if step_type == "tool" else "llm_call"


def _emit_local_events(
    local_result: "EvaluationResponse",
    request: "EvaluationRequest",
    local_controls: list["_ControlAdapter"],
    trace_id: str | None,
    span_id: str | None,
    agent_name: str | None,
) -> None:
    """Emit observability events for locally-evaluated controls.

    Mirrors the server's _emit_observability_events() so that SDK-evaluated
    controls are visible in the observability pipeline.

    When trace_id/span_id are missing, fallback all-zero IDs are used so events
    are still recorded (but clearly marked as uncorrelated).

    Only runs when observability is enabled.
    """
    if not is_observability_enabled():
        return

    global _trace_warning_logged  # noqa: PLW0603
    if not trace_id or not span_id:
        if not _trace_warning_logged:
            _logger.warning(
                "Emitting local control events without trace context; "
                "events will use fallback IDs and cannot be correlated with traces. "
                "Pass trace_id/span_id for full observability."
            )
            _trace_warning_logged = True
        trace_id = trace_id or _FALLBACK_TRACE_ID
        span_id = span_id or _FALLBACK_SPAN_ID

    applies_to = _map_applies_to(request.step.type)
    control_lookup = {c.id: c for c in local_controls}
    now = datetime.now(UTC)
    resolved_agent_name = agent_name or request.agent_name

    def _emit_matches(matches: list[ControlMatch] | None, matched: bool) -> None:
        if not matches:
            return
        for match in matches:
            ctrl = control_lookup.get(match.control_id)
            add_event(
                ControlExecutionEvent(
                    control_execution_id=match.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_name=resolved_agent_name,
                    control_id=match.control_id,
                    control_name=match.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=match.action,
                    matched=matched,
                    confidence=match.result.confidence,
                    timestamp=now,
                    evaluator_name=ctrl.control.evaluator.name if ctrl else None,
                    selector_path=ctrl.control.selector.path if ctrl else None,
                    error_message=match.result.error if not matched else None,
                    metadata=match.result.metadata or {},
                )
            )

    _emit_matches(local_result.matches, matched=True)
    _emit_matches(local_result.errors, matched=False)
    _emit_matches(local_result.non_matches, matched=False)


async def check_evaluation(
    client: AgentControlClient,
    agent_name: str,
    step: "Step",
    stage: Literal["pre", "post"],
) -> EvaluationResult:
    """Check if agent interaction is safe."""
    normalized_name = ensure_agent_name(agent_name)

    request = EvaluationRequest(
        agent_name=normalized_name,
        step=step,
        stage=stage,
    )
    request_payload = request.model_dump(mode="json")

    response = await client.http_client.post("/api/v1/evaluation", json=request_payload)
    response.raise_for_status()

    return cast(EvaluationResult, EvaluationResult.from_dict(response.json()))


@dataclass
class _ControlAdapter:
    """Adapts a control dict (from initAgent) to the ControlWithIdentity protocol."""

    id: int
    name: str
    control: "ControlDefinition"


def _merge_results(
    local_result: "EvaluationResponse",
    server_result: "EvaluationResponse",
) -> "EvaluationResult":
    """Merge local and server evaluation results."""
    is_safe = local_result.is_safe and server_result.is_safe
    confidence = min(local_result.confidence, server_result.confidence)

    matches: list[ControlMatch] | None = None
    if local_result.matches or server_result.matches:
        matches = (local_result.matches or []) + (server_result.matches or [])

    errors: list[ControlMatch] | None = None
    if local_result.errors or server_result.errors:
        errors = (local_result.errors or []) + (server_result.errors or [])

    non_matches: list[ControlMatch] | None = None
    if local_result.non_matches or server_result.non_matches:
        non_matches = (local_result.non_matches or []) + (server_result.non_matches or [])

    reason = None
    if local_result.reason and server_result.reason:
        reason = f"{local_result.reason}; {server_result.reason}"
    elif local_result.reason:
        reason = local_result.reason
    elif server_result.reason:
        reason = server_result.reason

    return EvaluationResult(
        is_safe=is_safe,
        confidence=confidence,
        reason=reason,
        matches=matches if matches else None,
        errors=errors if errors else None,
        non_matches=non_matches if non_matches else None,
    )


async def check_evaluation_with_local(
    client: AgentControlClient,
    agent_name: str,
    step: "Step",
    stage: Literal["pre", "post"],
    controls: list[dict[str, Any]],
    trace_id: str | None = None,
    span_id: str | None = None,
    event_agent_name: str | None = None,
) -> EvaluationResult:
    """
    Check if agent interaction is safe, running local controls first.

    This function executes controls with execution="sdk" locally in the SDK,
    then calls the server for execution="server" controls. If a local control
    denies, it short-circuits and returns immediately without calling the server.

    Note on parse errors: If a local control fails to parse/validate, it is
    skipped (logged as WARNING) and the error is included in result.errors.
    This does NOT affect is_safe or confidence—callers concerned with safety
    should check result.errors for any parse failures.

    Args:
        client: AgentControlClient instance
        agent_name: Normalized agent identifier
        step: Step payload to evaluate
        stage: 'pre' for pre-execution check, 'post' for post-execution check
        controls: List of control dicts from initAgent response
                  (each has 'id', 'name', 'control' keys)

    Returns:
        EvaluationResult with safety analysis (merged from local + server)

    Raises:
        httpx.HTTPError: If server request fails
    """
    normalized_name = ensure_agent_name(agent_name)
    # Partition controls by local flag
    local_controls: list[_ControlAdapter] = []
    parse_errors: list[ControlMatch] = []
    has_server_controls = False

    for control in controls:
        control_data = control.get("control", {})
        execution = control_data.get("execution", "server")
        is_local = execution == "sdk"

        if not is_local:
            has_server_controls = True
            continue

        try:
            control_def = ControlDefinition.model_validate(control_data)
            evaluator_name = control_def.evaluator.name

            if ":" in evaluator_name:
                raise RuntimeError(
                    f"Control '{control['name']}' is marked execution='sdk' but uses "
                    f"agent-scoped evaluator '{evaluator_name}' which is server-only. "
                    "Set execution='server' or use a built-in evaluator."
                )
            if evaluator_name not in list_evaluators():
                raise RuntimeError(
                    f"Control '{control['name']}' is marked execution='sdk' but evaluator "
                    f"'{evaluator_name}' is not available in the SDK. "
                    "Install the evaluator or set execution='server'."
                )

            local_controls.append(
                _ControlAdapter(
                    id=control["id"],
                    name=control["name"],
                    control=control_def,
                )
            )
        except RuntimeError:
            raise
        except Exception as exc:
            control_id = control.get("id", -1)
            control_name = control.get("name", "unknown")
            _logger.warning(
                "Skipping invalid local control '%s' (id=%s): %s",
                control_name,
                control_id,
                exc,
            )
            parse_errors.append(
                ControlMatch(
                    control_id=control_id,
                    control_name=control_name,
                    action="log",
                    result=EvaluatorResult(
                        matched=False,
                        confidence=0.0,
                        error=f"Failed to parse local control: {exc}",
                    ),
                    steering_context=None,
                )
            )

    def _with_parse_errors(result: EvaluationResult) -> EvaluationResult:
        if not parse_errors:
            return result
        combined_errors = (result.errors or []) + parse_errors
        return EvaluationResult(
            is_safe=result.is_safe,
            confidence=result.confidence,
            reason=result.reason,
            matches=result.matches,
            errors=combined_errors,
            non_matches=result.non_matches,
        )

    request = EvaluationRequest(
        agent_name=normalized_name,
        step=step,
        stage=stage,
    )

    local_result: EvaluationResponse | None = None
    if local_controls:
        engine = ControlEngine(local_controls, context="sdk")
        local_result = await engine.process(request)

        _emit_local_events(
            local_result,
            request,
            local_controls,
            trace_id,
            span_id,
            agent_name=event_agent_name,
        )

        if not local_result.is_safe:
            return _with_parse_errors(
                EvaluationResult(
                    is_safe=local_result.is_safe,
                    confidence=local_result.confidence,
                    reason=local_result.reason,
                    matches=local_result.matches,
                    errors=local_result.errors,
                    non_matches=local_result.non_matches,
                )
            )

    if has_server_controls:
        request_payload = request.model_dump(mode="json", exclude_none=True)
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        if span_id:
            headers["X-Span-Id"] = span_id

        response = await client.http_client.post(
            "/api/v1/evaluation",
            json=request_payload,
            headers=headers,
        )
        response.raise_for_status()
        server_result = EvaluationResponse.model_validate(response.json())

        if local_result is not None:
            return _with_parse_errors(_merge_results(local_result, server_result))

        return _with_parse_errors(
            EvaluationResult(
                is_safe=server_result.is_safe,
                confidence=server_result.confidence,
                reason=server_result.reason,
                matches=server_result.matches,
                errors=server_result.errors,
                non_matches=server_result.non_matches,
            )
        )

    if local_result is not None:
        return _with_parse_errors(
            EvaluationResult(
                is_safe=local_result.is_safe,
                confidence=local_result.confidence,
                reason=local_result.reason,
                matches=local_result.matches,
                errors=local_result.errors,
                non_matches=local_result.non_matches,
            )
        )

    return _with_parse_errors(EvaluationResult(is_safe=True, confidence=1.0))


async def evaluate_controls(
    step_name: str,
    *,
    input: Any | None = None,
    output: Any | None = None,
    context: dict[str, Any] | None = None,
    step_type: Literal["tool", "llm"] = "llm",
    stage: Literal["pre", "post"] = "pre",
    agent_name: str,
    trace_id: str | None = None,
    span_id: str | None = None,
) -> EvaluationResult:
    """
    Evaluate controls for a step.

    This convenience function evaluates controls (both local SDK-executed and
    server-executed) for a given step.

    Args:
        step_name: Name of the step (e.g., "chat", "search_db")
        input: Input data for the step (for pre-stage evaluation)
        output: Output data from the step (for post-stage evaluation)
        context: Additional context metadata
        step_type: Type of step - "llm" or "tool" (default: "llm")
        stage: When to evaluate - "pre" or "post" (default: "pre")
        agent_name: Agent name (required)
        trace_id: Optional OpenTelemetry trace ID for observability
        span_id: Optional OpenTelemetry span ID for observability

    Returns:
        EvaluationResult with is_safe, confidence, reason, matches, errors

    Raises:
        httpx.HTTPError: If server request fails

    Example:
        import agent_control

        # Evaluate controls for an agent
        result = await agent_control.evaluate_controls(
            "chat",
            input="User message here",
            stage="pre",
            agent_name="customer-service-bot"
        )

        # With trace/span IDs for observability
        result = await agent_control.evaluate_controls(
            "chat",
            input="User message",
            stage="pre",
            agent_name="customer-service-bot",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7"
        )
    """
    # Ensure server_url is set (for mypy type narrowing)
    if state.server_url is None:
        raise RuntimeError(
            "Server URL not configured. Call agent_control.init() first."
        )

    # Build Step dict (input and output are required by Step model)
    # Tool steps require dict input/output, LLM steps use strings
    default_value = {} if step_type == "tool" else ""
    step_dict: dict[str, Any] = {
        "type": step_type,
        "name": step_name,
        "input": input if input is not None else default_value,
        "output": output if output is not None else default_value,
    }
    if context is not None:
        step_dict["context"] = context

    # Convert to Step object if models available
    step_obj = Step(**step_dict)  # type: ignore

    # Get controls from server cache
    resolved_controls = state.server_controls or []

    # Evaluate using local + server controls
    async with AgentControlClient(base_url=state.server_url, api_key=state.api_key) as client:
        result = await check_evaluation_with_local(
            client=client,
            agent_name=agent_name,
            step=step_obj,
            stage=stage,
            controls=resolved_controls,
            trace_id=trace_id,
            span_id=span_id,
            event_agent_name=agent_name,
        )

    return result
