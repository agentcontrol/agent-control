#!/usr/bin/env python3
"""
Country-specific controls, using evaluate_controls() and `step.context`.

The caller passes the jurisdiction as request metadata in `context`, separate
from the text being checked. The controls select it with `context.jurisdiction`.

This is the form that gateways and non-Python clients use too. They send the
same `step.context` in the body of POST /api/v1/evaluation.

The same policy is authored in two ways:

  per-country : one control per country, each = AND(jurisdiction in [CC], rule)
  composite   : ONE control = OR( AND(DE, IBAN rule), AND(US, SSN rule) )

Each style is scoped to its own step name, so both run side by side on one agent.

A baseline control applies to every country. It has no jurisdiction condition,
so it also applies when the jurisdiction is missing. Here it is scoped to both
steps and blocks email addresses.

Note: a request with no jurisdiction matches no country rule, so country rules
are skipped. Add a catch-all control if you need a strict default.

Prerequisites:
    1. Agent Control server running: make server-run
    2. SDK installed: make sync

Usage:
    uv run python examples/country_controls/country_controls_context.py
"""

import asyncio
import logging
import os
import sys

# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

import agent_control
from agent_control import AgentControlClient

logging.basicConfig(level=logging.WARNING)

AGENT_NAME = "country-demo-context"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# Where the jurisdiction lives in the step. Only this path (and the step type)
# differs from country_controls_decorator.py.
JURISDICTION_PATH = "context.jurisdiction"
STEP_TYPE = "llm"

PER_COUNTRY_STEP = "answer-per-country"
COMPOSITE_STEP = "answer-composite"

DE_IBAN = r"\bDE\d{2}(?: ?\d{4}){4} ?\d{2}\b"
US_SSN = r"\b\d{3}-\d{2}-\d{4}\b"
EMAIL = r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"


# =============================================================================
# CONTROL DEFINITIONS
# =============================================================================


def jurisdiction_in(codes: list[str]) -> dict:
    return {
        "selector": {"path": JURISDICTION_PATH},
        "evaluator": {"name": "list", "config": {"values": codes}},
    }


def output_matches(pattern: str) -> dict:
    return {
        "selector": {"path": "output"},
        "evaluator": {"name": "regex", "config": {"pattern": pattern}},
    }


def control_definition(description: str, step_names: list[str], condition: dict) -> dict:
    return {
        "description": description,
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": [STEP_TYPE], "step_names": step_names, "stages": ["post"]},
        "condition": condition,
        "action": {"decision": "deny"},
        "tags": ["country-controls"],
    }


CONTROLS = {
    # Baseline: applies to every country, so it has no jurisdiction condition.
    "country-context-baseline-email": control_definition(
        "All countries: block email addresses.",
        [PER_COUNTRY_STEP, COMPOSITE_STEP],
        output_matches(EMAIL),
    ),
    # Style 1: one control per country.
    "country-context-de-iban": control_definition(
        "DE only: block German IBANs.",
        [PER_COUNTRY_STEP],
        {"and": [jurisdiction_in(["DE"]), output_matches(DE_IBAN)]},
    ),
    "country-context-us-ssn": control_definition(
        "US only: block US Social Security numbers.",
        [PER_COUNTRY_STEP],
        {"and": [jurisdiction_in(["US"]), output_matches(US_SSN)]},
    ),
    # Style 2: one composite control for all countries.
    "country-context-countries": control_definition(
        "One control, per-country branches: DE -> IBAN, US -> SSN.",
        [COMPOSITE_STEP],
        {
            "or": [
                {"and": [jurisdiction_in(["DE"]), output_matches(DE_IBAN)]},
                {"and": [jurisdiction_in(["US"]), output_matches(US_SSN)]},
            ]
        },
    ),
}


# =============================================================================
# SERVER SETUP
# =============================================================================


async def setup_controls() -> None:
    """Create the agent and its controls (safe to run repeatedly)."""
    print("=" * 60)
    print("STEP 1: Setting up agent and controls")
    print("=" * 60)

    async with AgentControlClient(base_url=SERVER_URL) as client:
        await client.health_check()

        response = await client.http_client.post(
            "/api/v1/agents/initAgent",
            json={
                "agent": {
                    "agent_name": AGENT_NAME,
                    "agent_description": "Country-specific controls demo (context)",
                },
                "steps": [],
            },
        )
        response.raise_for_status()
        print(f"✓ Agent: {AGENT_NAME}")

        for name, definition in CONTROLS.items():
            response = await client.http_client.put(
                "/api/v1/controls", json={"name": name, "data": definition}
            )
            if response.status_code == 409:
                # Already exists: look up its ID and refresh the definition.
                listing = await client.http_client.get(
                    "/api/v1/controls", params={"name": name, "limit": 100}
                )
                listing.raise_for_status()
                control_id = next(c["id"] for c in listing.json()["controls"] if c["name"] == name)
                update = await client.http_client.put(
                    f"/api/v1/controls/{control_id}/data", json={"data": definition}
                )
                update.raise_for_status()
                print(f"✓ Updated control '{name}' (ID: {control_id})")
            else:
                response.raise_for_status()
                control_id = response.json()["control_id"]
                print(f"✓ Created control '{name}' (ID: {control_id})")

            # Attaching is idempotent, so a re-run succeeds.
            attach = await client.http_client.post(
                f"/api/v1/agents/{AGENT_NAME}/controls/{control_id}"
            )
            attach.raise_for_status()


# =============================================================================
# THE AGENT STEPS
# =============================================================================

IBAN_TEXT = "Your refund goes to DE89 3704 0044 0532 0130 00."
SSN_TEXT = "Your SSN on file is 123-45-6789."
EMAIL_TEXT = "Contact your agent at jane.doe@example.com."
CLEAN_TEXT = "Your order ships on Tuesday."

# (label, answer text, jurisdiction, expected)
SCENARIOS = [
    ("DE + IBAN", IBAN_TEXT, "DE", "BLOCK"),
    ("US + IBAN (no US rule)", IBAN_TEXT, "US", "allow"),
    ("US + SSN", SSN_TEXT, "US", "BLOCK"),
    ("DE + SSN (no DE rule)", SSN_TEXT, "DE", "allow"),
    ("US + clean text", CLEAN_TEXT, "US", "allow"),
    ("DE + email (baseline)", EMAIL_TEXT, "DE", "BLOCK"),
    ("No jurisdiction + email (baseline)", EMAIL_TEXT, None, "BLOCK"),
]


async def outcome(step_name: str, text: str, jurisdiction: str | None) -> str:
    result = await agent_control.evaluate_controls(
        step_name,
        input="What is on file for me?",
        output=text,
        context={"jurisdiction": jurisdiction} if jurisdiction else None,
        step_type=STEP_TYPE,
        stage="post",
        agent_name=AGENT_NAME,
    )
    if result.is_safe:
        return "allow"
    return f"BLOCK ({', '.join(m.control_name for m in result.matches or [])})"


async def run_scenarios() -> int:
    print("\n" + "=" * 60)
    print("STEP 2: Running scenarios")
    print("=" * 60)

    failures = 0
    for label, text, jurisdiction, expected in SCENARIOS:
        print(f"\n{label}   (expected: {expected})")
        for style, step in [("per-country", PER_COUNTRY_STEP), ("composite", COMPOSITE_STEP)]:
            result = await outcome(step, text, jurisdiction)
            ok = result.split()[0] == expected
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {style + ':':<12} {result}")

    print(f"\n{len(SCENARIOS) * 2 - failures}/{len(SCENARIOS) * 2} checks passed")
    return failures


async def main() -> int:
    failures = await run_scenarios()
    await agent_control.ashutdown()
    return failures


if __name__ == "__main__":
    # Controls must exist before init(), which fetches them from the server.
    asyncio.run(setup_controls())
    agent_control.init(
        agent_name=AGENT_NAME,
        agent_description="Country-specific controls demo (context)",
        server_url=SERVER_URL,
        observability_enabled=False,
    )
    sys.exit(1 if asyncio.run(main()) else 0)
