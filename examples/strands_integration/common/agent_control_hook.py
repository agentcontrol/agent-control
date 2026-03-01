#!/usr/bin/env python3
"""
AgentControl Hook for AWS Strands Integration

A reusable hook that integrates AgentControl safety checks with Strands agents.
Evaluates controls at each event and applies actions based on control definitions.
"""

import os
from typing import Any, Callable, Literal, Optional

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
from agent_control import ControlSteerError, ControlViolationError
from agent_control_models import EvaluationResult

def _action_error(result: EvaluationResult) -> tuple[str, Exception] | None:
    """
    Return the first blocking action as an exception.

    Args:
        result: EvaluationResult from AgentControl

    Returns:
        ("deny", ControlViolationError) or ("steer", ControlSteerError) if a blocking
        action is present, otherwise None.
    """
    match = next(
        (m for m in (result.matches or []) if m.action in ("deny", "steer")),
        None,
    )
    if not match:
        return None

    msg = getattr(getattr(match, "result", None), "message", None) or result.reason
    msg = msg or f"Control '{match.control_name}' triggered"

    if match.action == "deny":
        err = ControlViolationError(message=f"Policy violation [{match.control_name}]: {msg}")
        return "deny", err

    ctx = getattr(match, "steering_context", None)
    ctx_msg = getattr(ctx, "message", None) if ctx else None
    err = ControlSteerError(
        control_name=match.control_name,
        message=f"Steering required [{match.control_name}]: {msg}",
        steering_context=ctx_msg or msg,
    )
    return "steer", err

class AgentControlHook(HookProvider):
    """
    A hook that integrates AgentControl safety checks with Strands agents.

    This hook intercepts Strands lifecycle events and evaluates controls using
    agent_control.evaluate_controls(). Each callback extracts step data from events
    and directly calls evaluate_controls() to check safety policies.

    Design:
        1. Callbacks intercept Strands lifecycle events
        2. Extract step data (tool name, input, output, etc.) from events
        3. Call evaluate_controls() with step_name, input/output, and stage
        4. If unsafe, raise ControlViolationError to block execution

    Multi-agent support: Each hook instance is tied to a specific agent via agent_name.
    Controls are filtered by agent_name during evaluation.

    Example:
        ```python
        # Initialize agent control SDK
        agent_control.init(agent_name="support-agent")

        # Create hook for monitoring specific events
        hook = AgentControlHook(
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
        agent_name: str,
        server_url: Optional[str] = None,
        event_control_list: Optional[list[type]] = None,
        on_violation_callback: Optional[Callable] = None,
        enable_logging: bool = True,
    ):
        """
        Initialize AgentControlHook.

        Args:
            agent_name: Name of the agent for logging and control filtering
            server_url: AgentControl server URL (default: from env or localhost:8000)
            event_control_list: List of event types to monitor. If None, monitors all.
            on_violation_callback: Optional callback when safety violation detected.
                                   Signature: callback(violation_info: dict, result: EvaluationResult)
            enable_logging: Whether to log control execution
        """
        super().__init__()
        self.agent_name = agent_name
        self.server_url = server_url or os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
        self.event_control_list = event_control_list
        self.on_violation_callback = on_violation_callback
        self.enable_logging = enable_logging

    # ============================================================================
    # Helper Methods
    # ============================================================================

    async def _evaluate_and_enforce(
        self,
        step_name: str,
        input: Any = None,
        output: Any = None,
        step_type: Literal["tool", "llm"] = "llm",
        stage: Literal["pre", "post"] = "pre",
        violation_type: str = "Step",
        use_runtime_error: bool = False,
    ) -> None:
        """Evaluate controls and enforce violations (raises on unsafe)."""
        # Evaluate controls
        result = await agent_control.evaluate_controls(
            step_name=step_name,
            input=input,
            output=output,
            step_type=step_type,
            stage=stage,
            agent_name=self.agent_name,
        )

        action = _action_error(result)
        if action:
            _, err = action
            if isinstance(err, ControlSteerError):
                print(f"\n🎯 STEER - {violation_type} needs correction")
                print(f"   Reason: {err}")
            if self.on_violation_callback:
                self.on_violation_callback(
                    {
                        "agent": self.agent_name,
                        "control_name": getattr(err, "control_name", "unknown"),
                        "stage": stage,
                    },
                    result,
                )
            if use_runtime_error:
                raise RuntimeError(str(err))
            raise err

        # Fail closed if unsafe without explicit deny/steer match
        if not result.is_safe:
            control_name = "unknown"
            reason = result.reason

            if result.matches and len(result.matches) > 0:
                first_match = result.matches[0]
                control_name = first_match.control_name

                if not reason:
                    msg = getattr(getattr(first_match, "result", None), "message", None)
                    reason = msg or f"Control '{control_name}' triggered"

            print(f"\n🚫 CONTROL VIOLATION - {violation_type} blocked")
            print(f"   Control: {control_name}")
            print(f"   Reason: {reason}")

            if self.on_violation_callback:
                self.on_violation_callback(
                    {
                        "agent": self.agent_name,
                        "control_name": control_name,
                        "stage": stage,
                    },
                    result,
                )

            error_msg = f"Policy violation [{control_name}]: {reason}"
            if use_runtime_error:
                raise RuntimeError(error_msg)
            raise agent_control.ControlViolationError(message=error_msg)
    # ============================================================================
    # Hook Registration
    # ============================================================================

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

    async def check_before_invocation(self, event: BeforeInvocationEvent):
        """Check controls before agent invocation (user input stage)."""
        if self.enable_logging:
            print(f"\n{'='*60}")
            print(f"🟢 AgentControlHook.check_before_invocation() CALLED")
            print(f"{'='*60}")

        input_text, _ = self._extract_messages(event)

        if self.enable_logging:
            print(f"📝 Extracted input text: {input_text[:200] if input_text else '(empty)'}")
            print(f"📊 Input length: {len(input_text)} characters")

        await self._evaluate_and_enforce(
            step_name="check_before_invocation",
            input=input_text,
            step_type="llm",
            stage="pre",
            violation_type="Invocation",
        )

    async def check_before_model(self, event: BeforeModelCallEvent):
        """Check controls before LLM call."""
        if self.enable_logging:
            print(f"\n{'='*60}")
            print(f"🔵 AgentControlHook.check_before_model() CALLED")
            print(f"{'='*60}")

        input_text, _ = self._extract_messages(event)

        if self.enable_logging:
            print(f"📝 Extracted input text: {input_text[:200]}")
            print(f"📊 Input length: {len(input_text)} characters")

        await self._evaluate_and_enforce(
            step_name="check_before_model",
            input=input_text,
            step_type="llm",
            stage="pre",
            violation_type="Model call",
        )

    async def check_after_model(self, event: AfterModelCallEvent):
        """Check controls after LLM call."""
        _, output_text = self._extract_messages(event)

        if self.enable_logging:
            print(f"🔍 [POST] Output: {output_text[:100]}...")

        await self._evaluate_and_enforce(
            step_name="check_after_model",
            output=output_text,
            step_type="llm",
            stage="post",
            violation_type="Model call",
        )

    async def check_before_tool(self, event: BeforeToolCallEvent):
        """
        Check controls before tool call.

        Tool calls require special handling because the LLM has ALREADY decided to call
        the tool and added it to conversation history. OpenAI requires a response message
        for each tool_call, so we raise RuntimeError (instead of ControlViolationError)
        to allow Strands to handle it gracefully without creating invalid conversation state.

        Raises:
            RuntimeError: If control violation detected (blocks tool execution)
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

        await self._evaluate_and_enforce(
            step_name=tool_name,
            input=tool_input,
            step_type="tool",
            stage="pre",
            violation_type="Tool execution",
            use_runtime_error=True,
        )

    async def check_after_tool(self, event: AfterToolCallEvent):
        """
        Check controls after tool call.

        Tool calls require special handling because the tool_call message is already
        in conversation history. OpenAI requires a response message for each tool_call,
        so we raise RuntimeError (instead of ControlViolationError) to allow Strands
        to handle it gracefully without creating invalid conversation state.

        Raises:
            RuntimeError: If control violation detected (blocks tool result)
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

        await self._evaluate_and_enforce(
            step_name=tool_name,
            output=tool_output,
            step_type="tool",
            stage="post",
            violation_type="Tool result",
            use_runtime_error=True,
        )

    async def check_before_node(self, event: BeforeNodeCallEvent):
        """Check controls before node call (multi-agent graphs)."""
        input_text, _ = self._extract_messages(event)
        node_id = event.node_id if hasattr(event, "node_id") else "unknown"

        await self._evaluate_and_enforce(
            step_name=node_id,
            input=input_text,
            step_type="llm",
            stage="pre",
            violation_type=f"Node call ({node_id})",
        )

    async def check_after_node(self, event: AfterNodeCallEvent):
        """Check controls after node call (multi-agent graphs)."""
        _, output_text = self._extract_messages(event)
        node_id = event.node_id if hasattr(event, "node_id") else "unknown"

        await self._evaluate_and_enforce(
            step_name=node_id,
            output=output_text,
            step_type="llm",
            stage="post",
            violation_type=f"Node result ({node_id})",
        )

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
