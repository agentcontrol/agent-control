#!/usr/bin/env python3
"""
Attribute-based controls, using the @control() decorator.

A rule applies only when a request attribute has a given value. This example
uses the country (jurisdiction) as the attribute. The same pattern works for
any attribute, such as tenant, user tier or channel.

The decorator builds the step from the function's arguments and cannot set
`step.context`. So here the jurisdiction is an ordinary function argument.
The controls select it with the path `input.jurisdiction`.

This works only for tool steps (and custom step types), where `input` is the
dict of all arguments. For an LLM step, `input` is a single string.

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
    uv run python examples/attribute_controls/attribute_controls_decorator.py
"""

import asyncio
import logging
import os
import sys

# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

import agent_control
from agent_control import AgentControlClient, ControlViolationError, control

logging.basicConfig(level=logging.WARNING)

AGENT_NAME = "attribute-demo-decorator"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# Where the jurisdiction lives in the step. Only this path (and the step type)
# differs from attribute_controls_context.py.
JURISDICTION_PATH = "input.jurisdiction"
STEP_TYPE = "tool"

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
        "tags": ["attribute-controls"],
    }


CONTROLS = {
    # Baseline: applies to every country, so it has no jurisdiction condition.
    "attribute-decorator-baseline-email": control_definition(
        "All countries: block email addresses.",
        [PER_COUNTRY_STEP, COMPOSITE_STEP],
        output_matches(EMAIL),
    ),
    # Style 1: one control per country.
    "attribute-decorator-de-iban": control_definition(
        "DE only: block German IBANs.",
        [PER_COUNTRY_STEP],
        {"and": [jurisdiction_in(["DE"]), output_matches(DE_IBAN)]},
    ),
    "attribute-decorator-us-ssn": control_definition(
        "US only: block US Social Security numbers.",
        [PER_COUNTRY_STEP],
        {"and": [jurisdiction_in(["US"]), output_matches(US_SSN)]},
    ),
    # Style 2: one composite control for all countries.
    "attribute-decorator-countries": control_definition(
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
                    "agent_description": "Attribute-based controls demo (decorator)",
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


# step_type="tool" makes `input` the dict of all arguments, so the controls can
# select `input.jurisdiction`. Without it, a plain function is an "llm" step.
# Both functions only return the text: the controls check it at the post stage.
@control(step_name=PER_COUNTRY_STEP, step_type=STEP_TYPE)
async def answer_per_country(*, text: str, jurisdiction: str | None) -> str:
    return text


@control(step_name=COMPOSITE_STEP, step_type=STEP_TYPE)
async def answer_composite(*, text: str, jurisdiction: str | None) -> str:
    return text


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
    ("No jurisdiction + IBAN", IBAN_TEXT, None, "allow"),
    ("No jurisdiction + email (baseline)", EMAIL_TEXT, None, "BLOCK"),
]


async def outcome(step_fn, text: str, jurisdiction: str | None) -> str:
    try:
        await step_fn(text=text, jurisdiction=jurisdiction)
    except ControlViolationError as e:
        return f"BLOCK ({e.control_name})"
    except RuntimeError as e:  # The SDK raises this when a control errors on the server.
        return f"ERROR ({e})"
    return "allow"


async def run_scenarios() -> int:
    print("\n" + "=" * 60)
    print("STEP 2: Running scenarios")
    print("=" * 60)

    failures = 0
    for label, text, jurisdiction, expected in SCENARIOS:
        print(f"\n{label}   (expected: {expected})")
        for style, step in [("per-country", answer_per_country), ("composite", answer_composite)]:
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
        agent_description="Attribute-based controls demo (decorator)",
        server_url=SERVER_URL,
        observability_enabled=False,
    )
    sys.exit(1 if asyncio.run(main()) else 0)
