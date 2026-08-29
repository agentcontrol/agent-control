"""Agent Control ToolNode integration for LangGraph."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent_control.integrations._tool_controls import (
    ToolControlState,
    resolve_agent,
    run_coro_sync,
)

try:
    from langchain_core.tools import BaseTool
    from langgraph.prebuilt import ToolNode
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "LangGraph integration requires langgraph. "
        "Install with: agent-control-sdk[langgraph]."
    ) from exc

logger = logging.getLogger(__name__)

_TOOLNODE_DEFAULT = object()


def create_controlled_tool_node(
    tools: Sequence[BaseTool | Callable[..., Any]],
    *,
    agent_name: str | None = None,
    name: str = "tools",
    tags: list[str] | None = None,
    handle_tool_errors: Any = _TOOLNODE_DEFAULT,
    messages_key: str = "messages",
) -> ToolNode:
    """Create a ToolNode configured with Agent Control policy enforcement."""
    resolved_agent = resolve_agent(agent_name)
    tool_node_ref: dict[str, ToolNode] = {}

    state = ToolControlState(
        agent=resolved_agent,
        get_tools=lambda: list(tool_node_ref["tool_node"].tools_by_name.values()),
    )

    def wrap_tool_call(
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        try:
            state.ensure_registered_sync()
        except Exception as exc:
            logger.error(
                "LangGraph ToolNode re-registration failed; "
                "continuing without blocking tool '%s': %s",
                request.tool_call["name"],
                exc,
                exc_info=True,
            )
        return run_coro_sync(state.run_with_controls(request, handler))

    async def awrap_tool_call(
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        try:
            await state.ensure_registered_async()
        except Exception as exc:
            logger.error(
                "LangGraph ToolNode async re-registration failed; "
                "continuing without blocking tool '%s': %s",
                request.tool_call["name"],
                exc,
                exc_info=True,
            )
        return await state.run_with_controls(request, handler)

    tool_node_kwargs: dict[str, Any] = {
        "name": name,
        "tags": tags,
        "messages_key": messages_key,
        "wrap_tool_call": wrap_tool_call,
        "awrap_tool_call": awrap_tool_call,
    }
    if handle_tool_errors is not _TOOLNODE_DEFAULT:
        tool_node_kwargs["handle_tool_errors"] = handle_tool_errors

    tool_node = ToolNode(tools, **tool_node_kwargs)
    tool_node_ref["tool_node"] = tool_node

    try:
        state.ensure_registered_sync()
    except Exception as exc:
        logger.error(
            "Initial LangGraph ToolNode registration failed; continuing without blocking tools: %s",
            exc,
            exc_info=True,
        )

    return tool_node
