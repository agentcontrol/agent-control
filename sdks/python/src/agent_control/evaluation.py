"""Evaluation check operations for Agent Control SDK."""

from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from .client import AgentControlClient
from .observability import get_logger

_logger = get_logger(__name__)

# Import models if available
try:
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
    )


async def check_evaluation_with_local(
    client: AgentControlClient,
    agent_uuid: UUID,
    step: "Step",
    stage: Literal["pre", "post"],
    controls: list[dict[str, Any]],
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

        # Short-circuit on local deny
        if not local_result.is_safe:
            return _with_parse_errors(
                EvaluationResult(
                    is_safe=local_result.is_safe,
                    confidence=local_result.confidence,
                    reason=local_result.reason,
                    matches=local_result.matches,
                    errors=local_result.errors,
                )
            )

    # Call server for non-local controls (if any exist)
    if has_server_controls:
        request_payload = request.model_dump(mode="json", exclude_none=True)
        response = await client.http_client.post("/api/v1/evaluation", json=request_payload)
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
            )
        )

    # No controls at all - still include parse_errors if any
    return _with_parse_errors(EvaluationResult(is_safe=True, confidence=1.0))
