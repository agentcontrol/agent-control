"""Agent Control hook integration for Strands."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal

from agent_control_models import EvaluationResult

import agent_control
from agent_control import ControlSteerError, ControlViolationError

try:
    from strands.hooks import (  # type: ignore[import-not-found]
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
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "Strands integration requires strands-agents. "
        "Install with: agent-control-sdk[strands-agents]."
    ) from exc

logger = logging.getLogger(__name__)


def _action_error(result: EvaluationResult) -> tuple[str, Exception] | None:
    """Return the first blocking action as an exception."""

    match = next((m for m in (result.matches or []) if m.action in ("deny", "steer")), None)
    if not match:
        return None

    msg = getattr(getattr(match, "result", None), "message", None) or result.reason
    msg = msg or f"Control '{match.control_name}' triggered"

    if match.action == "deny":
        deny_err = ControlViolationError(message=f"Policy violation [{match.control_name}]: {msg}")
        return "deny", deny_err

    ctx = getattr(match, "steering_context", None)
    ctx_msg = getattr(ctx, "message", None) if ctx else None
    steer_err = ControlSteerError(
        control_name=match.control_name,
        message=f"Steering required [{match.control_name}]: {msg}",
        steering_context=ctx_msg or msg,
    )
    return "steer", steer_err


class AgentControlHook(HookProvider):
    """Hook that integrates Agent Control with Strands lifecycle events.

    The Agent Control server is required for control distribution and policy assignment.
    Controls may specify execution="sdk" or execution="server".
    """

    def __init__(
        self,
        agent_name: str,
        event_control_list: list[type] | None = None,
        on_violation_callback: Callable[[dict[str, Any], EvaluationResult], None] | None = None,
        enable_logging: bool = True,
    ) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.event_control_list = event_control_list
        self.on_violation_callback = on_violation_callback
        self.enable_logging = enable_logging

    def _invoke_callback(self, control_name: str, stage: str, result: EvaluationResult) -> None:
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
        if use_runtime_error:
            raise RuntimeError(str(error))
        raise error

    async def _evaluate_and_enforce(
        self,
        step_name: str,
        input: Any | None = None,
        output: Any | None = None,
        step_type: Literal["tool", "llm"] = "llm",
        stage: Literal["pre", "post"] = "pre",
        violation_type: str = "Step",
        use_runtime_error: bool = False,
    ) -> None:
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
            control_name = getattr(err, "control_name", "unknown")
            self._invoke_callback(control_name, stage, result)
            if isinstance(err, ControlSteerError):
                logger.debug(
                    "agent=<%s>, step=<%s>, stage=<%s> | steering required",
                    self.agent_name,
                    step_name,
                    stage,
                )
            self._raise_error(err, use_runtime_error)

        if not result.is_safe:
            control_name = "unknown"
            reason = result.reason

            if result.matches:
                first_match = result.matches[0]
                control_name = first_match.control_name
                if not reason:
                    match_result = getattr(first_match, "result", None)
                    msg = getattr(match_result, "message", None) if match_result else None
                    reason = msg or f"Control '{control_name}' triggered"

            logger.debug(
                "agent=<%s>, control=<%s> | control violation",
                self.agent_name,
                control_name,
            )
            self._invoke_callback(control_name, stage, result)
            error_msg = f"Policy violation [{control_name}]: {reason}"
            self._raise_error(ControlViolationError(message=error_msg), use_runtime_error)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        event_map = {
            BeforeInvocationEvent: self.check_before_invocation,
            BeforeModelCallEvent: self.check_before_model,
            AfterModelCallEvent: self.check_after_model,
            BeforeToolCallEvent: self.check_before_tool,
            AfterToolCallEvent: self.check_after_tool,
            BeforeNodeCallEvent: self.check_before_node,
            AfterNodeCallEvent: self.check_after_node,
        }

        events_to_register = (
            self.event_control_list if self.event_control_list else event_map.keys()
        )

        if self.enable_logging:
            logger.debug(
                "agent=<%s>, events=<%s> | registering hooks",
                self.agent_name,
                ",".join([e.__name__ for e in events_to_register if e in event_map]),
            )

        for event_type in events_to_register:
            if event_type in event_map:
                registry.add_callback(event_type, event_map[event_type])  # type: ignore[arg-type]

    async def check_before_invocation(self, event: BeforeInvocationEvent) -> None:
        input_text, _ = self._extract_messages(event)
        await self._evaluate_and_enforce(
            step_name="check_before_invocation",
            input=input_text,
            step_type="llm",
            stage="pre",
            violation_type="Invocation",
        )

    async def check_before_model(self, event: BeforeModelCallEvent) -> None:
        input_text, _ = self._extract_messages(event)
        await self._evaluate_and_enforce(
            step_name="check_before_model",
            input=input_text,
            step_type="llm",
            stage="pre",
            violation_type="Model call",
        )

    async def check_after_model(self, event: AfterModelCallEvent) -> None:
        _, output_text = self._extract_messages(event)
        await self._evaluate_and_enforce(
            step_name="check_after_model",
            output=output_text,
            step_type="llm",
            stage="post",
            violation_type="Model call",
        )

    async def check_before_tool(self, event: BeforeToolCallEvent) -> None:
        tool_name, tool_input = self._extract_tool_data(event)
        await self._evaluate_and_enforce(
            step_name=tool_name,
            input=tool_input,
            step_type="tool",
            stage="pre",
            violation_type="Tool execution",
            use_runtime_error=True,
        )

    async def check_after_tool(self, event: AfterToolCallEvent) -> None:
        tool_name, tool_output = self._extract_tool_data(event)
        await self._evaluate_and_enforce(
            step_name=tool_name,
            output=tool_output,
            step_type="tool",
            stage="post",
            violation_type="Tool result",
            use_runtime_error=True,
        )

    async def check_before_node(self, event: BeforeNodeCallEvent) -> None:
        input_text, _ = self._extract_messages(event)
        node_id = getattr(event, "node_id", "unknown")
        await self._evaluate_and_enforce(
            step_name=node_id,
            input=input_text,
            step_type="llm",
            stage="pre",
            violation_type=f"Node call ({node_id})",
        )

    async def check_after_node(self, event: AfterNodeCallEvent) -> None:
        _, output_text = self._extract_messages(event)
        node_id = getattr(event, "node_id", "unknown")
        await self._evaluate_and_enforce(
            step_name=node_id,
            output=output_text,
            step_type="llm",
            stage="post",
            violation_type=f"Node result ({node_id})",
        )

    def _extract_user_message_from_list(self, messages: list | None, reverse: bool = False) -> str:
        if not messages:
            return ""
        msg_iter = reversed(messages) if reverse else messages
        for msg in msg_iter:
            if isinstance(msg, dict) and msg.get("role") == "user":
                return self._extract_content_text(msg.get("content", ""))
        return ""

    def _extract_messages(self, event: Any) -> tuple[str, str]:
        input_text = ""
        output_text = ""

        if isinstance(event, BeforeInvocationEvent):
            input_text = self._extract_user_message_from_list(event.messages)
        elif isinstance(event, BeforeModelCallEvent):
            if "messages" in event.invocation_state:
                input_text = self._extract_user_message_from_list(
                    event.invocation_state["messages"], reverse=True
                )
            elif "input" in event.invocation_state:
                input_text = self._extract_content_text(event.invocation_state["input"])
        elif isinstance(event, AfterModelCallEvent):
            if event.stop_response:
                message_content = event.stop_response.message.get("content", [])
                output_text = self._extract_content_text(message_content)
        elif isinstance(event, BeforeNodeCallEvent):
            state = event.invocation_state or {}
            if "messages" in state:
                input_text = self._extract_user_message_from_list(state["messages"], reverse=True)
            elif "input" in state:
                input_text = self._extract_content_text(state["input"])
        elif isinstance(event, AfterNodeCallEvent):
            state = event.invocation_state or {}
            for key in ("output", "result", "response", "messages"):
                if key in state:
                    output_text = self._extract_content_text(state[key])
                    break

        return input_text, output_text

    def _extract_tool_data(
        self,
        event: BeforeToolCallEvent | AfterToolCallEvent,
    ) -> tuple[str, Any]:
        if event.selected_tool:
            tool_name = event.selected_tool.tool_name
        else:
            tool_name = event.tool_use.get("name", "unknown-tool")

        if isinstance(event, BeforeToolCallEvent):
            tool_data = event.tool_use.get("input", {})
        else:
            if event.exception:
                tool_data = f"ERROR: {str(event.exception)}"
            else:
                tool_data = self._extract_content_text(event.result.get("content", []))

        return tool_name, tool_data

    def _extract_content_text(self, content: Any) -> str:
        if not content:
            return ""

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        text_parts.append(block["text"])
                    elif "citationsContent" in block:
                        citations_block = block["citationsContent"]
                        if "content" in citations_block:
                            for citation_item in citations_block["content"]:
                                if isinstance(citation_item, dict) and "text" in citation_item:
                                    text_parts.append(citation_item["text"])
                    elif "toolUse" in block:
                        tool_name = block["toolUse"].get("name", "unknown")
                        text_parts.append(f"[tool_use: {tool_name}]")
                    elif "toolResult" in block:
                        result_content = block["toolResult"].get("content", [])
                        result_text = self._extract_content_text(result_content)
                        if result_text:
                            text_parts.append(result_text)
                else:
                    text_parts.append(str(block))
            return "\n".join(text_parts)

        if isinstance(content, dict):
            if "text" in content:
                return str(content["text"])
            if "json" in content:
                import json

                return json.dumps(content["json"])

        return str(content)
