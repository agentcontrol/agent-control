"""Agent Control middleware integration for LangChain agents."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent_control.integrations._tool_controls import ToolControlState, resolve_agent, run_coro_sync

try:
    from langchain.agents.middleware import (
        AgentMiddleware,
        ExtendedModelResponse,
        ModelRequest,
        ModelResponse,
        ToolCallRequest,
    )
    from langchain_core.messages import AIMessage
    from langchain_core.tools import BaseTool
    from langgraph.types import Command
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "LangChain integration requires langchain. "
        "Install with: agent-control-sdk[langchain]."
    ) from exc

logger = logging.getLogger(__name__)


class AgentControlMiddleware(AgentMiddleware[Any, Any, Any]):
    """LangChain middleware that enforces Agent Control policies on tool calls."""

    tools: Sequence[BaseTool] = ()

    def __init__(self, *, agent_name: str | None = None) -> None:
        self._tools_by_name: dict[str, BaseTool] = {}
        self._state = ToolControlState(
            agent=resolve_agent(agent_name),
            get_tools=lambda: list(self._tools_by_name.values()),
        )

    def _capture_tools(self, tools: Sequence[BaseTool | dict[str, Any]]) -> None:
        for tool in tools:
            if isinstance(tool, BaseTool):
                self._tools_by_name[tool.name] = tool

    def _capture_request_tool(self, request: ToolCallRequest) -> None:
        if request.tool is not None:
            self._tools_by_name[request.tool.name] = request.tool

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any] | AIMessage | ExtendedModelResponse[Any]:
        self._capture_tools(request.tools)
        try:
            self._state.ensure_registered_sync()
        except Exception as exc:
            logger.error(
                "LangChain middleware re-registration failed; "
                "continuing without blocking model execution: %s",
                exc,
                exc_info=True,
            )
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any] | AIMessage | ExtendedModelResponse[Any]:
        self._capture_tools(request.tools)
        try:
            await self._state.ensure_registered_async()
        except Exception as exc:
            logger.error(
                "LangChain middleware async re-registration failed; "
                "continuing without blocking model execution: %s",
                exc,
                exc_info=True,
            )
        return await handler(request)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        self._capture_request_tool(request)
        try:
            self._state.ensure_registered_sync()
        except Exception as exc:
            logger.error(
                "LangChain middleware re-registration failed; "
                "continuing without blocking tool '%s': %s",
                request.tool_call["name"],
                exc,
                exc_info=True,
            )
        return run_coro_sync(self._state.run_with_controls(request, handler))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Command[Any] | Any]],
    ) -> Any:
        self._capture_request_tool(request)
        try:
            await self._state.ensure_registered_async()
        except Exception as exc:
            logger.error(
                "LangChain middleware async re-registration failed; "
                "continuing without blocking tool '%s': %s",
                request.tool_call["name"],
                exc,
                exc_info=True,
            )
        return await self._state.run_with_controls(request, handler)
