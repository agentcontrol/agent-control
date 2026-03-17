from __future__ import annotations

from typing import Annotated

from agent_control import control
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict

from model import create_chat_model
from tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "You are a helpful customer service assistant. "
    "You have access to order tracking, customer profiles, and internal systems. "
    "Use the appropriate tool for each question:\n"
    "- get_order_status: shipping status, items, delivery estimate\n"
    "- get_order_internal: payment details, internal notes, fraud flags\n"
    "- lookup_customer: name, membership, recent orders\n"
    "- lookup_customer_pii: phone, address, DOB, credit card, risk score\n"
    "Always use tools to answer questions. Be concise and helpful."
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


# Module-level shared state for the controlled LLM call.
# Must be module-level so @control() is registered before init().
_llm_messages: list[BaseMessage] = []
_llm_response: list = [None]
_llm_instance = None


@control(step_name="llm_call")
async def _invoke_llm(user_input: str) -> str:
    """Controlled LLM call - Agent Control evaluates input (pre) and output (post)."""
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + _llm_messages
    response = _llm_instance.invoke(messages)
    _llm_response[0] = response
    return str(response.content)


def build_graph():
    global _llm_instance
    _llm_instance = create_chat_model().bind_tools(ALL_TOOLS)

    async def call_model(state: AgentState):
        _llm_messages.clear()
        _llm_messages.extend(state["messages"])
        user_msg = state["messages"][-1]
        user_text = str(user_msg.content) if hasattr(user_msg, "content") else ""

        await _invoke_llm(user_input=user_text)

        return {"messages": [_llm_response[0]]}

    builder = StateGraph(AgentState)
    builder.add_node("llm", call_model)
    builder.add_node("tools", ToolNode(ALL_TOOLS))
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", tools_condition)
    builder.add_edge("tools", "llm")
    return builder.compile()
