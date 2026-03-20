"""
Secure Research Crew -- CrewAI multi-agent demo with per-agent Agent Control policies.

A 3-agent sequential crew where each agent has different controls:

  1. Researcher  -- queries a simulated database
     Controls: SQL evaluator (block DROP/DELETE, enforce LIMIT)
               LIST evaluator (block sensitive tables)

  2. Analyst    -- validates and processes research data
     Controls: JSON evaluator (require dataset, findings, confidence_score)
               JSON schema steer (add methodology if missing)

  3. Writer     -- generates the final report
     Controls: REGEX evaluator (block PII in output)
               Client-side citation check (steer if missing)

Scenarios:
  1. Happy path           -- all agents pass, report generated
  2. Researcher blocked   -- SQL injection attempt (DROP TABLE)
  3. Researcher restricted-- query to salary_data table
  4. Analyst steered      -- missing methodology, corrected, then succeeds
  5. Writer blocked       -- PII in report output

PREREQUISITE:
    uv run --active python setup_controls.py

Usage:
    uv run --active secure_research_crew
"""

import json
import os

import agent_control

# ---------------------------------------------------------------------------
# Configuration -- init must happen before tools are invoked (but can be
# after they are imported, since @control() is lazy).
# ---------------------------------------------------------------------------

AGENT_NAME = "secure-research-crew"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_description="Multi-agent research crew with per-agent policies",
    server_url=SERVER_URL,
)

# Import tools AFTER agent_control.init() -- the @control() decorator is
# applied at import time but does not call the server until invoked.
from secure_research_crew.tools.query_database import query_database  # noqa: E402
from secure_research_crew.tools.validate_data import validate_data  # noqa: E402
from secure_research_crew.tools.write_report import write_report  # noqa: E402


# ===========================================================================
# Scenario runners (direct tool calls -- avoids LLM costs for testing)
# ===========================================================================

def header(title: str) -> None:
    """Print a scenario header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run_scenario_1_happy_path():
    """Happy path: all three tools pass controls, report generated."""
    header("SCENARIO 1: Happy Path -- All Agents Pass Controls")

    # Step 1: Researcher queries safely
    print("\n--- Step 1: Researcher queries database ---")
    data = query_database.run("SELECT name, department FROM employees LIMIT 10")
    print(f"  Result: {data[:120]}...")

    # Step 2: Analyst validates with all required fields + methodology
    print("\n--- Step 2: Analyst validates data ---")
    analysis_request = json.dumps({
        "dataset": "employees",
        "findings": "Engineering department has 2 senior staff members",
        "confidence_score": 0.92,
        "methodology": "Cross-referenced employee records with department roster",
    })
    validated = validate_data.run(analysis_request)
    print(f"  Result: {validated[:120]}...")

    # Step 3: Writer generates clean report
    print("\n--- Step 3: Writer generates report ---")
    report_content = (
        "The engineering department analysis reveals 2 senior staff members "
        "with strong project involvement. Project Alpha and Gamma are active "
        "with combined budgets exceeding $370,000. Quarterly revenue shows "
        "consistent 12-18% growth.\n\n"
        "Sources: Internal database (employees, projects, quarterly_metrics)"
    )
    report = write_report.run(report_content)
    print(f"  Result:\n{report}")


def run_scenario_2_sql_injection():
    """Researcher blocked: SQL injection attempt with DROP TABLE."""
    header("SCENARIO 2: Researcher Blocked -- SQL Injection Attempt")

    result = query_database.run("DROP TABLE employees; SELECT * FROM employees LIMIT 10")
    print(f"  Result: {result}")
    assert "BLOCKED" in result, "Expected the query to be blocked!"
    print("\n  [OK] SQL injection correctly blocked by data-access-policy")


def run_scenario_3_restricted_table():
    """Researcher restricted: query to salary_data table denied."""
    header("SCENARIO 3: Researcher Restricted -- Sensitive Table Access")

    result = query_database.run("SELECT * FROM salary_data LIMIT 10")
    print(f"  Result: {result}")
    assert "BLOCKED" in result, "Expected the query to be blocked!"
    print("\n  [OK] Sensitive table access correctly blocked by data-access-policy")


def run_scenario_4_analyst_steered():
    """Analyst steered: methodology missing, auto-corrected, then succeeds."""
    header("SCENARIO 4: Analyst Steered -- Missing Methodology")

    # First attempt WITHOUT methodology -- should be steered, then auto-corrected
    analysis_request = json.dumps({
        "dataset": "quarterly_metrics",
        "findings": "Revenue growing at 15% average quarterly rate",
        "confidence_score": 0.88,
        # NOTE: methodology intentionally omitted
    })
    result = validate_data.run(analysis_request)
    print(f"  Result: {result[:200]}...")

    # The tool should have auto-added methodology after steering
    if "validated" in result:
        print("\n  [OK] Analyst was steered to add methodology and succeeded on retry")
    elif "BLOCKED" in result:
        print("\n  [INFO] Analyst was blocked (deny control fired before steer)")
    else:
        print(f"\n  [INFO] Result: {result}")


def run_scenario_5_writer_pii():
    """Writer blocked: PII detected in report output."""
    header("SCENARIO 5: Writer Blocked -- PII in Report Output")

    # Content that contains PII (email and phone number)
    pii_content = (
        "The project lead is Alice Johnson. For questions, contact her at "
        "alice.johnson@company.com or call 555-123-4567. "
        "Her SSN is 123-45-6789.\n\n"
        "Sources: HR database, project management system"
    )
    result = write_report.run(pii_content)
    print(f"  Result: {result}")
    assert "BLOCKED" in result, "Expected PII to be blocked!"
    print("\n  [OK] PII correctly blocked by content-safety-policy")


def run_full_crew():
    """Run the full 3-agent CrewAI crew for the happy path."""
    header("FULL CREW RUN: 3-Agent Sequential Pipeline")

    if not os.getenv("OPENAI_API_KEY"):
        print("\n  [SKIP] OPENAI_API_KEY not set -- skipping full crew run.")
        print("  The direct tool scenarios above demonstrate all control behavior.")
        return

    from secure_research_crew.crew import SecureResearchCrew

    print("\n  Running crew... (this uses LLM calls)\n")
    result = SecureResearchCrew().crew().kickoff()
    print("\n" + "-" * 70)
    print("  CREW OUTPUT:")
    print("-" * 70)
    print(result)


# ===========================================================================
# Verification
# ===========================================================================

def verify_setup() -> bool:
    """Check that the Agent Control server is running and controls are configured."""
    import httpx

    try:
        print("[setup] Verifying Agent Control server...")
        response = httpx.get(f"{SERVER_URL}/api/v1/controls?limit=100", timeout=5.0)
        response.raise_for_status()

        data = response.json()
        control_names = [c["name"] for c in data.get("controls", [])]

        required = [
            "researcher-sql-safety",
            "researcher-restricted-tables",
            "analyst-required-fields",
            "analyst-methodology-check",
            "writer-pii-blocker",
        ]
        missing = [c for c in required if c not in control_names]

        if missing:
            print(f"[setup] Missing controls: {missing}")
            print("[setup] Run setup_controls.py first.")
            return False

        print(f"[setup] Server OK -- {len(control_names)} controls found")
        return True

    except httpx.ConnectError:
        print(f"[setup] Cannot connect to {SERVER_URL}")
        print("[setup] Start the Agent Control server first (make server-run)")
        return False
    except Exception as e:
        print(f"[setup] Error: {e}")
        return False


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 70)
    print("  Secure Research Crew -- Agent Control Multi-Agent Demo")
    print("=" * 70)
    print()
    print("This demo runs 5 scenarios showing how different Agent Control")
    print("policies protect each agent in a CrewAI crew:")
    print()
    print("  1. Happy path         -- all agents pass controls")
    print("  2. SQL injection      -- researcher blocked by SQL evaluator")
    print("  3. Restricted table   -- researcher blocked by LIST evaluator")
    print("  4. Missing methodology-- analyst steered, then succeeds")
    print("  5. PII in report      -- writer blocked by REGEX evaluator")
    print()

    if not verify_setup():
        print("\nSetup verification failed. Exiting.")
        return

    # Run all direct-call scenarios (no LLM needed)
    run_scenario_1_happy_path()
    run_scenario_2_sql_injection()
    run_scenario_3_restricted_table()
    run_scenario_4_analyst_steered()
    run_scenario_5_writer_pii()

    # Summary
    header("SUMMARY")
    print("""
  Scenario 1 (Happy Path):        All 3 agents passed controls
  Scenario 2 (SQL Injection):     Researcher BLOCKED by sql evaluator
  Scenario 3 (Restricted Table):  Researcher BLOCKED by list evaluator
  Scenario 4 (Missing Method):    Analyst STEERED, then succeeded
  Scenario 5 (PII in Report):     Writer BLOCKED by regex evaluator

  Controls are enforced per-agent via policies:
    - data-access-policy       -> query_database tool
    - analysis-validation-policy -> validate_data tool
    - content-safety-policy    -> write_report tool

  Each policy targets specific step_names, so controls only fire
  for the tools belonging to that agent role.
""")

    # Optionally run full crew (requires OPENAI_API_KEY)
    print("-" * 70)
    if not os.getenv("OPENAI_API_KEY"):
        print("  Skipping full crew run (OPENAI_API_KEY not set).")
    else:
        answer = input("  Run full CrewAI crew with LLM? (y/N): ").strip().lower()
        if answer == "y":
            run_full_crew()
        else:
            print("  Skipping full crew run.")

    print("\n" + "=" * 70)
    print("  Demo complete!")
    print("=" * 70)


def run():
    """Entry point for [project.scripts]."""
    try:
        main()
    finally:
        agent_control.shutdown()


if __name__ == "__main__":
    try:
        main()
    finally:
        agent_control.shutdown()
