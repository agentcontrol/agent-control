"""Register an agent once and persist its ID locally for reuse.

This helper simplifies onboarding by:
- Generating a stable agent ID (UUID) on first run and saving it to `.agent_id`
- Registering the agent with the running server
- Re-using the same ID on subsequent runs

Env required:
- AGENT_CONTROL_URL (e.g., http://localhost:8000)
- AGENT_CONTROL_API_KEY (X-API-Key for the server)

Usage:
  uv run register_agent.py [--agent-name ai-defense-demo]

Then export the ID for other commands:
  export AGENT_ID=$(cat .agent_id)
"""

from __future__ import annotations

import argparse
import os
import uuid

import agent_control
import httpx


def _read_or_create_agent_id(path: str = ".agent_id") -> str:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                value = f.read().strip()
                uuid.UUID(value)  # validate
                return value
    except Exception:
        pass

    value = str(uuid.uuid4())
    with open(path, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Register agent and persist a stable agent ID")
    parser.add_argument("--agent-name", default="ai-defense-demo", help="Agent name")
    args = parser.parse_args()

    url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
    api_key = os.getenv("AGENT_CONTROL_API_KEY", "")
    if not api_key:
        print("❌ Missing AGENT_CONTROL_API_KEY")
        return 2

    agent_id = _read_or_create_agent_id()

    try:
        agent_control.init(
            agent_name=args.agent_name,
            agent_id=agent_id,
            url=url,
            api_key=api_key,
        )
        print(f"✅ Registered agent: {agent_id}")
    except httpx.HTTPStatusError as e:
        status = getattr(e.response, "status_code", None)
        if status == 409:
            print(f"ℹ️  Agent already registered: {agent_id}")
        else:
            raise

    print("Export for other commands:")
    print("  export AGENT_ID=$(cat .agent_id)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

