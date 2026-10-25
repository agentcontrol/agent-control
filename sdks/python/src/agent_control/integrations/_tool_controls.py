"""Shared tool-control helpers for optional framework integrations."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar, cast

from agent_control_models import Agent, EvaluationResult
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

import agent_control
from agent_control import AgentControlClient, agents
from agent_control._state import state as sdk_state
from agent_control.validation import ensure_agent_name

try:  # pragma: no cover - optional dependency
    from langgraph.types import Command as _ImportedLangGraphCommand
except Exception:  # pragma: no cover - optional dependency
    _LangGraphCommand: type[Any] | None = None
else:  # pragma: no cover - optional dependency
    _LangGraphCommand = cast(type[Any], _ImportedLangGraphCommand)

logger = logging.getLogger(__name__)

T = TypeVar("T")
ToolHandlerResult = ToolMessage | Any
ToolHandler = Callable[[Any], ToolHandlerResult | Awaitable[ToolHandlerResult]]


def resolve_agent(agent_name: str | None) -> Agent:
    """Resolve the initialized agent, optionally overriding the agent name."""
    current_agent = agent_control.current_agent()
    if current_agent is None:
        raise RuntimeError("Agent Control is not initialized. Call agent_control.init() first.")

    if agent_name is None:
        return current_agent

    return current_agent.model_copy(update={"agent_name": ensure_agent_name(agent_name)})


def run_coro_in_new_loop[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on a dedicated event loop in the current thread."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def run_coro_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine from a synchronous context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_container: list[T | None] = [None]
    exception_container: list[Exception | None] = [None]

    def run_in_thread() -> None:
        try:
            result_container[0] = run_coro_in_new_loop(coro)
        except Exception as exc:  # pragma: no cover - thread path is hard to force
            exception_container[0] = exc

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    thread.join(timeout=10)

    if exception_container[0] is not None:
        raise exception_container[0]
    if result_container[0] is None:
        raise RuntimeError("Timed out while waiting for Agent Control integration coroutine.")
    return result_container[0]


def _tool_block_prefix(tool_name: str) -> str:
    return f"Tool '{tool_name}' was blocked due to security policy."


def _tool_eval_error_prefix(tool_name: str) -> str:
    return f"Tool '{tool_name}' was blocked because policy evaluation failed."


def build_error_tool_message(
    *,
    tool_name: str,
    tool_call_id: str,
    content: str,
) -> ToolMessage:
    """Build an error ToolMessage preserving the original tool identifiers."""
    return ToolMessage(
        content=content,
        name=tool_name,
        tool_call_id=tool_call_id,
        status="error",
    )


def _append_detail(prefix: str, detail: str | None) -> str:
    if detail is None:
        return prefix
    normalized = detail.strip()
    if not normalized:
        return prefix
    return f"{prefix} {normalized}"


def _safe_tool_schema(tool: BaseTool, getter_name: str) -> dict[str, Any] | None:
    getter = getattr(tool, getter_name, None)
    if not callable(getter):
        return None

    try:
        schema = getter()
    except Exception as exc:
        logger.warning(
            "Failed to extract %s for tool '%s': %s",
            getter_name,
            tool.name,
            exc,
        )
        return None

    if not isinstance(schema, dict):
        logger.warning(
            "Ignoring non-dict %s for tool '%s': %r",
            getter_name,
            tool.name,
            schema,
        )
        return None

    return schema


def _normalize_tool_output(output: ToolHandlerResult) -> Any:
    if isinstance(output, ToolMessage):
        return output.content
    if _LangGraphCommand is not None and isinstance(output, _LangGraphCommand):
        command_payload = {
            "graph": output.graph,
            "update": output.update,
            "resume": output.resume,
            "goto": output.goto,
        }
        return {key: value for key, value in command_payload.items() if value is not None}
    return str(output)


def _first_result_message(result: EvaluationResult) -> str | None:
    for match in result.matches or []:
        message = match.result.message
        if message:
            return message
    return result.reason


def result_to_tool_message(
    *,
    result: EvaluationResult,
    tool_name: str,
    tool_call_id: str,
) -> ToolMessage | None:
    """Convert an evaluation result into a blocking ToolMessage when required."""
    if result.errors:
        error_names = ", ".join(error.control_name for error in result.errors)
        content = _append_detail(_tool_eval_error_prefix(tool_name), f"Errors: {error_names}")
        return build_error_tool_message(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            content=content,
        )

    matches = result.matches or []
    deny_match = next((match for match in matches if match.action == "deny"), None)
    if deny_match is not None:
        content = _append_detail(_tool_block_prefix(tool_name), deny_match.result.message)
        return build_error_tool_message(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            content=content,
        )

    steer_match = next((match for match in matches if match.action == "steer"), None)
    if steer_match is not None:
        guidance = None
        if steer_match.steering_context is not None:
            guidance = steer_match.steering_context.message
        if not guidance:
            guidance = steer_match.result.message or result.reason
        content = _tool_block_prefix(tool_name)
        if guidance:
            content = f"{content} Guidance: {guidance}"
        return build_error_tool_message(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            content=content,
        )

    if not result.is_safe:
        content = _append_detail(_tool_block_prefix(tool_name), _first_result_message(result))
        return build_error_tool_message(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            content=content,
        )

    return None


@dataclass
class ToolControlState:
    """Track framework tool registration state and enforce tool evaluations."""

    agent: Agent
    get_tools: Callable[[], Sequence[BaseTool]]
    observed_tool_names: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _current_tools(self) -> list[BaseTool]:
        return list(self.get_tools())

    def _current_tool_names(self) -> set[str]:
        return {tool.name for tool in self._current_tools()}

    def _normalized_steps(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for tool in self._current_tools():
            description = tool.description.strip() if tool.description else None
            step: dict[str, Any] = {
                "type": "tool",
                "name": tool.name,
            }
            if description:
                step["description"] = description
            input_schema = _safe_tool_schema(tool, "get_input_jsonschema")
            if input_schema is not None:
                step["input_schema"] = input_schema
            output_schema = _safe_tool_schema(tool, "get_output_jsonschema")
            if output_schema is not None:
                step["output_schema"] = output_schema
            steps.append(step)
        return steps

    async def _register_async(self) -> None:
        if sdk_state.server_url is None:
            raise RuntimeError(
                "Agent Control server URL is not configured. "
                "Call agent_control.init()."
            )

        async with AgentControlClient(
            base_url=sdk_state.server_url,
            api_key=sdk_state.api_key,
        ) as client:
            await agents.register_agent(
                client,
                self.agent,
                steps=self._normalized_steps(),
                conflict_mode="overwrite",
            )

    async def _register_and_refresh_async(self) -> None:
        await self._register_async()
        await agent_control.refresh_controls_async()

    def _register_and_refresh_sync(self) -> None:
        run_coro_sync(self._register_async())
        agent_control.refresh_controls()

    async def ensure_registered_async(self) -> None:
        current_tool_names = self._current_tool_names()
        with self.lock:
            should_register = current_tool_names != self.observed_tool_names

        if not should_register:
            return

        await self._register_and_refresh_async()
        with self.lock:
            self.observed_tool_names = current_tool_names

    def ensure_registered_sync(self) -> None:
        current_tool_names = self._current_tool_names()
        with self.lock:
            should_register = current_tool_names != self.observed_tool_names

        if not should_register:
            return

        self._register_and_refresh_sync()
        with self.lock:
            self.observed_tool_names = current_tool_names

    async def evaluate_request(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        tool_input: dict[str, Any],
        stage: Literal["pre", "post"],
        output: Any = None,
    ) -> ToolMessage | None:
        try:
            result = await agent_control.evaluate_controls(
                step_name=tool_name,
                input=tool_input,
                output=output,
                step_type="tool",
                stage=stage,
                agent_name=self.agent.agent_name,
            )
        except Exception as exc:
            logger.error(
                "Agent Control evaluation failed for tool '%s' (%s stage): %s",
                tool_name,
                stage,
                exc,
                exc_info=True,
            )
            return build_error_tool_message(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                content=_append_detail(_tool_eval_error_prefix(tool_name), str(exc)),
            )

        return result_to_tool_message(
            result=result,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )

    async def run_with_controls(
        self,
        request: Any,
        handler: ToolHandler,
    ) -> ToolHandlerResult:
        tool_name = request.tool_call["name"]
        tool_call_id = str(request.tool_call.get("id", tool_name))
        raw_args = request.tool_call.get("args", {})
        tool_input = raw_args if isinstance(raw_args, dict) else {"value": raw_args}

        pre_message = await self.evaluate_request(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            stage="pre",
        )
        if pre_message is not None:
            return pre_message

        response = handler(request)
        if inspect.isawaitable(response):
            response = await cast(Awaitable[ToolHandlerResult], response)

        post_message = await self.evaluate_request(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            stage="post",
            output=_normalize_tool_output(cast(ToolHandlerResult, response)),
        )
        if post_message is not None:
            return post_message

        return cast(ToolHandlerResult, response)
