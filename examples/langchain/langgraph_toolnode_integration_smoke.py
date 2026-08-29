"""Minimal LangGraph smoke test for the Agent Control ToolNode integration.

This example proves the LangGraph ToolNode wrapper path works without using
``@control()`` on the underlying tool implementation. It passes a plain
``@tool``-decorated Python function directly to the Agent Control LangGraph
integration.

Run:
    cd examples/langchain
    uv run setup_langgraph_toolnode_controls.py
    uv run langgraph_toolnode_integration_smoke.py

Prerequisite:
    Start the Agent Control server first (`cd server && make run`).
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Annotated, TypedDict

import agent_control
from agent_control.integrations.langgraph import create_controlled_tool_node
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

AGENT_NAME = "langgraph-toolnode-smoke"
AGENT_DESCRIPTION = "Minimal LangGraph ToolNode smoke test using Agent Control integration"


class AgentState(TypedDict):
    """LangGraph state object."""

    messages: Annotated[list[BaseMessage], add_messages]


@tool("get_weather")
async def get_weather(city: str) -> dict[str, str]:
    """Return a deterministic weather response for a city."""
    return {
        "city": city,
        "forecast": {
            "seattle": "Rainy and 53F",
            "tehran": "Sunny and 75F",
            "tokyo": "Clear and 61F",
        }.get(city.lower(), "Partly cloudy and 68F"),
    }


def _extract_city(user_text: str) -> str:
    """Extract a city token from a simple prompt."""
    match = re.search(r"(?:for|in)\s+([A-Za-z][A-Za-z\\s-]*)", user_text)
    if match:
        return match.group(1).strip().rstrip("?.!")
    return user_text.strip().split()[-1].rstrip("?.!")


def _build_graph():
    """Build a deterministic graph that always routes to the weather tool."""
    tool_node = create_controlled_tool_node([get_weather])

    def planner(state: AgentState) -> dict[str, list[AIMessage]]:
        user_text = str(state["messages"][-1].content)
        city = _extract_city(user_text)
        tool_call = {
            "name": "get_weather",
            "args": {"city": city},
            "id": f"call-weather-{city.lower().replace(' ', '-')}",
            "type": "tool_call",
        }
        return {"messages": [AIMessage(content="", tool_calls=[tool_call])]}  # type: ignore[arg-type]

    def finalize(state: AgentState) -> dict[str, list[AIMessage]]:
        tool_message = next(
            message for message in reversed(state["messages"]) if isinstance(message, ToolMessage)
        )
        status = getattr(tool_message, "status", None) or "success"
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"Tool `{tool_message.name}` finished with status `{status}`: "
                        f"{tool_message.content}"
                    )
                )
            ]
        }

    graph = StateGraph(AgentState)
    graph.add_node("planner", planner)
    graph.add_node("tools", tool_node)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "tools")
    graph.add_edge("tools", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


async def main() -> None:
    """Run the example with one allowed and one blocked scenario."""
    agent_control.init(
        agent_name=AGENT_NAME,
        agent_description=AGENT_DESCRIPTION,
        server_url=os.getenv("AGENT_CONTROL_URL"),
    )

    app = _build_graph()
    scenarios = [
        "What is the weather in Seattle?",
        "What is the weather in Tehran?",
    ]

    print("Running LangGraph ToolNode integration smoke test...")
    for prompt in scenarios:
        print("=" * 80)
        print(f"User: {prompt}")
        result = await app.ainvoke({"messages": [HumanMessage(content=prompt)]})

        final_message = result["messages"][-1]
        print(final_message.content)

        tool_message = next(
            message for message in reversed(result["messages"]) if isinstance(message, ToolMessage)
        )
        print(
            f"Raw tool message -> name={tool_message.name!r}, "
            f"status={getattr(tool_message, 'status', None)!r}, "
            f"content={tool_message.content!r}"
        )


if __name__ == "__main__":
    asyncio.run(main())
