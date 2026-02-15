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
from agent_control import ControlViolationError
from agent_control.client import AgentControlClient
from agent_control_models import Step


class AgentControlHook(HookProvider):
    """
    A hook that integrates AgentControl safety checks with Strands agents.

    Follows Strands HookProvider pattern for clean integration. Evaluates controls
    at each lifecycle event and applies actions based on control definitions.

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

        # Violation tracking for observability
        self.violation_history = []

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Register callbacks for Strands events."""
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

    async def check_before_invocation(self, event: BeforeInvocationEvent) -> None:
        """Check controls before agent invocation (user input stage)."""
        if self.enable_logging:
            print(f"\n{'='*60}")
            print(f"🟢 AgentControlHook.check_before_invocation() CALLED")
            print(f"{'='*60}")

        input_text, _ = self._extract_messages(event)

        if self.enable_logging:
            print(f"📝 Extracted input text: {input_text[:200] if input_text else '(empty)'}")
            print(f"📊 Input length: {len(input_text)} characters")

        step = Step(type="llm", name="user-input", input=input_text, output="")

        if self.enable_logging:
            print(f"📦 Created Step: type=llm, name=user-input")

        await self._evaluate_and_apply(step, stage="pre", event=event)

        if self.enable_logging:
            print(f"✅ check_before_invocation() COMPLETED")
            print(f"{'='*60}\n")

    async def check_before_model(self, event: BeforeModelCallEvent) -> None:
        """Check controls before LLM call."""
        print(f"\n{'='*60}")
        print(f"🔵 AgentControlHook.check_before_model() CALLED")
        print(f"{'='*60}")

        input_text, _ = self._extract_messages(event)

        print(f"📝 Extracted input text: {input_text[:200]}")
        print(f"📊 Input length: {len(input_text)} characters")

        step = Step(type="llm", name="model-input", input=input_text, output="")
        print(f"📦 Created Step: type=llm, name=model-input")

        await self._evaluate_and_apply(step, stage="pre", event=event)

        print(f"✅ check_before_model() COMPLETED")
        print(f"{'='*60}\n")

    async def check_after_model(self, event: AfterModelCallEvent) -> None:
        """Check controls after LLM call."""
        _, output_text = self._extract_messages(event)

        if self.enable_logging:
            print(f"🔍 [POST] Output: {output_text[:100]}...")

        step = Step(type="llm", name="model-output", input="", output=output_text)
        await self._evaluate_and_apply(step, stage="post", event=event)

    async def check_before_tool(self, event: BeforeToolCallEvent) -> None:
        """Check controls before tool call."""
        # ALWAYS log tool calls (even when enable_logging=False) for visibility
        print(f"\n{'='*70}")
        print(f"🔧 TOOL CALL INTERCEPTED - AgentControlHook.check_before_tool()")
        print(f"{'='*70}")

        # Extract tool name and input from event
        tool_name, tool_input = self._extract_tool_data(event, stage="pre")

        print(f"🔧 Tool name: {tool_name}")
        # Format tool_input for display (might be dict or string)
        if isinstance(tool_input, dict):
            import json
            tool_input_str = json.dumps(tool_input)
        else:
            tool_input_str = str(tool_input) if tool_input else ''
        print(f"📝 Tool input: {tool_input_str[:200] if tool_input_str else '(empty)'}")

        # Create Step with tool name as step_name (enables step_names targeting!)
        step = Step(type="tool", name=tool_name, input=tool_input, output="")

        print(f"📦 Created Step: type=tool, name={tool_name}")
        print(f"   → Controls with step_names=['{tool_name}'] will now be checked!")
        print(f"{'='*70}")

        await self._evaluate_and_apply(step, stage="pre", event=event)

        print(f"✅ check_before_tool() COMPLETED")
        print(f"{'='*70}\n")

    async def check_after_tool(self, event: AfterToolCallEvent) -> None:
        """Check controls after tool call."""
        if self.enable_logging:
            print(f"\n{'='*60}")
            print(f"🔧 AgentControlHook.check_after_tool() CALLED")
            print(f"{'='*60}")

        # Extract tool name and output from event
        tool_name, tool_output = self._extract_tool_data(event, stage="post")

        if self.enable_logging:
            print(f"🔧 Tool name: {tool_name}")
            print(f"📝 Tool output: {tool_output[:200] if tool_output else '(empty)'}")

        # Create Step with tool name as step_name
        # For tool steps, input must be a dict even in post-stage (use empty dict)
        step = Step(type="tool", name=tool_name, input={}, output=tool_output)

        if self.enable_logging:
            print(f"📦 Created Step: type=tool, name={tool_name}")

        await self._evaluate_and_apply(step, stage="post", event=event)

        if self.enable_logging:
            print(f"✅ check_after_tool() COMPLETED")
            print(f"{'='*60}\n")

    async def check_before_node(self, event: BeforeNodeCallEvent) -> None:
        """Check controls before node call (multi-agent graphs)."""
        input_text, _ = self._extract_messages(event)
        node_id = event.node_id if hasattr(event, "node_id") else "unknown"

        step = Step(type="llm", name=f"node-{node_id}", input=input_text, output="")
        await self._evaluate_and_apply(step, stage="pre", event=event)

    async def check_after_node(self, event: AfterNodeCallEvent) -> None:
        """Check controls after node call (multi-agent graphs)."""
        _, output_text = self._extract_messages(event)
        node_id = event.node_id if hasattr(event, "node_id") else "unknown"

        step = Step(type="llm", name=f"node-{node_id}", input="", output=output_text)
        await self._evaluate_and_apply(step, stage="post", event=event)

    # ============================================================================
    # Core Evaluation Logic
    # ============================================================================

    async def _check_controls(
        self,
        step: Step,
        stage: str,
        event: Any,
    ):
        """
        Evaluate step against controls and return the result.

        This method performs the actual control evaluation against the AgentControl server.
        Returns the full EvaluationResult for use by subclasses that need detailed information.

        Args:
            step: The Step object to evaluate
            stage: The evaluation stage ("pre" or "post")
            event: The Strands event that triggered this check

        Returns:
            EvaluationResult with is_safe, matches, non_matches, confidence, etc.
            Returns None if AgentControl is not initialized (fail-open)

        Raises:
            Exception: If there's an error communicating with AgentControl server
        """
        print(f"\n🔄 _check_controls() START")
        print(f"   Stage: {stage}")
        print(f"   Step type: {step.type}, Step name: {step.name}")

        # Get current agent context
        current_agent = agent_control.current_agent()
        if not current_agent:
            print("⚠️  AgentControl not initialized, skipping check")
            return None

        print(f"✓  AgentControl initialized: agent_id={current_agent.agent_id}")

        # Evaluate step against controls
        print(f"🌐 Calling AgentControl server at {self.server_url}...")
        async with AgentControlClient(base_url=self.server_url) as client:
            result = await agent_control.evaluation.check_evaluation(
                client=client,
                agent_uuid=self.agent_uuid,
                step=step,
                stage=stage,
            )

            print(f"\n📊 EVALUATION RESULT:")
            print(f"   is_safe: {result.is_safe}")
            print(f"   confidence: {result.confidence}")
            print(f"   matches: {len(result.matches or [])}")
            if result.matches:
                for i, match in enumerate(result.matches, 1):
                    print(f"   Match {i}: {match.control_name}")

            print(f"🔄 _check_controls() END\n")
            return result

    async def _evaluate_and_apply(
        self,
        step: Step,
        stage: str,
        event: Any,
    ) -> None:
        """
        Evaluate step against controls and apply action to event.

        This is where the actual control execution happens. Uses _check_controls()
        to get the evaluation result, then applies actions based on control definitions.
        """
        print(f"\n🔄 _evaluate_and_apply() START")
        print(f"   Stage: {stage}")
        print(f"   Step type: {step.type}, Step name: {step.name}")
        print(f"   Agent UUID: {self.agent_uuid}")
        print(f"   Server URL: {self.server_url}")

        try:
            # Evaluate step against controls
            result = await self._check_controls(step, stage, event)

            if result is None:
                # AgentControl not initialized, fail open
                return

            # Apply control action if not safe
            if not result.is_safe:
                print(f"🚫 NOT SAFE - Applying violation handling...")
                self._handle_violation(result, stage, event)
            else:
                print(f"✅ SAFE - No violations detected")

        except ControlViolationError:
            # Re-raise ControlViolationError to block the request
            print(f"🚨 ControlViolationError raised - blocking request")
            raise
        except Exception as e:
            print(f"❌ Error in AgentControl check: {e}")
            import traceback
            traceback.print_exc()
            # Fail open for availability

        print(f"🔄 _evaluate_and_apply() END\n")

    def _handle_violation(self, result: Any, stage: str, event: Any) -> None:
        """
        Handle safety violation by applying control action to event.

        Control definitions determine the action (deny/allow/warn).
        This method applies the action to the Strands event.
        """
        print(f"\n🚨 _handle_violation() START")

        # Get first matching control, or use generic info if matches is empty/None
        if result.matches and len(result.matches) > 0:
            match = result.matches[0]
            control_name = match.control_name
            control_id = match.control_id if hasattr(match, "control_id") else None
            message = getattr(match, "message", "Safety violation detected")
        else:
            # No match details, but is_safe=False - use generic info
            control_name = "unknown-control"
            control_id = None
            # Check if there's error information
            if result.errors and len(result.errors) > 0:
                message = f"Safety violation: {result.errors[0]}"
            else:
                message = "Safety violation detected by AgentControl"

        # Build violation info
        violation = {
            "agent": self.agent_name,
            "stage": stage,
            "control_name": control_name,
            "control_id": control_id,
            "message": message,
        }
        self.violation_history.append(violation)

        print(f"🚫 Safety violation detected!")
        print(f"   Agent: {violation['agent']}")
        print(f"   Stage: {violation['stage']}")
        print(f"   Control: {violation['control_name']}")
        print(f"   Message: {violation['message']}")

        # Call custom callback
        if self.on_violation_callback:
            print(f"📞 Calling custom violation callback...")
            self.on_violation_callback(violation, result)

        # Apply action to event based on event type
        # Control definitions determine the action - we just apply it
        print(f"⚡ Applying action to event...")
        self._apply_action_to_event(event, violation["message"])

        print(f"🚨 _handle_violation() END\n")

    def _apply_action_to_event(self, event: Any, message: str) -> None:
        """
        Apply control action to Strands event.

        Different event types support different action mechanisms:
        - BeforeInvocationEvent: Raise exception to block unsafe input
        - AfterModelCallEvent: Set retry=True to regenerate response
        - BeforeToolCallEvent: Set cancel_tool with message
        """
        if self.enable_logging:
            print(f"\n⚡ _apply_action_to_event() START")
            print(f"   Event type: {type(event).__name__}")
            print(f"   Message: {message}")
            print(f"   Has 'retry' attr: {hasattr(event, 'retry')}")
            print(f"   Has 'cancel_tool' attr: {hasattr(event, 'cancel_tool')}")

        # BeforeInvocationEvent - block by raising exception
        event_type_name = type(event).__name__

        if event_type_name == "BeforeInvocationEvent":
            print(f"\n{'='*70}")
            print(f"✅ SAFETY BLOCK SUCCESSFUL - REQUEST BLOCKED")
            print(f"{'='*70}")
            print(f"🛡️  AgentControl detected sensitive information in user input")
            print(f"🚫 Blocking request before it reaches the LLM")
            print(f"📝 Reason: {message}")
            print(f"{'='*70}")
            print(f"⚠️  NOTE: The 'node failed' / 'graph execution failed' messages below")
            print(f"    are from Strands framework - they indicate the safety block worked!")
            print(f"    This is a SUCCESS, not a failure.")
            print(f"{'='*70}\n")
            raise ControlViolationError(
                f"I cannot process your request at the moment because it contains sensitive information. {message}"
            )

        # AfterModelCallEvent - retry with guidance
        elif hasattr(event, "retry"):
            if self.enable_logging:
                print(f"✓  Setting event.retry = True")
            event.retry = True
            if hasattr(event, "retry_guidance"):
                if self.enable_logging:
                    print(f"✓  Setting event.retry_guidance = '{message}'")
                event.retry_guidance = message

        # BeforeToolCallEvent - cancel tool execution
        elif hasattr(event, "cancel_tool"):
            if self.enable_logging:
                print(f"✓  Setting event.cancel_tool = '{message}'")
            event.cancel_tool = message
        else:
            print(f"⚠️  WARNING: Event type '{event_type_name}' not handled - no action taken!")

        print(f"⚡ _apply_action_to_event() END\n")

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

    def _extract_tool_data(self, event: Any, stage: str) -> tuple[str, str]:
        """
        Extract tool name and input/output from tool call events.

        Handles BeforeToolCallEvent and AfterToolCallEvent from Strands.

        Args:
            event: BeforeToolCallEvent or AfterToolCallEvent
            stage: "pre" or "post" to determine what to extract

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
        if stage == "pre":
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

        else:  # stage == "post"
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
            print(f"🔍 Extracted tool data ({stage}): {tool_data_str[:100]}...")

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

    # ============================================================================
    # Observability Methods
    # ============================================================================

    def get_violation_count(self) -> int:
        """Get total number of safety violations detected."""
        return len(self.violation_history)

    def get_violations_by_stage(self, stage: str) -> list[dict]:
        """Get all violations for a specific stage (pre/post)."""
        return [v for v in self.violation_history if v["stage"] == stage]

    def reset_violations(self) -> None:
        """Clear violation history."""
        self.violation_history.clear()
