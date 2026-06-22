"""SQL query tool with @control protection."""

import asyncio

from agent_control import ControlViolationError, control
from crewai.tools import tool


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
