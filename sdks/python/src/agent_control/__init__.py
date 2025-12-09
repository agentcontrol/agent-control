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
            client, agent_uuid, payload, "pre"
        )
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import UUID

from . import agents, control_sets, controls, evaluation, plugins, policies

# Import client and operations modules
from .client import AgentControlClient

# Import control decorator and registry
from .control_decorators import DISCOVERED_POLICIES, ControlViolationError, control

# Import models if available
try:
    from agent_control_models import (
        Agent,
        EvaluationRequest,
        EvaluationResult,
        LlmCall,
        ToolCall,
    )
    MODELS_AVAILABLE = True
except ImportError:
    MODELS_AVAILABLE = False
    if not TYPE_CHECKING:
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

        class ToolCall:  # runtime fallback
            def __init__(
                self,
                tool_name: str,
                arguments: dict[str, Any],
                output: str | dict[str, Any] | None = None,
                context: dict[str, Any] | None = None,
            ):
                self.tool_name = tool_name
                self.arguments = arguments
                self.output = output
                self.context = context

        class LlmCall:  # runtime fallback
            def __init__(
                self,
                input: str | dict[str, Any],
                output: str | dict[str, Any] | None = None,
                context: dict[str, Any] | None = None,
            ):
                self.input = input
                self.output = output
                self.context = context

        class EvaluationRequest:  # runtime fallback
            def __init__(
                self,
                agent_uuid: UUID,
                payload: ToolCall | LlmCall,
                check_stage: str,
            ):
                self.agent_uuid = agent_uuid
                self.payload = payload
                self.check_stage = check_stage

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
    controls_file: str | None = None,
    tools: list[dict[str, Any]] | None = None,
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
        controls_file: Optional explicit path to controls.yaml (auto-discovered if not provided)
        tools: Optional list of tools with their schemas for registration:
               [{"tool_name": "search", "arguments": {...}, "output_schema": {...}}]
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
            tools=[
                {
                    "tool_name": "search_knowledge_base",
                    "arguments": {"query": {"type": "string"}},
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

    # Create agent instance with metadata
    # Convert agent_id to UUID (accept UUID string or generate from regular string)
    try:
        _agent_uuid = UUID(agent_id)
    except ValueError:
        # If not a valid UUID, generate UUID5 (namespace-based, deterministic)
        # Using DNS namespace for consistency
        import uuid
        _agent_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, agent_id)
        print(f"ℹ️  Generated UUID5 {_agent_uuid} from agent_id '{agent_id}'")

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
            async with AgentControlClient(base_url=_server_url) as client:
                # Check server health first
                try:
                    health = await client.health_check()
                    print(f"✓ Connected to Agent Control server: {_server_url}")
                    print(f"  Server status: {health.get('status', 'unknown')}")
                except Exception as e:
                    print(f"⚠️  Server not available: {e}")
                    return None

                # Register agent with tools and discovered policies
                try:
                    response = await agents.register_agent(
                        client,
                        _current_agent,
                        tools=tools or [],
                        policies=list(DISCOVERED_POLICIES)
                    )
                    created = response.get('created', False)
                    controls: list[dict[str, Any]] = response.get('controls', [])

                    if created:
                        print(f"✓ Agent registered: {agent_name} (ID: {_agent_uuid})")
                    else:
                        print(f"✓ Agent updated: {agent_name} (ID: {_agent_uuid})")

                    if tools:
                        print(f"  Registered {len(tools)} tool(s)")

                    return controls
                except Exception as e:
                    print(f"⚠️  Failed to register agent: {e}")
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
        print(f"⚠️  Could not connect to server: {e}")
        print("   Will use local controls if available.")

    # Store server controls globally for later use by @control decorator
    _server_controls = server_controls
    if server_controls:
        print(f"✓ Loaded {len(server_controls)} control(s) from server")
    else:
        print("ℹ️  No controls returned from server (use local controls.yaml or @control decorator)")

    return _current_agent


async def get_agent(agent_id: str, server_url: str | None = None) -> dict[str, Any]:
    """
    Get agent details from the server by ID.

    Args:
        agent_id: UUID or string identifier of the agent
        server_url: Optional server URL (defaults to AGENT_CONTROL_URL env var)

    Returns:
        Dictionary containing:
            - agent: Agent metadata (agent_name, agent_id, etc.)
            - tools: List of tools registered with the agent

    Raises:
        httpx.HTTPError: If request fails or agent not found

    Example:
        import asyncio
        import agent_control

        # Fetch agent from server
        async def main():
            agent_data = await agent_control.get_agent("bot-123")
            print(f"Agent: {agent_data['agent']['agent_name']}")
            print(f"Tools: {len(agent_data['tools'])}")

        asyncio.run(main())

        # Or using the client directly
        async with agent_control.AgentControlClient() as client:
            agent_data = await agent_control.agents.get_agent(client, "bot-123")
    """
    _final_server_url = server_url or os.getenv('AGENT_CONTROL_URL') or 'http://localhost:8000'

    async with AgentControlClient(base_url=_final_server_url) as client:
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

    # Agent management
    "get_agent",

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
    "control_sets",
    "evaluation",
    "plugins",

    # Tool inference utilities
    "tool",
    "extract_tools_from_functions",
    "tools_from_module",

    # Models (if available)
    "Agent",
    "LlmCall",
    "ToolCall",
    "EvaluationRequest",
    "EvaluationResult",
]

__version__ = "0.1.0"
