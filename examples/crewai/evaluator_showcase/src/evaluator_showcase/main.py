"""
CrewAI Data Analyst with All Four Built-in Evaluators.

Demonstrates every built-in Agent Control evaluator in a realistic
data-analyst scenario where a CrewAI crew queries databases and
generates reports:

  SQL   - Validates queries before execution (block DROP, enforce LIMIT)
  LIST  - Restricts access to sensitive tables (audit_log, salary_data)
  REGEX - Catches PII leaking through query results (SSN, emails)
  JSON  - Validates analysis requests (required fields, constraints)

PREREQUISITE:
    Run setup_controls.py first:

        $ uv run --active python setup_controls.py

    Then run this example:

        $ uv run --active evaluator_showcase

Scenarios:
    1. Safe SELECT query            -> SQL evaluator ALLOWS
    2. DROP TABLE injection         -> SQL evaluator DENIES
    3. Query without LIMIT          -> SQL evaluator DENIES
    4. Query sensitive table        -> LIST evaluator DENIES
    5. Query returns PII            -> REGEX evaluator DENIES (post-execution)
    6. Valid analysis request       -> JSON evaluator ALLOWS
    7. Missing required fields      -> JSON evaluator DENIES
    8. Missing purpose field        -> JSON evaluator STEERS (then allowed)
"""

import json
import os

import agent_control

from evaluator_showcase.tools import create_sql_tool, create_analysis_tool
from evaluator_showcase.crew import EvaluatorShowcaseCrew

# ── Configuration ───────────────────────────────────────────────────────
AGENT_NAME = "crewai-data-analyst"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_description="CrewAI data analyst with all evaluator types",
    server_url=SERVER_URL,
)


# ── Scenario Runner ─────────────────────────────────────────────────────

def verify_server():
    import httpx

    try:
        r = httpx.get(f"{SERVER_URL}/api/v1/controls?limit=100", timeout=5.0)
        r.raise_for_status()
        names = [c["name"] for c in r.json().get("controls", [])]
        required = [
            "sql-safety-check",
            "restrict-sensitive-tables",
            "pii-in-query-results",
            "validate-analysis-request",
            "steer-require-purpose",
        ]
        missing = [n for n in required if n not in names]
        if missing:
            print(f"Missing controls: {missing}")
            print("Run:  uv run --active python setup_controls.py")
            return False
        print(f"Server OK - {len(names)} controls active")
        return True
    except Exception as e:
        print(f"Cannot reach server at {SERVER_URL}: {e}")
        return False


def run_direct_test(title, evaluator, tool_fn, input_data, expected):
    """Run a test by calling the tool function directly (bypasses CrewAI LLM)."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"  Evaluator: {evaluator}")
    print(f"  Expected:  {expected}")
    print(f"{'=' * 60}")

    result = tool_fn.run(**input_data) if hasattr(tool_fn, 'run') else tool_fn(
        **input_data
    )
    print(f"\n  Result: {str(result)[:200]}")
    return result


def main():
    print("=" * 60)
    print("  CrewAI Data Analyst - Evaluator Showcase")
    print("  All 4 Built-in Evaluators: SQL, LIST, REGEX, JSON")
    print("=" * 60)
    print()

    if not verify_server():
        return

    if not os.getenv("OPENAI_API_KEY"):
        print("\nSet OPENAI_API_KEY to run the JSON/analysis scenarios.")
        print("SQL, LIST, and REGEX scenarios work without it.\n")

    sql_tool = create_sql_tool()
    analysis_tool = create_analysis_tool()

    # ════════════════════════════════════════════════════════════════
    #  SQL EVALUATOR SCENARIOS
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#" * 60)
    print("  PART 1: SQL EVALUATOR")
    print("  Validates queries before they reach the database")
    print("#" * 60)

    # 1a. Safe query
    run_direct_test(
        "1a. Safe SELECT with LIMIT",
        "SQL",
        sql_tool,
        {"query": "SELECT order_id, product, total FROM orders LIMIT 10"},
        "ALLOWED - safe read-only query with LIMIT",
    )

    # 1b. DROP TABLE injection
    run_direct_test(
        "1b. DROP TABLE Injection",
        "SQL",
        sql_tool,
        {"query": "DROP TABLE orders; SELECT * FROM users LIMIT 5"},
        "DENIED - DROP is a blocked operation + multi-statement",
    )

    # 1c. Missing LIMIT clause
    run_direct_test(
        "1c. SELECT Without LIMIT",
        "SQL",
        sql_tool,
        {"query": "SELECT * FROM orders"},
        "DENIED - require_limit is enforced",
    )

    # 1d. DELETE attempt
    run_direct_test(
        "1d. DELETE Attempt",
        "SQL",
        sql_tool,
        {"query": "DELETE FROM orders WHERE status = 'cancelled'"},
        "DENIED - DELETE is a blocked operation",
    )

    # ════════════════════════════════════════════════════════════════
    #  LIST EVALUATOR SCENARIOS
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#" * 60)
    print("  PART 2: LIST EVALUATOR")
    print("  Restricts access to sensitive tables")
    print("#" * 60)

    # 2a. Query allowed table
    run_direct_test(
        "2a. Query Public Table (orders)",
        "LIST",
        sql_tool,
        {"query": "SELECT * FROM orders LIMIT 10"},
        "ALLOWED - 'orders' is not in the restricted list",
    )

    # 2b. Query restricted table
    run_direct_test(
        "2b. Query Restricted Table (salary_data)",
        "LIST",
        sql_tool,
        {"query": "SELECT * FROM salary_data LIMIT 10"},
        "DENIED - 'salary_data' is in the restricted table list",
    )

    # 2c. Query another restricted table
    run_direct_test(
        "2c. Query Restricted Table (audit_log)",
        "LIST",
        sql_tool,
        {"query": "SELECT * FROM audit_log LIMIT 5"},
        "DENIED - 'audit_log' is in the restricted table list",
    )

    # ════════════════════════════════════════════════════════════════
    #  REGEX EVALUATOR SCENARIOS
    # ════════════════════════════════════════════════════════════════
    print("\n" + "#" * 60)
    print("  PART 3: REGEX EVALUATOR")
    print("  Scans query results for PII patterns (post-execution)")
    print("#" * 60)

    # 3a. Clean results
    run_direct_test(
        "3a. Query With Clean Results",
        "REGEX (POST)",
        sql_tool,
        {"query": "SELECT order_id, product, total FROM orders LIMIT 10"},
        "ALLOWED - results contain no PII patterns",
    )

    # 3b. Results contain PII (SSN, email)
    run_direct_test(
        "3b. Query Returns PII (SSN + Email)",
        "REGEX (POST)",
        sql_tool,
        {"query": "SELECT * FROM customers_full LIMIT 10"},
        "DENIED - SSN (123-45-6789) and email detected in results",
    )

    # ════════════════════════════════════════════════════════════════
    #  JSON EVALUATOR SCENARIOS
    # ════════════════════════════════════════════════════════════════
    if os.getenv("OPENAI_API_KEY"):
        print("\n" + "#" * 60)
        print("  PART 4: JSON EVALUATOR")
        print("  Validates analysis request structure and constraints")
        print("#" * 60)

        # 4a. Valid request
        run_direct_test(
            "4a. Valid Analysis Request (all fields present)",
            "JSON",
            analysis_tool,
            {
                "request": json.dumps(
                    {
                        "dataset": "sales_q4",
                        "date_range": "2024-10-01 to 2024-12-31",
                        "max_rows": 5000,
                        "purpose": "Quarterly revenue analysis for board meeting",
                    }
                )
            },
            "ALLOWED - all required fields present with valid constraints",
        )

        # 4b. Missing required field (date_range)
        run_direct_test(
            "4b. Missing Required Field (date_range)",
            "JSON",
            analysis_tool,
            {
                "request": json.dumps(
                    {
                        "dataset": "sales_q4",
                        "max_rows": 500,
                        "purpose": "Quick check",
                    }
                )
            },
            "DENIED - 'date_range' is a required field",
        )

        # 4c. max_rows exceeds constraint
        run_direct_test(
            "4c. Field Constraint Violation (max_rows > 10000)",
            "JSON",
            analysis_tool,
            {
                "request": json.dumps(
                    {
                        "dataset": "full_export",
                        "date_range": "2024-01-01 to 2024-12-31",
                        "max_rows": 50000,
                        "purpose": "Full year export",
                    }
                )
            },
            "DENIED - max_rows exceeds maximum of 10000",
        )

        # 4d. Missing purpose → STEER (then auto-fill and retry)
        run_direct_test(
            "4d. Missing Purpose -> STEER (auto-fill and retry)",
            "JSON (STEER)",
            analysis_tool,
            {
                "request": json.dumps(
                    {
                        "dataset": "inventory",
                        "date_range": "2024-11-01 to 2024-11-30",
                        "max_rows": 1000,
                    }
                )
            },
            "STEERED to collect purpose, then ALLOWED after auto-fill",
        )

    # ── Full CrewAI Crew Demo ───────────────────────────────────────
    if os.getenv("OPENAI_API_KEY"):
        print("\n" + "#" * 60)
        print("  PART 5: FULL CREWAI CREW")
        print("  Agent autonomously handles a multi-step data request")
        print("#" * 60)

        crew = EvaluatorShowcaseCrew().crew()

        print("\n  Running crew with a safe data request...")
        result = crew.kickoff(
            inputs={
                "request": (
                    "Query the orders table for the top 5 orders by total amount, "
                    "then analyze the sales_q4 dataset for the date range "
                    "2024-10-01 to 2024-12-31 with max 2000 rows. "
                    "The purpose is quarterly sales performance review."
                )
            }
        )
        print(f"\n  Crew Result: {str(result)[:300]}")

    # ── Summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Demo Complete!")
    print("=" * 60)
    print("""
  Evaluators Demonstrated:

    SQL EVALUATOR (input validation):
      - Blocked DROP TABLE injection          (destructive operation)
      - Blocked SELECT without LIMIT          (require_limit enforced)
      - Blocked DELETE statement               (blocked operation)
      - Allowed safe SELECT with LIMIT         (passed all checks)

    LIST EVALUATOR (access control):
      - Blocked query to salary_data           (restricted table)
      - Blocked query to audit_log             (restricted table)
      - Allowed query to orders                (not restricted)

    REGEX EVALUATOR (output scanning):
      - Blocked results with SSN + email       (PII detected post-execution)
      - Allowed clean results                  (no PII patterns found)

    JSON EVALUATOR (request validation):
      - Blocked missing required field         (date_range absent)
      - Blocked constraint violation           (max_rows > 10000)
      - Steered to collect missing purpose     (STEER action + retry)
      - Allowed valid complete request         (all fields valid)

  Key Insight:
    Each evaluator serves a different purpose:
      SQL   -> Structural query safety (BEFORE execution)
      LIST  -> Access control / allowlists / blocklists
      REGEX -> Pattern detection in free-text (AFTER execution)
      JSON  -> Schema validation with constraints
""")


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
