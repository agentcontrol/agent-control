"""
Setup script for the OpenShell CI triage example.

This example attaches a policy, not direct controls, so the same policy can be
reused across multiple shell-capable agents running in OpenShell sandboxes.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

from agent_control import AgentControlClient, agents, controls, policies
from agent_control_models import Agent

AGENT_NAME = "openshell-ci-triage-agent"
POLICY_NAME = "openshell-command-governance"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


CONTROL_SPECS: list[tuple[str, dict[str, Any]]] = [
    (
        "deny-secret-file-access",
        {
            "description": "Block shell commands that target secrets or credential-bearing files.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["execute_shell_command"],
                "stages": ["pre"],
            },
            "condition": {
                "selector": {"path": "input.command"},
                "evaluator": {
                    "name": "regex",
                    "config": {
                        "pattern": (
                            r"(\.env(\.|$))|"
                            r"(id_rsa)|"
                            r"(\.aws/credentials)|"
                            r"(printenv)|"
                            r"((^|\s)(cat|less|more|grep|sed)\s+[^\n]*(secret|token|credential))"
                        )
                    },
                },
            },
            "action": {
                "decision": "deny",
                "message": (
                    "Secret-bearing files and environment material must not be read from the shell. "
                    "Use approved config summaries instead."
                ),
            },
        },
    ),
    (
        "deny-outside-workspace-reads",
        {
            "description": "Block attempts to inspect files outside the demo workspace through the shell.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["execute_shell_command"],
                "stages": ["pre"],
            },
            "condition": {
                "selector": {"path": "input.command"},
                "evaluator": {
                    "name": "regex",
                    "config": {
                        "pattern": (
                            r"((^|\s)(cat|less|more|head|tail|grep|sed)\s+"
                            r"([^-\s][^\n]*\s+)?/[^\n]*)"
                        )
                    },
                },
            },
            "action": {
                "decision": "deny",
                "message": (
                    "Shell reads must stay inside the current repository workspace. "
                    "Use repository-local files only."
                ),
            },
        },
    ),
    (
        "deny-unsafe-bootstrap-install",
        {
            "description": "Block curl-pipe-shell and similar bootstrap installers.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["execute_shell_command"],
                "stages": ["pre"],
            },
            "condition": {
                "selector": {"path": "input.command"},
                "evaluator": {
                    "name": "regex",
                    "config": {
                        "pattern": r"(curl[^\n]*\|\s*(bash|sh))|(wget[^\n]*\|\s*(bash|sh))"
                    },
                },
            },
            "action": {
                "decision": "deny",
                "message": (
                    "Bootstrap installers like curl-pipe-shell are not allowed. "
                    "Use approved internal package acquisition paths instead."
                ),
            },
        },
    ),
    (
        "deny-unapproved-package-install",
        {
            "description": "Block generic package installation attempts that are not the approved semgrep flow.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["execute_shell_command"],
                "stages": ["pre"],
            },
            "condition": {
                "and": [
                    {
                        "selector": {"path": "input.command"},
                        "evaluator": {
                            "name": "regex",
                            "config": {
                                "pattern": r"((^|\s)npm\s+install\b)|((^|\s)pip\s+install\b)"
                            },
                        },
                    },
                    {
                        "not": {
                            "selector": {"path": "input.command"},
                            "evaluator": {
                                "name": "regex",
                                "config": {"pattern": r"\bsemgrep\b"},
                            },
                        }
                    },
                ]
            },
            "action": {
                "decision": "deny",
                "message": (
                    "Generic package installation is not allowed during autonomous triage. "
                    "Only approved tool acquisition paths may be used."
                ),
            },
        },
    ),
    (
        "deny-destructive-shell-operations",
        {
            "description": "Block destructive shell commands even when the binary is allowed in the sandbox.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["execute_shell_command"],
                "stages": ["pre"],
            },
            "condition": {
                "selector": {"path": "input.command"},
                "evaluator": {
                    "name": "regex",
                    "config": {
                        "pattern": (
                            r"(rm\s+-rf)|"
                            r"(git\s+push[^\n]*--force)|"
                            r"(terraform\s+destroy)|"
                            r"(kubectl\s+delete)|"
                            r"(chmod\s+777)|"
                            r"(shutdown|reboot|mkfs)"
                        )
                    },
                },
            },
            "action": {
                "decision": "deny",
                "message": "Destructive shell operations are not allowed for autonomous remediation.",
            },
        },
    ),
    (
        "steer-unpinned-tool-install",
        {
            "description": "Rewrite package installation to a pinned internal-mirror command.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["execute_shell_command"],
                "stages": ["pre"],
            },
            "condition": {
                "and": [
                    {
                        "selector": {"path": "input.command"},
                        "evaluator": {
                            "name": "regex",
                            "config": {
                                "pattern": r"((^|\s)uv\s+pip\s+install\b[^\n]*\bsemgrep\b)|((^|\s)pip\s+install\b[^\n]*\bsemgrep\b)"
                            },
                        },
                    },
                    {
                        "not": {
                            "selector": {"path": "input.command"},
                            "evaluator": {
                                "name": "regex",
                                "config": {
                                    "pattern": r"uv\s+pip\s+install\s+--index-url\s+https://packages\.company\.internal/simple\s+semgrep==1\.84\.0"
                                },
                            },
                        }
                    },
                ]
            },
            "action": {
                "decision": "steer",
                "message": "Use pinned tooling from the approved internal mirror.",
                "steering_context": {
                    "message": (
                        '{"rewrite_command": "uv pip install --index-url '
                        'https://packages.company.internal/simple semgrep==1.84.0", '
                        '"reason": "Package installs must use pinned versions from the approved '
                        'internal mirror."}'
                    )
                },
            },
        },
    ),
    (
        "deny-secret-output-leak",
        {
            "description": "Block command output that contains secrets from being surfaced or persisted.",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["execute_shell_command"],
                "stages": ["post"],
            },
            "condition": {
                "selector": {"path": "output.stdout"},
                "evaluator": {
                    "name": "regex",
                    "config": {
                        "pattern": r"(sk-prod-[A-Za-z0-9_-]+)|(BEGIN [A-Z ]*PRIVATE KEY)|(INTERNAL_API_TOKEN=)"
                    },
                },
            },
            "action": {
                "decision": "deny",
                "message": "Command output contains secret material and cannot be returned to the agent.",
            },
        },
    ),
]


async def ensure_agent(client: AgentControlClient) -> None:
    """Register the demo agent."""
    agent = Agent(
        agent_name=AGENT_NAME,
        agent_description=(
            "Daily CI triage agent running inside an OpenShell sandbox "
            "with Agent Control command governance"
        ),
        agent_created_at=datetime.now(UTC).isoformat(),
    )
    await agents.register_agent(client, agent, steps=[])


async def ensure_control(
    client: AgentControlClient,
    name: str,
    definition: dict[str, Any],
) -> int:
    """Create or update a control and return its identifier."""
    try:
        result = await controls.create_control(client, name=name, data=definition)
        return int(result["control_id"])
    except Exception as exc:
        if "409" not in str(exc):
            raise

        listing = await controls.list_controls(client, name=name, limit=1)
        existing = listing.get("controls") or []
        if not existing:
            raise
        control_id = int(existing[0]["id"])
        await controls.set_control_data(client, control_id, definition)
        return control_id


async def ensure_policy(client: AgentControlClient, name: str) -> int:
    """Create or reuse a policy."""
    try:
        result = await policies.create_policy(client, name)
        return int(result["policy_id"])
    except Exception as exc:
        if "409" not in str(exc):
            raise

        response = await agents.get_agent_policies(client, AGENT_NAME)
        policy_ids = response.get("policy_ids") or []
        if policy_ids:
            return int(policy_ids[0])
        raise RuntimeError(
            f"Policy '{name}' already exists but is not attached to agent '{AGENT_NAME}'. "
            "Attach it once in the UI or remove the existing policy before rerunning setup."
        )


async def main() -> None:
    """Create policy-backed controls and attach the policy to the agent."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        await ensure_agent(client)
        print(f"Registered agent: {AGENT_NAME}")

        policy_id = await ensure_policy(client, POLICY_NAME)
        print(f"Using policy: {POLICY_NAME} (id={policy_id})")

        control_ids: list[int] = []
        for name, definition in CONTROL_SPECS:
            control_id = await ensure_control(client, name, definition)
            await policies.add_control_to_policy(client, policy_id, control_id)
            control_ids.append(control_id)
            print(f"Bound control '{name}' to policy (id={control_id})")

        await agents.add_agent_policy(client, AGENT_NAME, policy_id)
        print(f"Attached policy '{POLICY_NAME}' to agent '{AGENT_NAME}'")

        print()
        print("Setup complete.")
        print("Controls in policy:")
        for control_id, (name, _) in zip(control_ids, CONTROL_SPECS, strict=False):
            print(f"  - {name} (id={control_id})")


if __name__ == "__main__":
    asyncio.run(main())
