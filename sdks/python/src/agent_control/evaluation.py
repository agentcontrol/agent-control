"""Evaluation check operations for Agent Control SDK."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from .client import AgentControlClient
from .observability import add_event, get_logger, is_observability_enabled

_logger = get_logger(__name__)

# Fallback IDs used when trace context is missing.
# All-zero values are invalid trace/span IDs per OpenTelemetry, making them
# easy to filter in observability queries while still recording the event.
_FALLBACK_TRACE_ID = "0" * 32
_FALLBACK_SPAN_ID = "0" * 16
_trace_warning_logged = False

# Import models if available
try:
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

    MODELS_AVAILABLE = True
    ENGINE_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    ENGINE_AVAILABLE = False
    # Runtime fallbacks
    Step = Any  # type: ignore
    EvaluationRequest = Any  # type: ignore
    EvaluationResponse = Any  # type: ignore
    EvaluationResult = Any  # type: ignore
    EvaluatorResult = Any  # type: ignore
    ControlDefinition = Any  # type: ignore
    ControlMatch = Any  # type: ignore
    ControlEngine = Any  # type: ignore
    ControlExecutionEvent = Any  # type: ignore


def _map_applies_to(step_type: str) -> Literal["llm_call", "tool_call"]:
    """Map step type to observability applies_to value.

    Matches the server pattern at endpoints/evaluation.py.
    """
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
    if not ENGINE_AVAILABLE:
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

    def _emit_matches(matches: list[ControlMatch] | None, matched: bool) -> None:
        if not matches:
            return
        for m in matches:
            ctrl = control_lookup.get(m.control_id)
            add_event(
                ControlExecutionEvent(
                    control_execution_id=m.control_execution_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    agent_uuid=request.agent_uuid,
                    agent_name=agent_name or "unknown",
                    control_id=m.control_id,
                    control_name=m.control_name,
                    check_stage=request.stage,
                    applies_to=applies_to,
                    action=m.action,
                    matched=matched,
                    confidence=m.result.confidence,
                    timestamp=now,
                    evaluator_name=ctrl.control.evaluator.name if ctrl else None,
                    selector_path=ctrl.control.selector.path if ctrl else None,
                    error_message=m.result.error if not matched else None,
                    metadata=m.result.metadata or {},
                )
            )

    _emit_matches(local_result.matches, matched=True)
    _emit_matches(local_result.errors, matched=False)
    _emit_matches(local_result.non_matches, matched=False)


async def check_evaluation(
    client: AgentControlClient,
    agent_uuid: UUID,
    step: "Step",
    stage: Literal["pre", "post"],
) -> EvaluationResult:
    """
    Check if agent interaction is safe.

    Args:
        client: AgentControlClient instance
        agent_uuid: UUID of the agent making the request
        step: Step payload to evaluate
        stage: 'pre' for pre-execution check, 'post' for post-execution check

    Returns:
        EvaluationResult with safety analysis

    Raises:
        httpx.HTTPError: If request fails

    Example:
        # Pre-check before LLM step
        async with AgentControlClient() as client:
            result = await check_evaluation(
                client=client,
                agent_uuid=agent.agent_id,
                step={"type": "llm", "name": "support-answer", "input": "User question"},
                stage="pre"
            )

        # Post-check after tool execution
        async with AgentControlClient() as client:
            result = await check_evaluation(
                client=client,
                agent_uuid=agent.agent_id,
                step={
                    "type": "tool",
                    "name": "search",
                    "input": {"query": "test"},
                    "output": {"results": []},
                },
                stage="post"
            )
    """
    if MODELS_AVAILABLE:
        request = EvaluationRequest(
            agent_uuid=agent_uuid,
            step=step,
            stage=stage,
        )
        request_payload = request.model_dump(mode="json")
    else:
        # Fallback for when models aren't available
        if isinstance(step, dict):
            step_dict = step
        else:
            step_dict = {
                "type": getattr(step, "type", None),
                "name": getattr(step, "name", None),
                "input": getattr(step, "input", None),
                "output": getattr(step, "output", None),
                "context": getattr(step, "context", None),
            }
            step_dict = {k: v for k, v in step_dict.items() if v is not None}

        if not step_dict.get("name"):
            raise ValueError("step.name is required for evaluation requests")

        request_payload = {
            "agent_uuid": str(agent_uuid),
            "step": step_dict,
            "stage": stage,
        }

    response = await client.http_client.post("/api/v1/evaluation", json=request_payload)
    response.raise_for_status()

    if MODELS_AVAILABLE:
        return cast(EvaluationResult, EvaluationResult.from_dict(response.json()))
    else:
        data = response.json()
        # Create a simple result object
        class _EvaluationResult:
            def __init__(self, is_safe: bool, confidence: float, reason: str | None = None):
                self.is_safe = is_safe
                self.confidence = confidence
                self.reason = reason
        return cast(EvaluationResult, _EvaluationResult(**data))


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
    """Merge local and server evaluation results.

    Merge semantics:
    - is_safe: False if either is False (deny from either → deny)
    - confidence: min of both (most conservative)
    - matches: combined from both
    - errors: combined from both
    """
    is_safe = local_result.is_safe and server_result.is_safe

    # Use minimum confidence (most conservative)
    confidence = min(local_result.confidence, server_result.confidence)

    # Combine matches
    matches: list[ControlMatch] | None = None
    if local_result.matches or server_result.matches:
        matches = (local_result.matches or []) + (server_result.matches or [])

    # Combine errors
    errors: list[ControlMatch] | None = None
    if local_result.errors or server_result.errors:
        errors = (local_result.errors or []) + (server_result.errors or [])

    # Combine non_matches
    non_matches: list[ControlMatch] | None = None
    if local_result.non_matches or server_result.non_matches:
        non_matches = (local_result.non_matches or []) + (server_result.non_matches or [])

    # Combine reasons
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
    agent_uuid: UUID,
    step: "Step",
    stage: Literal["pre", "post"],
    controls: list[dict[str, Any]],
    trace_id: str | None = None,
    span_id: str | None = None,
    agent_name: str | None = None,
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
        agent_uuid: UUID of the agent making the request
        step: Step payload to evaluate
        stage: 'pre' for pre-execution check, 'post' for post-execution check
        controls: List of control dicts from initAgent response
                  (each has 'id', 'name', 'control' keys)

    Returns:
        EvaluationResult with safety analysis (merged from local + server)

    Raises:
        httpx.HTTPError: If server request fails
        RuntimeError: If engine is not available

    Example:
        # Get controls from initAgent
        init_response = await register_agent(client, agent, steps)
        controls = init_response.get('controls', [])

        # Check with local execution
        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent.agent_id,
            step={"type": "llm", "name": "support-answer", "input": "User question"},
            stage="pre",
            controls=controls,
        )
    """
    if not ENGINE_AVAILABLE:
        raise RuntimeError(
            "Local evaluation requires agent_control_engine. "
            "Install with: pip install agent-control-engine"
        )

    # Partition controls by local flag
    local_controls: list[_ControlAdapter] = []
    parse_errors: list[ControlMatch] = []
    has_server_controls = False

    for c in controls:
        control_data = c.get("control", {})
        execution = control_data.get("execution", "server")
        is_local = execution == "sdk"

        # Track server controls early, before any parsing that might fail
        if not is_local:
            has_server_controls = True
            continue  # Server controls are handled by the server, not parsed here

        # Parse and validate local controls
        try:
            control_def = ControlDefinition.model_validate(control_data)

            # Validate evaluator is available locally
            evaluator_name = control_def.evaluator.name
            # Agent-scoped evaluators (agent:evaluator) are server-only
            if ":" in evaluator_name:
                raise RuntimeError(
                    f"Control '{c['name']}' is marked execution='sdk' but uses "
                    f"agent-scoped evaluator '{evaluator_name}' which is server-only. "
                    "Set execution='server' or use a built-in evaluator."
                )
            if evaluator_name not in list_evaluators():
                raise RuntimeError(
                    f"Control '{c['name']}' is marked execution='sdk' but evaluator "
                    f"'{evaluator_name}' is not available in the SDK. "
                    "Install the evaluator or set execution='server'."
                )

            local_controls.append(_ControlAdapter(
                id=c["id"],
                name=c["name"],
                control=control_def,
            ))
        except RuntimeError:
            # Re-raise our explicit errors
            raise
        except Exception as e:
            # Validation/parse error - log and add to errors list
            control_id = c.get("id", -1)
            control_name = c.get("name", "unknown")
            _logger.warning(
                "Skipping invalid local control '%s' (id=%s): %s",
                control_name,
                control_id,
                e,
            )
            parse_errors.append(
                ControlMatch(
                    control_id=control_id,
                    control_name=control_name,
                    action="log",
                    result=EvaluatorResult(
                        matched=False,
                        confidence=0.0,
                        error=f"Failed to parse local control: {e}",
                    ),
                )
            )

    def _with_parse_errors(result: EvaluationResult) -> EvaluationResult:
        """Merge parse_errors into result.errors."""
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

    # Build evaluation request
    request = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=step,
        stage=stage,
    )

    # Run local controls if any
    local_result: EvaluationResponse | None = None
    if local_controls:
        engine = ControlEngine(local_controls, context="sdk")
        local_result = await engine.process(request)

        # Emit observability events for locally-evaluated controls
        # (before short-circuit so events are always emitted for local controls)
        _emit_local_events(
            local_result, request, local_controls,
            trace_id, span_id, agent_name,
        )

        # Short-circuit on local deny
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

    # Call server for non-local controls (if any exist)
    if has_server_controls:
        request_payload = request.model_dump(mode="json", exclude_none=True)
        # Forward trace context as headers so server-emitted events have correct IDs
        headers: dict[str, str] = {}
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        if span_id:
            headers["X-Span-Id"] = span_id
        response = await client.http_client.post(
            "/api/v1/evaluation", json=request_payload, headers=headers,
        )
        response.raise_for_status()
        server_result = EvaluationResponse.model_validate(response.json())

        # Merge results if we had local controls
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

    # Only local controls existed (and they all passed)
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

    # No controls at all - still include parse_errors if any
    return _with_parse_errors(EvaluationResult(is_safe=True, confidence=1.0))
