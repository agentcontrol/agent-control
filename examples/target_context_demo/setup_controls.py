#!/usr/bin/env python3
"""Set up the target-context demo: agent + two controls + one binding.

Layout:

- ``block-pii-output`` is attached directly to the agent. It applies on
  every call regardless of target context.
- ``block-prod-restricted-input`` is bound to ``(env, prod)`` via a
  control binding. It applies only when the SDK's session target is
  ``(env, prod)`` and is omitted from the merged set otherwise.

When the demo agent calls ``init(target_type="env", target_id="prod")``,
the server returns the de-duplicated union: both controls. Re-init for a
different ``env`` value (or no target) drops the prod-bound control from
the returned set.

Prerequisites:
    - Agent Control server running at AGENT_CONTROL_URL (default localhost:8000).

Usage:
    uv run python examples/target_context_demo/setup_controls.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

# Add the SDK to path for development.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

from agent_control import AgentControlClient

AGENT_NAME = "demo-target-bot"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

PII_CONTROL_NAME = "block-pii-output"
PROD_CONTROL_NAME = "block-prod-restricted-input"

PII_CONTROL: dict[str, Any] = {
    "description": "Block SSN-like patterns in agent output (always on).",
    "enabled": True,
    "execution": "server",
    "scope": {"step_types": ["llm"], "stages": ["post"]},
    "condition": {
        "selector": {"path": "output"},
        "evaluator": {
            "name": "regex",
            "config": {"pattern": r"\b\d{3}-\d{2}-\d{4}\b", "flags": []},
        },
    },
    "action": {"decision": "deny"},
    "tags": ["pii", "agent-attached"],
}

PROD_CONTROL: dict[str, Any] = {
    "description": "Reject restricted input keywords on prod.",
    "enabled": True,
    "execution": "server",
    "scope": {"step_types": ["llm"], "stages": ["pre"]},
    "condition": {
        "selector": {"path": "input"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["DROP TABLE", "rm -rf", "sudo"],
                "logic": "any",
                "match_on": "match",
                "match_mode": "contains",
                "case_sensitive": False,
            },
        },
    },
    "action": {"decision": "deny"},
    "tags": ["env-bound", "prod-only"],
}


async def _create_or_get_control(
    client: AgentControlClient, name: str, definition: dict[str, Any]
) -> int:
    """Create a control by name; return its ID. Surfaces 409 cleanly."""
    response = await client.http_client.put(
        "/api/v1/controls",
        json={"name": name, "data": definition},
    )
    if response.status_code == 409:
        # Control already exists from a previous run — look it up.
        page = await client.http_client.get(
            "/api/v1/controls", params={"name": name}
        )
        page.raise_for_status()
        for entry in page.json().get("controls", []):
            if entry.get("name") == name:
                return int(entry["id"])
        raise RuntimeError(f"Control {name!r} reported as existing but not found.")
    response.raise_for_status()
    return int(response.json()["control_id"])


async def main() -> None:
    print(f"Server: {SERVER_URL}")
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register the agent (no target context here — registration is
        #    independent of target binding).
        register = await client.http_client.post(
            "/api/v1/agents/initAgent",
            json={
                "agent": {
                    "agent_name": AGENT_NAME,
                    "agent_description": "Demo agent for target context.",
                },
                "steps": [],
            },
        )
        register.raise_for_status()
        print(f"  ✓ Registered agent: {AGENT_NAME}")

        # 2. Create both controls.
        pii_id = await _create_or_get_control(client, PII_CONTROL_NAME, PII_CONTROL)
        print(f"  ✓ Control {PII_CONTROL_NAME!r} -> id={pii_id}")
        prod_id = await _create_or_get_control(
            client, PROD_CONTROL_NAME, PROD_CONTROL
        )
        print(f"  ✓ Control {PROD_CONTROL_NAME!r} -> id={prod_id}")

        # 3. Attach the PII control directly to the agent (always on).
        attach = await client.http_client.post(
            f"/api/v1/agents/{AGENT_NAME}/controls/{pii_id}"
        )
        attach.raise_for_status()
        print(f"  ✓ Attached {PII_CONTROL_NAME!r} directly to {AGENT_NAME}")

        # 4. Bind the prod-only control to (env, prod) via the natural-key
        #    upsert endpoint. Idempotent: re-running the script is safe.
        upsert = await client.http_client.put(
            "/api/v1/control-bindings/by-key",
            json={
                "target_type": "env",
                "target_id": "prod",
                "control_id": prod_id,
                "enabled": True,
            },
        )
        upsert.raise_for_status()
        body = upsert.json()
        action = "Created" if body.get("created") else "Updated"
        print(
            f"  ✓ {action} binding "
            f"({PROD_CONTROL_NAME!r} -> env=prod) id={body['binding_id']}"
        )

    print(
        "\nReady. Run the demo:\n"
        "  uv run python examples/target_context_demo/demo_agent.py"
    )


if __name__ == "__main__":
    asyncio.run(main())
