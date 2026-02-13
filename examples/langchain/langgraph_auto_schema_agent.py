"""LangGraph agent that relies on auto-derived step schemas from @control tools.

This example demonstrates the SDK flow we want:
1. Define tool-like functions with Python type hints.
2. Decorate them with ``@control()``.
3. Call ``agent_control.init(...)`` without explicit ``steps=...``.
4. Let the SDK auto-discover decorated functions and derive JSON Schemas.

Run:
    cd examples/langchain
    uv run langgraph_auto_schema_agent.py

Prerequisite:
    Start the Agent Control server (`cd server && make run`) so @control()
    evaluations can execute successfully at runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Annotated, Literal, TypedDict
from uuid import UUID

import agent_control
from agent_control import ControlViolationError, control, get_registered_steps
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

AGENT_ID = UUID("736dc6fa-6f6d-4464-a655-c3fe2f5d2e6e")
AGENT_NAME = "LangGraph Auto Schema Demo"
AGENT_DESCRIPTION = "LangGraph tool routing with @control auto step schema derivation"


class AgentState(TypedDict):
    """LangGraph state object."""

    messages: Annotated[list[BaseMessage], add_messages]


class OrderStatus(BaseModel):
    """Structured result for order status lookups."""

    order_id: str = Field(description="External order identifier")
    status: Literal["processing", "shipped", "delivered"]
    estimated_delivery_days: int | None = Field(
        default=None,
        ge=0,
        description="Days until delivery; null when already delivered",
    )
    history: list[str] = Field(default_factory=list)


class RefundDecision(BaseModel):
    """Structured result for refund checks."""

    order_id: str
    reason: Literal["damaged", "late", "cancelled"]
    approved: bool
    approved_amount: float = Field(ge=0)


class OrderStatusPayload(TypedDict):
    """Tool payload returned to LangGraph."""

    order_id: str
    status: Literal["processing", "shipped", "delivered"]
    estimated_delivery_days: int | None
    history: list[str]


class RefundDecisionPayload(TypedDict):
    """Tool payload returned to LangGraph."""

    order_id: str
    reason: Literal["damaged", "late", "cancelled"]
    approved: bool
    approved_amount: float


def _parse_order_id(user_text: str) -> str:
    """Extract a stable order identifier from user text."""
    match = re.search(r"(?:order\s*)?(\d{4,8})", user_text)
    if match:
        return f"ORD-{match.group(1)}"
    return "ORD-1001"


async def _lookup_order_status(order_id: str, include_history: bool = False) -> OrderStatus:
    """Fetch fulfillment status for an order."""
    base = OrderStatus(order_id=order_id, status="shipped", estimated_delivery_days=2)
    if include_history:
        base.history = [
            "Label created",
            "Picked up by carrier",
            "Arrived at regional hub",
        ]
    return base


setattr(_lookup_order_status, "name", "lookup_order_status")
setattr(_lookup_order_status, "tool_name", "lookup_order_status")
_lookup_order_status_checked = control()(_lookup_order_status)


async def _issue_refund(
    order_id: str,
    reason: Literal["damaged", "late", "cancelled"],
    requested_amount: float | None = None,
) -> RefundDecision:
    """Evaluate refund eligibility for an order."""
    approved_amount = requested_amount if requested_amount is not None else 25.0
    is_approved = approved_amount <= 100.0
    return RefundDecision(
        order_id=order_id,
        reason=reason,
        approved=is_approved,
        approved_amount=approved_amount if is_approved else 0.0,
    )


setattr(_issue_refund, "name", "issue_refund")
setattr(_issue_refund, "tool_name", "issue_refund")
_issue_refund_checked = control()(_issue_refund)


@tool("lookup_order_status")
async def lookup_order_status(order_id: str, include_history: bool = False) -> OrderStatusPayload:
    """LangGraph tool wrapper for order status."""
    result = await _lookup_order_status_checked(
        order_id=order_id,
        include_history=include_history,
    )
    return {
        "order_id": result.order_id,
        "status": result.status,
        "estimated_delivery_days": result.estimated_delivery_days,
        "history": result.history,
    }


@tool("issue_refund")
async def issue_refund(
    order_id: str,
    reason: Literal["damaged", "late", "cancelled"],
    requested_amount: float | None = None,
) -> RefundDecisionPayload:
    """LangGraph tool wrapper for refund decisions."""
    result = await _issue_refund_checked(
        order_id=order_id,
        reason=reason,
        requested_amount=requested_amount,
    )
    return {
        "order_id": result.order_id,
        "reason": result.reason,
        "approved": result.approved,
        "approved_amount": result.approved_amount,
    }


def _build_graph():
    """Build a simple deterministic LangGraph flow with ToolNode."""
    tool_node = ToolNode([lookup_order_status, issue_refund])

    def planner(state: AgentState) -> dict[str, list[AIMessage]]:
        last_message = state["messages"][-1]
        user_text = str(last_message.content)
        lower = user_text.lower()
        order_id = _parse_order_id(user_text)

        if "refund" in lower:
            reason: Literal["damaged", "late", "cancelled"] = "late"
            if "damaged" in lower:
                reason = "damaged"
            elif "cancel" in lower:
                reason = "cancelled"

            requested_amount: float | None = 49.0 if "49" in lower else None
            tool_call = {
                "name": "issue_refund",
                "args": {
                    "order_id": order_id,
                    "reason": reason,
                    "requested_amount": requested_amount,
                },
                "id": "call-refund-1",
                "type": "tool_call",
            }
        else:
            include_history = "history" in lower or "timeline" in lower
            tool_call = {
                "name": "lookup_order_status",
                "args": {
                    "order_id": order_id,
                    "include_history": include_history,
                },
                "id": "call-status-1",
                "type": "tool_call",
            }

        return {"messages": [AIMessage(content="", tool_calls=[tool_call])]}  # type: ignore[arg-type]

    def finalize(state: AgentState) -> dict[str, list[AIMessage]]:
        tool_message = next(
            message for message in reversed(state["messages"]) if isinstance(message, ToolMessage)
        )
        return {
            "messages": [
                AIMessage(content=f"Tool `{tool_message.name}` returned: {tool_message.content}")
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


def _print_auto_derived_steps() -> None:
    """Show the step schemas auto-derived from @control-decorated functions."""
    print("\nAuto-derived step schemas from @control():")
    for step in get_registered_steps():
        print("-" * 80)
        print(json.dumps(step, indent=2, sort_keys=True))


async def main() -> None:
    """Run the demo end-to-end."""
    print("Initializing Agent Control (no explicit steps passed)...")
    agent_control.init(
        agent_name=AGENT_NAME,
        agent_id=AGENT_ID,
        agent_description=AGENT_DESCRIPTION,
        server_url=os.getenv("AGENT_CONTROL_URL"),
    )

    _print_auto_derived_steps()

    app = _build_graph()

    scenarios = [
        "Track order 1001 and include its history",
        "Issue a refund for order 2048 because it was late (49 dollars)",
    ]

    print("\nRunning LangGraph scenarios...")
    for prompt in scenarios:
        print("=" * 80)
        print(f"User: {prompt}")
        try:
            result = await app.ainvoke({"messages": [HumanMessage(content=prompt)]})
            final_message = result["messages"][-1]
            print(f"Assistant: {final_message.content}")
        except ControlViolationError as exc:
            print(f"Assistant: Request blocked by control policy: {exc.message}")
        except RuntimeError as exc:
            print(
                "Assistant: Control evaluation is unavailable. "
                f"Start the Agent Control server and retry. Details: {exc}"
            )
            break


if __name__ == "__main__":
    asyncio.run(main())
