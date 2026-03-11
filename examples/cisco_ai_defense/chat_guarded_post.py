"""Decorator-based example focusing on POST (output) checks.

Prereqs:
  1) Run the server with Cisco AI Defense evaluator available
  2) Seed controls and attach to the agent with examples/cisco_ai_defense/setup_ai_defense_controls.py
  3) Set env: AGENT_CONTROL_URL, AGENT_CONTROL_API_KEY

Run:
  uv run chat_guarded_post.py --agent-name ai-defense-demo

This example sends a safe input but produces a toxic/unsafe output to
demonstrate that POST-stage checks (output) will block the response.
"""

from __future__ import annotations

import argparse
import asyncio
import os

import agent_control
import httpx
from agent_control import control


@control()
async def reply_with_potentially_unsafe_output(message: str) -> str:
    # Input asks for contact info; simulate a model leaking PII (email)
    # which should be blocked by a POST (output) control.
    if "john" in message.lower() and "email" in message.lower():
        return "John Smith's email is jsmith@gmail.com."
    return "All good. Nothing sensitive here."


async def main() -> int:
    parser = argparse.ArgumentParser(description="Cisco AI Defense POST-check example")
    parser.add_argument("--agent-name", default="ai-defense-demo", help="Agent name")
    args = parser.parse_args()

    url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
    api_key = os.getenv("AGENT_CONTROL_API_KEY", "")
    if not api_key:
        print("Error: Missing AGENT_CONTROL_API_KEY")
        return 2

    try:
        agent_control.init(
            agent_name=args.agent_name,
            server_url=url,
            api_key=api_key,
        )
    except httpx.HTTPStatusError as e:
        # Allow already-registered agent IDs to proceed (idempotent runs)
        status = getattr(e.response, "status_code", None)
        if status == 409:
            print("Info: Agent already registered (409). Continuing...")
        else:
            raise

    cases = [
        "Say hello in a friendly way.",  # safe input, safe output
        "What's John Smith's email address?",  # input without PII, output leaks PII (email)
    ]

    for i, msg in enumerate(cases, start=1):
        print(f"\nCase {i}: {msg}")
        try:
            resp = await reply_with_potentially_unsafe_output(msg)
            print(f"   Response delivered: {resp}")
        except agent_control.control_decorators.ControlViolationError as e:  # type: ignore[attr-defined]
            print(f"   Blocked by POST policy (PII): {e}")
        except Exception as e:  # noqa: BLE001
            print(f"   Error: {e}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
