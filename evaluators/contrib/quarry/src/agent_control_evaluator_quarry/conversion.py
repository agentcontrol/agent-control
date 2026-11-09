"""Translate recursive Agent Control steps into Quarry's OpenAI message wire format."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from agent_control_models import JSONObject, JSONValue, Step

from .config import SessionMode


class StepConversionError(ValueError):
    """The supplied step cannot represent an unambiguous Quarry conversation."""


def _text(value: JSONValue) -> str:
    try:
        return value if isinstance(value, str) else json.dumps(value, allow_nan=False)
    except ValueError as exc:
        raise StepConversionError("Tool data must be valid finite JSON.") from exc


def _empty(value: JSONValue) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _message_list(value: JSONValue) -> list[JSONObject]:
    if isinstance(value, dict) and set(value) == {"messages"}:
        value = value["messages"]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise StepConversionError("LLM history must be a messages array of objects.")
    return [item for item in value if isinstance(item, dict)]


@dataclass
class _ConversationBuilder:
    """Request-local conversion state; never retained on the cached evaluator."""

    max_messages: int
    messages: list[JSONObject] = field(default_factory=list)
    calls: dict[str, JSONObject] = field(default_factory=dict)
    llm_calls: set[str] = field(default_factory=set)
    tool_steps: set[str] = field(default_factory=set)
    completed: set[str] = field(default_factory=set)
    tools: list[JSONObject] | None = None

    def append(self, message: JSONObject, *, from_llm: bool = True) -> None:
        if len(self.messages) >= self.max_messages:
            raise StepConversionError("Conversation exceeds max_messages; no scan was run.")
        self.messages.append(message)
        calls = message.get("tool_calls")
        if message.get("role") == "assistant" and isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict) and isinstance(call.get("id"), str):
                    call_id = call["id"]
                    assert isinstance(call_id, str)
                    if call_id in self.calls:
                        raise StepConversionError("Duplicate tool-call ID in conversation.")
                    self.calls[call_id] = call
                    if from_llm:
                        self.llm_calls.add(call_id)
        if message.get("role") == "tool":
            call_id = message.get("tool_call_id")
            if isinstance(call_id, str):
                if call_id in self.completed:
                    raise StepConversionError("Duplicate tool result in conversation.")
                self.completed.add(call_id)

    def add(self, step: Step, path: str, depth: int = 0) -> None:
        if depth > 32:
            raise StepConversionError("Step hierarchy exceeds 32 levels.")
        if step.tools is not None:
            if self.tools is not None and self.tools != step.tools:
                raise StepConversionError("Tool definitions must remain identical within a scan.")
            self.tools = step.tools
        if step.type == "trace":
            if not _empty(step.input) or not _empty(step.output):
                raise StepConversionError(
                    "Trace content must be in Step.children, not input/output."
                )
            for index, child in enumerate(step.children or []):
                self.add(child, f"{path}_{index}", depth + 1)
        elif step.type == "llm":
            if step.children:
                raise StepConversionError("LLM steps cannot have children; use a trace container.")
            self.add_llm(step)
        elif step.type == "tool":
            self.add_tool(step, path, depth)
        else:
            raise StepConversionError("Supported child types are trace, llm, and tool.")

    def add_llm(self, step: Step) -> None:
        if isinstance(step.input, str):
            if step.input:
                self.append({"role": "user", "content": step.input})
        elif step.input is not None:
            history = _message_list(step.input)
            # Message arrays represent cumulative history, while text represents a new turn.
            # Require an exact prefix so repeated snapshots cannot invent duplicate events.
            if history[: len(self.messages)] != self.messages:
                raise StepConversionError(
                    "LLM history must extend the exact conversation prefix; "
                    "use text for a new turn."
                )
            for message in history[len(self.messages) :]:
                self.append(message)
        if isinstance(step.output, str):
            if step.output:
                self.append({"role": "assistant", "content": step.output})
        elif step.output is not None:
            if not isinstance(step.output, dict) or step.output.get("role") != "assistant":
                raise StepConversionError("LLM output must be text or an assistant message object.")
            self.append(step.output)

    def add_tool(self, step: Step, path: str, depth: int) -> None:
        call_id = (step.context or {}).get("tool_call_id")
        if call_id is not None and (not isinstance(call_id, str) or not call_id):
            raise StepConversionError("context.tool_call_id must be a non-empty string.")
        if call_id is None:
            if self.llm_calls - self.completed - self.tool_steps:
                raise StepConversionError(
                    "Tool steps linking an LLM call need context.tool_call_id."
                )
            call_id = f"ac_quarry_{path}"
            if call_id in self.calls:
                raise StepConversionError("Generated tool-call ID conflicts with an existing call.")
        assert isinstance(call_id, str)
        if call_id in self.completed or call_id in self.tool_steps:
            raise StepConversionError("Tool step repeats a tool-call ID.")
        self.tool_steps.add(call_id)
        if call_id in self.calls:
            function = self.calls[call_id].get("function")
            if not isinstance(function, dict) or function.get("name") != step.name:
                raise StepConversionError("Tool step name does not match its assistant call.")
            arguments = function.get("arguments")
            try:
                decoded: JSONValue = json.loads(arguments) if isinstance(arguments, str) else None
            except ValueError as exc:
                raise StepConversionError(
                    "Assistant tool-call arguments must be valid JSON."
                ) from exc
            if decoded != step.input:
                raise StepConversionError("Tool step arguments do not match its assistant call.")
        else:
            self.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": step.name, "arguments": _text(step.input)},
                        }
                    ],
                },
                from_llm=False,
            )
        for index, child in enumerate(step.children or []):
            self.add(child, f"{path}_{index}", depth + 1)
        if step.output is not None:
            self.append({"role": "tool", "tool_call_id": call_id, "content": _text(step.output)})

    def conversation(self) -> JSONObject:
        result: JSONObject = {"messages": list(self.messages)}
        if self.tools is not None:
            result["tools"] = list(self.tools)
        return result


def conversations_from_step(
    step: Step, *, session_mode: SessionMode | None, max_messages: int
) -> list[JSONObject]:
    """Convert a trace or session, preserving child order and explicit session boundaries.

    Trace containers hold content only in children. Sessions contain ordered traces.
    ``per_trace`` isolates each trace; ``continuous`` allows rules across trace boundaries.
    Empty containers produce no conversations. Unknown or ambiguous structures raise
    StepConversionError instead of silently omitting events.

    Args:
        step: Complete trace/session hierarchy in chronological order.
        session_mode: Explicit boundary semantics, required for session roots.
        max_messages: Maximum messages allowed in each converted conversation.

    Returns:
        Quarry conversation objects, one per scan according to the session mode.

    Raises:
        StepConversionError: If conversion requires guessing, dropping content, or
            exceeding the configured message limit or hierarchy depth limit.
    """
    if step.type not in {"trace", "session"}:
        raise StepConversionError("quarry.policy requires a trace or session root Step.")
    roots = [step]
    if step.type == "session":
        if session_mode is None:
            raise StepConversionError("Session evaluation requires an explicit session_mode.")
        if not _empty(step.input) or not _empty(step.output):
            raise StepConversionError("Session content must be in Step.children, not input/output.")
        roots = step.children or []
        if any(child.type != "trace" for child in roots):
            raise StepConversionError(
                "Session children must be trace steps in chronological order."
            )
    builder = _ConversationBuilder(max_messages=max_messages)
    if step.tools is not None:
        builder.tools = step.tools
    conversations: list[JSONObject] = []
    for index, root in enumerate(roots):
        builder.add(root, str(index))
        if step.type == "session" and session_mode == "per_trace":
            if builder.messages:
                conversations.append(builder.conversation())
            builder = _ConversationBuilder(max_messages=max_messages, tools=step.tools)
    if builder.messages:
        conversations.append(builder.conversation())
    return conversations
