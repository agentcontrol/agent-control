#!/usr/bin/env python3
"""Provision the Cursor guardrails hook — Agent Control agent + controls.

Defines two controls on a single AC agent so the runtime hook can issue one
@control() call and let AC orchestrate:
  - block-secrets-v4 (regex)         — server-local match on the prompt input
  - block-pii-v4     (galileo.luna2) — calls Galileo Protect with rules in
                                       payload (stage_type=local) against the
                                       Galileo local stage created here

Re-running is safe; existing rows are updated in place. Run once per machine
(or whenever you change the patterns/configs in this file).

Usage:
    .venv/bin/python3 scripts/setup.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent_control import AgentControlClient

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

AGENT_NAME = os.getenv("AC_AGENT_NAME", "cursor-protect-v4")
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
GALILEO_PROJECT = os.getenv("GALILEO_PROJECT", "protect-cursor")
GALILEO_API_KEY = os.getenv("GALILEO_API_KEY", "")
GALILEO_CONSOLE_URL = os.getenv("GALILEO_CONSOLE_URL", "https://console.galileo.ai").rstrip("/")
GALILEO_LOCAL_STAGE = os.getenv("GALILEO_PROTECT_LOCAL_STAGE", "Cursor Protect v4 (local)")


SECRETS_PATTERN = "|".join([
    r"AKIA[0-9A-Z]{16}",
    r"ASIA[0-9A-Z]{16}",
    r"gh[pousr]_[A-Za-z0-9]{36,}",
    r"github_pat_[A-Za-z0-9_]{82}",
    r"sk-ant-[A-Za-z0-9_\-]{40,}",
    r"sk-[A-Za-z0-9]{32,}",
    r"sk_(?:live|test)_[A-Za-z0-9]{24,}",
    r"xox[abposr]-[A-Za-z0-9\-]{10,}",
    r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----",
])


SECRETS_CONTROL = {
    "name": "block-secrets-v4",
    "data": {
        "description": "Block common secret formats in the Cursor prompt input.",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "condition": {
            "selector": {"path": "input"},
            "evaluator": {
                "name": "regex",
                "config": {"pattern": SECRETS_PATTERN, "flags": []},
            },
        },
        "action": {"decision": "deny"},
        "tags": ["cursor", "secrets", "input-filter", "guardrails", "sdk"],
    },
}


def PII_CONTROL(stage_name: str) -> dict:
    return {
        "name": "block-pii-v4",
        "data": {
            "description": "Block PII via Galileo Protect (luna2, local stage).",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": {
                "selector": {"path": "input"},
                "evaluator": {
                    "name": "galileo.luna2",
                    "config": {
                        "stage_type": "local",
                        "stage_name": stage_name,
                        "metric": "input_pii",
                        "operator": "not_empty",
                        "target_value": 0,
                        "galileo_project": GALILEO_PROJECT,
                        "payload_field": "input",
                        "on_error": "allow",
                        "timeout_ms": 8000,
                    },
                },
            },
            "action": {"decision": "deny"},
            "tags": ["cursor", "pii", "luna2", "galileo-protect", "guardrails", "sdk"],
        },
    }


# ── Galileo: ensure the local stage exists ----------------------------------

def _galileo_api() -> str:
    return GALILEO_CONSOLE_URL.replace("console.", "api.") if "console." in GALILEO_CONSOLE_URL else GALILEO_CONSOLE_URL


def _gal_request(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    headers = {"Galileo-API-Key": GALILEO_API_KEY, "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{_galileo_api()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, None


def _resolve_galileo_project_id() -> str | None:
    status, projects = _gal_request("GET", f"/projects/all?project_name={GALILEO_PROJECT}")
    if status != 200 or not isinstance(projects, list) or not projects:
        return None
    matches = [p for p in projects if p.get("name") == GALILEO_PROJECT]
    return matches[0]["id"] if matches else None


def ensure_galileo_local_stage() -> bool:
    if not GALILEO_API_KEY:
        print("  ✗ GALILEO_API_KEY not set — cannot create local stage")
        return False

    pid = _resolve_galileo_project_id()
    if not pid:
        print(f"  ✗ Galileo project {GALILEO_PROJECT!r} not found")
        return False
    print(f"  Galileo project {GALILEO_PROJECT}: id={pid}")

    status, existing = _gal_request("GET", f"/projects/{pid}/stages?stage_name={urllib.parse.quote(GALILEO_LOCAL_STAGE)}")
    if status == 200 and isinstance(existing, dict) and existing.get("id") and existing.get("type") == "local":
        print(f"  local stage {GALILEO_LOCAL_STAGE!r}: already exists (id={existing['id']})")
        return True

    body = {
        "name": GALILEO_LOCAL_STAGE,
        "project_id": pid,
        "description": "Local stage for the guardrails PII control — rules sent in payload.",
        "type": "local",
        "paused": False,
    }
    status, result = _gal_request("POST", f"/projects/{pid}/stages", body=body)
    if status not in (200, 201):
        print(f"  ✗ failed to create local stage: http={status} body={result}")
        return False
    print(f"  local stage {GALILEO_LOCAL_STAGE!r}: created (id={result.get('id')})")
    return True


# ── AC: agent + controls ----------------------------------------------------

async def upsert_agent(client: AgentControlClient) -> None:
    resp = await client.http_client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {
                "agent_name": AGENT_NAME,
                "agent_description": "Cursor guardrails hook (SDK + @control + observability).",
            },
            "steps": [],
        },
    )
    resp.raise_for_status()
    created = resp.json().get("created", False)
    print(f"  agent {AGENT_NAME}: {'created' if created else 'already exists'}")


async def upsert_control(client: AgentControlClient, spec: dict) -> int:
    name = spec["name"]
    resp = await client.http_client.put("/api/v1/controls", json=spec)
    if resp.status_code == 409:
        existing = await _find_control_id(client, name)
        if existing is None:
            raise RuntimeError(f"control {name!r} reported 409 but cannot be found")
        upd = await client.http_client.put(
            f"/api/v1/controls/{existing}/data", json={"data": spec["data"]}
        )
        upd.raise_for_status()
        print(f"  control {name}: updated (id={existing})")
        return existing
    resp.raise_for_status()
    control_id = resp.json()["control_id"]
    print(f"  control {name}: created (id={control_id})")
    return control_id


async def _find_control_id(client: AgentControlClient, name: str) -> int | None:
    resp = await client.http_client.get(f"/api/v1/agents/{AGENT_NAME}/controls")
    if resp.status_code == 200:
        for ctrl in resp.json().get("controls", []):
            if ctrl.get("name") == name:
                return ctrl.get("id")
    resp = await client.http_client.get("/api/v1/controls")
    if resp.status_code == 200:
        for ctrl in resp.json().get("controls", []):
            if ctrl.get("name") == name:
                return ctrl.get("id")
    return None


async def associate(client: AgentControlClient, control_id: int) -> None:
    resp = await client.http_client.post(
        f"/api/v1/agents/{AGENT_NAME}/controls/{control_id}"
    )
    if resp.status_code not in (200, 201, 409):
        resp.raise_for_status()


async def main() -> int:
    print(f"Agent Control: {SERVER_URL}")
    print(f"Agent:         {AGENT_NAME}")
    print()

    print("[1/3] Ensure Galileo local stage")
    pii_ready = ensure_galileo_local_stage()
    print()

    print("[2/3] Ensure AC agent + controls")
    async with AgentControlClient(base_url=SERVER_URL) as client:
        try:
            await client.health_check()
        except Exception as exc:
            print(f"  ✗ AC server unreachable at {SERVER_URL}: {exc}")
            print("    Start it with:  docker compose up -d")
            return 1

        await upsert_agent(client)

        secrets_id = await upsert_control(client, SECRETS_CONTROL)
        await associate(client, secrets_id)

        if pii_ready:
            pii_id = await upsert_control(client, PII_CONTROL(GALILEO_LOCAL_STAGE))
            await associate(client, pii_id)
        else:
            print("  block-pii-v4: skipped (Galileo local stage not ready)")
    print()

    print("[3/3] Done.")
    print(f"  UI: http://localhost:4000")
    print(f"    agent '{AGENT_NAME}'")
    print(f"      → block-secrets-v4 (regex)")
    print(f"      → block-pii-v4     (galileo.luna2, stage_type=local, metric=input_pii)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
