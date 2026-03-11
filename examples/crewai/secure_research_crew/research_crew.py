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
    uv run python setup_controls.py

Usage:
    uv run python research_crew.py
"""

import asyncio
import json
import os
import re

import agent_control
from agent_control import ControlSteerError, ControlViolationError, control
from crewai import Agent, Crew, Task
from crewai.tools import tool

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "secure-research-crew"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_description="Multi-agent research crew with per-agent policies",
    server_url=SERVER_URL,
)

# ---------------------------------------------------------------------------
# Simulated database (no real DB needed)
# ---------------------------------------------------------------------------

SIMULATED_DB = {
    "employees": [
        {"id": 1, "name": "Alice Johnson", "department": "Engineering", "role": "Senior Engineer"},
        {"id": 2, "name": "Bob Williams", "department": "Marketing", "role": "Marketing Lead"},
        {"id": 3, "name": "Carol Davis", "department": "Engineering", "role": "Staff Engineer"},
    ],
    "projects": [
        {"id": 101, "name": "Project Alpha", "status": "active", "budget": 150000},
        {"id": 102, "name": "Project Beta", "status": "completed", "budget": 80000},
        {"id": 103, "name": "Project Gamma", "status": "active", "budget": 220000},
    ],
    "quarterly_metrics": [
        {"quarter": "Q1", "revenue": 2400000, "growth": 0.12},
        {"quarter": "Q2", "revenue": 2700000, "growth": 0.15},
        {"quarter": "Q3", "revenue": 3100000, "growth": 0.18},
    ],
}


def simulate_query(query: str) -> str:
    """Return simulated data based on query content."""
    q = query.lower()
    if "employee" in q or "staff" in q:
        rows = SIMULATED_DB["employees"]
    elif "project" in q:
        rows = SIMULATED_DB["projects"]
    elif "metric" in q or "revenue" in q or "quarterly" in q:
        rows = SIMULATED_DB["quarterly_metrics"]
    else:
        rows = SIMULATED_DB["quarterly_metrics"]  # default

    # Respect LIMIT if present
    limit_match = re.search(r"limit\s+(\d+)", q)
    if limit_match:
        limit = int(limit_match.group(1))
        rows = rows[:limit]

    return json.dumps(rows, indent=2)


# ===========================================================================
# Tool 1: Researcher -- query_database
# ===========================================================================

async def _query_database(query: str) -> str:
    """Execute a database query (simulated). Protected by Agent Control."""
    return simulate_query(query)


# Mark as tool for step detection
_query_database.name = "query_database"           # type: ignore[attr-defined]
_query_database.tool_name = "query_database"       # type: ignore[attr-defined]

# Apply @control() decorator
_controlled_query_database = control()(_query_database)


@tool("query_database")
def query_database(query: str) -> str:
    """Query the research database. Input must be a SQL SELECT statement with a LIMIT clause.
    Dangerous operations (DROP, DELETE, TRUNCATE) are blocked.
    Access to sensitive tables (salary_data, admin_users) is denied.

    Args:
        query: A SQL SELECT query string.
    """
    print(f"\n  [Researcher] Executing query: {query[:80]}...")
    try:
        result = asyncio.run(_controlled_query_database(query=query))
        print("  [Researcher] Query succeeded.")
        return result
    except ControlViolationError as e:
        msg = f"BLOCKED by data-access-policy: {e.message}"
        print(f"  [Researcher] {msg}")
        return msg
    except RuntimeError as e:
        msg = f"ERROR: {e}"
        print(f"  [Researcher] {msg}")
        return msg


# ===========================================================================
# Tool 2: Analyst -- validate_data
# ===========================================================================

async def _validate_data(request: dict) -> str:
    """Validate and process research data. Protected by Agent Control.

    The request dict should contain:
      - dataset: str
      - findings: str
      - confidence_score: float (0-1)
      - methodology: str (optional, but will be steered if missing)
    """
    # If we reach here, controls passed -- produce analysis output
    return json.dumps({
        "status": "validated",
        "dataset": request.get("dataset"),
        "findings": request.get("findings"),
        "confidence_score": request.get("confidence_score"),
        "methodology": request.get("methodology", ""),
        "summary": (
            f"Analysis of '{request.get('dataset')}' confirms findings with "
            f"confidence {request.get('confidence_score')}. "
            f"Methodology: {request.get('methodology', 'N/A')}."
        ),
    }, indent=2)


_validate_data.name = "validate_data"             # type: ignore[attr-defined]
_validate_data.tool_name = "validate_data"         # type: ignore[attr-defined]

_controlled_validate_data = control()(_validate_data)


@tool("validate_data")
def validate_data(request_json: str) -> str:
    """Validate research data. Input must be a JSON string with fields:
    dataset (str), findings (str), confidence_score (float 0-1).
    A methodology field is recommended -- you will be asked to add one if missing.

    Args:
        request_json: JSON string with the analysis request.
    """
    try:
        request = json.loads(request_json)
    except json.JSONDecodeError:
        return "ERROR: Input must be valid JSON."

    print(f"\n  [Analyst] Validating data for dataset: {request.get('dataset', '?')}")

    max_attempts = 3
    current_request = dict(request)

    for attempt in range(1, max_attempts + 1):
        try:
            result = asyncio.run(_controlled_validate_data(request=current_request))
            print(f"  [Analyst] Validation passed (attempt {attempt}).")
            return result
        except ControlViolationError as e:
            msg = f"BLOCKED by analysis-validation-policy: {e.message}"
            print(f"  [Analyst] {msg}")
            return msg
        except ControlSteerError as e:
            print(f"  [Analyst] STEERED (attempt {attempt}): {e.message}")
            # Parse steering context for corrective instructions
            try:
                guidance = json.loads(e.steering_context)
            except (json.JSONDecodeError, TypeError):
                guidance = {"reason": e.steering_context}

            reason = guidance.get("reason", "Correction required")
            print(f"  [Analyst] Steering reason: {reason}")

            # Apply corrections
            retry_with = guidance.get("retry_with", {})
            for key, hint in retry_with.items():
                if key not in current_request or not current_request[key]:
                    # Auto-fill with a reasonable default
                    if key == "methodology":
                        current_request[key] = (
                            "Data collected via automated database queries. "
                            "Validated through cross-referencing multiple tables "
                            "and statistical confidence scoring."
                        )
                    else:
                        current_request[key] = hint
                    print(f"  [Analyst] Added missing field '{key}'.")
            continue

    return "ERROR: Failed to pass validation after max attempts."


# ===========================================================================
# Tool 3: Writer -- write_report
# ===========================================================================

async def _write_report(content: str, sources: str = "") -> str:
    """Generate a formatted report. Protected by Agent Control.

    The @control decorator sends the output to the server for PII checking.
    """
    # Build the report body
    report = f"""Research Report
{'=' * 40}

{content}
"""
    if sources:
        report += f"""
Sources:
{sources}
"""
    return report


_write_report.name = "write_report"               # type: ignore[attr-defined]
_write_report.tool_name = "write_report"           # type: ignore[attr-defined]

_controlled_write_report = control()(_write_report)


@tool("write_report")
def write_report(content: str) -> str:
    """Generate the final research report. The content should NOT contain
    PII (social security numbers, email addresses, phone numbers).
    Include a 'Sources:' section at the end for citations.

    Args:
        content: The report body text, including a Sources section.
    """
    # Split content and sources if the LLM included them together
    sources = ""
    for marker in ["Sources:", "References:", "Citations:"]:
        if marker in content:
            parts = content.split(marker, 1)
            content = parts[0].strip()
            sources = parts[1].strip()
            break

    print(f"\n  [Writer] Generating report ({len(content)} chars)...")

    max_attempts = 3
    current_content = content
    current_sources = sources

    for attempt in range(1, max_attempts + 1):
        try:
            result = asyncio.run(
                _controlled_write_report(content=current_content, sources=current_sources)
            )

            # Client-side citation check: steer if no sources section
            if not current_sources:
                print(f"  [Writer] STEERED (attempt {attempt}): Report lacks source citations.")
                current_sources = "Internal database queries (employees, projects, quarterly_metrics tables)"
                print("  [Writer] Added default citation sources.")
                # Re-run with sources added
                result = asyncio.run(
                    _controlled_write_report(content=current_content, sources=current_sources)
                )

            print(f"  [Writer] Report generated successfully (attempt {attempt}).")
            return result

        except ControlViolationError as e:
            msg = f"BLOCKED by content-safety-policy: {e.message}"
            print(f"  [Writer] {msg}")
            return msg

        except ControlSteerError as e:
            print(f"  [Writer] STEERED (attempt {attempt}): {e.message}")
            try:
                guidance = json.loads(e.steering_context)
            except (json.JSONDecodeError, TypeError):
                guidance = {"reason": e.steering_context}
            print(f"  [Writer] Steering reason: {guidance.get('reason', e.steering_context)}")
            continue

    return "ERROR: Failed to generate report after max attempts."


# ===========================================================================
# Scenario runner (direct tool calls -- avoids LLM costs for testing)
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

    # Define agents
    researcher = Agent(
        role="Research Data Analyst",
        goal="Query the database to gather employee and project data for analysis",
        backstory=(
            "You are a meticulous data researcher who queries databases to gather "
            "information. You always use proper SQL with LIMIT clauses and never "
            "attempt to access restricted tables."
        ),
        tools=[query_database],
        verbose=True,
    )

    analyst = Agent(
        role="Data Validation Analyst",
        goal="Validate the research data and produce a structured analysis with methodology",
        backstory=(
            "You are a rigorous analyst who validates data quality. You always "
            "include dataset name, findings, confidence scores, AND methodology "
            "in your analysis. You format your output as JSON."
        ),
        tools=[validate_data],
        verbose=True,
    )

    writer = Agent(
        role="Report Writer",
        goal="Generate a professional research report without any PII",
        backstory=(
            "You are a skilled report writer who creates clear, professional "
            "research reports. You NEVER include personal information like "
            "email addresses, phone numbers, or SSNs. You always cite sources."
        ),
        tools=[write_report],
        verbose=True,
    )

    # Define tasks
    research_task = Task(
        description=(
            "Query the employees and projects tables to gather data about "
            "engineering department staffing and active projects. "
            "Use the query_database tool with proper SQL SELECT statements "
            "that include LIMIT clauses."
        ),
        expected_output="Raw data from employee and project queries in JSON format",
        agent=researcher,
    )

    analysis_task = Task(
        description=(
            "Take the research data and validate it using the validate_data tool. "
            "Submit a JSON string with these fields: dataset, findings, "
            "confidence_score (0-1), and methodology. Example:\n"
            '{"dataset": "employees", "findings": "...", '
            '"confidence_score": 0.9, "methodology": "..."}'
        ),
        expected_output="Validated analysis with methodology in JSON format",
        agent=analyst,
    )

    report_task = Task(
        description=(
            "Write a professional research report using the write_report tool. "
            "The report should summarize the validated analysis findings. "
            "Do NOT include any email addresses, phone numbers, or SSNs. "
            "Include a 'Sources:' section at the end citing the data tables used."
        ),
        expected_output="A formatted research report with findings and source citations",
        agent=writer,
    )

    # Create and run crew
    crew = Crew(
        agents=[researcher, analyst, writer],
        tasks=[research_task, analysis_task, report_task],
        verbose=True,
    )

    print("\n  Running crew... (this uses LLM calls)\n")
    result = crew.kickoff()
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


if __name__ == "__main__":
    main()
