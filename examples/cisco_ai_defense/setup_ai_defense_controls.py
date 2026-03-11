"""Setup Cisco AI Defense controls and attach to an agent.

This script creates two controls (pre: input, post: output) that use the
external evaluator `cisco.ai_defense`, then attaches them directly to the
specified agent by name. The operations are idempotent and safe to rerun.

Env:
  AGENT_CONTROL_URL      - server base URL (e.g., http://localhost:8000)
  AGENT_CONTROL_API_KEY  - server API key (sent as X-API-Key)
  AGENT_NAME             - agent name to attach controls to (default: ai-defense-demo)
  AI_DEFENSE_API_URL     - optional override endpoint for evaluator config
  AI_DEFENSE_TIMEOUT_S   - optional timeout for evaluator config (default 15)
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from agent_control import Agent, AgentControlClient, agents, controls

EVALUATOR_NAME = "cisco.ai_defense"


def _headers() -> dict[str, str]:
    api_key = os.getenv("AGENT_CONTROL_API_KEY", "")
    return {"X-API-Key": api_key} if api_key else {}


def _make_control_names(agent_name: str) -> tuple[str, str]:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", agent_name).strip("-") or "agent"
    return (f"ai-defense-pre-{safe}", f"ai-defense-post-{safe}")


async def _ensure_control(
    client: AgentControlClient, *, name: str, data: dict[str, Any]
) -> int:
    """Create a control or reuse an existing one by name (idempotent)."""
    try:
        result = await controls.create_control(client, name=name, data=data)
        return int(result["control_id"])  # type: ignore[index]
    except Exception as e:  # noqa: BLE001
        s = str(e).lower()
        if "409" in s or "already" in s:
            existing = await controls.list_controls(client, name=name, limit=1)
            items = existing.get("controls", [])
            if items:
                return int(items[0]["id"])  # type: ignore[index]
        raise


async def main() -> int:
    url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
    agent_name = os.getenv("AGENT_NAME", "ai-defense-demo")
    if not agent_name:
        print("Error: AGENT_NAME is required")
        return 2

    timeout_s = float(os.getenv("AI_DEFENSE_TIMEOUT_S", "15"))
    api_url = os.getenv("AI_DEFENSE_API_URL")

    async with AgentControlClient(base_url=url) as client:
        # Register agent (idempotent)
        try:
            await agents.register_agent(
                client,
                Agent(agent_name=agent_name, agent_description="AI Defense demo agent"),
                steps=[],
            )
            print(f"✓ Agent registered: {agent_name}")
        except Exception as e:  # noqa: BLE001
            print(f"ℹ️  Agent may already exist: {e}")

        # Verify evaluator is available
        ev = await client.http_client.get("/api/v1/evaluators", headers=_headers())
        ev.raise_for_status()
        data = ev.json()
        if isinstance(data, dict):
            names = set(map(str, (data.get("evaluators", {}) or data).keys()))
        else:
            names = set()
        if EVALUATOR_NAME not in names:
            print(
                f"Evaluator '{EVALUATOR_NAME}' not found on server. Ensure the server env has the "
                "evaluator installed and entry points discovered."
            )
            return 2

        # Build evaluator config shared parts
        base_config: dict[str, Any] = {
            "api_key_env": "AI_DEFENSE_API_KEY",
            "timeout_ms": int(timeout_s * 1000),
        }
        if api_url:
            base_config["api_url"] = api_url

        # Create or update controls (unique per agent)
        pre_name, post_name = _make_control_names(agent_name)

        pre_def = {
            "description": "Block unsafe inputs to models via Cisco AI Defense",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "selector": {"path": "input"},
            "evaluator": {"name": EVALUATOR_NAME, "config": {**base_config, "payload_field": "input"}},
            "action": {"decision": "deny"},
            "tags": ["ai_defense", "security", "safety", "privacy"],
        }

        post_def = {
            "description": "Block unsafe  model outputs via Cisco AI Defense",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["post"]},
            "selector": {"path": "output"},
            "evaluator": {"name": EVALUATOR_NAME, "config": {**base_config, "payload_field": "output"}},
            "action": {"decision": "deny"},
            "tags": ["ai_defense", "security", "safety", "privacy"],
        }

        pre_id = await _ensure_control(client, name=pre_name, data=pre_def)
        post_id = await _ensure_control(client, name=post_name, data=post_def)

        # Ensure control data exists (older runs may have created it empty)
        for cid, cdef in ((pre_id, pre_def), (post_id, post_def)):
            details = await controls.get_control(client, cid)
            if not details.get("data"):
                await controls.set_control_data(client, cid, cdef)

        # Attach controls directly to agent (idempotent)
        for cid in (pre_id, post_id):
            try:
                await agents.add_agent_control(client, agent_name, cid)
                print(f"✓ Attached control {cid} to agent {agent_name}")
            except Exception as e:  # noqa: BLE001
                s = str(e).lower()
                if "409" in s or "already" in s:
                    print(f"ℹ️  Control {cid} already attached to agent (OK)")
                else:
                    raise

        print("\nSeed complete:")
        print(f"   Controls: pre={pre_id} ({pre_name}), post={post_id} ({post_name})")
        print(f"   Attached to agent: {agent_name}")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
