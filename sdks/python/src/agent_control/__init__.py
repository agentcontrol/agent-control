"""
Agent Control - Unified agent control, monitoring, and SDK client.

This package provides a complete interface for controlling your agents with
automatic registration, rule enforcement, and server communication.

Usage:
    import agent_control

    # Initialize at the base of your agent file
    agent_control.init(
        agent_name="my-customer-service-bot"
    )

    # Apply server-defined controls using the decorator
    # Control configuration is on server - update rules without code changes!
    @agent_control.control()
    async def chat(message: str) -> str:
        return await assistant.respond(message)

    # Optional policy label for grouping/readability; control selection still follows
    # the server's active controls (policy + direct associations).
    @agent_control.control(policy="safety-policy")
    async def process(input: str) -> str:
        return await pipeline.run(input)

    # Use custom step name for control matching
    @agent_control.control(step_name="user_query_handler")
    async def handle_input(user_message: str) -> str:
        return await process_query(user_message)

    # Or use the client directly for server-side checks
    async with agent_control.AgentControlClient() as client:
        result = await agent_control.evaluation.check_evaluation(
            client,
            agent_name,
            step={"type": "llm", "name": "chat", "input": "Hello"},
            stage="pre",
        )
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

import asyncio
import os
import threading
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

import httpx
from agent_control_models import (
    Agent,
    ControlAction,
    ControlDefinition,
    ControlMatch,
    ControlScope,
    ControlSelector,
    EvaluationRequest,
    EvaluationResult,
    EvaluatorResult,
    EvaluatorSpec,
    Step,
    StepSchema,
)

from . import agents, controls, evaluation, evaluators, policies
from ._control_registry import (
    StepSchemaDict,
    get_registered_steps,
    merge_explicit_and_auto_steps,
)
from ._control_registry import (
    clear as clear_step_registry,
)

# Import client and operations modules
from .client import AgentControlClient

# Import control decorator
from .control_decorators import ControlSteerError, ControlViolationError, control
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
from .validation import ensure_agent_name

# Module logger
logger = get_logger(__name__)


# ============================================================================
# Global State
# ============================================================================

# Global agent instance
_current_agent: Agent | None = None
_control_engine = None
_client: AgentControlClient | None = None
_server_controls: list[dict[str, Any]] | None = None
_server_url: str | None = None
_api_key: str | None = None
_policy_refresh_interval_seconds: int | None = None
_refresh_thread: threading.Thread | None = None
_refresh_stop_event: threading.Event | None = None
_refresh_lock = threading.Lock()

F = TypeVar("F", bound=Callable[..., Any])


def get_server_controls() -> list[dict[str, Any]] | None:
    """Get the cached server controls.

    Returns the controls that were fetched during init() or the last
    refresh_controls() call. Returns None if no controls are cached.

    Returns:
        List of control dicts or None if not initialized.

    Example:
        controls = agent_control.get_server_controls()
        if controls:
            print(f"Loaded {len(controls)} controls")
            for c in controls:
                print(f"  - {c['name']} (execution: {c['control'].get('execution', 'server')})")
    """
    return _server_controls


def _publish_server_controls(
    controls: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Publish controls using swap-only snapshot semantics."""
    global _server_controls

    if controls is None:
        _server_controls = None
        return None

    # Snapshot copy: publish a new list reference and avoid in-place mutation.
    _server_controls = list(controls)
    return _server_controls


def _run_coro_in_new_loop[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on a dedicated event loop in the current thread."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _policy_refresh_worker(stop_event: threading.Event, interval_seconds: int) -> None:
    """Background worker that periodically refreshes controls."""
    while not stop_event.wait(interval_seconds):
        try:
            _run_coro_in_new_loop(refresh_controls_async())
        except Exception as exc:
            logger.error(
                "Background policy refresh loop iteration failed: %s",
                exc,
                exc_info=True,
            )


def _stop_policy_refresh_loop() -> None:
    """Stop the background policy refresh loop if running."""
    global _policy_refresh_interval_seconds, _refresh_thread, _refresh_stop_event

    with _refresh_lock:
        stop_event = _refresh_stop_event
        refresh_thread = _refresh_thread
        _policy_refresh_interval_seconds = None
        _refresh_stop_event = None
        _refresh_thread = None

    if stop_event is not None:
        stop_event.set()

    if refresh_thread is not None and refresh_thread.is_alive():
        refresh_thread.join(timeout=2)
        if refresh_thread.is_alive():
            logger.warning("Timed out while stopping policy refresh loop thread")


def _start_policy_refresh_loop(interval_seconds: int) -> None:
    """Start a background loop that refreshes controls on a fixed interval."""
    global _policy_refresh_interval_seconds, _refresh_thread, _refresh_stop_event

    if interval_seconds <= 0:
        return

    stop_event = threading.Event()
    refresh_thread = threading.Thread(
        target=_policy_refresh_worker,
        args=(stop_event, interval_seconds),
        name="agent-control-policy-refresh",
        daemon=True,
    )
    with _refresh_lock:
        _policy_refresh_interval_seconds = interval_seconds
        _refresh_stop_event = stop_event
        _refresh_thread = refresh_thread

    refresh_thread.start()
    logger.info("Started policy refresh loop (interval=%ss)", interval_seconds)


async def refresh_controls_async() -> list[dict[str, Any]] | None:
    """Refresh controls from the server asynchronously.

    Fetches the latest controls from the server and updates the cache.
    Use this when you've made changes to controls in the UI or API
    and want the SDK to pick them up without restarting.

    Returns:
        List of control dicts or None if fetch failed.

    Example:
        # After updating a control in the UI
        controls = await agent_control.refresh_controls_async()
        print(f"Refreshed {len(controls)} controls")
    """
    if _current_agent is None:
        raise RuntimeError("Agent not initialized. Call agent_control.init() first.")

    if _server_url is None:
        raise RuntimeError("Server URL not set. Call agent_control.init() first.")

    try:
        async with AgentControlClient(base_url=_server_url, api_key=_api_key) as client:
            response = await agents.list_agent_controls(client, _current_agent.agent_name)
            refreshed_controls = _publish_server_controls(response.get("controls", []))
            logger.info("Refreshed %d control(s) from server", len(refreshed_controls or []))
            return refreshed_controls
    except Exception as exc:
        logger.error(
            "Failed to refresh controls; keeping previous cache (%d control(s)): %s",
            len(_server_controls or []),
            exc,
            exc_info=True,
        )
        return _server_controls


def refresh_controls() -> list[dict[str, Any]] | None:
    """Refresh controls from the server synchronously.

    Fetches the latest controls from the server and updates the cache.
    Use this when you've made changes to controls in the UI or API
    and want the SDK to pick them up without restarting.

    Returns:
        List of control dicts or None if fetch failed.

    Example:
        # After updating a control in the UI
        controls = agent_control.refresh_controls()
        print(f"Refreshed {len(controls)} controls")
    """
    try:
        asyncio.get_running_loop()
        # We're in an async context - run in thread
        result_container: list[list[dict[str, Any]] | None] = [None]
        exception_container: list[Exception | None] = [None]

        def run_in_thread() -> None:
            try:
                result_container[0] = _run_coro_in_new_loop(refresh_controls_async())
            except Exception as e:
                exception_container[0] = e
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()
        thread.join(timeout=10)

        if exception_container[0]:
            raise exception_container[0]
        return result_container[0]

    except RuntimeError:
        # No running event loop - we're in a sync context
        return _run_coro_in_new_loop(refresh_controls_async())


# ============================================================================
# Public API Functions
# ============================================================================

def init(
    agent_name: str,
    agent_description: str | None = None,
    agent_version: str | None = None,
    server_url: str | None = None,
    api_key: str | None = None,
    controls_file: str | None = None,
    steps: list[StepSchemaDict] | None = None,
    conflict_mode: Literal["strict", "overwrite"] = "overwrite",
    observability_enabled: bool | None = None,
    log_config: dict[str, Any] | None = None,
    policy_refresh_interval_seconds: int = 60,
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
        agent_name: Unique identifier for your agent (will be normalized to lowercase)
        agent_description: Optional description of what your agent does
        agent_version: Optional version string (e.g., "1.0.0")
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var
                   or http://localhost:8000)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)
        controls_file: Optional explicit path to controls.yaml (auto-discovered if not provided)
        steps: Optional list of step schemas for registration:
               [{"type": "tool", "name": "search", "input_schema": {...}, "output_schema": {...}}]
        conflict_mode: Conflict handling mode for initAgent registration.
            Defaults to "overwrite" in SDK flows.
        observability_enabled: Optional bool to enable/disable observability (defaults to env var)
        log_config: Optional logging configuration dict:
               {"enabled": True, "span_start": True, "span_end": True, "control_eval": True}
        policy_refresh_interval_seconds: Interval for background policy refresh loop.
            Defaults to 60 seconds. Set to 0 to disable background refresh.
        **kwargs: Additional metadata to store with the agent

    Returns:
        Agent instance with all metadata

    Example:
        import agent_control

        agent_control.init(
            agent_name="customer-service-bot",
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

        # Now use @control decorator to apply agent-associated controls
        from agent_control import control

        @control()  # Applies controls associated with the agent
        async def handle(message: str):
            return message

    Environment Variables:
        AGENT_CONTROL_URL: Server URL (default: http://localhost:8000)
    """
    global _current_agent, _control_engine, _client, _server_url, _api_key

    if not agent_name:
        raise ValueError(
            "The 'agent_name' argument is required for initialization.\n"
            "Please provide a valid agent identifier, e.g.:\n"
            '    agent_control.init(agent_name="customer-service-bot")'
        )

    # Validate and normalize agent_name
    _agent_name = ensure_agent_name(agent_name)

    if policy_refresh_interval_seconds < 0:
        raise ValueError("policy_refresh_interval_seconds must be >= 0")

    # Re-init behavior: always stop existing loop before mutating shared agent/session globals.
    _stop_policy_refresh_loop()

    # Configure logging if provided (do this early before any logging happens)
    if log_config:
        configure_logging(log_config)

    # Create agent instance with metadata
    _current_agent = Agent(
        agent_name=_agent_name,
        agent_description=agent_description,
        agent_created_at=datetime.now(UTC).isoformat(),
        agent_updated_at=None,
        agent_version=agent_version,
        agent_metadata=kwargs
    )

    # Get server URL (ensure it's always a string)
    _server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'
    _api_key = api_key

    # Merge auto-discovered steps from @control() decorators with explicit steps.
    # Explicit steps take precedence when (type, name) collides.
    auto_steps = get_registered_steps()
    merge_result = merge_explicit_and_auto_steps(steps, auto_steps)
    registration_steps: list[dict[str, Any]] = [dict(step) for step in merge_result.steps]

    if auto_steps:
        if merge_result.overridden_keys:
            formatted = ", ".join(
                f"{step_type}:{step_name}" for step_type, step_name in merge_result.overridden_keys
            )
            logger.warning(
                "Skipping %d auto-discovered step(s) overridden by explicit steps: %s",
                len(merge_result.overridden_keys),
                formatted,
            )

        logger.debug(
            "Auto-discovered %d step(s) from @control() decorators (%d after merge)",
            len(auto_steps),
            len(registration_steps),
        )

    # Register with server and fetch controls
    server_controls = None
    try:
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
                        steps=registration_steps,
                        conflict_mode=conflict_mode,
                    )
                    created = response.get('created', False)
                    controls: list[dict[str, Any]] = response.get('controls', [])

                    if created:
                        logger.info("Agent registered: %s", _agent_name)
                    else:
                        logger.info("Agent updated: %s", _agent_name)

                    if registration_steps:
                        logger.debug("Registered %d step(s)", len(registration_steps))

                    return controls
                except httpx.HTTPStatusError:
                    # Surface API errors like name conflicts
                    raise
                except Exception as e:
                    logger.error("Failed to register agent: %s", e, exc_info=True)
                    return None

        # Run registration - handle both sync and async contexts
        try:
            # Check if we're already in an event loop
            asyncio.get_running_loop()
            # We're in an async context - schedule the coroutine
            result_container: list[list[dict[str, Any]] | None] = [None]
            exception_container: list[Exception | None] = [None]

            def run_in_thread() -> None:
                try:
                    result_container[0] = _run_coro_in_new_loop(register())
                except Exception as e:
                    exception_container[0] = e

            thread = threading.Thread(target=run_in_thread, daemon=True)
            thread.start()
            thread.join(timeout=10)  # 10 second timeout

            if exception_container[0]:
                raise exception_container[0]
            server_controls = result_container[0]

        except RuntimeError:
            # No running event loop - we're in a sync context
            server_controls = _run_coro_in_new_loop(register())

    except httpx.HTTPStatusError:
        # Surface server-side errors (e.g., 409 conflicts)
        raise
    except Exception as e:
        logger.error("Could not connect to server: %s", e, exc_info=True)
        logger.info("Will use local controls if available")

    # Store server controls globally for later use by @control decorator.
    published_controls = _publish_server_controls(server_controls)
    if published_controls:
        logger.info("Loaded %d control(s) from server", len(published_controls))
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

    if policy_refresh_interval_seconds > 0:
        _start_policy_refresh_loop(policy_refresh_interval_seconds)
    else:
        logger.debug("Policy refresh loop disabled (policy_refresh_interval_seconds=0)")

    return _current_agent


async def get_agent(
    agent_name: str,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Get agent details from the server by name.

    Args:
        agent_name: Agent identifier
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - agent: Agent metadata
            - steps: List of steps registered with the agent

    Raises:
        httpx.HTTPError: If request fails or agent not found

    Example:
        import asyncio
        import agent_control

        # Fetch agent from server
        async def main():
            agent_data = await agent_control.get_agent(
                "customer-service-bot"
            )
            print(f"Agent: {agent_data['agent']['agent_name']}")
            print(f"Steps: {len(agent_data['steps'])}")

        asyncio.run(main())

        # Or using the client directly
        async with agent_control.AgentControlClient() as client:
            agent_data = await agent_control.agents.get_agent(
                client, "customer-service-bot"
            )
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.get_agent(client, agent_name)


def current_agent() -> Agent | None:
    """
    Get the currently initialized agent (from init()).

    Returns:
        Current Agent instance or None if not initialized

    Example:
        agent_control.init(
            agent_name="My Bot",
        )
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
        cursor: Optional cursor for pagination (agent name of last item from previous page)
        limit: Number of results per page (default 20, max 100)

    Returns:
        Dictionary containing:
            - agents: List of agent summaries with agent_name,
                      policy_ids, created_at, step_count, evaluator_count
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
                print(f"  - {agent['agent_name']}")
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
# Agent Association Convenience Functions
# ============================================================================


async def get_agent_policies(
    agent_name: str,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """List policy IDs associated with an agent."""
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.get_agent_policies(client, agent_name)


async def add_agent_policy(
    agent_name: str,
    policy_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Associate a policy with an agent (additive, idempotent)."""
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.add_agent_policy(client, agent_name, policy_id)


async def remove_agent_policy_association(
    agent_name: str,
    policy_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Remove one policy association from an agent (idempotent)."""
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.remove_agent_policy_association(client, agent_name, policy_id)


async def remove_all_agent_policies(
    agent_name: str,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Remove all policy associations from an agent."""
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.remove_all_agent_policies(client, agent_name)


async def add_agent_control(
    agent_name: str,
    control_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Associate a control directly with an agent (idempotent)."""
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.add_agent_control(client, agent_name, control_id)


async def remove_agent_control(
    agent_name: str,
    control_id: int,
    server_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Remove a direct control association from an agent (idempotent)."""
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url, api_key=api_key) as client:
        return await agents.remove_agent_control(client, agent_name, control_id)


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

    By default, deletion fails if the control is associated with any policy or agent.
    Use force=True to automatically dissociate and delete.

    Args:
        control_id: ID of the control to delete
        force: If True, remove associations before deleting
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)
        api_key: Optional API key for authentication (defaults to AGENT_CONTROL_API_KEY env var)

    Returns:
        Dictionary containing:
            - success: True if control was deleted
            - dissociated_from_policies: List of policy IDs the control was removed from
            - dissociated_from_agents: List of agent names the control was removed from

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
            print(
                "Deleted, removed from "
                f"{len(result['dissociated_from_policies'])} policies and "
                f"{len(result['dissociated_from_agents'])} agents"
            )

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


__all__ = [
    # Initialization
    "init",
    "current_agent",

    # Control sync
    "get_server_controls",
    "refresh_controls",
    "refresh_controls_async",
    # Step registry (auto-discovered from @control decorators)
    "get_registered_steps",
    "clear_step_registry",

    # SDK Logging
    "get_logger",
    # Agent management
    "get_agent",
    "list_agents",
    "get_agent_policies",
    "add_agent_policy",
    "remove_agent_policy_association",
    "remove_all_agent_policies",
    "add_agent_control",
    "remove_agent_control",
    # Control management
    "create_control",
    "list_controls",
    "get_control",
    "delete_control",
    "update_control",
    # Decorator
    "control",
    "ControlViolationError",
    "ControlSteerError",
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
    # Models (re-exported when available)
    "Agent",
    "Step",
    "StepSchema",
    "EvaluationRequest",
    "EvaluationResult",
    "ControlDefinition",
    "ControlSelector",
    "ControlScope",
    "ControlAction",
    "ControlMatch",
    "EvaluatorSpec",
    "EvaluatorResult",
]
