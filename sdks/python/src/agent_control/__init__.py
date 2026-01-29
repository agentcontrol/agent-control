"""
Agent Control - Unified agent control, monitoring, and SDK client.

This package provides a complete interface for controlling your agents with
automatic registration, rule enforcement, and server communication.

Usage:
    import agent_control

    # Initialize at the base of your agent file
    agent_control.init(
        agent_name="my-customer-service-bot",
        agent_id="csbot-prod-v1"
    )

    # Apply server-defined controls using the decorator
    # Control configuration is on server - update rules without code changes!
    @agent_control.control()
    async def chat(message: str) -> str:
        return await assistant.respond(message)

    # Apply all controls for this agent
    @agent_control.control(policy="safety-policy")
    async def process(input: str) -> str:
        return await pipeline.run(input)

    # Or use the client directly for server-side checks
    async with agent_control.AgentControlClient() as client:
        result = await agent_control.evaluation.check_evaluation(
            client,
            agent_uuid,
            step={"type": "llm", "name": "chat", "input": "Hello"},
            stage="pre",
        )
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, TypeVar
from uuid import UUID

from . import agents, controls, evaluation, evaluators, policies

# Import client and operations modules
from .client import AgentControlClient

# Import control decorator
from .control_decorators import ControlViolationError, control
from .evaluation import check_evaluation_with_local
from .observability import (
    LogConfig,
    add_event,
    configure_logging,
    get_event_batcher,
    get_log_config,
    get_logger,
    init_observability,
    is_observability_enabled,
    log_control_evaluation,
    shutdown_observability,
)

# Import tracing and observability
from .tracing import (
    get_current_span_id,
    get_current_trace_id,
    get_trace_and_span_ids,
    is_otel_available,
    with_trace,
)

# Module logger
logger = get_logger(__name__)

# Import models if available
try:
    from agent_control_models import (
        Agent,
        ControlAction,
        ControlDefinition,
        ControlSelector,
        EvaluationRequest,
        EvaluationResult,
        EvaluatorConfig,
        Step,
        StepSchema,
    )
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    if not TYPE_CHECKING:
        class ControlDefinition:
            pass

        class ControlSelector:
            pass

        class ControlAction:
            pass

        class EvaluatorConfig:
            pass

        class Agent:  # runtime fallback
            def __init__(
                self,
                agent_id: str | UUID,
                agent_name: str,
                **kwargs: object
            ):
                self.agent_id = agent_id
                self.agent_name = agent_name
                for k, v in kwargs.items():
                    setattr(self, k, v)

        class Step:  # runtime fallback
            def __init__(
                self,
                type: str,
                name: str,
                input: Any,
                output: Any = None,
                context: dict[str, Any] | None = None,
            ):
                self.type = type
                self.name = name
                self.input = input
                self.output = output
                self.context = context

        class StepSchema:  # runtime fallback
            def __init__(
                self,
                type: str,
                name: str,
                description: str | None = None,
                input_schema: dict[str, Any] | None = None,
                output_schema: dict[str, Any] | None = None,
                metadata: dict[str, Any] | None = None,
            ):
                self.type = type
                self.name = name
                self.description = description
                self.input_schema = input_schema
                self.output_schema = output_schema
                self.metadata = metadata

        class EvaluationRequest:  # runtime fallback
            def __init__(
                self,
                agent_uuid: UUID,
                step: Step,
                stage: str,
            ):
                self.agent_uuid = agent_uuid
                self.step = step
                self.stage = stage

        class EvaluationResult:  # runtime fallback
            def __init__(
                self,
                is_safe: bool,
                confidence: float,
                reason: str | None = None
            ):
                self.is_safe = is_safe
                self.confidence = confidence
                self.reason = reason


# ============================================================================
# Global State
# ============================================================================

# Global agent instance
_current_agent: Agent | None = None
_control_engine = None
_client: AgentControlClient | None = None
_server_controls: list | None = None

F = TypeVar("F", bound=Callable[..., Any])


# ============================================================================
# Public API Functions
# ============================================================================

def init(
    agent_name: str,
    agent_id: str,
    agent_description: str | None = None,
    agent_version: str | None = None,
    server_url: str | None = None,
    api_key: str | None = None,
    controls_file: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    observability_enabled: bool | None = None,
    log_config: dict[str, Any] | None = None,
    **kwargs: object
) -> Agent:
    """
    Initialize Agent Control with your agent's information.

    This function should be called once at the base of your agent file.
    It will:
    1. Create an Agent instance with your metadata
    2. Register with the Agent Control server via /initAgent endpoint
    3. Fetch controls from the server
    4. Auto-discover and load local controls.yaml as fallback
    5. Enable the @control decorator

    Args:
        agent_name: Human-readable name for your agent (e.g., "Customer Service Bot")
        agent_id: Unique identifier for your agent. Can be:
                 - A UUID string (e.g., "550e8400-e29b-41d4-a716-446655440000")
                 - Any string (e.g., "csbot-prod-v1") - will be converted to UUID
        agent_description: Optional description of what your agent does
        agent_version: Optional version string (e.g., "1.0.0")
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var
                   or http://localhost:8000)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)
        controls_file: Optional explicit path to controls.yaml (auto-discovered if not provided)
        steps: Optional list of step schemas for registration:
               [{"type": "tool", "name": "search", "input_schema": {...}, "output_schema": {...}}]
        observability_enabled: Optional bool to enable/disable observability (defaults to env var)
        log_config: Optional logging configuration dict:
               {"enabled": True, "span_start": True, "span_end": True, "control_eval": True}
        **kwargs: Additional metadata to store with the agent

    Returns:
        Agent instance with all metadata

    Example:
        import agent_control

        agent_control.init(
            agent_name="Customer Service Bot",
            agent_id="csbot-prod-v1",
            agent_description="Handles customer inquiries and support tickets",
            agent_version="2.1.0",
            steps=[
                {
                    "type": "tool",
                    "name": "search_knowledge_base",
                    "input_schema": {"query": {"type": "string"}},
                    "output_schema": {"results": {"type": "array"}}
                }
            ]
        )

        # Now use @control decorator to apply the agent's policy
        from agent_control import control

        @control()  # Applies agent's assigned policy
        async def handle(message: str):
            return message

    Environment Variables:
        AGENT_CONTROL_URL: Server URL (default: http://localhost:8000)
    """
    global _current_agent, _control_engine, _client, _server_controls

    if not agent_id:
        raise ValueError(
            "The 'agent_id' argument is required for initialization.\n"
            "Please provide a unique string identifier for your agent, e.g.:\n"
            '    agent_control.init(agent_name="my-agent", agent_id="my-agent-v1")'
        )

    # Configure logging if provided (do this early before any logging happens)
    if log_config:
        configure_logging(log_config)

    # Create agent instance with metadata
    # Convert agent_id to UUID (accept UUID string or generate from regular string)
    try:
        _agent_uuid = UUID(agent_id)
    except ValueError:
        # If not a valid UUID, generate UUID5 (namespace-based, deterministic)
        # Using DNS namespace for consistency
        import uuid
        _agent_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, agent_id)
        logger.info("Generated UUID5 %s from agent_id '%s'", _agent_uuid, agent_id)

    _current_agent = Agent(
        agent_id=_agent_uuid,
        agent_name=agent_name,
        agent_description=agent_description,
        agent_created_at=datetime.now(UTC).isoformat(),
        agent_updated_at=None,
        agent_version=agent_version,
        agent_metadata=kwargs
    )

    # Get server URL (ensure it's always a string)
    _server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    # Register with server and fetch controls
    server_controls = None
    try:
        import asyncio

        async def register() -> list[dict[str, Any]] | None:
            async with AgentControlClient(base_url=_server_url, api_key=api_key) as client:
                # Check server health first
                try:
                    health = await client.health_check()
                    logger.info("Connected to Agent Control server: %s", _server_url)
                    logger.debug("Server status: %s", health.get('status', 'unknown'))
                except Exception as e:
                    logger.error("Server not available: %s", e, exc_info=True)
                    return None

                # Register agent with steps
                try:
                    response = await agents.register_agent(
                        client,
                        _current_agent,
                        steps=steps or []
                    )
                    created = response.get('created', False)
                    controls: list[dict[str, Any]] = response.get('controls', [])

                    if created:
                        logger.info("Agent registered: %s (ID: %s)", agent_name, _agent_uuid)
                    else:
                        logger.info("Agent updated: %s (ID: %s)", agent_name, _agent_uuid)

                    if steps:
                        logger.debug("Registered %d step(s)", len(steps))

                    return controls
                except Exception as e:
                    logger.error("Failed to register agent: %s", e, exc_info=True)
                    return None

        # Run registration - handle both sync and async contexts
        try:
            # Check if we're already in an event loop
            loop = asyncio.get_running_loop()
            # We're in an async context - schedule the coroutine
            import threading

            result_container: list[list[dict[str, Any]] | None] = [None]
            exception_container: list[Exception | None] = [None]

            def run_in_thread() -> None:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    result_container[0] = new_loop.run_until_complete(register())
                except Exception as e:
                    exception_container[0] = e
                finally:
                    new_loop.close()

            thread = threading.Thread(target=run_in_thread)
            thread.start()
            thread.join(timeout=10)  # 10 second timeout

            if exception_container[0]:
                raise exception_container[0]
            server_controls = result_container[0]

        except RuntimeError:
            # No running event loop - we're in a sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            server_controls = loop.run_until_complete(register())
            loop.close()

    except Exception as e:
        logger.error("Could not connect to server: %s", e, exc_info=True)
        logger.info("Will use local controls if available")

    # Store server controls globally for later use by @control decorator
    _server_controls = server_controls
    if server_controls:
        logger.info("Loaded %d control(s) from server", len(server_controls))
    else:
        logger.debug(
            "No controls returned from server "
            "(use local controls.yaml or @control decorator)"
        )

    # Initialize observability if enabled
    batcher = init_observability(
        server_url=_server_url,
        api_key=api_key,
        enabled=observability_enabled,
    )
    if batcher:
        logger.info("Observability enabled")

    return _current_agent


async def get_agent(
    agent_id: str,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Get agent details from the server by ID.

    Args:
        agent_id: UUID or string identifier of the agent
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - agent: Agent metadata (agent_name, agent_id, etc.)
            - steps: List of steps registered with the agent

    Raises:
        httpx.HTTPError: If request fails or agent not found

    Example:
        import asyncio
        import agent_control

        # Fetch agent from server
        async def main():
            agent_data = await agent_control.get_agent("bot-123")
            print(f"Agent: {agent_data['agent']['agent_name']}")
            print(f"Steps: {len(agent_data['steps'])}")

        asyncio.run(main())

        # Or using the client directly
        async with agent_control.AgentControlClient() as client:
            agent_data = await agent_control.agents.get_agent(client, "bot-123")
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.get_agent(client, agent_id)


def current_agent() -> Agent | None:
    """
    Get the currently initialized agent (from init()).

    Returns:
        Current Agent instance or None if not initialized

    Example:
        agent_control.init(agent_name="My Bot", agent_id="bot-123")
        agent = agent_control.current_agent()
        print(agent.agent_name)  # "My Bot"
    """
    return _current_agent


async def list_agents(
    server_url: str | None = None,
    api_key: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """
    List all registered agents from the server.

    Args:
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)
        cursor: Optional cursor for pagination (UUID of last agent from previous page)
        limit: Number of results per page (default 20, max 100)

    Returns:
        Dictionary containing:
            - agents: List of agent summaries with agent_id, agent_name,
                      policy_id, created_at, step_count, evaluator_count
            - pagination: Object with limit, total, next_cursor, has_more

    Raises:
        httpx.HTTPError: If request fails

    Example:
        import asyncio
        import agent_control

        async def main():
            result = await agent_control.list_agents()
            print(f"Total agents: {result['pagination']['total']}")
            for agent in result['agents']:
                print(f"  - {agent['agent_name']} ({agent['agent_id']})")
            # Fetch next page
            if result['pagination']['has_more']:
                next_page = await agent_control.list_agents(
                    cursor=result['pagination']['next_cursor']
                )

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.list_agents(client, cursor=cursor, limit=limit)


# ============================================================================
# Control Management Convenience Functions
# ============================================================================


async def list_controls(
    server_url: str | None = None,
    api_key: str | None = None,
    cursor: int | None = None,
    limit: int = 20,
    name: str | None = None,
    enabled: bool | None = None,
    step_type: str | None = None,
    stage: Literal["pre", "post"] | None = None,
    execution: Literal["server", "sdk"] | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    """
    List all controls from the server with optional filtering.

    Args:
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)
        cursor: Control ID to start after (for pagination)
        limit: Number of results per page (default 20, max 100)
        name: Optional filter by name (partial, case-insensitive)
        enabled: Optional filter by enabled status
        step_type: Optional filter by step type (built-ins: 'tool', 'llm')
        stage: Optional filter by stage ('pre' or 'post')
        execution: Optional filter by execution ('server' or 'sdk')
        tag: Optional filter by tag

    Returns:
        Dictionary containing:
            - controls: List of control summaries
            - pagination: Object with limit, total, next_cursor, has_more

    Raises:
        httpx.HTTPError: If request fails

    Example:
        import asyncio
        import agent_control

        async def main():
            # List all controls
            result = await agent_control.list_controls()
            print(f"Total controls: {result['pagination']['total']}")

            # Filter enabled LLM controls
            llm_controls = await agent_control.list_controls(
                enabled=True,
                step_type="llm"
            )

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await controls.list_controls(
            client,
            cursor=cursor,
            limit=limit,
            name=name,
            enabled=enabled,
            step_type=step_type,
            stage=stage,
            execution=execution,
            tag=tag,
        )


async def create_control(
    name: str,
    data: dict[str, Any] | ControlDefinition | None = None,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Create a new control, optionally with configuration.

    If `data` is provided, the control is created and configured in one call.
    Otherwise, use `agent_control.controls.set_control_data()` to configure it later.

    Args:
        name: Unique name for the control
        data: Optional control definition with selector, evaluator, action, etc.
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - control_id: ID of the created control
            - configured: True if data was set, False if only name was created

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 409: Control with this name already exists
        HTTPException 422: If data doesn't match schema

    Example:
        import asyncio
        import agent_control

        async def main():
            # Create and configure in one call
            result = await agent_control.create_control(
                name="ssn-blocker",
                data={
                    "execution": "server",
                    "scope": {"step_types": ["llm"], "stages": ["post"]},
                    "selector": {"path": "output"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": r"\\d{3}-\\d{2}-\\d{4}"}
                    },
                    "action": {"decision": "deny"}
                }
            )
            print(f"Created control {result['control_id']}")

            # Or create without config (configure later)
            result = await agent_control.create_control(name="my-control")

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await controls.create_control(client, name, data=data)


async def get_control(
    control_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Get a control by ID from the server.

    Args:
        control_id: ID of the control
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - id: Control ID
            - name: Control name
            - data: Control definition or None if not configured

    Raises:
        httpx.HTTPError: If request fails or control not found

    Example:
        import asyncio
        import agent_control

        async def main():
            control = await agent_control.get_control(5)
            print(f"Control: {control['name']}")

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await controls.get_control(client, control_id)


async def delete_control(
    control_id: int,
    force: bool = False,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Delete a control from the server.

    By default, deletion fails if the control is associated with any policy.
    Use force=True to automatically dissociate and delete.

    Args:
        control_id: ID of the control to delete
        force: If True, remove associations before deleting
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - success: True if control was deleted
            - dissociated_from: List of policy IDs the control was removed from

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control not found
        HTTPException 409: Control is in use (and force=False)

    Example:
        import asyncio
        import agent_control

        async def main():
            # Force delete
            result = await agent_control.delete_control(5, force=True)
            print(f"Deleted, removed from {len(result['dissociated_from'])} policies")

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await controls.delete_control(client, control_id, force=force)


async def update_control(
    control_id: int,
    name: str | None = None,
    enabled: bool | None = None,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Update control metadata (name and/or enabled status).

    Args:
        control_id: ID of the control to update
        name: New name for the control (optional)
        enabled: Enable or disable the control (optional)
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - success: True if update succeeded
            - name: Current control name
            - enabled: Current enabled status (if control has data)

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Control not found
        HTTPException 409: Name conflict
        HTTPException 422: Cannot update enabled (no data configured)

    Example:
        import asyncio
        import agent_control

        async def main():
            # Rename and disable
            result = await agent_control.update_control(
                5,
                name="pii-protection-v2",
                enabled=False
            )
            print(f"Updated: {result['name']}, enabled={result['enabled']}")

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await controls.update_control(client, control_id, name=name, enabled=enabled)


# ============================================================================
# Policy-Control Management Convenience Functions
# ============================================================================


async def add_control_to_policy(
    policy_id: int,
    control_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Add a control to a policy.

    This operation is idempotent - adding the same control multiple times has no effect.
    Agents with this policy will immediately see the added control.

    Args:
        policy_id: ID of the policy
        control_id: ID of the control to add
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - success: True if operation succeeded

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Policy or control not found

    Example:
        import asyncio
        import agent_control

        async def main():
            await agent_control.add_control_to_policy(policy_id=1, control_id=5)
            print("Control added to policy")

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await policies.add_control_to_policy(client, policy_id, control_id)


async def remove_control_from_policy(
    policy_id: int,
    control_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Remove a control from a policy.

    This operation is idempotent - removing a non-associated control has no effect.
    Agents with this policy will immediately lose the removed control.

    Args:
        policy_id: ID of the policy
        control_id: ID of the control to remove
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - success: True if operation succeeded

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Policy or control not found

    Example:
        import asyncio
        import agent_control

        async def main():
            await agent_control.remove_control_from_policy(policy_id=1, control_id=5)
            print("Control removed from policy")

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await policies.remove_control_from_policy(client, policy_id, control_id)


async def list_policy_controls(
    policy_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    List all controls associated with a policy.

    Args:
        policy_id: ID of the policy
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - control_ids: List of control IDs associated with the policy

    Raises:
        httpx.HTTPError: If request fails
        HTTPException 404: Policy not found

    Example:
        import asyncio
        import agent_control

        async def main():
            result = await agent_control.list_policy_controls(policy_id=1)
            print(f"Policy has {len(result['control_ids'])} controls")

        asyncio.run(main())
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await policies.list_policy_controls(client, policy_id)


# Note: The @control decorator is imported from control_decorators.py
# It applies server-defined policies to agent functions.
# See: from agent_control import control


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Initialization
    "init",
    "current_agent",

    # SDK Logging
    "get_logger",

    # Agent management
    "get_agent",
    "list_agents",

    # Control management
    "create_control",
    "list_controls",
    "get_control",
    "delete_control",
    "update_control",

    # Decorator (server-side policy evaluation)
    "control",

    # Control Decorator
    "control",
    "ControlViolationError",

    # Client
    "AgentControlClient",

    # Operation modules
    "agents",
    "policies",
    "controls",
    "evaluation",
    "evaluators",

    # Policy-Control management
    "add_control_to_policy",
    "remove_control_from_policy",
    "list_policy_controls",


    # Tool inference utilities
    "tool",
    "extract_tools_from_functions",
    "tools_from_module",

    # Local evaluation
    "check_evaluation_with_local",

    # Tracing
    "get_trace_and_span_ids",
    "get_current_trace_id",
    "get_current_span_id",
    "with_trace",
    "is_otel_available",

    # Observability
    "init_observability",
    "add_event",
    "shutdown_observability",
    "is_observability_enabled",
    "get_event_batcher",
    "configure_logging",
    "get_log_config",
    "log_control_evaluation",
    "LogConfig",

    # Models (if available)
    "Agent",
    "Step",
    "StepSchema",
    "EvaluationRequest",
    "EvaluationResult",
    "ControlDefinition",
    "ControlSelector",
    "ControlAction",
    "EvaluatorConfig",
]

__version__ = "0.1.0"
