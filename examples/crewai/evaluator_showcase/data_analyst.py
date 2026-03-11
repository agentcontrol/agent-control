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

        $ uv run python setup_controls.py

    Then run this example:

        $ uv run python data_analyst.py

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

import asyncio
import json
import os

import agent_control
from agent_control import ControlSteerError, ControlViolationError, control
from crewai import Agent, Crew, LLM, Task
from crewai.tools import tool

# ── Configuration ───────────────────────────────────────────────────────
AGENT_NAME = "crewai-data-analyst"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_description="CrewAI data analyst with all evaluator types",
    server_url=SERVER_URL,
)


# ── Simulated Database ──────────────────────────────────────────────────
# In a real app these would hit an actual database. The simulated responses
# let us demonstrate how Agent Control inspects both input AND output.

SIMULATED_RESULTS = {
    "safe": (
        "| order_id | product   | total  |\n"
        "|----------|-----------|--------|\n"
        "| 1001     | Widget A  | 29.99  |\n"
        "| 1002     | Widget B  | 49.99  |\n"
        "| 1003     | Gadget X  | 149.99 |\n"
        "\n3 rows returned."
    ),
    "pii": (
        "| customer_id | name       | ssn         | email              |\n"
        "|-------------|------------|-------------|--------------------|  \n"
        "| C-101       | John Smith | 123-45-6789 | john@example.com   |\n"
        "| C-102       | Jane Doe   | 987-65-4321 | jane@example.com   |\n"
        "\n2 rows returned."
    ),
}


# ── Tool 1: SQL Query Runner ────────────────────────────────────────────

def create_sql_tool():
    """Build the SQL query tool with @control protection."""

    async def _run_sql_query(query: str) -> str:
        """Execute a SQL query against the database (protected)."""
        # Simulate: if query touches customers_full, return PII results
        if "customers_full" in query.lower():
            return SIMULATED_RESULTS["pii"]
        return SIMULATED_RESULTS["safe"]

    _run_sql_query.name = "run_sql_query"  # type: ignore[attr-defined]
    _run_sql_query.tool_name = "run_sql_query"  # type: ignore[attr-defined]
    controlled_fn = control()(_run_sql_query)

    @tool("run_sql_query")
    def run_sql_query_tool(query: str) -> str:
        """Run a SQL query against the company database.

        Args:
            query: The SQL query to execute
        """
        if isinstance(query, dict):
            query = query.get("query", str(query))

        print(f"\n  [SQL TOOL] Query: {query[:80]}...")

        try:
            result = asyncio.run(controlled_fn(query=query))
            print(f"  [SQL TOOL] Query executed successfully")
            return result

        except ControlViolationError as e:
            print(f"  [SQL TOOL] BLOCKED by {e.control_name}: {e.message[:100]}")
            return f"QUERY BLOCKED: {e.message}"

        except Exception as e:
            print(f"  [SQL TOOL] Error: {e}")
            return f"Query error: {e}"

    return run_sql_query_tool


# ── Tool 2: Data Analyzer ───────────────────────────────────────────────

def create_analysis_tool():
    """Build the analysis tool with JSON validation and steering."""

    llm = LLM(model="gpt-4o-mini", temperature=0.3)

    async def _analyze_data(request: dict) -> str:
        """Run data analysis (protected by JSON validation controls).

        Takes a single dict param so the @control() decorator sends it
        as input.request — and the JSON evaluator can check which fields
        are present or absent.
        """
        dataset = request.get("dataset", "")
        date_range = request.get("date_range", "")
        max_rows = request.get("max_rows", 1000)
        purpose = request.get("purpose", "")

        prompt = f"""Summarize this data analysis in 2-3 sentences:
- Dataset: {dataset}
- Date range: {date_range}
- Max rows: {max_rows}
- Purpose: {purpose}

Provide a brief, professional analysis summary."""

        return llm.call([{"role": "user", "content": prompt}])

    _analyze_data.name = "analyze_data"  # type: ignore[attr-defined]
    _analyze_data.tool_name = "analyze_data"  # type: ignore[attr-defined]
    controlled_fn = control()(_analyze_data)

    @tool("analyze_data")
    def analyze_data_tool(request: str) -> str:
        """Analyze a dataset with validation controls.

        Args:
            request: JSON string with fields: dataset (required), date_range (required),
                max_rows (optional, 1-10000), purpose (recommended for audit compliance)
        """
        if isinstance(request, dict):
            params = request
        else:
            try:
                params = json.loads(request)
            except (json.JSONDecodeError, TypeError):
                return f"Invalid request format. Expected JSON, got: {request!r}"

        # Build the request dict — only include fields that have values.
        # The JSON evaluator checks which fields are PRESENT in this dict,
        # so omitting a field triggers the "required_fields" check.
        request_dict: dict = {}
        if params.get("dataset"):
            request_dict["dataset"] = params["dataset"]
        if params.get("date_range"):
            request_dict["date_range"] = params["date_range"]
        if params.get("max_rows") is not None:
            request_dict["max_rows"] = int(params["max_rows"])
        if params.get("purpose"):
            request_dict["purpose"] = params["purpose"]

        print(f"\n  [ANALYSIS TOOL] Request: {request_dict}")

        # Steering retry loop
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                result = asyncio.run(controlled_fn(request=request_dict))
                print(f"  [ANALYSIS TOOL] Analysis complete")
                return result

            except ControlViolationError as e:
                print(f"  [ANALYSIS TOOL] BLOCKED by {e.control_name}: {e.message[:100]}")
                return f"ANALYSIS BLOCKED: {e.message}"

            except ControlSteerError as e:
                print(f"  [ANALYSIS TOOL] STEERED by {e.control_name}")
                try:
                    guidance = json.loads(e.steering_context)
                except (json.JSONDecodeError, TypeError):
                    guidance = {}

                reason = guidance.get("reason", "Correction needed")
                actions = guidance.get("required_actions", [])
                print(f"    Reason: {reason}")
                print(f"    Actions: {actions}")

                if "collect_purpose" in actions:
                    auto_purpose = f"Quarterly {request_dict.get('dataset', 'data')} analysis for business reporting"
                    request_dict["purpose"] = auto_purpose
                    print(f"    Auto-filled purpose: {auto_purpose}")

                continue

        return "ANALYSIS FAILED: Could not satisfy all controls."

    return analyze_data_tool


# ── CrewAI Crew ─────────────────────────────────────────────────────────

def create_analyst_crew(sql_tool, analysis_tool):
    analyst = Agent(
        role="Data Analyst",
        goal="Execute data queries and analysis while respecting all data governance controls",
        backstory=(
            "You are a data analyst at a company with strict data governance policies. "
            "You use run_sql_query to query the database and analyze_data for analysis. "
            "You always comply with security controls and never attempt to bypass them."
        ),
        tools=[sql_tool, analysis_tool],
        verbose=True,
    )

    task = Task(
        description=(
            "Execute this data request: {request}\n\n"
            "Use the appropriate tool and report the outcome."
        ),
        expected_output="Query results or analysis, or an explanation if blocked by controls",
        agent=analyst,
    )

    return Crew(agents=[analyst], tasks=[task], verbose=True)


# ── Scenario Runner ─────────────────────────────────────────────────────

def verify_server():
    import httpx

    try:
        r = httpx.get(f"{SERVER_URL}/api/v1/controls", timeout=5.0)
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
            print("Run:  uv run python setup_controls.py")
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

        crew = create_analyst_crew(sql_tool, analysis_tool)

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


if __name__ == "__main__":
    main()
