"""
Setup script for the CrewAI Evaluator Showcase.

Creates controls using ALL four built-in evaluators in a realistic
data-analyst agent scenario:

  REGEX - Block PII patterns (SSN, credit cards) in query results
  LIST  - Restrict access to sensitive database tables
  JSON  - Validate query parameters have required fields and constraints
  SQL   - Prevent dangerous SQL operations (DROP, DELETE, multi-statement)

Run once before running the demo:
    uv run --active python setup_controls.py
"""

import asyncio
import os

from agent_control import Agent, AgentControlClient, agents, controls

AGENT_NAME = "crewai-data-analyst"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def setup():
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # ── Register Agent ──────────────────────────────────────────────
        agent = Agent(
            agent_name=AGENT_NAME,
            agent_description=(
                "CrewAI data analyst agent that queries databases with "
                "controls on SQL safety, PII leakage, table access, and data validation"
            ),
        )

        try:
            await agents.register_agent(client, agent, steps=[])
            print(f"  Agent registered: {AGENT_NAME}")
        except Exception as e:
            if "already exists" in str(e).lower() or "409" in str(e):
                print(f"  Agent already registered: {AGENT_NAME}")
            else:
                raise

        # ── Control Definitions ─────────────────────────────────────────
        control_defs = [
            # ┌─────────────────────────────────────────────────────────┐
            # │  SQL EVALUATOR                                          │
            # │  Validates SQL queries for safety before execution.     │
            # │  Blocks DROP/DELETE/TRUNCATE, enforces LIMIT,           │
            # │  prevents multi-statement injection.                    │
            # └─────────────────────────────────────────────────────────┘
            (
                "sql-safety-check",
                {
                    "description": (
                        "Validate SQL queries: block destructive operations, "
                        "enforce LIMIT, prevent multi-statement injection"
                    ),
                    "enabled": True,
                    "execution": "server",
                    "scope": {
                        "step_types": ["tool"],
                        "step_names": ["run_sql_query"],
                        "stages": ["pre"],
                    },
                    "selector": {"path": "input.query"},
                    "evaluator": {
                        "name": "sql",
                        "config": {
                            "blocked_operations": [
                                "DROP",
                                "DELETE",
                                "TRUNCATE",
                                "ALTER",
                                "GRANT",
                                "INSERT",
                                "UPDATE",
                            ],
                            "allow_multi_statements": False,
                            "require_limit": True,
                            "max_limit": 100,
                        },
                    },
                    "action": {"decision": "deny"},
                },
            ),
            # ┌─────────────────────────────────────────────────────────┐
            # │  LIST EVALUATOR                                         │
            # │  Restricts which tables the agent can query.            │
            # │  Contains-match against the SQL query text to catch     │
            # │  references to sensitive tables.                        │
            # └─────────────────────────────────────────────────────────┘
            (
                "restrict-sensitive-tables",
                {
                    "description": (
                        "Block queries that reference sensitive tables: "
                        "audit_log, admin_users, payment_methods, salary_data"
                    ),
                    "enabled": True,
                    "execution": "server",
                    "scope": {
                        "step_types": ["tool"],
                        "step_names": ["run_sql_query"],
                        "stages": ["pre"],
                    },
                    "selector": {"path": "input.query"},
                    "evaluator": {
                        "name": "list",
                        "config": {
                            "values": [
                                "audit_log",
                                "admin_users",
                                "payment_methods",
                                "salary_data",
                            ],
                            "logic": "any",
                            "match_mode": "contains",
                            "case_sensitive": False,
                        },
                    },
                    "action": {"decision": "deny"},
                },
            ),
            # ┌─────────────────────────────────────────────────────────┐
            # │  REGEX EVALUATOR                                        │
            # │  Scans query RESULTS for PII patterns after execution.  │
            # │  Catches SSNs, credit card numbers, and email           │
            # │  addresses that might leak through query results.       │
            # └─────────────────────────────────────────────────────────┘
            (
                "pii-in-query-results",
                {
                    "description": (
                        "Block query results containing PII: "
                        "SSN, credit card numbers, or email addresses"
                    ),
                    "enabled": True,
                    "execution": "server",
                    "scope": {
                        "step_types": ["tool"],
                        "step_names": ["run_sql_query"],
                        "stages": ["post"],
                    },
                    "selector": {"path": "output"},
                    "evaluator": {
                        "name": "regex",
                        "config": {
                            "pattern": (
                                r"(?:"
                                r"\b\d{3}-\d{2}-\d{4}\b"  # SSN
                                r"|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"  # Credit card
                                r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"  # Email
                                r")"
                            )
                        },
                    },
                    "action": {"decision": "deny"},
                },
            ),
            # ┌─────────────────────────────────────────────────────────┐
            # │  JSON EVALUATOR                                         │
            # │  Validates the analysis request structure before the    │
            # │  agent starts working. Ensures required fields exist    │
            # │  and constraints are met (date range, row limit).       │
            # └─────────────────────────────────────────────────────────┘
            (
                "validate-analysis-request",
                {
                    "description": (
                        "Validate analysis request: require dataset, date_range, "
                        "and max_rows fields with proper constraints"
                    ),
                    "enabled": True,
                    "execution": "server",
                    "scope": {
                        "step_types": ["tool"],
                        "step_names": ["analyze_data"],
                        "stages": ["pre"],
                    },
                    "selector": {"path": "input.request"},
                    "evaluator": {
                        "name": "json",
                        "config": {
                            "required_fields": ["dataset", "date_range"],
                            "field_constraints": {
                                "max_rows": {
                                    "type": "number",
                                    "min": 1,
                                    "max": 10000,
                                }
                            },
                        },
                    },
                    "action": {"decision": "deny"},
                },
            ),
            # ┌─────────────────────────────────────────────────────────┐
            # │  JSON EVALUATOR (STEER)                                 │
            # │  When analysis request is missing the optional          │
            # │  "purpose" field, steer the agent to collect it.        │
            # │  This demonstrates json + steer together.               │
            # └─────────────────────────────────────────────────────────┘
            (
                "steer-require-purpose",
                {
                    "description": (
                        "Steer agent to collect analysis purpose when not provided"
                    ),
                    "enabled": True,
                    "execution": "server",
                    "scope": {
                        "step_types": ["tool"],
                        "step_names": ["analyze_data"],
                        "stages": ["pre"],
                    },
                    "selector": {"path": "input.request"},
                    "evaluator": {
                        "name": "json",
                        "config": {
                            "required_fields": ["purpose"],
                        },
                    },
                    "action": {
                        "decision": "steer",
                        "steering_context": {
                            "message": (
                                '{"required_actions": ["collect_purpose"],'
                                ' "reason": "Every data analysis must include a stated purpose'
                                ' for audit compliance. Please add a purpose field.",'
                                ' "retry_with": {"purpose": "<describe analysis goal>"}}'
                            )
                        },
                    },
                },
            ),
        ]

        # ── Create Controls & Associate with Agent ──────────────────────
        control_ids = []
        for name, data in control_defs:
            evaluator = data["evaluator"]["name"].upper()
            decision = data["action"]["decision"].upper()
            try:
                result = await controls.create_control(client, name=name, data=data)
                cid = result["control_id"]
                print(f"  [{evaluator:5s}|{decision:5s}] Created: {name} (ID: {cid})")
                control_ids.append(cid)
            except Exception as e:
                if "409" in str(e):
                    clist = await controls.list_controls(client, name=name, limit=1)
                    if clist["controls"]:
                        cid = clist["controls"][0]["id"]
                        print(f"  [{evaluator:5s}|EXIST] Already exists: {name} (ID: {cid})")
                        control_ids.append(cid)
                else:
                    raise

        print()
        for cid in control_ids:
            try:
                await agents.add_agent_control(client, AGENT_NAME, cid)
            except Exception:
                pass  # Already associated

        print(f"  All {len(control_ids)} controls associated with agent")

        # ── Summary ─────────────────────────────────────────────────────
        print()
        print("Setup complete! Evaluators configured:")
        print()
        print("  SQL   - Block destructive ops, enforce LIMIT, prevent injection")
        print("  LIST  - Restrict access to sensitive tables")
        print("  REGEX - Detect PII (SSN, credit cards, emails) in results")
        print("  JSON  - Validate request structure and field constraints")
        print("  JSON  - Steer agent to provide analysis purpose")
        print()
        print("Run the demo:  uv run --active python -m evaluator_showcase.main")


if __name__ == "__main__":
    print("=" * 60)
    print("  CrewAI Data Analyst - Evaluator Showcase Setup")
    print("=" * 60)
    print()
    asyncio.run(setup())
