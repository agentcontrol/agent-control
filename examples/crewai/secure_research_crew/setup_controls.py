"""
Setup script for the Secure Research Crew controls and policies.

Creates three policies (one per crew agent) with distinct controls:
  - data-access-policy         (Researcher): SQL safety + restricted table list
  - analysis-validation-policy (Analyst):    JSON field validation + steer on missing methodology
  - content-safety-policy      (Writer):     PII regex blocking

All controls are also directly associated with the runtime agent
("secure-research-crew") for immediate enforcement. The policies provide
organizational grouping and can be managed independently on the server.

This script is fully idempotent -- safe to run multiple times.

Usage:
    uv run --active python setup_controls.py
"""

import asyncio
import os

from agent_control import Agent, AgentControlClient, agents, controls, policies

AGENT_NAME = "secure-research-crew"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def create_control_idempotent(client, name: str, data: dict) -> int:
    """Create a control, handling 409 conflicts gracefully.

    On conflict, looks up the existing control by name and updates its data
    to ensure the configuration matches the desired state.
    """
    try:
        result = await controls.create_control(client, name=name, data=data)
        control_id = result["control_id"]
        print(f"  + Created control: {name} (ID: {control_id})")
        return control_id
    except Exception as e:
        if "409" in str(e):
            controls_list = await controls.list_controls(client, name=name, limit=1)
            if controls_list["controls"]:
                control_id = controls_list["controls"][0]["id"]
                await controls.set_control_data(client, control_id, data)
                print(f"  ~ Control exists: {name} (ID: {control_id}) -- data updated")
                return control_id
            raise RuntimeError(f"409 conflict but could not find control '{name}'")
        raise


async def create_policy_safe(client, name: str) -> int | None:
    """Create a policy. Returns the ID on success, None on 409 conflict.

    The server does not expose a list-policies-by-name endpoint, so on
    conflict we cannot reliably retrieve the existing policy ID. In that
    case we return None and the caller uses direct agent-control associations
    as a fallback (which are always idempotent).
    """
    try:
        result = await policies.create_policy(client, name=name)
        policy_id = result["policy_id"]
        print(f"  + Created policy: {name} (ID: {policy_id})")
        return policy_id
    except Exception as e:
        if "409" in str(e):
            print(f"  ~ Policy already exists: {name} (skipping policy-level association)")
            # Try to extract policy_id from error response body
            if hasattr(e, "response"):
                try:
                    body = e.response.json()
                    if "policy_id" in body:
                        return body["policy_id"]
                except Exception:
                    pass
            return None
        raise


# ---------------------------------------------------------------------------
# Control definitions
# ---------------------------------------------------------------------------

def researcher_controls() -> list[tuple[str, dict]]:
    """Controls for the Researcher agent's query_database tool."""
    sql_safety = {
        "description": "Block dangerous SQL operations and enforce LIMIT clause",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["tool"],
            "step_names": ["query_database"],
            "stages": ["pre"],
        },
        "selector": {"path": "input.query"},
        "evaluator": {
            "name": "sql",
            "config": {
                "blocked_operations": ["DROP", "DELETE", "TRUNCATE", "ALTER", "INSERT", "UPDATE"],
                "allow_multi_statements": False,
                "require_limit": True,
                "max_limit": 100,
            },
        },
        "action": {"decision": "deny"},
    }

    restricted_tables = {
        "description": "Block access to sensitive tables (salary_data, admin_users, credentials)",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["tool"],
            "step_names": ["query_database"],
            "stages": ["pre"],
        },
        "selector": {"path": "input.query"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["salary_data", "admin_users", "credentials", "auth_tokens"],
                "logic": "any",
                "match_mode": "contains",
                "case_sensitive": False,
            },
        },
        "action": {"decision": "deny"},
    }

    return [
        ("researcher-sql-safety", sql_safety),
        ("researcher-restricted-tables", restricted_tables),
    ]


def analyst_controls() -> list[tuple[str, dict]]:
    """Controls for the Analyst agent's validate_data tool."""
    required_fields = {
        "description": "Require dataset, findings, and confidence_score in analysis",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["tool"],
            "step_names": ["validate_data"],
            "stages": ["pre"],
        },
        "selector": {"path": "input.request"},
        "evaluator": {
            "name": "json",
            "config": {
                "required_fields": ["dataset", "findings", "confidence_score"],
                "field_constraints": {
                    "confidence_score": {
                        "type": "number",
                        "min": 0,
                        "max": 1,
                    }
                },
            },
        },
        "action": {"decision": "deny"},
    }

    missing_methodology = {
        "description": "Steer analyst to add methodology when missing",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["tool"],
            "step_names": ["validate_data"],
            "stages": ["pre"],
        },
        "selector": {"path": "input.request"},
        "evaluator": {
            "name": "json",
            "config": {
                "json_schema": {
                    "type": "object",
                    "oneOf": [
                        {
                            "required": ["methodology"],
                            "properties": {
                                "methodology": {"type": "string", "minLength": 1}
                            },
                        }
                    ],
                }
            },
        },
        "action": {
            "decision": "steer",
            "steering_context": {
                "message": (
                    '{"required_actions": ["add_methodology"], '
                    '"reason": "Analysis must include a methodology section '
                    'describing how data was collected and validated.", '
                    '"retry_with": {"methodology": '
                    '"<describe your data collection and validation method>"}}'
                )
            },
        },
    }

    return [
        ("analyst-required-fields", required_fields),
        ("analyst-methodology-check", missing_methodology),
    ]


def writer_controls() -> list[tuple[str, dict]]:
    """Controls for the Writer agent's write_report tool."""
    pii_regex = {
        "description": "Block PII (SSN, email, phone) in report output",
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["tool"],
            "step_names": ["write_report"],
            "stages": ["post"],
        },
        "selector": {"path": "output"},
        "evaluator": {
            "name": "regex",
            "config": {
                "pattern": (
                    r"(?:"
                    r"\b\d{3}-\d{2}-\d{4}\b"           # SSN
                    r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"  # Email
                    r"|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"  # Phone
                    r")"
                )
            },
        },
        "action": {"decision": "deny"},
    }

    # NOTE: The citation-presence check is handled client-side in the tool
    # wrapper (write_report in research_crew.py) because the regex evaluator
    # triggers actions on match, not on non-match. The tool adds citations
    # if they are missing before returning the report.

    return [
        ("writer-pii-blocker", pii_regex),
    ]


# ---------------------------------------------------------------------------
# Main setup
# ---------------------------------------------------------------------------

async def setup():
    """Create all controls, policies, and agent associations."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register the runtime agent
        agent = Agent(
            agent_name=AGENT_NAME,
            agent_description=(
                "Multi-agent research crew with per-agent policies: "
                "Researcher (data access), Analyst (validation), Writer (content safety)"
            ),
        )
        try:
            await agents.register_agent(client, agent, steps=[])
            print(f"[agent] Registered: {AGENT_NAME}")
        except Exception as e:
            if "409" in str(e) or "already" in str(e).lower():
                print(f"[agent] Already exists: {AGENT_NAME}")
            else:
                raise

        # 2. Create controls grouped by role
        print("\n[controls] Creating researcher controls...")
        researcher_ids = []
        for name, data in researcher_controls():
            cid = await create_control_idempotent(client, name, data)
            researcher_ids.append(cid)

        print("\n[controls] Creating analyst controls...")
        analyst_ids = []
        for name, data in analyst_controls():
            cid = await create_control_idempotent(client, name, data)
            analyst_ids.append(cid)

        print("\n[controls] Creating writer controls...")
        writer_ids = []
        for name, data in writer_controls():
            cid = await create_control_idempotent(client, name, data)
            writer_ids.append(cid)

        all_control_ids = researcher_ids + analyst_ids + writer_ids

        # 3. Create policies and associate controls
        print("\n[policies] Creating policies and associating controls...")

        policy_groups = [
            ("data-access-policy", researcher_ids),
            ("analysis-validation-policy", analyst_ids),
            ("content-safety-policy", writer_ids),
        ]

        for policy_name, control_ids in policy_groups:
            pid = await create_policy_safe(client, policy_name)
            if pid is not None:
                for cid in control_ids:
                    await policies.add_control_to_policy(client, pid, cid)
                print(f"    {policy_name}: {len(control_ids)} controls linked")
                # Assign policy to agent
                try:
                    await agents.add_agent_policy(client, AGENT_NAME, pid)
                    print(f"    {policy_name} -> {AGENT_NAME}")
                except Exception as e:
                    if "409" in str(e) or "already" in str(e).lower():
                        print(f"    {policy_name} already assigned (OK)")
                    else:
                        raise

        # 4. Also add controls directly to the agent as a reliable fallback.
        #    Direct associations are always idempotent and guarantee the controls
        #    are active even if policy association had issues on re-run.
        print("\n[agent] Adding direct control associations (idempotent)...")
        for cid in all_control_ids:
            try:
                await agents.add_agent_control(client, AGENT_NAME, cid)
            except Exception as e:
                if "409" in str(e) or "already" in str(e).lower():
                    pass  # Already associated, which is fine
                else:
                    raise
        print(f"  + {len(all_control_ids)} controls directly associated with {AGENT_NAME}")

        # Summary
        print("\n" + "=" * 60)
        print("Setup complete!")
        print("=" * 60)
        print(f"""
Agent:    {AGENT_NAME}
Policies: 3
Controls: {len(all_control_ids)}

  data-access-policy (Researcher -> query_database):
    - researcher-sql-safety         [pre, deny]   Block DROP/DELETE, enforce LIMIT
    - researcher-restricted-tables  [pre, deny]   Block salary_data, admin_users, ...

  analysis-validation-policy (Analyst -> validate_data):
    - analyst-required-fields       [pre, deny]   Require dataset, findings, confidence_score
    - analyst-methodology-check     [pre, steer]  Steer if methodology missing

  content-safety-policy (Writer -> write_report):
    - writer-pii-blocker            [post, deny]  Block SSN, email, phone in output

You can now run:  uv run --active python -m secure_research_crew.main
""")


if __name__ == "__main__":
    print("=" * 60)
    print("Secure Research Crew -- Control & Policy Setup")
    print("=" * 60)
    print()
    asyncio.run(setup())
