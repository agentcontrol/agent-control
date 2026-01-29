"""
Control decorator for server-side protection of agent functions.

This module provides a decorator that applies server-defined policies to agent functions.
Policies contain multiple controls (regex, list, Luna2, etc.) that are managed server-side.

Architecture:
    SERVER defines: Policies -> Controls (stage, selector, evaluator, action)
    SDK decorator: just marks WHERE the policy applies

Usage:
    import agent_control

    agent_control.init(agent_name="my-agent", agent_id="agent-123")

    # Apply the agent's assigned policy
    @agent_control.control()
    async def chat(message: str) -> str:
        return await assistant.respond(message)

    # The server's policy contains controls that define:
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

from agent_control import AgentControlClient
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

    agent_uuid: str
    agent_name: str
    server_url: str
    func: Callable
    args: tuple
    kwargs: dict
    trace_id: str
    span_id: str
    start_time: float

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
        return _create_evaluation_payload(self.func, self.args, self.kwargs, output=None)

    def post_payload(self, output: Any) -> dict[str, Any]:
        """Build payload for post-execution check (supports tool call detection)."""
        return _create_evaluation_payload(self.func, self.args, self.kwargs, output=output)

    def process_result(self, result: dict[str, Any], check_stage: str) -> None:
        """
        Process evaluation result: log, handle actions, update stats.

        Args:
            result: Server evaluation response
            check_stage: "pre" or "post"

        Raises:
            ControlViolationError: If any control triggers with "deny" action
        """
        # Log each control evaluation
        _log_control_evaluations(result, self.trace_id, self.span_id, check_stage)

        # Handle deny/warn/log actions (may raise ControlViolationError)
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
    agent_uuid: str,
    step: dict[str, Any],
    stage: str,
    server_url: str,
    trace_id: str | None = None,
    span_id: str | None = None,
) -> dict[str, Any]:
    """Call server evaluation endpoint asynchronously."""
    # Build headers with trace/span IDs for distributed tracing
    headers = {}
    if trace_id:
        headers["X-Trace-Id"] = trace_id
    if span_id:
        headers["X-Span-Id"] = span_id

    async with AgentControlClient(base_url=server_url) as client:
        response = await client.http_client.post(
            "/api/v1/evaluation",
            json={
                "agent_uuid": str(agent_uuid),
                "step": step,
                "stage": stage
            },
            headers=headers,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


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
    output: Any = None
) -> dict[str, Any]:
    """
    Create evaluation payload for server, detecting if it's a tool step or LLM step.

    Returns a Step payload structure.
    """
    sig = inspect.signature(func)
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()

    # Check if this function is a tool (has tool_name attribute from @tool decorator)
    tool_name = getattr(func, "name", None) or getattr(func, "tool_name", None)

    if tool_name:
        # This is a tool step
        return {
            "type": "tool",
            "name": tool_name,
            "input": dict(bound.arguments),
            "output": output if isinstance(output, (str, int, float, bool, dict, list)) else (
                None if output is None else str(output)
            ),
        }

    # This is an LLM step
    input_data = _extract_input_from_args(func, args, kwargs)
    return {
        "type": "llm",
        "name": func.__name__,
        "input": input_data,
        "output": output if isinstance(output, (str, int, float, bool, dict, list)) else (
            None if output is None else str(output)
        ),
    }


def _handle_evaluation_result(result: dict[str, Any]) -> None:
    """Handle evaluation result from server - raise on deny."""
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

    if not is_safe:
        for match in matches:
            if not isinstance(match, dict):
                logger.warning(f"Invalid match format: {match}")
                continue

            action = match.get("action", "deny")
            control_id = match.get("control_id")
            matched_control = match.get("control_name", "unknown")

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
                    control_name=matched_control,
                    message=message,
                    metadata=metadata
                )
            elif action == "warn":
                logger.warning(f"⚠️ Control [{matched_control}]: {message}")
            elif action == "log":
                logger.info(f"ℹ️ Control [{matched_control}]: {message}")


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


async def _execute_with_control(
    func: Callable,
    args: tuple,
    kwargs: dict,
    is_async: bool,
) -> Any:
    """
    Core control execution logic for both async and sync functions.

    This function is always called in an async context (either directly with await
    for async functions, or inside asyncio.run() for sync functions), so it can
    always use await _evaluate() directly.

    Args:
        func: The wrapped function to execute
        args: Positional arguments for the function
        kwargs: Keyword arguments for the function
        is_async: Whether the wrapped function is async

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

    # Get trace context: inherit trace_id if set, always generate new span_id
    # This allows multiple @control() calls to share the same trace but have unique spans
    existing_trace_id = get_current_trace_id()
    if existing_trace_id:
        trace_id = existing_trace_id
        span_id = _generate_span_id()  # New span for this function
    else:
        trace_id, span_id = get_trace_and_span_ids()  # New trace and span

    ctx = ControlContext(
        agent_uuid=str(agent.agent_id),
        agent_name=agent.agent_name,
        server_url=_get_server_url(),
        func=func,
        args=args,
        kwargs=kwargs,
        trace_id=trace_id,
        span_id=span_id,
        start_time=time.perf_counter(),
    )
    ctx.log_start()

    try:
        # PRE-EXECUTION: Check controls with check_stage="pre"
        try:
            result = await _evaluate(
                ctx.agent_uuid, ctx.pre_payload(), "pre",
                ctx.server_url, ctx.trace_id, ctx.span_id
            )
            ctx.process_result(result, "pre")
        except ControlViolationError:
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
                ctx.agent_uuid, ctx.post_payload(output), "post",
                ctx.server_url, ctx.trace_id, ctx.span_id
            )
            ctx.process_result(result, "post")
        except ControlViolationError:
            raise
        except Exception as e:
            logger.error(f"Post-execution control check failed: {e}")

        return output
    finally:
        ctx.log_end()


def control(policy: str | None = None) -> Callable[[F], F]:
    """
    Decorator to apply server-defined policy at this code location.

    The policy's controls (stage, selector, evaluator, action) are defined
    on the SERVER. This decorator just marks WHERE to apply the policy.

    Args:
        policy: Optional policy name for documentation. The agent's assigned
                policy is automatically used. This parameter is for clarity
                in code when multiple policies exist.

    Returns:
        Decorated function

    Raises:
        ControlViolationError: If any control triggers with "deny" action

    How it works:
        1. Before function execution: Calls server with stage="pre"
           - Server evaluates all "pre" controls in the agent's policy
        2. Function executes
        3. After function execution: Calls server with stage="post"
           - Server evaluates all "post" controls in the agent's policy

    Example:
        import agent_control

        # Initialize agent (connects to server, loads policy)
        agent_control.init(agent_name="my-bot", agent_id="bot-123")

        # Apply the agent's policy (all controls)
        @agent_control.apply_control()
        async def chat(message: str) -> str:
            return await assistant.respond(message)

        # Document which policy this uses (optional, for clarity)
        @agent_control.apply_control(policy="safety-policy")
        async def process(input: str) -> str:
            return await pipeline.run(input)

    Server Setup (separate from agent code):
        1. Create controls via API:
           PUT /api/v1/controls {"name": "block-toxic-inputs"}
           PUT /api/v1/controls/{id}/data {"data": {...}}

        2. Create policy and add controls:
           PUT /api/v1/policies {"name": "safety-policy"}
           POST /api/v1/policies/{policy_id}/controls/{control_id}

        3. Assign policy to agent:
           POST /api/v1/agents/{agent_id}/policy/{policy_id}
    """
    # The policy parameter is for documentation only - the server uses
    # the agent's assigned policy automatically
    _ = policy

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await _execute_with_control(func, args, kwargs, is_async=True)

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
                _execute_with_control(func, args, kwargs, is_async=False)
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
]
