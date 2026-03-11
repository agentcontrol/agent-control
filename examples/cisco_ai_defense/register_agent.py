"""Register an agent by name.

This helper simplifies onboarding by registering the agent with the running
server using its name. Agents are keyed by `agent_name`.

Env required:
- AGENT_CONTROL_URL (e.g., http://localhost:8000)
- AGENT_CONTROL_API_KEY (X-API-Key for the server)

Usage:
  uv run register_agent.py [--agent-name ai-defense-demo]
"""

from __future__ import annotations

import argparse
import os

import agent_control
import httpx



def main() -> int:
    parser = argparse.ArgumentParser(description="Register agent and persist a stable agent ID")
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
        print(f"Registered agent: {args.agent_name}")
    except httpx.HTTPStatusError as e:
        status = getattr(e.response, "status_code", None)
        if status == 409:
            print(f"Info: Agent already registered: {args.agent_name}")
        else:
            raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
