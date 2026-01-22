"""Evaluation check operations for Agent Control SDK."""

import logging
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from .client import AgentControlClient
from .control_decorators import ControlViolationError, HumanReviewRequiredError

_logger = logging.getLogger(__name__)

# Import models if available
try:
    from agent_control_engine import list_plugins
    from agent_control_engine.core import ControlEngine
    from agent_control_models import (
        ControlDefinition,
        ControlMatch,
        EvaluationRequest,
        EvaluationResponse,
        EvaluationResult,
        EvaluatorResult,
        LlmCall,
        ToolCall,
    )

    MODELS_AVAILABLE = True
    ENGINE_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    ENGINE_AVAILABLE = False
    # Runtime fallbacks
    ToolCall = Any  # type: ignore
    LlmCall = Any  # type: ignore
    EvaluationRequest = Any  # type: ignore
    EvaluationResponse = Any  # type: ignore
    EvaluationResult = Any  # type: ignore
    EvaluatorResult = Any  # type: ignore
    ControlDefinition = Any  # type: ignore
    ControlMatch = Any  # type: ignore
    ControlEngine = Any  # type: ignore


def _raise_on_control_violation(result: "EvaluationResult") -> None:
    """
    Check evaluation result and raise appropriate exceptions.

    Args:
        result: EvaluationResult to check

    Raises:
        ControlViolationError: If result.is_safe is False and action is "deny"
        HumanReviewRequiredError: If result.human_review_required is True
    """
    # Check human_review_required at the top level - must raise regardless of matches
    if result.human_review_required:
        matches = result.matches or []

        # Try to find the specific control that triggered human review
        for match in matches:
            if isinstance(match, dict) and match.get("action") == "human_review":
                result_data = match.get("result") or {}
                if isinstance(result_data, dict):
                    message = result_data.get("message", "Control triggered")
                    metadata = result_data.get("metadata", {})
                else:
                    message = "Control triggered"
                    metadata = {}

                raise HumanReviewRequiredError(
                    control_id=match.get("control_id"),
                    control_name=match.get("control_name", "unknown"),
                    message=f"Human review required: {message}",
                    metadata=metadata,
                )

        # If no specific match found, still raise with generic message
        raise HumanReviewRequiredError(
            message="Human review required by policy"
        )

    # Check if unsafe (deny actions)
    if not result.is_safe:
        matches = result.matches or []

        for match in matches:
            if not isinstance(match, dict):
                continue

            action = match.get("action", "deny")
            control_id = match.get("control_id")
            control_name = match.get("control_name", "unknown")

            # Safely extract result message and metadata
            result_data = match.get("result") or {}
            if isinstance(result_data, dict):
                message = result_data.get("message", "Control triggered")
                metadata = result_data.get("metadata", {})
            else:
                message = "Control triggered"
                metadata = {}

            if action == "deny":
                raise ControlViolationError(
                    control_id=control_id,
                    control_name=control_name,
                    message=message,
                    metadata=metadata
                )


async def check_evaluation(
    client: AgentControlClient,
    agent_uuid: UUID,
    payload: "ToolCall | LlmCall",
    check_stage: Literal["pre", "post"],
    raise_on_violation: bool = True,
) -> EvaluationResult:
    """
    Check if agent interaction is safe.

    Args:
        client: AgentControlClient instance
        agent_uuid: UUID of the agent making the request
        payload: Either a ToolCall or LlmCall instance
        check_stage: 'pre' for pre-execution check, 'post' for post-execution check
        raise_on_violation: If True (default), raise exceptions when controls trigger.
                           If False, return the result without raising.

    Returns:
        EvaluationResult with safety analysis

    Raises:
        httpx.HTTPError: If request fails
        ControlViolationError: If any control triggers with "deny" action
        (when raise_on_violation=True)
        HumanReviewRequiredError: If any control triggers with
        "human_review" action (when raise_on_violation=True)

    Example:
        # Pre-check before LLM call (raises exceptions on control violations)
        async with AgentControlClient() as client:
            try:
                result = await check_evaluation(
                    client=client,
                    agent_uuid=agent.agent_id,
                    payload=LlmCall(input="User question", output=None),
                    check_stage="pre"
                )
            except HumanReviewRequiredError as e:
                print(f"Human review required: {e.message}")
                # Handle human review workflow
            except ControlViolationError as e:
                print(f"Denied by control: {e.message}")

        # Post-check after tool execution (without raising exceptions)
        async with AgentControlClient() as client:
            result = await check_evaluation(
                client=client,
                agent_uuid=agent.agent_id,
                payload=ToolCall(
                    tool_name="search",
                    arguments={"query": "test"},
                    output={"results": []}
                ),
                check_stage="post",
                raise_on_violation=False
            )
            if not result.is_safe:
                print("Control violation detected")
    """
    if MODELS_AVAILABLE:
        request = EvaluationRequest(
            agent_uuid=agent_uuid,
            payload=payload,
            check_stage=check_stage
        )
        request_payload = request.model_dump(mode="json")
    else:
        # Fallback for when models aren't available
        payload_dict = {
            "tool_name": getattr(payload, "tool_name", None),
            "arguments": getattr(payload, "arguments", None),
            "input": getattr(payload, "input", None),
            "output": getattr(payload, "output", None),
            "context": getattr(payload, "context", None),
        }
        # Remove None values
        payload_dict = {k: v for k, v in payload_dict.items() if v is not None}

        request_payload = {
            "agent_uuid": str(agent_uuid),
            "payload": payload_dict,
            "check_stage": check_stage,
        }

    response = await client.http_client.post("/api/v1/evaluation", json=request_payload)
    response.raise_for_status()

    if MODELS_AVAILABLE:
        result = cast(EvaluationResult, EvaluationResult.from_dict(response.json()))
    else:
        data = response.json()
        # Create a simple result object
        class _EvaluationResult:
            def __init__(self, is_safe: bool, confidence: float, reason: str | None = None,
                        human_review_required: bool = False,
                        matches: list | None = None,
                        errors: list | None = None):
                self.is_safe = is_safe
                self.confidence = confidence
                self.reason = reason
                self.human_review_required = human_review_required
                self.matches = matches
                self.errors = errors
        result = cast(EvaluationResult, _EvaluationResult(**data))

    # Raise exceptions if controls triggered and raise_on_violation is True
    if raise_on_violation:
        _raise_on_control_violation(result)

    return result


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
    - human_review_required: True if either requires review
    - confidence: min of both (most conservative)
    - matches: combined from both
    - errors: combined from both
    """
    is_safe = local_result.is_safe and server_result.is_safe

    # If either requires human review, flag it
    human_review_required = (
        local_result.human_review_required
        or server_result.human_review_required
    )

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
        human_review_required=human_review_required,
        matches=matches if matches else None,
        errors=errors if errors else None,
    )


async def check_evaluation_with_local(
    client: AgentControlClient,
    agent_uuid: UUID,
    payload: "ToolCall | LlmCall",
    check_stage: Literal["pre", "post"],
    controls: list[dict[str, Any]],
) -> EvaluationResult:
    """
    Check if agent interaction is safe, running local controls first.

    This function executes controls with `local=True` locally in the SDK,
    then calls the server for `local=False` controls. If a local control
    denies, it short-circuits and returns immediately without calling the server.

    Note on parse errors: If a local control fails to parse/validate, it is
    skipped (logged as WARNING) and the error is included in result.errors.
    This does NOT affect is_safe or confidence—callers concerned with safety
    should check result.errors for any parse failures.

    Args:
        client: AgentControlClient instance
        agent_uuid: UUID of the agent making the request
        payload: Either a ToolCall or LlmCall instance
        check_stage: 'pre' for pre-execution check, 'post' for post-execution check
        controls: List of control dicts from initAgent response
                  (each has 'id', 'name', 'control' keys)

    Returns:
        EvaluationResult with safety analysis (merged from local + server)

    Raises:
        httpx.HTTPError: If server request fails
        RuntimeError: If engine is not available

    Example:
        # Get controls from initAgent
        init_response = await register_agent(client, agent, tools)
        controls = init_response.get('controls', [])

        # Check with local execution
        result = await check_evaluation_with_local(
            client=client,
            agent_uuid=agent.agent_id,
            payload=LlmCall(input="User question", output=None),
            check_stage="pre",
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
        is_local = control_data.get("local", False)

        # Track server controls early, before any parsing that might fail
        if not is_local:
            has_server_controls = True
            continue  # Server controls are handled by the server, not parsed here

        # Parse and validate local controls
        try:
            control_def = ControlDefinition.model_validate(control_data)

            # Validate plugin is available locally
            plugin_name = control_def.evaluator.plugin
            # Agent-scoped plugins (agent:evaluator) are server-only
            if ":" in plugin_name:
                raise RuntimeError(
                    f"Control '{c['name']}' is marked local=True but uses "
                    f"agent-scoped evaluator '{plugin_name}' which is server-only. "
                    f"Set local=False or use a built-in plugin."
                )
            if plugin_name not in list_plugins():
                raise RuntimeError(
                    f"Control '{c['name']}' is marked local=True but plugin "
                    f"'{plugin_name}' is not available in the SDK. "
                    f"Install the plugin or set local=False."
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
            human_review_required=result.human_review_required,
            matches=result.matches,
            errors=combined_errors,
        )

    # Build evaluation request
    request = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=payload,
        check_stage=check_stage,
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
                    human_review_required=local_result.human_review_required,
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
                human_review_required=server_result.human_review_required,
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
                human_review_required=local_result.human_review_required,
                matches=local_result.matches,
                errors=local_result.errors,
            )
        )

    # No controls at all - still include parse_errors if any
    return _with_parse_errors(EvaluationResult(is_safe=True, confidence=1.0))

