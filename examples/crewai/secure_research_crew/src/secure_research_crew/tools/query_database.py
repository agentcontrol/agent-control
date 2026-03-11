"""Researcher tool: query_database -- queries a simulated database with Agent Control protection."""

import asyncio
import json
import re

from agent_control import ControlViolationError, control
from crewai.tools import tool

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


# ---------------------------------------------------------------------------
# Async inner function + @control() decorator
# ---------------------------------------------------------------------------

async def _query_database(query: str) -> str:
    """Execute a database query (simulated). Protected by Agent Control."""
    return simulate_query(query)


# Mark as tool for step detection
_query_database.name = "query_database"           # type: ignore[attr-defined]
_query_database.tool_name = "query_database"       # type: ignore[attr-defined]

# Apply @control() decorator
_controlled_query_database = control()(_query_database)


# ---------------------------------------------------------------------------
# CrewAI @tool wrapper
# ---------------------------------------------------------------------------

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
