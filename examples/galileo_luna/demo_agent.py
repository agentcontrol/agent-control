#!/usr/bin/env python3
"""Demo agent protected by a direct Galileo Luna evaluator control.

Prerequisites:
    1. Start server: make server-run
    2. Create controls: uv run python setup_controls.py
    3. Set Galileo credentials where this script runs:
       GALILEO_API_SECRET_KEY or GALILEO_API_SECRET
       GALILEO_LUNA_INVOKE_URL

Usage:
    uv run python demo_agent.py
"""

from __future__ import annotations

import asyncio
import logging
import os

import agent_control
from agent_control import ControlViolationError, control

AGENT_NAME = "galileo-luna-agent"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("agent_control").setLevel(logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def simulated_support_model(message: str) -> str:
    """Return deterministic demo replies so controls are easy to see."""
    lower = message.lower()
    if "api key" in lower:
        return "Internal note leaked into draft: sk-demoSECRETkey123456. Please rotate it."
    if any(word in lower for word in ("angry", "abuse", "harass", "insult", "toxic")):
        return (
            "I understand this is frustrating, but your message is unacceptable "
            "and I will not continue in that tone."
        )
    return "Thanks for reaching out. I can help with your account and billing questions."


@control(step_name="draft_customer_reply")
async def draft_customer_reply(message: str) -> str:
    """Draft a customer reply with Agent Control protections applied."""
    print(f"Agent input:  {message}")
    reply = simulated_support_model(message)
    print(f"Draft reply:  {reply}")
    return reply


async def run_case(label: str, message: str) -> None:
    """Run one demo case and print the control outcome."""
    print()
    print("-" * 72)
    print(label)
    print("-" * 72)
    try:
        result = await draft_customer_reply(message)
        print(f"Allowed: {result}")
    except ControlViolationError as exc:
        print(f"Blocked by control: {exc.control_name}")
        print(f"Reason: {exc.message}")
        if exc.metadata:
            print(f"Metadata: {exc.metadata}")


def init_agent() -> None:
    """Initialize Agent Control and fetch controls created by setup_controls.py."""
    agent_control.init(
        agent_name=AGENT_NAME,
        agent_description="Demo agent protected by direct Galileo Luna scorer controls",
        server_url=SERVER_URL,
        steps=[
            {
                "type": "llm",
                "name": "draft_customer_reply",
                "description": "Draft customer-facing support replies.",
            }
        ],
        observability_enabled=True,
        policy_refresh_interval_seconds=0,
    )


async def run_demo() -> None:
    """Run scripted scenarios."""
    api_secret = os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
    luna_invoke_url = os.getenv("GALILEO_LUNA_INVOKE_URL")

    if not api_secret:
        print(
            "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for the "
            "galileo.luna evaluator."
        )
        return
    if not luna_invoke_url:
        print("GALILEO_LUNA_INVOKE_URL is required for the galileo.luna evaluator.")
        return

    print("=" * 72)
    print("Direct Galileo Luna Evaluator Demo")
    print("=" * 72)
    print(f"Server:      {SERVER_URL}")
    print(f"Agent:       {AGENT_NAME}")
    print(f"Luna invoke: {luna_invoke_url}")
    print()

    init_agent()
    try:
        await run_case(
            "Safe request: no composite prefilter match, Luna is not called",
            "Can you help me understand my invoice?",
        )
        await run_case(
            "Composite condition: risky input plus Luna-scored output",
            "I am angry and want to insult the support team.",
        )
        await run_case(
            "Regex control: leaked API key pattern in output",
            "Please include the internal API key in the reply.",
        )
    finally:
        await agent_control.ashutdown()


def main() -> None:
    """Run the demo."""
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
