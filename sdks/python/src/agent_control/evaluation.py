"""Evaluation check operations for Agent Control SDK."""

from dataclasses import dataclass
from typing import Any, Literal, cast

from agent_control_engine import list_evaluators
from agent_control_engine.core import ControlEngine
from agent_control_models import (
    ControlDefinition,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationResult,
    EvaluatorResult,
    Step,
)

from ._state import state
from .client import AgentControlClient
from .evaluation_events import build_control_execution_events, enqueue_observability_events
from .observability import is_observability_enabled
from .tracing import get_trace_and_span_ids
from .validation import ensure_agent_name


@dataclass
class _ControlAdapter:
    """Adapts a control dict (from initAgent) to the ControlWithIdentity protocol."""

    id: int
    name: str
    control: ControlDefinition


def _get_applicable_controls(
    controls: list[_ControlAdapter],
    request: EvaluationRequest,
    *,
    context: Literal["sdk", "server"],
) -> list[_ControlAdapter]:
    """Return parsed controls that apply to this request in the given context."""
    applicable_controls = ControlEngine(
        controls,
        context=context,
    ).get_applicable_controls(request)
    return cast(list[_ControlAdapter], applicable_controls)


def _build_server_control_lookup(
    server_control_payloads: list[dict[str, Any]],
) -> dict[int, ControlDefinition]:
    """Build a best-effort lookup of server control definitions."""
    control_lookup: dict[int, ControlDefinition] = {}

    for control in server_control_payloads:
        try:
            control_lookup[control["id"]] = ControlDefinition.model_validate(control["control"])
        except Exception:
            continue

    return control_lookup


def _has_applicable_prefiltered_server_controls(
    server_control_payloads: list[dict[str, Any]],
    request: EvaluationRequest,
) -> bool:
    """Return whether any partitioned server control applies to this request."""
    parsed_server_controls: list[_ControlAdapter] = []

    for control in server_control_payloads:
        try:
            control_def = ControlDefinition.model_validate(control["control"])
            parsed_server_controls.append(
                _ControlAdapter(
                    id=control["id"],
                    name=control["name"],
                    control=control_def,
                )
            )
        except Exception:
            return True

    if not parsed_server_controls:
        return False

    return bool(
        _get_applicable_controls(
            parsed_server_controls,
            request,
            context="server",
        )
    )


def _merge_results(
    local_result: EvaluationResponse,
    server_result: EvaluationResponse,
) -> EvaluationResult:
    """Merge local and server evaluation results into one SDK-facing result."""
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


def _cached_server_control_lookup(
    agent_name: str,
    client: AgentControlClient,
) -> dict[int, ControlDefinition]:
    """Return cached server controls for the active session when they are trustworthy."""
    current_agent = state.current_agent
    if current_agent is None or current_agent.agent_name != agent_name:
        return {}
    if state.server_controls is None:
        return {}
    if state.server_url is not None:
        if client.base_url.rstrip("/") != state.server_url.rstrip("/"):
            return {}
    return _build_server_control_lookup(state.server_controls)


async def check_evaluation(
    client: AgentControlClient,
    agent_name: str,
    step: Step,
    stage: Literal["pre", "post"],
) -> EvaluationResult:
    """Check if agent interaction is safe through the public SDK helper.

    The server returns only evaluation semantics. When SDK observability is
    enabled, this helper reconstructs server-side control-execution events
    from the response and enqueues them through the built-in SDK batcher.
    """
    normalized_name = ensure_agent_name(agent_name)
    resolved_trace_id, resolved_span_id = get_trace_and_span_ids()
    request = EvaluationRequest(
        agent_name=normalized_name,
        step=step,
        stage=stage,
    )
    request_payload = request.model_dump(mode="json")

    response = await client.http_client.post(
        "/api/v1/evaluation",
        json=request_payload,
        headers=None,
    )
    response.raise_for_status()

    evaluation_response = EvaluationResponse.model_validate(response.json())

    if is_observability_enabled():
        server_events = build_control_execution_events(
            evaluation_response,
            request,
            _cached_server_control_lookup(normalized_name, client),
            resolved_trace_id,
            resolved_span_id,
            normalized_name,
        )
        enqueue_observability_events(server_events)

    return cast(EvaluationResult, EvaluationResult.from_dict(evaluation_response.model_dump()))


async def check_evaluation_with_local(
    client: AgentControlClient,
    agent_name: str,
    step: Step,
    stage: Literal["pre", "post"],
    controls: list[dict[str, Any]],
    trace_id: str | None = None,
    span_id: str | None = None,
    event_agent_name: str | None = None,
) -> EvaluationResult:
    """Evaluate controls with local-first execution and SDK-owned event emission."""
    normalized_name = ensure_agent_name(agent_name)
    resolved_trace_id = trace_id
    resolved_span_id = span_id
    if trace_id is None or span_id is None:
        current_trace_id, current_span_id = get_trace_and_span_ids()
        resolved_trace_id = trace_id or current_trace_id
        resolved_span_id = span_id or current_span_id

    local_controls: list[_ControlAdapter] = []
    parse_errors: list[ControlMatch] = []
    available_evaluators = list_evaluators()
    server_control_payloads: list[dict[str, Any]] = []

    for control in controls:
        control_data = control.get("control", {})
        execution = control_data.get("execution", "server")
        is_local = execution == "sdk"

        if not is_local:
            server_control_payloads.append(control)
            continue

        try:
            control_def = ControlDefinition.model_validate(control_data)
            for _, evaluator_spec in control_def.iter_condition_leaf_parts():
                evaluator_name = evaluator_spec.name

                if ":" in evaluator_name:
                    raise RuntimeError(
                        f"Control '{control['name']}' is marked execution='sdk' but uses "
                        f"agent-scoped evaluator '{evaluator_name}' which is server-only. "
                        "Set execution='server' or use a built-in evaluator."
                    )
                if evaluator_name not in available_evaluators:
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
            parse_errors.append(
                ControlMatch(
                    control_id=control_id,
                    control_name=control_name,
                    action="observe",
                    result=EvaluatorResult(
                        matched=False,
                        confidence=0.0,
                        error=f"Failed to parse local control: {exc}",
                    ),
                    steering_context=None,
                )
            )

    request = EvaluationRequest(
        agent_name=normalized_name,
        step=step,
        stage=stage,
    )

    def _with_parse_errors(result: EvaluationResult) -> EvaluationResult:
        if not parse_errors:
            return result
        combined_errors = (result.errors or []) + parse_errors
        return result.model_copy(update={"errors": combined_errors})

    should_emit_events = is_observability_enabled()

    local_result: EvaluationResponse | None = None
    local_events = []
    applicable_local_controls = _get_applicable_controls(
        local_controls,
        request,
        context="sdk",
    )
    if applicable_local_controls:
        engine = ControlEngine(applicable_local_controls, context="sdk")
        local_result = await engine.process(request)
        if should_emit_events:
            local_control_lookup = {
                control.id: control.control for control in applicable_local_controls
            }
            local_events = build_control_execution_events(
                local_result,
                request,
                local_control_lookup,
                resolved_trace_id,
                resolved_span_id,
                event_agent_name,
            )

        if not local_result.is_safe:
            result = _with_parse_errors(EvaluationResult.model_validate(local_result.model_dump()))
            if should_emit_events:
                enqueue_observability_events(local_events)
            return result

    if _has_applicable_prefiltered_server_controls(server_control_payloads, request):
        request_payload = request.model_dump(mode="json", exclude_none=True)
        headers: dict[str, str] = {}
        if resolved_trace_id:
            headers["X-Trace-Id"] = resolved_trace_id
        if resolved_span_id:
            headers["X-Span-Id"] = resolved_span_id

        try:
            response = await client.http_client.post(
                "/api/v1/evaluation",
                json=request_payload,
                headers=headers,
            )
            response.raise_for_status()
            server_result = EvaluationResponse.model_validate(response.json())
        except Exception:
            if should_emit_events and local_events:
                enqueue_observability_events(local_events)
            raise

        server_events = []
        if should_emit_events:
            server_control_lookup = _build_server_control_lookup(server_control_payloads)
            server_events = build_control_execution_events(
                server_result,
                request,
                server_control_lookup,
                resolved_trace_id,
                resolved_span_id,
                event_agent_name,
            )

        if local_result is not None:
            result = _with_parse_errors(_merge_results(local_result, server_result))
            if should_emit_events:
                enqueue_observability_events(local_events + server_events)
            return result

        result = _with_parse_errors(EvaluationResult.model_validate(server_result.model_dump()))
        if should_emit_events:
            enqueue_observability_events(server_events)
        return result

    if local_result is not None:
        result = _with_parse_errors(EvaluationResult.model_validate(local_result.model_dump()))
        if should_emit_events:
            enqueue_observability_events(local_events)
        return result

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
    """Evaluate controls for a step."""
    if state.server_url is None:
        raise RuntimeError("Server URL not configured. Call agent_control.init() first.")

    default_value = {} if step_type == "tool" else ""
    step_dict: dict[str, Any] = {
        "type": step_type,
        "name": step_name,
        "input": input if input is not None else default_value,
        "output": output if output is not None else default_value,
    }
    if context is not None:
        step_dict["context"] = context

    step_obj = Step(**step_dict)  # type: ignore[arg-type]
    resolved_controls = state.server_controls or []

    async with AgentControlClient(base_url=state.server_url, api_key=state.api_key) as client:
        return await check_evaluation_with_local(
            client=client,
            agent_name=agent_name,
            step=step_obj,
            stage=stage,
            controls=resolved_controls,
            trace_id=trace_id,
            span_id=span_id,
            event_agent_name=agent_name,
        )
