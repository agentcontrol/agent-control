"""
Control decorator for server-side protection of agent functions.

This module provides a decorator that applies server-defined controls to agent functions.
Controls can be associated via policies and direct agent-control links.

Architecture:
    SERVER defines: Policies -> Controls (stage, selector, evaluator, action)
    SDK decorator: just marks WHERE controls are evaluated

Usage:
    import agent_control

    agent_control.init(
        agent_name="my-agent-identity",
    )

    # Apply controls associated with the agent
    @agent_control.control()
    async def chat(message: str) -> str:
        return await assistant.respond(message)

    # Server-side controls define:
    # - stage: "pre" or "post"
    # - selector.path: "input" or "output"
    # - evaluator: regex, list, Luna2 evaluator, etc.
    # - action: deny, warn, or log
"""

import asyncio
import functools
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from agent_control_models import Step

from agent_control import AgentControlClient
from agent_control.evaluation import check_evaluation_with_local
from agent_control.observability import (
    get_logger,
    log_control_evaluation,
    log_span_end,
    log_span_start,
)
from agent_control.settings import get_settings
from agent_control.tracing import _generate_span_id, get_current_trace_id, get_trace_and_span_ids

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class ControlContext:
    """
    Holds state during control execution.

    This class encapsulates all the shared logic between async and sync
    control wrappers, including stats tracking, result processing, and logging.
    """

    agent_name: str
    server_url: str
    func: Callable
    args: tuple
    kwargs: dict
    trace_id: str
    span_id: str
    start_time: float
    step_name: str | None = None

    # Stats (mutually exclusive: errors vs matches vs non_matches)
    total_executions: int = 0
    total_matches: int = 0
    total_non_matches: int = 0
    total_errors: int = 0
    actions: dict[str, int] = field(default_factory=dict)

    def log_start(self) -> None:
        """Log span start."""
        log_span_start(self.trace_id, self.span_id, self.func.__name__, self.agent_name)

    def log_end(self) -> None:
        """Log span end with accumulated stats."""
        duration_ms = (time.perf_counter() - self.start_time) * 1000
        log_span_end(
            self.trace_id,
            self.span_id,
            self.func.__name__,
            duration_ms,
            executions=self.total_executions,
            matches=self.total_matches,
            non_matches=self.total_non_matches,
            errors=self.total_errors,
            actions=self.actions if self.actions else None,
        )

    def pre_payload(self) -> dict[str, Any]:
        """Build payload for pre-execution check (supports tool call detection)."""
        return _create_evaluation_payload(
            self.func, self.args, self.kwargs, output=None, step_name=self.step_name
        )

    def post_payload(self, output: Any) -> dict[str, Any]:
        """Build payload for post-execution check (supports tool call detection)."""
        return _create_evaluation_payload(
            self.func, self.args, self.kwargs, output=output, step_name=self.step_name
        )

    def process_result(self, result: dict[str, Any], check_stage: str) -> None:
        """
        Process evaluation result: log, handle actions, update stats.

        Args:
            result: Server evaluation response
            check_stage: "pre" or "post"

        Raises:
            ControlViolationError: If any control triggers with "deny" action
            ControlSteerError: If any control triggers with "steer" action
        """
        # Log each control evaluation
        _log_control_evaluations(result, self.trace_id, self.span_id, check_stage)

        # Handle deny/steer/warn/log actions (may raise ControlViolationError, ControlSteerError)
        _handle_evaluation_result(result)

        # Update stats in place
        self._update_stats(result)

    def _update_stats(self, result: dict[str, Any]) -> None:
        """
        Update stats in place from evaluation result.

        The server returns three mutually exclusive lists:
        - matches: controls where condition matched
        - non_matches: controls that were evaluated but didn't match
        - errors: controls that failed during evaluation
        """
        # Process matches (controls that matched)
        for match in result.get("matches") or []:
            self.total_executions += 1
            self.total_matches += 1
            action = match.get("action", "allow")
            self.actions[action] = self.actions.get(action, 0) + 1

        # Process non-matches (controls evaluated but didn't match)
        for _ in result.get("non_matches") or []:
            self.total_executions += 1
            self.total_non_matches += 1

        # Process errors (controls that failed evaluation)
        for _ in result.get("errors") or []:
            self.total_executions += 1
            self.total_errors += 1


class ControlViolationError(Exception):
    """Raised when a control is triggered with 'deny' action."""

    def __init__(
        self,
        control_id: int | str | None = None,
        control_name: str | None = None,
        message: str = "Control violation",
        metadata: dict[str, Any] | None = None
    ):
        self.control_id = control_id
        self.control_name = control_name or (str(control_id) if control_id else "unknown")
        self.message = message
        self.metadata = metadata or {}
        super().__init__(f"Control violation [{self.control_name}]: {message}")


class ControlSteerError(Exception):
    """Raised when a control is triggered with 'steer' action.

    This error indicates the agent should modify its approach based on
    the provided steering context and potentially retry the operation.

    Unlike ControlViolationError (deny), this is not a hard block but
    a corrective signal that allows the application to adjust and retry.
    """

    def __init__(
        self,
        control_id: int | str | None = None,
        control_name: str | None = None,
        message: str = "Control steering required",
        metadata: dict[str, Any] | None = None,
        steering_context: str | None = None,
        input_data: Any | None = None,
        output_data: Any | None = None
    ):
        self.control_id = control_id
        self.control_name = control_name or (str(control_id) if control_id else "unknown")
        self.message = message
        self.metadata = metadata or {}
        self.steering_context = steering_context or self.metadata.get(
            "steering_context", "No steering context provided"
        )
        self.input_data = input_data
        self.output_data = output_data
        super().__init__(
            f"Control steering [{self.control_name}]: {message}\n"
            f"Steering context: {self.steering_context}"
        )


def _get_current_agent() -> Any | None:
    """Get the current agent from agent_control module."""
    try:
        import agent_control
        return agent_control.current_agent()
    except Exception:
        return None


def _get_server_url() -> str:
    """Get the server URL from settings."""
    return get_settings().url


async def _evaluate(
    agent_name: str,
    step: dict[str, Any],
    stage: str,
    server_url: str,
    trace_id: str | None = None,
    span_id: str | None = None,
    controls: list[dict[str, Any]] | None = None,
    event_agent_name: str | None = None,
) -> dict[str, Any]:
    """Call evaluation with support for local (SDK) and server execution.

    If controls are provided, uses check_evaluation_with_local() which:
    - Evaluates execution="sdk" controls locally in the SDK
    - Sends execution="server" controls to the server

    If no controls provided, falls back to server-only evaluation.
    """
    # Build headers with trace/span IDs for distributed tracing
    headers = {}
    if trace_id:
        headers["X-Trace-Id"] = trace_id
    if span_id:
        headers["X-Span-Id"] = span_id

    async with AgentControlClient(base_url=server_url) as client:
        # If we have controls, use local evaluation which handles both SDK and server controls
        if controls is not None:
            try:
                # Build Step object for evaluation
                step_obj = Step(**step)

                result = await check_evaluation_with_local(
                    client=client,
                    agent_name=agent_name,
                    step=step_obj,
                    stage=stage,  # type: ignore
                    controls=controls,
                    trace_id=trace_id,
                    span_id=span_id,
                    event_agent_name=event_agent_name,
                )

                # Convert result to dict format expected by process_result
                # Build a lookup map for control definitions by ID
                control_defs_by_id = {
                    c.get("id"): c.get("control", {})
                    for c in controls if isinstance(c, dict)
                }

                return {
                    "is_safe": result.is_safe,
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "matches": [
                        {
                            "control_id": m.control_id,
                            "control_name": m.control_name,
                            "action": m.action,
                            "control": control_defs_by_id.get(m.control_id, {}),
                            "result": {
                                "matched": m.result.matched,
                                "confidence": m.result.confidence,
                                "message": m.result.message,
                                "error": m.result.error,
                                "metadata": m.result.metadata,
                            },
                            "control_execution_id": m.control_execution_id,
                            "steering_context": (
                                {"message": m.steering_context.message}
                                if m.steering_context else None
                            ),
                        }
                        for m in (result.matches or [])
                    ] if result.matches else None,
                    "errors": [
                        {
                            "control_id": e.control_id,
                            "control_name": e.control_name,
                            "action": e.action,
                            "control": control_defs_by_id.get(e.control_id, {}),
                            "result": {
                                "matched": e.result.matched,
                                "confidence": e.result.confidence,
                                "message": e.result.message,
                                "error": e.result.error,
                                "metadata": e.result.metadata,
                            },
                            "control_execution_id": e.control_execution_id,
                            "steering_context": (
                                {"message": e.steering_context.message}
                                if e.steering_context else None
                            ),
                        }
                        for e in (result.errors or [])
                    ] if result.errors else None,
                    "non_matches": [
                        {
                            "control_id": nm.control_id,
                            "control_name": nm.control_name,
                            "action": nm.action,
                            "control": control_defs_by_id.get(nm.control_id, {}),
                            "result": {
                                "matched": nm.result.matched,
                                "confidence": nm.result.confidence,
                                "message": nm.result.message,
                                "error": nm.result.error,
                                "metadata": nm.result.metadata,
                            },
                            "control_execution_id": nm.control_execution_id,
                            "steering_context": (
                                {"message": nm.steering_context.message}
                                if nm.steering_context else None
                            ),
                        }
                        for nm in (result.non_matches or [])
                    ] if result.non_matches else None,
                }
            except Exception as e:
                logger.warning(
                    "Local evaluation failed: %s. Falling back to server-only evaluation.",
                    e,
                )

        # Fallback: server-only evaluation
        response = await client.http_client.post(
            "/api/v1/evaluation",
            json={
                "agent_name": str(agent_name),
                "step": step,
                "stage": stage
            },
            headers=headers,
        )
        response.raise_for_status()
        result_dict: dict[str, Any] = response.json()
        return result_dict


def _extract_input_from_args(func: Callable, args: tuple, kwargs: dict) -> str:
    """
    Extract input data from function arguments.

    Tries common parameter names, then falls back to first string argument.
    """
    sig = inspect.signature(func)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()

    # Common input parameter names (in order of preference)
    input_names = ["input", "message", "query", "text", "prompt", "content", "user_input"]

    for name in input_names:
        if name in bound.arguments:
            value = bound.arguments[name]
            if value is not None:
                return str(value)

    # Fall back to first string argument
    for param_name, value in bound.arguments.items():
        if isinstance(value, str):
            return value

    # Last resort: stringify all arguments
    return str(bound.arguments)


def _create_evaluation_payload(
    func: Callable,
    args: tuple,
    kwargs: dict,
    output: Any = None,
    step_name: str | None = None
) -> dict[str, Any]:
    """
    Create evaluation payload for server, detecting if it's a tool step or LLM step.

    Returns a Step payload structure.

    Args:
        func: The function being evaluated
        args: Function positional arguments
        kwargs: Function keyword arguments
        output: Function output (None for pre-execution)
        step_name: Optional explicit step name to override auto-detection
    """
    sig = inspect.signature(func)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()

    # Determine step name priority: explicit step_name > tool_name > func.__name__
    if step_name:
        # Explicit step_name provided - use it
        determined_name = step_name
        # Try to detect if it's a tool based on attributes
        is_tool = (
            getattr(func, "name", None) is not None
            or getattr(func, "tool_name", None) is not None
        )
        step_type = "tool" if is_tool else "llm"
    else:
        # Auto-detect: Check if function has tool_name from @tool decorator
        tool_name = getattr(func, "name", None) or getattr(func, "tool_name", None)
        if tool_name:
            determined_name = tool_name
            step_type = "tool"
        else:
            determined_name = func.__name__
            step_type = "llm"

    if step_type == "tool":
        # This is a tool step
        return {
            "type": "tool",
            "name": determined_name,
            "input": dict(bound.arguments),
            "output": output if isinstance(output, (str, int, float, bool, dict, list)) else (
                None if output is None else str(output)
            ),
        }

    # This is an LLM step
    input_data = _extract_input_from_args(func, args, kwargs)
    return {
        "type": "llm",
        "name": determined_name,
        "input": input_data,
        "output": output if isinstance(output, (str, int, float, bool, dict, list)) else (
            None if output is None else str(output)
        ),
    }


def _handle_evaluation_result(result: dict[str, Any]) -> None:
    """Handle evaluation result from server - raise on deny or steer."""
    if not result:
        logger.warning("Received empty evaluation result from server")
        return

    is_safe = result.get("is_safe", True)
    matches = result.get("matches") or []  # Handle None case
    errors = result.get("errors") or []  # Handle server-side evaluation errors

    # CRITICAL: Check errors array FIRST - server-side failures must block execution
    if errors:
        error_messages = []
        for error in errors:
            if isinstance(error, dict):
                control_name = error.get("control_name", "unknown")
                error_msg = error.get("result", {}).get("message", "Unknown error")
                error_messages.append(f"[{control_name}] {error_msg}")

        raise RuntimeError(
            f"Control evaluation failed on server. Execution blocked for safety.\n"
            f"Errors: {'; '.join(error_messages)}"
        )

    # CRITICAL: Handle actions in priority order: deny > steer > warn > log
    # Check blocking actions first (deny/steer), then always log warn/log

    if not is_safe:
        # Pass 1: Check for deny actions (highest priority - blocks immediately)
        for match in matches:
            if not isinstance(match, dict) or match.get("action", "deny") != "deny":
                continue

            result_data = match.get("result") or {}
            message = (
                result_data.get("message", "Control triggered")
                if isinstance(result_data, dict)
                else "Control triggered"
            )
            metadata = result_data.get("metadata", {}) if isinstance(result_data, dict) else {}
            raise ControlViolationError(
                control_id=match.get("control_id"),
                control_name=match.get("control_name", "unknown"),
                message=message,
                metadata=metadata
            )

        # Pass 2: Check for steer actions (second priority - signals correction needed)
        for match in matches:
            if not isinstance(match, dict) or match.get("action", "deny") != "steer":
                continue

            result_data = match.get("result") or {}
            message = (
                result_data.get("message", "Control triggered")
                if isinstance(result_data, dict)
                else "Control triggered"
            )
            metadata = result_data.get("metadata", {}) if isinstance(result_data, dict) else {}

            # Extract steering_context directly from match (now a first-class field)
            steering_context_obj = match.get("steering_context")

            # Extract message from SteeringContext object or use as string
            if isinstance(steering_context_obj, dict):
                steering_context = steering_context_obj.get("message", message)
            elif isinstance(steering_context_obj, str):
                steering_context = steering_context_obj
            else:
                # No steering context provided, use evaluator message
                steering_context = message

            raise ControlSteerError(
                control_id=match.get("control_id"),
                control_name=match.get("control_name", "unknown"),
                message=message,
                metadata=metadata,
                steering_context=steering_context
            )

    # Log warn and log actions (non-blocking, always processed)
    for match in matches:
        if not isinstance(match, dict):
            continue

        action = match.get("action", "deny")
        if action not in ("warn", "log"):
            continue

        result_data = match.get("result") or {}
        message = (
            result_data.get("message", "Control triggered")
            if isinstance(result_data, dict)
            else "Control triggered"
        )
        control_name = match.get("control_name", "unknown")

        if action == "warn":
            logger.warning(f"⚠️ Control [{control_name}]: {message}")
        else:  # action == "log"
            logger.info(f"ℹ️ Control [{control_name}]: {message}")


def _log_control_evaluations(
    result: dict[str, Any],
    trace_id: str,
    span_id: str,
    check_stage: str,
) -> None:
    """Log each control evaluation from the result for debugging."""
    # Log matches
    for match in result.get("matches") or []:
        _log_single_control(match, trace_id, span_id, check_stage, matched=True)

    # Log errors
    for error in result.get("errors") or []:
        _log_single_control(error, trace_id, span_id, check_stage, matched=False)

    # Log non-matches
    for non_match in result.get("non_matches") or []:
        _log_single_control(non_match, trace_id, span_id, check_stage, matched=False)


def _log_single_control(
    control_data: dict[str, Any],
    trace_id: str,
    span_id: str,
    check_stage: str,
    matched: bool,
) -> None:
    """Log a single control evaluation."""
    log_control_evaluation(
        trace_id=trace_id,
        span_id=span_id,
        control_name=control_data.get("control_name", "unknown"),
        matched=matched,
        action=control_data.get("action", "allow"),
        confidence=control_data.get("result", {}).get("confidence", 0.0),
        duration_ms=control_data.get("result", {}).get("execution_duration_ms"),
        control_execution_id=control_data.get("control_execution_id"),
        check_stage=check_stage,
    )


def _get_server_controls() -> list[dict[str, Any]] | None:
    """Get the cached server controls from agent_control module."""
    try:
        import agent_control
        return agent_control.get_server_controls()
    except Exception as exc:
        logger.debug(
            "Unable to access cached server controls; proceeding without local cache.",
            exc_info=exc,
        )
        return None


async def _execute_with_control(
    func: Callable,
    args: tuple,
    kwargs: dict,
    is_async: bool,
    step_name: str | None = None,
) -> Any:
    """
    Core control execution logic for both async and sync functions.

    This function is always called in an async context (either directly with await
    for async functions, or inside asyncio.run() for sync functions), so it can
    always use await _evaluate() directly.

    Uses cached controls from init() to support both SDK-side and server-side
    evaluation. Controls with execution="sdk" are evaluated locally, while
    execution="server" controls are sent to the server.

    Args:
        func: The wrapped function to execute
        args: Positional arguments for the function
        kwargs: Keyword arguments for the function
        is_async: Whether the wrapped function is async
        step_name: Optional explicit step name for control matching

    Returns:
        The result of the wrapped function

    Raises:
        ControlViolationError: If any control triggers with "deny" action
    """
    agent = _get_current_agent()
    if agent is None:
        logger.warning(
            "No agent initialized. Call agent_control.init() first. "
            "Running without protection."
        )
        if is_async:
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    # Get cached controls for local evaluation support
    controls = _get_server_controls()

    # Get trace context: inherit trace_id if set, always generate new span_id
    # This allows multiple @control() calls to share the same trace but have unique spans
    existing_trace_id = get_current_trace_id()
    if existing_trace_id:
        trace_id = existing_trace_id
        span_id = _generate_span_id()  # New span for this function
    else:
        trace_id, span_id = get_trace_and_span_ids()  # New trace and span

    ctx = ControlContext(
        agent_name=agent.agent_name,
        server_url=_get_server_url(),
        func=func,
        args=args,
        kwargs=kwargs,
        trace_id=trace_id,
        span_id=span_id,
        start_time=time.perf_counter(),
        step_name=step_name,
    )
    ctx.log_start()

    try:
        # PRE-EXECUTION: Check controls with check_stage="pre"
        try:
            result = await _evaluate(
                ctx.agent_name, ctx.pre_payload(), "pre",
                ctx.server_url, ctx.trace_id, ctx.span_id,
                controls=controls,
                event_agent_name=ctx.agent_name,
            )
            ctx.process_result(result, "pre")
        except (ControlViolationError, ControlSteerError):
            raise
        except Exception as e:
            # FAIL-SAFE: If control check fails, DO NOT execute the function
            logger.error(f"Pre-execution control check failed: {e}")
            raise RuntimeError(
                f"Control check failed unexpectedly. Execution blocked for safety. Error: {e}"
            ) from e

        # Execute the function
        if is_async:
            output = await func(*args, **kwargs)
        else:
            output = func(*args, **kwargs)

        # POST-EXECUTION: Check controls with check_stage="post"
        try:
            result = await _evaluate(
                ctx.agent_name, ctx.post_payload(output), "post",
                ctx.server_url, ctx.trace_id, ctx.span_id,
                controls=controls,
                event_agent_name=ctx.agent_name,
            )
            ctx.process_result(result, "post")
        except (ControlViolationError, ControlSteerError):
            raise
        except Exception as e:
            logger.error(f"Post-execution control check failed: {e}")

        return output
    finally:
        ctx.log_end()


def control(policy: str | None = None, step_name: str | None = None) -> Callable[[F], F]:
    """
    Decorator to apply server-defined controls at this code location.

    Controls (stage, selector, evaluator, action) are defined on the SERVER.
    This decorator marks WHERE to evaluate controls for the current agent.

    Args:
        policy: Optional policy name for documentation. This parameter is for
                clarity in code when multiple policies exist.
        step_name: Optional custom name for this step. If not provided, uses
                   the function name.

    Returns:
        Decorated function

    Raises:
        ControlViolationError: If any control triggers with "deny" action

    How it works:
        1. Before function execution: Calls server with stage="pre"
           - Server evaluates all matching "pre" controls for the agent
        2. Function executes
        3. After function execution: Calls server with stage="post"
           - Server evaluates all matching "post" controls for the agent

    Example:
        import agent_control

        # Initialize agent (connects to server, loads control associations)
        agent_control.init(
            agent_name="my-bot-identity",
        )

        # Apply controls associated with the agent
        @agent_control.control()
        async def chat(message: str) -> str:
            return await assistant.respond(message)

        # Document which policy this uses (optional, for clarity)
        @agent_control.control(policy="safety-policy")
        async def process(input: str) -> str:
            return await pipeline.run(input)

        # Custom step name for control matching
        @agent_control.control(step_name="user_query_handler")
        async def handle_user_input(user_message: str) -> str:
            return await process_query(user_message)

    Server Setup (separate from agent code):
        1. Create controls via API:
           PUT /api/v1/controls {"name": "block-toxic-inputs"}
           PUT /api/v1/controls/{id}/data {"data": {...}}

        2. Create policy and add controls:
           PUT /api/v1/policies {"name": "safety-policy"}
           POST /api/v1/policies/{policy_id}/controls/{control_id}

        3. Associate policy and/or controls with an agent:
           POST /api/v1/agents/{agent_name}/policies/{policy_id}
           POST /api/v1/agents/{agent_name}/controls/{control_id}
    """
    # The policy parameter is for documentation only - the server evaluates
    # controls associated with the agent via policy and direct links.
    _ = policy

    def decorator(func: F) -> F:
        # Register this function's step schema for auto-discovery by init()
        from agent_control._control_registry import register

        register(func, policy)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await _execute_with_control(
                func, args, kwargs, is_async=True, step_name=step_name
            )

        # Copy over ALL attributes from the original function (important for LangChain tools)
        for attr in dir(func):
            if not attr.startswith('_') and attr not in ('__call__', '__wrapped__'):
                try:
                    setattr(async_wrapper, attr, getattr(func, attr))
                except (AttributeError, TypeError):
                    pass

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return asyncio.run(
                _execute_with_control(func, args, kwargs, is_async=False, step_name=step_name)
            )

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    "control",
    "ControlViolationError",
    "ControlSteerError",
]
