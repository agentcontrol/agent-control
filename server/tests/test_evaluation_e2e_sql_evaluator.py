"""End-to-end tests for SQL evaluator plugin."""

from agent_control_models import EvaluationRequest, Step
from fastapi.testclient import TestClient

from .utils import create_and_assign_policy

# =============================================================================
# Step Tests - Pre-check validation
# SQL queries in tool input, validated before execution
# =============================================================================


def test_sql_read_only_agent(client: TestClient):
    """Test read-only agent with LIMIT enforcement."""
    # Given: A control allowing only SELECT with LIMIT enforcement
    control_data = {
        "description": "Read-only agent with LIMIT",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.query"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "allowed_operations": ["SELECT"],
                "require_limit": True,
                "max_limit": 1000
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="ReadOnlyAgent"
    )

    # Case 1: SELECT with LIMIT 100 → Allowed
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users LIMIT 100"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: INSERT query → Denied (not in allowed_operations)
    req_insert = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "INSERT INTO users (name) VALUES ('test')"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_insert.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name

    # Case 3: SELECT without LIMIT → Denied (require_limit)
    req_no_limit = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_no_limit.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False

    # Case 4: SELECT with LIMIT 5000 → Denied (exceeds max_limit)
    req_high_limit = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users LIMIT 5000"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_high_limit.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False


def test_sql_multi_tenant_security(client: TestClient):
    """Test multi-tenant isolation with required tenant_id filtering."""
    # Given: A control requiring tenant_id in WHERE clause
    control_data = {
        "description": "Multi-tenant security",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.query"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "required_columns": ["tenant_id"],
                "column_context": "where"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="MultiTenantAgent"
    )

    # Case 1: SELECT with WHERE tenant_id = 123 → Allowed
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM orders WHERE tenant_id = 123"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: SELECT without tenant_id in WHERE → Denied
    req_no_tenant = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM orders WHERE status = 'active'"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_no_tenant.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name

    # Case 3: SELECT with tenant_id in SELECT but not WHERE → Denied
    req_select_only = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT tenant_id, name FROM orders"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_select_only.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False


def test_sql_block_destructive_operations(client: TestClient):
    """Test production safety - block dangerous operations."""
    # Given: A control blocking destructive operations
    control_data = {
        "description": "Block destructive operations",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.query"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "blocked_operations": ["DROP", "TRUNCATE", "DELETE"]
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="SafeAgent"
    )

    # Case 1: SELECT query → Allowed
    req_select = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_select.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: INSERT query → Allowed
    req_insert = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "INSERT INTO logs (message) VALUES ('test')"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_insert.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 3: DROP TABLE → Denied
    req_drop = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "DROP TABLE users"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_drop.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name

    # Case 4: DELETE FROM → Denied
    req_delete = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "DELETE FROM users WHERE id = 1"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_delete.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False

    # Case 5: TRUNCATE TABLE → Denied
    req_truncate = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "TRUNCATE TABLE logs"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_truncate.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False


def test_sql_table_restrictions(client: TestClient):
    """Test restricting access to specific tables (analytics use case)."""
    # Given: A control allowing only specific tables
    control_data = {
        "description": "Restrict to analytics tables",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.query"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "allowed_tables": ["users", "orders"]
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="AnalyticsAgent"
    )

    # Case 1: SELECT from users → Allowed
    req_users = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_users.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: SELECT from orders → Allowed
    req_orders = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM orders"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_orders.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 3: SELECT from admin_data → Denied
    req_admin = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM admin_data"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_admin.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name

    # Case 4: SELECT from sensitive_data → Denied
    req_sensitive = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM sensitive_data"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_sensitive.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False


def test_sql_multi_statement_blocking(client: TestClient):
    """Test preventing SQL injection via multi-statement queries."""
    # Given: A control blocking multi-statement queries
    control_data = {
        "description": "Block multi-statement queries",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.query"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "allow_multi_statements": False
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="SingleStatementAgent"
    )

    # Case 1: Single SELECT → Allowed
    req_single = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users WHERE id = 1"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_single.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: Multi-statement (SQL injection attempt) → Denied
    req_multi = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users; DROP TABLE users;"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_multi.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name


def test_sql_limit_enforcement(client: TestClient):
    """Test comprehensive LIMIT enforcement."""
    # Given: A control requiring LIMIT with max value
    control_data = {
        "description": "Enforce LIMIT clause",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.query"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "require_limit": True,
                "max_limit": 1000
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="LimitAgent"
    )

    # Case 1: SELECT with LIMIT 500 → Allowed
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users LIMIT 500"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: SELECT with LIMIT 1000 → Allowed (exact boundary)
    req_boundary = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users LIMIT 1000"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_boundary.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 3: SELECT with LIMIT 1001 → Denied (exceeds max)
    req_exceed = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users LIMIT 1001"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_exceed.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name

    # Case 4: SELECT without LIMIT → Denied (required)
    req_no_limit = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "SELECT * FROM users"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_no_limit.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False

    # Case 5: INSERT without LIMIT → Allowed (LIMIT only applies to SELECT)
    req_insert = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", 
            name="execute_sql",
            input={"query": "INSERT INTO users (name) VALUES ('test')"},
            output=None
        ),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_insert.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True


# =============================================================================
# Step Tests - Post-check validation
# SQL queries generated by LLM in output, validated after generation
# =============================================================================


def test_sql_llm_output_validation_read_only(client: TestClient):
    """Test validating LLM-generated SQL for read-only operations."""
    # Given: A control validating LLM output for read-only SQL
    control_data = {
        "description": "Validate LLM-generated SQL",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm_inference"], "stages": ["post"]},
        "selector": {"path": "output"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "allowed_operations": ["SELECT"],
                "require_limit": True
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="LlmReadOnlyAgent"
    )

    # Case 1: LLM outputs SELECT with LIMIT → Allowed
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Generate a query to get all users",
            output="SELECT * FROM users LIMIT 10"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: LLM outputs DELETE → Denied (not SELECT)
    req_delete = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Delete user with id 1",
            output="DELETE FROM users WHERE id = 1"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_delete.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name

    # Case 3: LLM outputs SELECT without LIMIT → Denied (missing LIMIT)
    req_no_limit = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Get all users",
            output="SELECT * FROM users"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_no_limit.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False


def test_sql_llm_output_multi_statement_blocking(client: TestClient):
    """Test preventing LLM from generating SQL injection patterns."""
    # Given: A control blocking multi-statement queries in LLM output
    control_data = {
        "description": "Block multi-statement in LLM output",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm_inference"], "stages": ["post"]},
        "selector": {"path": "output"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "allow_multi_statements": False
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="LlmSingleStatementAgent"
    )

    # Case 1: LLM outputs single statement → Allowed
    req_single = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Get user by id",
            output="SELECT * FROM users WHERE id = 1"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_single.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: LLM outputs multi-statement (injection pattern) → Denied
    req_multi = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Get users and drop table",
            output="SELECT * FROM users; DROP TABLE users;"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_multi.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name


def test_sql_llm_output_table_restrictions(client: TestClient):
    """Test restricting LLM-generated queries to specific tables."""
    # Given: A control restricting LLM to specific tables
    control_data = {
        "description": "Restrict LLM to analytics tables",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm_inference"], "stages": ["post"]},
        "selector": {"path": "output"},
        "evaluator": {
            "plugin": "sql",
            "config": {
                "allowed_tables": ["analytics", "reports"]
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(
        client, control_data, agent_name="LlmAnalyticsAgent"
    )

    # Case 1: LLM outputs query on analytics table → Allowed
    req_analytics = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Get analytics data",
            output="SELECT * FROM analytics WHERE date > '2024-01-01'"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_analytics.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 2: LLM outputs query on reports table → Allowed
    req_reports = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Get monthly reports",
            output="SELECT * FROM reports WHERE month = 'January'"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_reports.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is True

    # Case 3: LLM outputs query on users table → Denied (not in allowed_tables)
    req_users = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm_inference", name="test-step", 
            input="Get all users",
            output="SELECT * FROM users"
        ),
        stage="post"
    )
    resp = client.post("/api/v1/evaluation", json=req_users.model_dump(mode="json"))
    assert resp.status_code == 200
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name
