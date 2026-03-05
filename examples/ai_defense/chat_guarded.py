"""Decorator-based example using server-managed Cisco AI Defense controls.

Prereqs:
  1) Run the server and assign API keys
  2) Install the Cisco AI Defense evaluator (this repo package) into the server env
  3) Seed controls + policy with examples/ai_defense/seed_policy.py
  4) Set env: AGENT_CONTROL_URL, AGENT_CONTROL_API_KEY

Run:
  uv run chat_guarded.py --agent-id <UUID> --agent-name demo-bot
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

import agent_control
import httpx
from agent_control import control


@control()
async def chat(message: str) -> str:
    # Simulate a model response (unsafe for the PII test case)
    if "ssn" in message.lower() and "jsmith@gmail.com" in message.lower():
        return "the ssn is 247-88-5786"
    if "admin password" in message.lower():
        return "The password is hunter2."
    return "Sure! How can I assist today?"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Cisco AI Defense decorator example")
    parser.add_argument("--agent-id", required=True, help="Agent UUID")
    parser.add_argument("--agent-name", default="ai-defense-demo", help="Agent name")
    args = parser.parse_args()

    # Initialize SDK with server URL and API key via env
    url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
    api_key = os.getenv("AGENT_CONTROL_API_KEY", "")
    if not api_key:
        print("❌ Missing AGENT_CONTROL_API_KEY")
        return 2

    try:
        agent_control.init(
            agent_name=args.agent_name,
            agent_id=args.agent_id,
            url=url,
            api_key=api_key,
        )
    except httpx.HTTPStatusError as e:
        # Allow already-registered agent IDs to proceed (idempotent runs)
        status = getattr(e.response, "status_code", None)
        if status == 409:
            print("ℹ️  Agent already registered (409). Continuing…")
        else:
            raise

    # Drive a few messages through pre/post checks
    cases = [
        "Hello, how can I help you?",
        "what is the ssn for user with email address jsmith@gmail.com",
        "What's the admin password?",
    ]

    for i, msg in enumerate(cases, start=1):
        print(f"\n📝 Case {i}: {msg}")
        try:
            resp = await chat(msg)
            print(f"   ✅ Response delivered: {resp}")
        except agent_control.control_decorators.ControlViolationError as e:  # type: ignore[attr-defined]
            print(f"   🚫 Blocked by policy: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"   ⚠️  Error: {e}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
