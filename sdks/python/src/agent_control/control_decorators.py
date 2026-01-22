"""
Control decorator for server-side protection of agent functions.

This module provides a decorator that applies server-defined policies to agent functions.
Policies contain multiple controls (regex, list, Luna2, etc.) that are managed server-side.

Architecture:
    SERVER defines: Policies -> Controls (check_stage, selector, evaluator, action)
    SDK decorator: just marks WHERE the policy applies

Usage:
    import agent_control

    agent_control.init(agent_name="my-agent", agent_id="agent-123")

    # Apply the agent's assigned policy
    @agent_control.control()
    async def chat(message: str) -> str:
        return await assistant.respond(message)

    # The server's policy contains controls that define:
    # - check_stage: "pre" or "post"
    # - selector.path: "input" or "output"
    # - evaluator: regex, list, Luna2 plugin, etc.
    # - action: deny, warn, or log
"""

import asyncio
import functools
import inspect
import logging
import os
from collections.abc import Callable
from typing import Any, TypeVar

from agent_control import AgentControlClient

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class ControlViolationError(Exception):
    """Raised when a control is triggered with 'deny' action."""

    def __init__(
        self,
        control_name: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ):
        self.control_name = control_name
        self.message = message
        self.metadata = metadata or {}
        super().__init__(f"Control violation [{control_name}]: {message}")

class HumanReviewRequiredError(Exception):
    """Raised when a control is triggered with 'human_review' action."""

    def __init__(
        self,
        control_name: str,
        message: str,
        metadata: dict[str, Any] | None = None
    ):
        self.control_name = control_name
        self.message = message
        self.metadata = metadata or {}
        super().__init__(f"Control interrupt [{control_name}]: {message}")


def _get_current_agent() -> Any | None:
    """Get the current agent from agent_control module."""
    try:
        import agent_control
        return agent_control.current_agent()
    except Exception:
        return None


def _get_server_url() -> str:
    """Get the server URL from environment or default."""
    return os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def _evaluate_async(
    agent_uuid: str,
    payload: dict[str, Any],
    check_stage: str,
    server_url: str
) -> dict[str, Any]:
    """Call server evaluation endpoint asynchronously."""

    async with AgentControlClient(base_url=server_url) as client:
        response = await client.http_client.post(
            "/api/v1/evaluation",
            json={
                "agent_uuid": str(agent_uuid),
                "payload": payload,
                "check_stage": check_stage
            }
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def _evaluate_sync(
    agent_uuid: str,
    payload: dict[str, Any],
    check_stage: str,
    server_url: str
) -> dict[str, Any]:
    """Call server evaluation endpoint synchronously."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(
        _evaluate_async(agent_uuid, payload, check_stage, server_url)
    )
    loop.close()
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


def _handle_evaluation_result(result: dict[str, Any]) -> None:
    """Handle evaluation result from server - raise on deny."""
    is_safe = result.get("is_safe", True)
    human_review_required = result.get("human_review_required", False)
    matches = result.get("matches", [])

    if not is_safe or human_review_required:
        for match in matches:
            action = match.get("action", "deny")
            matched_control = match.get("control_name", "unknown")
            message = match.get("result", {}).get("message", "Control triggered")
            metadata = match.get("result", {}).get("metadata", {})

            if action == "human_review":
                raise HumanReviewRequiredError(
                    message=f"Human review required: {message}",
                    control_name=match.get("control_name"),
                    metadata=metadata,
                )
            elif action == "deny":
                raise ControlViolationError(
                    control_name=matched_control,
                    message=message,
                    metadata=metadata
                )
            elif action == "warn":
                logger.warning(f"⚠️ Control [{matched_control}]: {message}")
            elif action == "log":
                logger.info(f"ℹ️ Control [{matched_control}]: {message}")


def control(policy: str | None = None) -> Callable[[F], F]:
    """
    Decorator to apply server-defined policy at this code location.

    The policy's controls (check_stage, selector, evaluator, action) are defined
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
        1. Before function execution: Calls server with check_stage="pre"
           - Server evaluates all "pre" controls in the agent's policy
        2. Function executes
        3. After function execution: Calls server with check_stage="post"
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
            agent = _get_current_agent()
            if agent is None:
                logger.warning(
                    "No agent initialized. Call agent_control.init() first. "
                    "Running without protection."
                )
                return await func(*args, **kwargs)

            server_url = _get_server_url()
            agent_uuid = str(agent.agent_id)

            # Extract input from function arguments
            input_data = _extract_input_from_args(func, args, kwargs)

            # PRE-EXECUTION: Check controls with check_stage="pre"
            try:
                payload = {"input": input_data}
                result = await _evaluate_async(agent_uuid, payload, "pre", server_url)
                _handle_evaluation_result(result)
            except ControlViolationError:
                raise
            except Exception as e:
                logger.error(f"Pre-execution control check failed: {e}")

            # Execute the function
            output = await func(*args, **kwargs)

            # POST-EXECUTION: Check controls with check_stage="post"
            try:
                payload = {"input": input_data, "output": str(output) if output else ""}
                result = await _evaluate_async(agent_uuid, payload, "post", server_url)
                _handle_evaluation_result(result)
            except ControlViolationError:
                raise
            except Exception as e:
                logger.error(f"Post-execution control check failed: {e}")

            return output

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            agent = _get_current_agent()
            if agent is None:
                logger.warning(
                    "No agent initialized. Call agent_control.init() first. "
                    "Running without protection."
                )
                return func(*args, **kwargs)

            server_url = _get_server_url()
            agent_uuid = str(agent.agent_id)

            input_data = _extract_input_from_args(func, args, kwargs)

            # PRE-EXECUTION
            try:
                payload = {"input": input_data}
                result = _evaluate_sync(agent_uuid, payload, "pre", server_url)
                _handle_evaluation_result(result)
            except ControlViolationError:
                raise
            except Exception as e:
                logger.error(f"Pre-execution control check failed: {e}")

            # Execute
            output = func(*args, **kwargs)

            # POST-EXECUTION
            try:
                payload = {"input": input_data, "output": str(output) if output else ""}
                result = _evaluate_sync(agent_uuid, payload, "post", server_url)
                _handle_evaluation_result(result)
            except ControlViolationError:
                raise
            except Exception as e:
                logger.error(f"Post-execution control check failed: {e}")

            return output

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
