#!/usr/bin/env python3
"""
AgentControl Hook for AWS Strands Integration

A reusable hook that integrates AgentControl safety checks with Strands agents.
Evaluates controls at each event and applies actions based on control definitions.
"""

import os
from typing import Any, Callable, Optional
from uuid import UUID

from strands.hooks import (
    AfterModelCallEvent,
    AfterNodeCallEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeModelCallEvent,
    BeforeNodeCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

import agent_control


class AgentControlHook(HookProvider):
    """
    A hook that integrates AgentControl safety checks with Strands agents.

    This hook uses a "hook mode" design where callbacks decorated with @control
    return evaluation data instead of performing evaluation directly. The decorator
    handles the actual control evaluation and event cancellation.

    Hook Mode Design:
        1. Callbacks intercept Strands lifecycle events
        2. Extract step data (tool name, input, output, etc.) from events
        3. Return dict with step data to @control decorator
        4. Decorator evaluates controls in POST-EXECUTION flow
        5. If unsafe, decorator raises ControlViolationError

    Multi-agent support: Each hook instance is tied to a specific agent via agent_uuid.
    The AgentControl server filters controls by agent_uuid during evaluation.

    Example:
        ```python
        # For single agent
        hook = AgentControlHook(
            agent_uuid=UUID("..."),
            agent_name="support-agent",
            event_control_list=[BeforeModelCallEvent, AfterModelCallEvent]
        )

        agent = Agent(
            model=model,
            system_prompt="...",
            hooks=[hook]
        )
        ```
    """

    def __init__(
        self,
        agent_uuid: UUID,
        agent_name: str,
        server_url: Optional[str] = None,
        event_control_list: Optional[list[type]] = None,
        on_violation_callback: Optional[Callable] = None,
        enable_logging: bool = True,
    ):
        """
        Initialize AgentControlHook.

        Args:
            agent_uuid: UUID of the agent (used to filter controls on server)
            agent_name: Name of the agent for logging
            server_url: AgentControl server URL (default: from env or localhost:8000)
            event_control_list: List of event types to monitor. If None, monitors all.
            on_violation_callback: Optional callback when safety violation detected.
                                   Signature: callback(violation_info: dict, result: EvaluationResult)
            enable_logging: Whether to log control execution
        """
        super().__init__()
        self.agent_uuid = agent_uuid
        self.agent_name = agent_name
        self.server_url = server_url or os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
        self.event_control_list = event_control_list
        self.on_violation_callback = on_violation_callback
        self.enable_logging = enable_logging

    def _base_request(self, event: Any) -> dict:
        """
        Build base request dict with common fields for hook mode.

        This dict is merged with step-specific data in each callback and returned
        to the @control decorator for evaluation.

        Args:
            event: Strands event object (BeforeToolCallEvent, AfterModelCallEvent, etc.)

        Returns:
            Dict with agent_uuid, server_url, and event that @control decorator uses
        """
        return {
            "agent_uuid": str(self.agent_uuid),
            "server_url": self.server_url,
            "event": event,
        }

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """
        Register callback methods with Strands HookRegistry.

        Maps Strands event types to hook callback methods. If event_control_list
        is specified, only registers callbacks for those event types.

        Args:
            registry: Strands HookRegistry for registering callbacks
            **kwargs: Additional arguments passed by Strands framework
        """
        print(f"\n{'='*60}")
        print(f"🔧 AgentControlHook.register_hooks() CALLED")
        print(f"   Agent: {self.agent_name}")
        print(f"   Agent UUID: {self.agent_uuid}")
        print(f"   Server URL: {self.server_url}")
        print(f"{'='*60}")

        # Map event types to callback methods
        event_map = {
            BeforeInvocationEvent: self.check_before_invocation,
            BeforeModelCallEvent: self.check_before_model,
            AfterModelCallEvent: self.check_after_model,
            BeforeToolCallEvent: self.check_before_tool,
            AfterToolCallEvent: self.check_after_tool,
            BeforeNodeCallEvent: self.check_before_node,
            AfterNodeCallEvent: self.check_after_node,
        }

        # Determine which events to register
        events_to_register = self.event_control_list if self.event_control_list else event_map.keys()

        print(f"\n📋 Registering callbacks for events:")
        for event_type in events_to_register:
            if event_type in event_map:
                registry.add_callback(event_type, event_map[event_type])
                print(f"   ✓ {event_type.__name__} -> {event_map[event_type].__name__}")

        print(f"\n✅ AgentControlHook registration complete!\n")

    # ============================================================================
    # Event Callbacks (following Strands naming conventions)
    # ============================================================================

    @agent_control.control()
    async def check_before_invocation(self, event: BeforeInvocationEvent):
        """
        Check controls before agent invocation (user input stage).

        This callback intercepts the initial user input before the agent processes it.
        Returns a dict that the @control decorator uses to evaluate controls in hook mode.

        Hook Mode Flow:
            1. Callback executes and extracts user input from event
            2. Returns dict with step data to @control decorator
            3. Decorator evaluates controls in POST-EXECUTION flow
            4. If unsafe, decorator raises ControlViolationError

        Returns:
            Dict with agent_uuid, server_url, event, step, and stage for control evaluation
        """
        if self.enable_logging:
            print(f"\n{'='*60}")
            print(f"🟢 AgentControlHook.check_before_invocation() CALLED")
            print(f"{'='*60}")

        input_text, _ = self._extract_messages(event)

        if self.enable_logging:
            print(f"📝 Extracted input text: {input_text[:200] if input_text else '(empty)'}")
            print(f"📊 Input length: {len(input_text)} characters")

        return {
            **self._base_request(event),
            "step": {
                "input": input_text,
            },
            "stage": "post",
        }

    @agent_control.control()
    async def check_before_model(self, event: BeforeModelCallEvent):
        """
        Check controls before LLM call.

        This callback intercepts messages before they're sent to the LLM.
        Returns a dict that the @control decorator uses to evaluate controls in hook mode.

        Hook Mode Flow:
            1. Callback executes and extracts messages from event
            2. Returns dict with step data to @control decorator
            3. Decorator evaluates controls in POST-EXECUTION flow
            4. If unsafe, decorator raises ControlViolationError

        Returns:
            Dict with agent_uuid, server_url, event, step, and stage for control evaluation
        """
        if self.enable_logging:
            print(f"\n{'='*60}")
            print(f"🔵 AgentControlHook.check_before_model() CALLED")
            print(f"{'='*60}")

        input_text, _ = self._extract_messages(event)

        if self.enable_logging:
            print(f"📝 Extracted input text: {input_text[:200]}")
            print(f"📊 Input length: {len(input_text)} characters")

        return {
            **self._base_request(event),
            "step": {
                "type": "llm",
                "input": {"messages": input_text},
            },
            "stage": "post",
        }

    @agent_control.control()
    async def check_after_model(self, event: AfterModelCallEvent):
        """
        Check controls after LLM call.

        This callback intercepts the LLM's response before it's returned to the agent.
        Returns a dict that the @control decorator uses to evaluate controls in hook mode.

        Hook Mode Flow:
            1. Callback executes and extracts model output from event
            2. Returns dict with step data to @control decorator
            3. Decorator evaluates controls in POST-EXECUTION flow
            4. If unsafe, decorator raises ControlViolationError

        Returns:
            Dict with agent_uuid, server_url, event, step, and stage for control evaluation
        """
        _, output_text = self._extract_messages(event)

        if self.enable_logging:
            print(f"🔍 [POST] Output: {output_text[:100]}...")

        return {
            **self._base_request(event),
            "step": {
                "type": "llm",
                "output": output_text,
            },
            "stage": "post",
        }

    @agent_control.control()
    async def check_before_tool(self, event: BeforeToolCallEvent):
        """
        Check controls before tool call.

        This callback intercepts tool calls before they execute.
        Returns a dict that the @control decorator uses to evaluate controls in hook mode.

        Hook Mode Flow:
            1. Callback executes and extracts tool name and input from event
            2. Returns dict with step data to @control decorator
            3. Decorator evaluates controls in POST-EXECUTION flow
            4. If unsafe, decorator raises ControlViolationError

        Important: The step name is set to the actual tool name (e.g., "process_refund"),
        enabling server-side controls to target specific tools using step_names.

        Returns:
            Dict with agent_uuid, server_url, event, step, and stage for control evaluation
        """
        # ALWAYS log tool calls (even when enable_logging=False) for visibility
        print(f"\n{'='*70}")
        print(f"🔧 TOOL CALL INTERCEPTED - AgentControlHook.check_before_tool()")
        print(f"{'='*70}")

        # Extract tool name and input from event
        tool_name, tool_input = self._extract_tool_data(event, event_phase="pre")

        print(f"🔧 Tool name: {tool_name}")
        # Format tool_input for display (might be dict or string)
        if isinstance(tool_input, dict):
            import json
            tool_input_str = json.dumps(tool_input)
        else:
            tool_input_str = str(tool_input) if tool_input else ''
        print(f"📝 Tool input: {tool_input_str[:200] if tool_input_str else '(empty)'}")

        print(f"📦 Created Step: type=tool, name={tool_name}")
        print(f"   → Controls with step_names=['{tool_name}'] will now be checked!")
        print(f"{'='*70}")

        return {
            **self._base_request(event),
            "step": {
                "type": "tool",
                "input": tool_input,
            },
            "stage": "post",
        }

    @agent_control.control()
    async def check_after_tool(self, event: AfterToolCallEvent):
        """
        Check controls after tool call.

        This callback intercepts tool results after they execute.
        Returns a dict that the @control decorator uses to evaluate controls in hook mode.

        Hook Mode Flow:
            1. Callback executes and extracts tool name and output from event
            2. Returns dict with step data to @control decorator
            3. Decorator evaluates controls in POST-EXECUTION flow
            4. If unsafe, decorator raises ControlViolationError

        Returns:
            Dict with agent_uuid, server_url, event, step, and stage for control evaluation
        """
        if self.enable_logging:
            print(f"\n{'='*60}")
            print(f"🔧 AgentControlHook.check_after_tool() CALLED")
            print(f"{'='*60}")

        # Extract tool name and output from event
        tool_name, tool_output = self._extract_tool_data(event, event_phase="post")

        if self.enable_logging:
            print(f"🔧 Tool name: {tool_name}")
            print(f"📝 Tool output: {tool_output[:200] if tool_output else '(empty)'}")

        return {
            **self._base_request(event),
            "step": {
                "type": "tool",
                "output": tool_output,
            },
            "stage": "post",
        }

    @agent_control.control()
    async def check_before_node(self, event: BeforeNodeCallEvent):
        """
        Check controls before node call (multi-agent graphs).

        This callback intercepts node calls in multi-agent graph execution.
        Returns a dict that the @control decorator uses to evaluate controls in hook mode.

        Hook Mode Flow:
            1. Callback executes and extracts node input from event
            2. Returns dict with step data to @control decorator
            3. Decorator evaluates controls in POST-EXECUTION flow
            4. If unsafe, decorator raises ControlViolationError

        Returns:
            Dict with agent_uuid, server_url, event, step, and stage for control evaluation
        """
        input_text, _ = self._extract_messages(event)
        node_id = event.node_id if hasattr(event, "node_id") else "unknown"

        return {
            **self._base_request(event),
            "step": {
                "type": "llm",
                "input": input_text,
            },
            "stage": "post",
        }

    @agent_control.control()
    async def check_after_node(self, event: AfterNodeCallEvent):
        """
        Check controls after node call (multi-agent graphs).

        This callback intercepts node results in multi-agent graph execution.
        Returns a dict that the @control decorator uses to evaluate controls in hook mode.

        Hook Mode Flow:
            1. Callback executes and extracts node output from event
            2. Returns dict with step data to @control decorator
            3. Decorator evaluates controls in POST-EXECUTION flow
            4. If unsafe, decorator raises ControlViolationError

        Returns:
            Dict with agent_uuid, server_url, event, step, and stage for control evaluation
        """
        _, output_text = self._extract_messages(event)
        node_id = event.node_id if hasattr(event, "node_id") else "unknown"

        return {
            **self._base_request(event),
            "step": {
                "type": "llm",
                "output": output_text,
            },
            "stage": "post",
        }

    # ============================================================================
    # Message Extraction Utilities
    # ============================================================================

    def _extract_messages(self, event: Any) -> tuple[str, str]:
        """
        Extract input and output messages from event.

        Handles different event types:
        - BeforeInvocationEvent: has event.messages (user input)
        - AfterModelCallEvent: has event.stop_response.message (model output)

        Returns:
            Tuple of (input_text, output_text)
        """
        input_text = ""
        output_text = ""

        # BeforeInvocationEvent - has messages attribute with user input
        if hasattr(event, "messages") and event.messages:
            if self.enable_logging:
                print(f"📥 Extracting from BeforeInvocationEvent.messages")
            for msg in event.messages:
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    input_text = self._extract_content_text(content)
                    break
                elif hasattr(msg, "role") and msg.role == "user":
                    content = msg.content if hasattr(msg, "content") else ""
                    input_text = self._extract_content_text(content)
                    break

        # AfterModelCallEvent - has stop_response.message with model output
        if hasattr(event, "stop_response") and event.stop_response:
            if self.enable_logging:
                print(f"📤 Extracting from AfterModelCallEvent.stop_response.message")
            if hasattr(event.stop_response, "message"):
                output_text = self._extract_content_text(event.stop_response.message)

        if self.enable_logging:
            print(f"📊 Extraction result: input={len(input_text)} chars, output={len(output_text)} chars")

        return input_text, output_text

    def _extract_tool_data(self, event: Any, event_phase: str) -> tuple[str, str]:
        """
        Extract tool name and input/output from tool call events.

        Handles BeforeToolCallEvent and AfterToolCallEvent from Strands.

        Args:
            event: BeforeToolCallEvent or AfterToolCallEvent
            event_phase: "pre" tool execution or "post" tool execution to determine what to extract

        Returns:
            Tuple of (tool_name, tool_data)
            - tool_name: Name of the tool being called
            - tool_data: Input parameters (pre) or output result (post)
        """
        import json

        tool_name = "unknown-tool"
        tool_data = ""

        # Extract tool name from selected_tool or tool_use
        if hasattr(event, "selected_tool") and event.selected_tool:
            # selected_tool is an AgentTool object with name attribute
            if hasattr(event.selected_tool, "name"):
                tool_name = event.selected_tool.name
            elif hasattr(event.selected_tool, "__name__"):
                tool_name = event.selected_tool.__name__
        elif hasattr(event, "tool_use") and event.tool_use:
            # tool_use is a dict with toolName key
            if isinstance(event.tool_use, dict):
                tool_name = event.tool_use.get("toolName", "unknown-tool")
            elif hasattr(event.tool_use, "get"):
                tool_name = event.tool_use.get("toolName", "unknown-tool")

        if self.enable_logging:
            print(f"🔍 Extracted tool name: {tool_name}")

        # Extract input (pre-stage) or output (post-stage)
        if event_phase == "pre":
            # BeforeToolCallEvent - extract tool parameters from tool_use
            if hasattr(event, "tool_use") and event.tool_use:
                if isinstance(event.tool_use, dict):
                    # Get input from tool_use dict
                    # For tool steps, Step model requires dict input, not JSON string!
                    tool_input = event.tool_use.get("input", {})
                    tool_data = tool_input  # Keep as dict for tool steps
                elif hasattr(event.tool_use, "get"):
                    tool_input = event.tool_use.get("input", {})
                    tool_data = tool_input  # Keep as dict for tool steps

        else:  # event_phase == "post"
            # AfterToolCallEvent - extract result
            if hasattr(event, "result") and event.result:
                # result is a ToolResult object or dict
                if isinstance(event.result, dict):
                    # Get content from result dict
                    content = event.result.get("content", "")
                    tool_data = self._extract_content_text(content)
                elif hasattr(event.result, "content"):
                    # ToolResult object with content attribute
                    tool_data = self._extract_content_text(event.result.content)
                else:
                    tool_data = str(event.result)

            # Check for exception
            if hasattr(event, "exception") and event.exception:
                tool_data = f"ERROR: {str(event.exception)}"

        if self.enable_logging:
            # Convert tool_data to string for safe slicing
            tool_data_str = str(tool_data) if isinstance(tool_data, dict) else tool_data
            print(f"🔍 Extracted tool data ({event_phase}): {tool_data_str[:100]}...")

        return tool_name, tool_data

    def _extract_content_text(self, content: Any) -> str:
        """
        Extract text from various content formats.

        Handles: string, dict with 'content' key, list of content blocks, objects with 'content' attr
        """
        if not content:
            return ""

        # String content
        if isinstance(content, str):
            return content

        # Dict with 'content' key
        if isinstance(content, dict):
            content = content.get("content", content)

        # Object with 'content' attribute
        if hasattr(content, "content"):
            content = content.content

        # List of content blocks
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    text_parts.append(block["text"])
                elif hasattr(block, "text"):
                    text_parts.append(block.text)
                else:
                    text_parts.append(str(block))
            return " ".join(text_parts)

        return str(content)
