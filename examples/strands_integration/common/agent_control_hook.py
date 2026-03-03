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

    def _invoke_callback(self, control_name: str, stage: str, result: EvaluationResult) -> None:
        """Helper to invoke violation callback if configured."""
        if self.on_violation_callback:
            self.on_violation_callback(
                {
                    "agent": self.agent_name,
                    "control_name": control_name,
                    "stage": stage,
                },
                result,
            )

    def _raise_error(self, error: Exception, use_runtime_error: bool) -> None:
        """Helper to raise error (RuntimeError wrapper if requested)."""
        if use_runtime_error:
            raise RuntimeError(str(error))
        raise error

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

        # Check for explicit deny/steer actions
        action = _action_error(result)
        if action:
            _, err = action
            if isinstance(err, ControlSteerError):
                print(f"\n🎯 STEER - {violation_type} needs correction")
                print(f"   Reason: {err}")

            control_name = getattr(err, "control_name", "unknown")
            self._invoke_callback(control_name, stage, result)
            self._raise_error(err, use_runtime_error)

        # Fail closed if unsafe without explicit deny/steer match
        if not result.is_safe:
            control_name = "unknown"
            reason = result.reason

            if result.matches:
                first_match = result.matches[0]
                control_name = first_match.control_name

                if not reason:
                    # Extract message from first match result
                    match_result = getattr(first_match, "result", None)
                    msg = getattr(match_result, "message", None) if match_result else None
                    reason = msg or f"Control '{control_name}' triggered"

            print(f"\n🚫 CONTROL VIOLATION - {violation_type} blocked")
            print(f"   Control: {control_name}")
            print(f"   Reason: {reason}")

            self._invoke_callback(control_name, stage, result)

            error_msg = f"Policy violation [{control_name}]: {reason}"
            self._raise_error(
                agent_control.ControlViolationError(message=error_msg),
                use_runtime_error
            )
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
        tool_name, tool_input = self._extract_tool_data(event)

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
        tool_name, tool_output = self._extract_tool_data(event)

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
        node_id = getattr(event, "node_id", "unknown")

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
        node_id = getattr(event, "node_id", "unknown")

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

    def _extract_user_message_from_list(self, messages: list | None, reverse: bool = False) -> str:
        """Extract user message content from Strands message list (TypedDict with role and content)."""
        if not messages:
            return ""

        msg_iter = reversed(messages) if reverse else messages
        for msg in msg_iter:
            if isinstance(msg, dict) and msg.get("role") == "user":
                return self._extract_content_text(msg.get("content", ""))
        return ""

    def _extract_messages(self, event: Any) -> tuple[str, str]:
        """
        Extract input and output messages from event.

        Handles all Strands event types based on actual structure:
        - BeforeInvocationEvent: messages (Optional[list[Message]])
        - BeforeModelCallEvent: invocation_state (dict, has default_factory)
        - AfterModelCallEvent: stop_response.message (Optional[ModelStopResponse])
        - BeforeNodeCallEvent: invocation_state (Optional[dict], defaults to None)
        - AfterNodeCallEvent: invocation_state (Optional[dict], defaults to None)

        Returns:
            Tuple of (input_text, output_text)
        """
        input_text = ""
        output_text = ""

        # BeforeInvocationEvent - messages is Optional (list[Message] | None)
        if isinstance(event, BeforeInvocationEvent):
            if self.enable_logging:
                print(f"📥 Extracting from BeforeInvocationEvent.messages")
            input_text = self._extract_user_message_from_list(event.messages)

        # BeforeModelCallEvent - invocation_state has default_factory=dict (always present)
        elif isinstance(event, BeforeModelCallEvent):
            if self.enable_logging:
                print(f"📥 Extracting from BeforeModelCallEvent.invocation_state")
            if "messages" in event.invocation_state:
                input_text = self._extract_user_message_from_list(
                    event.invocation_state["messages"], reverse=True
                )
            elif "input" in event.invocation_state:
                input_text = self._extract_content_text(event.invocation_state["input"])

        # AfterModelCallEvent - stop_response is Optional (ModelStopResponse | None)
        # ModelStopResponse.message is required Message TypedDict (always present if stop_response exists)
        elif isinstance(event, AfterModelCallEvent):
            if self.enable_logging:
                print(f"📤 Extracting from AfterModelCallEvent.stop_response.message")
            if event.stop_response:
                # Extract content list directly from Message TypedDict
                message_content = event.stop_response.message.get("content", [])
                output_text = self._extract_content_text(message_content)

        # BeforeNodeCallEvent - invocation_state is Optional (dict | None, defaults to None)
        elif isinstance(event, BeforeNodeCallEvent):
            if self.enable_logging:
                print(f"📥 Extracting from BeforeNodeCallEvent.invocation_state")
            state = event.invocation_state or {}
            if "messages" in state:
                input_text = self._extract_user_message_from_list(state["messages"], reverse=True)
            elif "input" in state:
                input_text = self._extract_content_text(state["input"])

        # AfterNodeCallEvent - invocation_state is Optional (dict | None, defaults to None)
        elif isinstance(event, AfterNodeCallEvent):
            if self.enable_logging:
                print(f"📤 Extracting from AfterNodeCallEvent.invocation_state")
            state = event.invocation_state or {}
            for key in ("output", "result", "response", "messages"):
                if key in state:
                    output_text = self._extract_content_text(state[key])
                    break

        if self.enable_logging:
            print(f"📊 Extraction result: input={len(input_text)} chars, output={len(output_text)} chars")

        return input_text, output_text

    def _extract_tool_data(self, event: BeforeToolCallEvent | AfterToolCallEvent) -> tuple[str, str]:
        """
        Extract tool name and input/output from tool call events.

        Handles BeforeToolCallEvent and AfterToolCallEvent from Strands.

        Actual Strands structure:
        - Both events have: selected_tool (AgentTool | None), tool_use (ToolUse TypedDict)
        - BeforeToolCallEvent: extract from tool_use["input"]
        - AfterToolCallEvent: extract from result (ToolResult TypedDict) or exception
        - ToolUse TypedDict has: name (str), toolUseId (str), input (Any)
        - ToolResult TypedDict has: content (list[ToolResultContent]), status, toolUseId
        - AgentTool ABC has: tool_name property

        Args:
            event: BeforeToolCallEvent or AfterToolCallEvent

        Returns:
            Tuple of (tool_name, tool_data)
            - tool_name: Name of the tool being called
            - tool_data: Input parameters (Before) or output result (After)
        """
        # Extract tool name (both events have selected_tool and tool_use)
        # Prefer selected_tool.tool_name (AgentTool has tool_name property)
        if event.selected_tool:
            tool_name = event.selected_tool.tool_name
        else:
            # Fallback to tool_use["name"] (ToolUse is required TypedDict, always present)
            tool_name = event.tool_use.get("name", "unknown-tool")

        if self.enable_logging:
            print(f"🔍 Extracted tool name: {tool_name}")

        # Extract input or output based on event type
        if isinstance(event, BeforeToolCallEvent):
            # BeforeToolCallEvent - extract from tool_use["input"] (ToolUse is required, always dict)
            # Keep as dict for Step model (tool steps require dict input, not JSON string)
            tool_data = event.tool_use.get("input", {})

        else:  # AfterToolCallEvent
            # Check for exception first
            if event.exception:
                tool_data = f"ERROR: {str(event.exception)}"
            else:
                # Extract from result (ToolResult is required, always dict)
                # ToolResult has content: list[ToolResultContent]
                # ToolResultContent TypedDict has: text, json, image, document
                tool_data = self._extract_content_text(event.result.get("content", []))

        if self.enable_logging:
            tool_data_str = str(tool_data) if isinstance(tool_data, dict) else tool_data
            event_type = "pre" if isinstance(event, BeforeToolCallEvent) else "post"
            print(f"🔍 Extracted tool data ({event_type}): {tool_data_str[:100]}...")

        return tool_name, tool_data

    def _extract_content_text(self, content: Any) -> str:
        """
        Extract text from Strands content structures for control inspection.

        Handles ContentBlock and ToolResultContent TypedDict structures:
        - text: Plain text content
        - citationsContent: Nested text blocks (unwrapped recursively)
        - toolUse: Tool name (for control traceability)
        - toolResult: Tool output text (recursively extracted)
        - json: Structured data (stringified for inspection)
        - Media blocks (image/video/document): Skipped (not text-inspectable)

        Args:
            content: Can be:
                - list[ContentBlock] from Message.content
                - list[ToolResultContent] from ToolResult.content
                - str from invocation_state
                - dict from invocation_state

        Returns:
            Extracted text string for control evaluation
        """
        if not content:
            return ""

        # String content (from invocation_state)
        if isinstance(content, str):
            return content

        # List of content blocks (ContentBlock or ToolResultContent TypedDicts)
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    # Extract 'text' field (standard text block)
                    if "text" in block:
                        text_parts.append(block["text"])
                    # Extract from citationsContent (nested text blocks)
                    elif "citationsContent" in block:
                        citations_block = block["citationsContent"]
                        if "content" in citations_block:
                            for citation_item in citations_block["content"]:
                                if isinstance(citation_item, dict) and "text" in citation_item:
                                    text_parts.append(citation_item["text"])
                    # For toolUse, include name for control traceability
                    elif "toolUse" in block:
                        tool_name = block["toolUse"].get("name", "unknown")
                        text_parts.append(f"[tool_use: {tool_name}]")
                    # For toolResult, recursively extract text from result content
                    elif "toolResult" in block:
                        result_content = block["toolResult"].get("content", [])
                        result_text = self._extract_content_text(result_content)
                        if result_text:
                            text_parts.append(result_text)
                    # Media blocks (image, video, document) - skip, not text-inspectable
                else:
                    text_parts.append(str(block))
            return "\n".join(text_parts)

        # Dict - single content block or invocation_state value
        if isinstance(content, dict):
            # Single ContentBlock with 'text' field
            if "text" in content:
                return content["text"]
            # ToolResultContent with 'json' field - stringify for inspection
            if "json" in content:
                import json
                return json.dumps(content["json"])

        return str(content)
