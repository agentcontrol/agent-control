"""Agent Control plugin integration for Strands."""

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
    )
    from strands.plugins import Plugin  # type: ignore[import-not-found]
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "Strands integration requires strands-agents. "
        "Install with: agent-control-sdk[strands-agents]."
    ) from exc

logger = logging.getLogger(__name__)


def _action_error(result: EvaluationResult) -> tuple[str, Exception] | None:
    """Return the first blocking action as an exception."""

    matches = result.matches or []
    deny_match = next((m for m in matches if m.action == "deny"), None)
    if deny_match:
        msg = getattr(getattr(deny_match, "result", None), "message", None) or result.reason
        msg = msg or f"Control '{deny_match.control_name}' triggered"
        deny_err = ControlViolationError(
            control_id=deny_match.control_id,
            control_name=deny_match.control_name,
            message=msg,
            metadata=getattr(deny_match.result, "metadata", None),
        )
        return "deny", deny_err

    steer_match = next((m for m in matches if m.action == "steer"), None)
    if not steer_match:
        return None

    msg = getattr(getattr(steer_match, "result", None), "message", None) or result.reason
    msg = msg or f"Control '{steer_match.control_name}' triggered"
    ctx = getattr(steer_match, "steering_context", None)
    ctx_msg = getattr(ctx, "message", None) if ctx else None
    steer_err = ControlSteerError(
        control_id=steer_match.control_id,
        control_name=steer_match.control_name,
        message=f"Steering required [{steer_match.control_name}]: {msg}",
        metadata=getattr(steer_match.result, "metadata", None),
        steering_context=ctx_msg or msg,
    )
    return "steer", steer_err


class AgentControlPlugin(Plugin):
    """Plugin that integrates Agent Control with Strands lifecycle events.

    The Agent Control server is required for control distribution and policy assignment.
    Controls may specify execution="sdk" or execution="server".
    """

    name = "agent-control-plugin"

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
        context: dict[str, Any] | None = None,
        step_type: Literal["tool", "llm"] = "llm",
        stage: Literal["pre", "post"] = "pre",
        use_runtime_error: bool = False,
    ) -> None:
        result = await agent_control.evaluate_controls(
            step_name=step_name,
            input=input,
            output=output,
            context=context,
            step_type=step_type,
            stage=stage,
            agent_name=self.agent_name,
        )

        if result.errors:
            error_names = ", ".join(
                e.control_name for e in result.errors if getattr(e, "control_name", None)
            )
            self._raise_error(
                RuntimeError(
                    "Control evaluation failed; execution blocked for safety. "
                    f"Errors: {error_names or 'unknown'}"
                ),
                use_runtime_error,
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
            self._raise_error(
                ControlViolationError(
                    control_name=control_name,
                    message=reason or "Control violation",
                    metadata=(
                        getattr(first_match.result, "metadata", None)
                        if result.matches
                        else None
                    ),
                ),
                use_runtime_error,
            )

    def init_agent(self, agent: Any) -> None:
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
                agent.add_hook(event_map[event_type], event_type)

    async def check_before_invocation(self, event: BeforeInvocationEvent) -> None:
        input_text, _ = self._extract_messages(event)
        await self._evaluate_and_enforce(
            step_name="check_before_invocation",
            input=input_text,
            step_type="llm",
            stage="pre",
        )

    async def check_before_model(self, event: BeforeModelCallEvent) -> None:
        input_text, _ = self._extract_messages(event)
        await self._evaluate_and_enforce(
            step_name="check_before_model",
            input=input_text,
            step_type="llm",
            stage="pre",
        )

    async def check_after_model(self, event: AfterModelCallEvent) -> None:
        input_text, output_text = self._extract_messages(event)
        context = self._extract_context(event)
        await self._evaluate_and_enforce(
            step_name="check_after_model",
            input=input_text,
            output=output_text,
            context=context,
            step_type="llm",
            stage="post",
        )

    async def check_before_tool(self, event: BeforeToolCallEvent) -> None:
        tool_name, tool_input = self._extract_tool_data(event)
        context = self._extract_context(event)
        await self._evaluate_and_enforce(
            step_name=tool_name,
            input=tool_input,
            context=context,
            step_type="tool",
            stage="pre",
            use_runtime_error=True,
        )

    async def check_after_tool(self, event: AfterToolCallEvent) -> None:
        tool_name, tool_output = self._extract_tool_data(event)
        tool_input = event.tool_use.get("input", {}) if event.tool_use else {}
        context = self._extract_context(event)
        await self._evaluate_and_enforce(
            step_name=tool_name,
            input=tool_input,
            output=tool_output,
            context=context,
            step_type="tool",
            stage="post",
            use_runtime_error=True,
        )

    async def check_before_node(self, event: BeforeNodeCallEvent) -> None:
        input_text, _ = self._extract_messages(event)
        node_id = getattr(event, "node_id", "unknown")
        context = self._extract_context(event)
        await self._evaluate_and_enforce(
            step_name=node_id,
            input=input_text,
            context=context,
            step_type="llm",
            stage="pre",
        )

    async def check_after_node(self, event: AfterNodeCallEvent) -> None:
        input_text, output_text = self._extract_messages(event)
        node_id = getattr(event, "node_id", "unknown")
        context = self._extract_context(event)
        await self._evaluate_and_enforce(
            step_name=node_id,
            input=input_text,
            output=output_text,
            context=context,
            step_type="llm",
            stage="post",
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
            state = event.invocation_state or {}
            if "messages" in state:
                input_text = self._extract_user_message_from_list(
                    state["messages"], reverse=True
                )
            elif "input" in state:
                input_text = self._extract_content_text(state["input"])
        elif isinstance(event, AfterModelCallEvent):
            state = event.invocation_state or {}
            if "messages" in state:
                input_text = self._extract_user_message_from_list(
                    state["messages"], reverse=True
                )
            elif "input" in state:
                input_text = self._extract_content_text(state["input"])
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
            if "messages" in state:
                input_text = self._extract_user_message_from_list(state["messages"], reverse=True)
            elif "input" in state:
                input_text = self._extract_content_text(state["input"])

        return input_text, output_text

    def _extract_context(self, event: Any) -> dict[str, Any] | None:
        state = getattr(event, "invocation_state", None)
        if isinstance(state, dict):
            ctx = state.get("context")
            if isinstance(ctx, dict):
                return ctx
        return None

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
                    elif "content" in block:
                        nested = self._extract_content_text(block["content"])
                        if nested:
                            text_parts.append(nested)
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
            if "content" in content:
                return self._extract_content_text(content["content"])
            if "json" in content:
                import json

                return json.dumps(content["json"])

        return str(content)
