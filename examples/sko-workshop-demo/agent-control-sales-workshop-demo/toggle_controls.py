#!/usr/bin/env python3
"""Toggle PII control at runtime to demonstrate no‑code policy updates."""

import argparse
import asyncio
import os
import sys

SDK_FALLBACK = "/Users/namrataghadi/code/agentcontrol/agent-control/sdks/python/src"
if SDK_FALLBACK not in sys.path:
    sys.path.insert(0, SDK_FALLBACK)

from agent_control import AgentControlClient, controls

SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
CONTROL_NAME = "rag-block-pii-output"


async def _get_control_id(client: AgentControlClient) -> int:
    res = await controls.list_controls(client, name=CONTROL_NAME, limit=1)
    ctrls = res.get("controls") or []
    if not ctrls:
        raise RuntimeError(f"Control '{CONTROL_NAME}' not found. Run setup_controls.py first.")
    return ctrls[0]["id"]


async def _set_enabled(client: AgentControlClient, control_id: int, enabled: bool) -> None:
    detail = await controls.get_control(client, control_id)
    data = detail.get("data") or {}
    data["enabled"] = enabled
    await controls.set_control_data(client, control_id, data)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-pii", action="store_true", help="Disable PII block")
    parser.add_argument("--block-pii", action="store_true", help="Enable PII block")
    args = parser.parse_args()

    if not args.allow_pii and not args.block_pii:
        parser.error("Choose --allow-pii or --block-pii")

    async with AgentControlClient(base_url=SERVER_URL) as client:
        control_id = await _get_control_id(client)
        await _set_enabled(client, control_id, enabled=bool(args.block_pii))

        status = "ENABLED (blocking)" if args.block_pii else "DISABLED (allowing)"
        print(f"{CONTROL_NAME} -> {status}")


if __name__ == "__main__":
    asyncio.run(main())
