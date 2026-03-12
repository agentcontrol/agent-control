"""Minimal LangChain middleware smoke test for Agent Control.

This example proves the LangChain agent-factory middleware path works with
``AgentControlMiddleware`` and protects tool calls without using ``@control()``.
It passes a plain ``@tool``-decorated Python function directly to
``langchain.create_agent(...)``.

Run:
    cd examples/langchain
    uv run setup_langchain_middleware_controls.py
    uv run langchain_middleware_smoke.py

Prerequisite:
    Start the Agent Control server first (`cd server && make run`).
"""

from __future__ import annotations

import os

import agent_control
from agent_control.integrations.langchain import AgentControlMiddleware
from langchain.agents import create_agent
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

AGENT_NAME = "langchain-middleware-smoke"
AGENT_DESCRIPTION = "Minimal LangChain middleware smoke test using Agent Control"


@tool("get_weather")
def get_weather(city: str) -> dict[str, str]:
    """Return a deterministic weather response for a city."""
    return {
        "city": city,
        "forecast": {
            "seattle": "Rainy and 53F",
            "tehran": "Sunny and 75F",
            "tokyo": "Clear and 61F",
        }.get(city.lower(), "Partly cloudy and 68F"),
    }


def _build_agent_for_city(city: str):
    tool_call_id = f"call-weather-{city.lower().replace(' ', '-')}"
    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_weather",
                        "args": {"city": city},
                        "id": tool_call_id,
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=f"Finished processing weather lookup for {city}."),
        ]
    )
    return create_agent(
        model=model,
        tools=[get_weather],
        middleware=[AgentControlMiddleware()],
        system_prompt="Always use the available weather tool before replying.",
        name="agent-control-langchain-middleware-smoke",
    )


def _run_scenario(prompt: str, city: str) -> None:
    app = _build_agent_for_city(city)
    result = app.invoke({"messages": [HumanMessage(content=prompt)]})

    print("=" * 80)
    print(f"User: {prompt}")
    print(f"Final response: {result['messages'][-1].content}")

    tool_message = next(
        message for message in reversed(result["messages"]) if isinstance(message, ToolMessage)
    )
    print(
        f"Raw tool message -> name={tool_message.name!r}, "
        f"status={getattr(tool_message, 'status', None)!r}, "
        f"content={tool_message.content!r}"
    )


def main() -> None:
    """Run the example with one allowed and one blocked scenario."""
    agent_control.init(
        agent_name=AGENT_NAME,
        agent_description=AGENT_DESCRIPTION,
        server_url=os.getenv("AGENT_CONTROL_URL"),
    )

    print("Running LangChain middleware smoke test...")
    _run_scenario("What is the weather in Seattle?", "Seattle")
    _run_scenario("What is the weather in Tehran?", "Tehran")


if __name__ == "__main__":
    main()
