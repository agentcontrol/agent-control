"""Seed Cisco AI Defense Chat Inspection controls and assign policy to an agent.

This script creates/updates two controls (pre: input, post: output) that use
the external evaluator `ai_defense.chat_inspect`, creates/updates a policy,
attaches the controls, and assigns the policy to the specified agent.

Env:
  AGENT_CONTROL_URL      - server base URL (e.g., http://localhost:8000)
  AGENT_CONTROL_API_KEY  - server API key (sent as X-API-Key)
  AGENT_NAME             - agent name to assign policy to (default: ai-defense-demo)
  POLICY_NAME            - policy name to create/use (default: ai-defense-policy)
  AI_DEFENSE_API_URL     - optional override endpoint for evaluator config
  AI_DEFENSE_TIMEOUT_S   - optional timeout for evaluator config (default 15)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from agent_control import AgentControlClient


EVALUATOR_NAME = "ai_defense.chat_inspect"


def _headers() -> dict[str, str]:
    api_key = os.getenv("AGENT_CONTROL_API_KEY", "")
    return {"X-API-Key": api_key} if api_key else {}


async def _ensure_control(client: AgentControlClient, name: str) -> int:
    # Try to find control by name (case-insensitive contains); then verify exact match
    resp = await client.http_client.get("/api/v1/controls", params={"name": name}, headers=_headers())
    resp.raise_for_status()
    data = resp.json()
    # Server returns list under 'controls' key (not 'items')
    for item in data.get("controls", []):
        if item.get("name") == name:
            return int(item["id"])  # type: ignore[index]

    # Create if not found
    create = await client.http_client.put("/api/v1/controls", json={"name": name}, headers=_headers())
    create.raise_for_status()
    return int(create.json()["control_id"])  # type: ignore[index]


async def _set_control_data(client: AgentControlClient, control_id: int, *, stage: str, selector_path: str) -> None:
    timeout_s = float(os.getenv("AI_DEFENSE_TIMEOUT_S", "15"))
    api_url = os.getenv("AI_DEFENSE_API_URL")

    evaluator_config: dict[str, Any] = {
        "name": EVALUATOR_NAME,
        "config": {
            "api_key_env": "AI_DEFENSE_API_KEY",
            "timeout_ms": int(timeout_s * 1000),
            "payload_field": "input" if stage == "pre" else "output",
        },
    }
    if api_url:
        evaluator_config["config"]["api_url"] = api_url

    control_def = {
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["llm"],
            "stages": [stage],
        },
        "selector": {"path": selector_path},
        "evaluator": evaluator_config,
        "action": {"decision": "deny"},
        "tags": ["ai-defense", "chat-inspect", stage, "llm"],
    }

    resp = await client.http_client.put(
        f"/api/v1/controls/{control_id}/data",
        json={"data": control_def},
        headers=_headers(),
    )
    resp.raise_for_status()


async def _ensure_policy(client: AgentControlClient, name: str, *, agent_name: str) -> int:
    """Create policy if missing, otherwise reuse existing assignment.

    Notes:
        The server API does not expose list/search by policy name. To be
        idempotent on reruns, if creation returns HTTP 409 we attempt to
        reuse the policy currently assigned to the target agent. This
        covers the common rerun path where a prior invocation already
        created and assigned the policy. If the policy exists but is not
        assigned to the agent, the script will raise with guidance.
    """
    resp = await client.http_client.put("/api/v1/policies", json={"name": name}, headers=_headers())
    if resp.status_code == 409:
        # Policy with this name exists. Try to reuse the agent's assigned policy.
        assigned = await client.http_client.get(
            f"/api/v1/agents/{agent_name}/policy", headers=_headers()
        )
        if assigned.status_code == 200:
            return int(assigned.json()["policy_id"])  # type: ignore[index]

        # No assignment to infer the policy ID from. Create a new unique policy name
        # derived from the requested name and the agent name suffix.
        suffix = agent_name.replace(" ", "-")[-6:]
        alt_name = f"{name}-{suffix}"
        alt_resp = await client.http_client.put(
            "/api/v1/policies", json={"name": alt_name}, headers=_headers()
        )
        if alt_resp.status_code == 409:
            # Extremely unlikely double collision – append a timestamp-based suffix
            import time

            alt_name = f"{name}-{int(time.time())}"
            alt_resp = await client.http_client.put(
                "/api/v1/policies", json={"name": alt_name}, headers=_headers()
            )
        alt_resp.raise_for_status()
        return int(alt_resp.json()["policy_id"])  # type: ignore[index]
    resp.raise_for_status()
    return int(resp.json()["policy_id"])  # type: ignore[index]


async def _attach_control(client: AgentControlClient, policy_id: int, control_id: int) -> None:
    resp = await client.http_client.post(
        f"/api/v1/policies/{policy_id}/controls/{control_id}", headers=_headers()
    )
    resp.raise_for_status()


async def _assign_policy(client: AgentControlClient, agent_name: str, policy_id: int) -> None:
    resp = await client.http_client.post(
        f"/api/v1/agents/{agent_name}/policy/{policy_id}", headers=_headers()
    )
    resp.raise_for_status()


async def main() -> int:
    url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
    agent_name = os.getenv("AGENT_NAME", "ai-defense-demo")
    if not agent_name:
        print("❌ AGENT_NAME is required")
        return 2
    policy_name = os.getenv("POLICY_NAME", "ai-defense-policy")

    async with AgentControlClient(base_url=url) as client:
        # Verify evaluator is available
        ev = await client.http_client.get("/api/v1/evaluators", headers=_headers())
        ev.raise_for_status()
        data = ev.json()
        names: set[str]
        if isinstance(data, dict) and "evaluators" in data:
            # Older/alternate shape: {"evaluators": [{"name": ...}, ...]} or a dict
            evaluators = data["evaluators"]
            if isinstance(evaluators, list):
                names = {str(e.get("name")) for e in evaluators if isinstance(e, dict)}
            elif isinstance(evaluators, dict):
                names = set(map(str, evaluators.keys()))
            else:
                names = set()
        elif isinstance(data, dict):
            # Current server shape: {"name": EvaluatorInfo, ...}
            names = set(map(str, data.keys()))
        else:
            names = set()
        if EVALUATOR_NAME not in names:
            print(
                f"❌ Evaluator '{EVALUATOR_NAME}' not found on server. Ensure the server environment\n"
                f"   has the Cisco AI Defense evaluator installed and entry points discovered."
            )
            return 2

        # Create or update controls
        pre_name = "ai-defense-pre"
        post_name = "ai-defense-post"
        pre_id = await _ensure_control(client, pre_name)
        post_id = await _ensure_control(client, post_name)
        await _set_control_data(client, pre_id, stage="pre", selector_path="input")
        await _set_control_data(client, post_id, stage="post", selector_path="output")

        # Create policy and attach controls
        try:
            policy_id = await _ensure_policy(client, policy_name, agent_name=agent_name)
        except RuntimeError as e:
            print(f"⚠️  {e}")
            return 2

        await _attach_control(client, policy_id, pre_id)
        await _attach_control(client, policy_id, post_id)

        # Assign policy to agent (by name)
        await _assign_policy(client, agent_name, policy_id)

        print("✅ Seed complete:")
        print(f"   Policy: {policy_name} (id={policy_id})")
        print(f"   Controls: pre={pre_id}, post={post_id}")
        print(f"   Assigned to agent: {agent_name}")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
