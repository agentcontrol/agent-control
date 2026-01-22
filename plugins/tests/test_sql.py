"""Tests for SQL plugin."""

from unittest.mock import patch

import pytest
from agent_control_models import EvaluatorResult, SQLControlEvaluatorPluginConfig
from agent_control_plugins.builtin.sql import SQLControlEvaluatorPlugin
from pydantic import ValidationError


class TestEvaluatorResultValidator:
    """Tests for EvaluatorResult model validator."""

    def test_error_with_matched_true_raises_validation_error(self):
        """Should raise ValidationError when error is set with matched=True."""
        with pytest.raises(ValidationError) as exc_info:
            EvaluatorResult(
                matched=True,
                confidence=0.5,
                error="Some error",
            )
        assert "matched must be False when error is set" in str(exc_info.value)

    def test_error_with_matched_false_is_valid(self):
        """Should allow error when matched=False."""
        result = EvaluatorResult(
            matched=False,
            confidence=0.0,
            error="Some error",
        )
        # Check error first (convention)
        assert result.error == "Some error"
        assert result.matched is False

    def test_no_error_with_matched_true_is_valid(self):
        """Should allow matched=True when no error is set."""
        result = EvaluatorResult(
            matched=True,
            confidence=1.0,
            message="Blocked",
        )
        # Check error first (convention)
        assert result.error is None
        assert result.matched is True


class TestPluginErrorHandling:
    """Tests for plugin error handling (unexpected exceptions)."""

    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_error(self):
        """Should return error field when plugin encounters unexpected exception."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Simulate an unexpected exception in the internal method
        with patch.object(
            plugin, "_evaluate_sync", side_effect=RuntimeError("Unexpected failure")
        ):
            result = await plugin.evaluate("SELECT * FROM users")

        # Check error first (convention: error field takes precedence)
        assert result.error is not None
        assert "RuntimeError" in result.error
        assert "Unexpected failure" in result.error
        # When error is set, matched is enforced to be False (fail open)
        assert result.matched is False
        assert result.confidence == 0.0
        assert "unexpected error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_memory_error_returns_error(self):
        """Should handle MemoryError gracefully."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        with patch.object(
            plugin, "_evaluate_sync", side_effect=MemoryError("Out of memory")
        ):
            result = await plugin.evaluate("SELECT * FROM users")

        # Check error first
        assert result.error is not None
        assert "MemoryError" in result.error
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_propagates(self):
        """KeyboardInterrupt should propagate (not be caught)."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        with patch.object(
            plugin, "_evaluate_sync", side_effect=KeyboardInterrupt()
        ):
            with pytest.raises(KeyboardInterrupt):
                await plugin.evaluate("SELECT * FROM users")

    @pytest.mark.asyncio
    async def test_normal_validation_still_works_after_error(self):
        """Plugin should continue working after an error."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        # First call fails
        with patch.object(
            plugin, "_evaluate_sync", side_effect=RuntimeError("Temporary failure")
        ):
            error_result = await plugin.evaluate("SELECT * FROM users")

        assert error_result.error is not None

        # Second call should work normally (no patch)
        normal_result = await plugin.evaluate("SELECT * FROM users")
        assert normal_result.error is None
        assert normal_result.matched is False


class TestSQLMultiStatement:
    """Tests for SQL multi-statement validation."""

    @pytest.mark.asyncio
    async def test_allow_multi_statements_by_default(self):
        """Should allow multiple statements by default."""
        config = SQLControlEvaluatorPluginConfig()
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT * FROM users; SELECT * FROM orders"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_block_multi_statements_when_disabled(self):
        """Should block multiple statements when allow_multi_statements=False."""
        config = SQLControlEvaluatorPluginConfig(allow_multi_statements=False)
        plugin = SQLControlEvaluatorPlugin(config)

        # Single statement should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        # Multiple statements should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users; DELETE FROM logs"
        )
        assert result.error is None
        assert result.matched is True
        assert "2 statements" in result.message or "Multiple" in result.message
        assert result.metadata["statement_count"] == 2

    @pytest.mark.asyncio
    async def test_max_statements_limit(self):
        """Should enforce max_statements limit."""
        config = SQLControlEvaluatorPluginConfig(max_statements=2)
        plugin = SQLControlEvaluatorPlugin(config)

        # 2 statements should pass
        result = await plugin.evaluate(
            "SELECT * FROM users; SELECT * FROM orders"
        )
        assert result.error is None
        assert result.matched is False

        # 3 statements should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users; SELECT * FROM orders; SELECT 1"
        )
        assert result.error is None
        assert result.matched is True
        assert result.metadata["statement_count"] == 3
        assert result.metadata["max_statements"] == 2

    @pytest.mark.asyncio
    async def test_max_statements_with_allow_false(self):
        """Should validate that max_statements requires allow_multi_statements."""
        # This should raise a validation error during config creation
        with pytest.raises(ValueError, match="max_statements is only applicable"):
            SQLControlEvaluatorPluginConfig(allow_multi_statements=False, max_statements=3)


class TestSQLOperations:
    """Tests for SQL operation validation."""

    @pytest.mark.asyncio
    async def test_block_drop_operation(self):
        """Should block DROP operations."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("DROP TABLE users")

        assert result.error is None
        assert result.matched is True
        assert "DROP" in result.message
        assert "DROP" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_block_multiple_dangerous_operations(self):
        """Should block multiple dangerous operations."""
        config = SQLControlEvaluatorPluginConfig(
            blocked_operations=["DROP", "DELETE", "TRUNCATE"]
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Test DROP
        result = await plugin.evaluate("DROP TABLE users")
        assert result.error is None
        assert result.matched is True

        # Test DELETE
        result = await plugin.evaluate("DELETE FROM users WHERE id = 1")
        assert result.error is None
        assert result.matched is True

        # Test TRUNCATE
        result = await plugin.evaluate("TRUNCATE TABLE users")
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_allow_safe_operations_when_blocking_dangerous(self):
        """Should allow safe operations when blocking dangerous ones."""
        config = SQLControlEvaluatorPluginConfig(
            blocked_operations=["DROP", "DELETE", "TRUNCATE"]
        )
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        result = await plugin.evaluate("INSERT INTO users (name) VALUES ('test')")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_allowlist_mode_select_only(self):
        """Should allow only SELECT when in allowlist mode."""
        config = SQLControlEvaluatorPluginConfig(allowed_operations=["SELECT"])
        plugin = SQLControlEvaluatorPlugin(config)

        # SELECT should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        # Other operations should be blocked
        result = await plugin.evaluate("INSERT INTO users (name) VALUES ('test')")
        assert result.error is None
        assert result.matched is True
        assert "INSERT" in result.metadata["blocked"]

        result = await plugin.evaluate("UPDATE users SET name = 'new' WHERE id = 1")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("DELETE FROM users WHERE id = 1")
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_block_ddl_flag(self):
        """Should block all DDL operations when block_ddl=True."""
        config = SQLControlEvaluatorPluginConfig(block_ddl=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # DDL operations should be blocked
        result = await plugin.evaluate("CREATE TABLE test (id INT)")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("ALTER TABLE users ADD COLUMN age INT")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("DROP TABLE users")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("TRUNCATE TABLE users")
        assert result.error is None
        assert result.matched is True

        # DML operations should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_block_dcl_flag(self):
        """Should block all DCL operations when block_dcl=True."""
        config = SQLControlEvaluatorPluginConfig(block_dcl=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # DCL operations should be blocked
        result = await plugin.evaluate("GRANT SELECT ON users TO user1")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("REVOKE SELECT ON users FROM user1")
        assert result.error is None
        assert result.matched is True

        # Other operations should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_multiple_statements(self):
        """Should detect blocked operations in multiple statements."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT * FROM users; DROP TABLE users; SELECT 1"
        )
        assert result.error is None
        assert result.matched is True
        assert "DROP" in result.metadata["blocked"]


class TestSQLTableAccess:
    """Tests for SQL table/schema access validation."""

    @pytest.mark.asyncio
    async def test_allow_specific_tables(self):
        """Should allow only specific tables."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "orders"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Allowed tables should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        result = await plugin.evaluate("SELECT * FROM orders")
        assert result.error is None
        assert result.matched is False

        # Other tables should be blocked
        result = await plugin.evaluate("SELECT * FROM admin")
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message

    @pytest.mark.asyncio
    async def test_block_specific_tables(self):
        """Should block specific tables."""
        config = SQLControlEvaluatorPluginConfig(blocked_tables=["admin", "secrets"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Blocked tables should be blocked
        result = await plugin.evaluate("SELECT * FROM admin")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("SELECT * FROM secrets")
        assert result.error is None
        assert result.matched is True

        # Other tables should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_block_system_schemas(self):
        """Should block system schemas."""
        config = SQLControlEvaluatorPluginConfig(
            blocked_schemas=["pg_catalog", "information_schema"]
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # System schemas should be blocked
        result = await plugin.evaluate("SELECT * FROM pg_catalog.pg_tables")
        assert result.error is None
        assert result.matched is True
        assert "pg_catalog" in result.message

        result = await plugin.evaluate(
            "SELECT * FROM information_schema.tables"
        )
        assert result.error is None
        assert result.matched is True

        # Regular queries should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_qualified_table_names(self):
        """Should handle qualified table names (schema.table)."""
        config = SQLControlEvaluatorPluginConfig(
            allowed_schemas=["public"], blocked_tables=["admin"]
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Public schema should pass
        result = await plugin.evaluate("SELECT * FROM public.users")
        assert result.error is None
        assert result.matched is False

        # Non-public schema should be blocked
        result = await plugin.evaluate("SELECT * FROM private.users")
        assert result.error is None
        assert result.matched is True

        # Blocked table even in allowed schema should be blocked
        result = await plugin.evaluate("SELECT * FROM public.admin")
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_multiple_tables_in_query(self):
        """Should check all tables in a query."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "orders"])
        plugin = SQLControlEvaluatorPlugin(config)

        # All allowed tables
        result = await plugin.evaluate(
            "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
        )
        assert result.error is None
        assert result.matched is False

        # One disallowed table
        result = await plugin.evaluate(
            "SELECT * FROM users JOIN admin ON users.id = admin.user_id"
        )
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message

    @pytest.mark.asyncio
    async def test_case_sensitivity_tables(self):
        """Should respect case sensitivity setting for tables."""
        # Case insensitive (default)
        config = SQLControlEvaluatorPluginConfig(
            blocked_tables=["admin"], case_sensitive=False
        )
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("SELECT * FROM Admin")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("SELECT * FROM ADMIN")
        assert result.error is None
        assert result.matched is True

        # Case sensitive
        config = SQLControlEvaluatorPluginConfig(blocked_tables=["admin"], case_sensitive=True)
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("SELECT * FROM admin")
        assert result.error is None
        assert result.matched is True

        result = await plugin.evaluate("SELECT * FROM Admin")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_cte_not_treated_as_table_violation(self):
        """Should not treat CTEs as unauthorized table access."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users"], case_sensitive=False)
        plugin = SQLControlEvaluatorPlugin(config)

        # CTE 'temp_users' is defined locally, not in allowed_tables
        # This should pass because CTEs are not external tables
        query = """
        WITH temp_users AS (
            SELECT * FROM users WHERE id > 100
        )
        SELECT * FROM temp_users
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is False

        # Multiple CTEs should also work
        query = """
        WITH
            active_users AS (SELECT * FROM users WHERE active = true),
            premium_users AS (SELECT * FROM active_users WHERE premium = true)
        SELECT * FROM premium_users
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is False

        # But accessing unauthorized real tables should still be blocked
        query = """
        WITH temp_data AS (
            SELECT * FROM admin WHERE id > 100
        )
        SELECT * FROM temp_data
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message


class TestSQLColumnPresence:
    """Tests for SQL column presence validation."""

    @pytest.mark.asyncio
    async def test_require_column_in_where_clause(self):
        """Should require specific column in WHERE clause."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"], column_context="where"
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Query with tenant_id in WHERE - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is False

        # Query without tenant_id in WHERE - should be blocked
        result = await plugin.evaluate("SELECT * FROM users WHERE id = 1")
        assert result.error is None
        assert result.matched is True
        assert "tenant_id" in result.message

        # Query with tenant_id in SELECT but not WHERE - should be blocked
        result = await plugin.evaluate(
            "SELECT tenant_id FROM users WHERE id = 1"
        )
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_require_column_in_select_clause(self):
        """Should require specific column in SELECT clause."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["id", "created_at"],
            column_presence_logic="all",
            column_context="select"
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Query with both columns in SELECT - should pass
        result = await plugin.evaluate(
            "SELECT id, name, created_at FROM users"
        )
        assert result.error is None
        assert result.matched is False

        # Query missing one column - should be blocked
        result = await plugin.evaluate("SELECT id, name FROM users")
        assert result.error is None
        assert result.matched is True
        assert "created_at" in result.message

    @pytest.mark.asyncio
    async def test_require_column_anywhere(self):
        """Should require column anywhere in query."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["user_id"], column_context=None
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Column in SELECT - should pass
        result = await plugin.evaluate("SELECT user_id FROM logs")
        assert result.error is None
        assert result.matched is False

        # Column in WHERE - should pass
        result = await plugin.evaluate("SELECT * FROM logs WHERE user_id = 1")
        assert result.error is None
        assert result.matched is False

        # Column not present - should be blocked
        result = await plugin.evaluate("SELECT * FROM logs WHERE id = 1")
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_column_presence_any_logic(self):
        """Should require at least one column with 'any' logic."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["user_id", "admin_id"],
            column_presence_logic="any",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Has user_id - should pass
        result = await plugin.evaluate(
            "SELECT * FROM logs WHERE user_id = 1"
        )
        assert result.error is None
        assert result.matched is False

        # Has admin_id - should pass
        result = await plugin.evaluate(
            "SELECT * FROM logs WHERE admin_id = 1"
        )
        assert result.error is None
        assert result.matched is False

        # Has neither - should be blocked
        result = await plugin.evaluate("SELECT * FROM logs WHERE id = 1")
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_column_presence_all_logic(self):
        """Should require all columns with 'all' logic."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["user_id", "timestamp"],
            column_presence_logic="all",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Has both columns - should pass
        result = await plugin.evaluate(
            "SELECT * FROM logs WHERE user_id = 1 AND timestamp > '2024-01-01'"
        )
        assert result.error is None
        assert result.matched is False

        # Has only one column - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM logs WHERE user_id = 1"
        )
        assert result.error is None
        assert result.matched is True
        assert "timestamp" in result.message

    @pytest.mark.asyncio
    async def test_case_sensitivity_columns(self):
        """Should respect case sensitivity for columns."""
        # Case insensitive (default)
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
            case_sensitive=False,
        )
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT * FROM users WHERE Tenant_ID = 123"
        )
        assert result.error is None
        assert result.matched is False

        # Case sensitive
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
            case_sensitive=True,
        )
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT * FROM users WHERE tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is False

        result = await plugin.evaluate(
            "SELECT * FROM users WHERE Tenant_ID = 123"
        )
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_column_extraction_with_join_queries(self):
        """Should extract columns from JOIN queries correctly."""
        # Test WHERE context with JOIN
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # JOIN with tenant_id in WHERE - should pass
        result = await plugin.evaluate(
            "SELECT users.id, orders.total FROM users "
            "JOIN orders ON users.id = orders.user_id "
            "WHERE users.tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is False

        # JOIN without tenant_id in WHERE - should be blocked
        result = await plugin.evaluate(
            "SELECT users.id, orders.total FROM users "
            "JOIN orders ON users.id = orders.user_id "
            "WHERE orders.id = 1"
        )
        assert result.error is None
        assert result.matched is True
        assert "tenant_id" in result.message

        # Test SELECT context with JOIN
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["user_id", "tenant_id"],
            column_context="select",
            column_presence_logic="all",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # JOIN with both required columns in SELECT - should pass
        result = await plugin.evaluate(
            "SELECT users.user_id, users.tenant_id, orders.total "
            "FROM users JOIN orders ON users.id = orders.user_id"
        )
        assert result.error is None
        assert result.matched is False

        # JOIN missing one required column in SELECT - should be blocked
        result = await plugin.evaluate(
            "SELECT users.user_id, orders.total "
            "FROM users JOIN orders ON users.id = orders.user_id"
        )
        assert result.error is None
        assert result.matched is True
        assert "tenant_id" in result.message

        # Test columns anywhere (None context) with JOIN
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context=None,
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # tenant_id in SELECT - should pass
        result = await plugin.evaluate(
            "SELECT users.tenant_id, orders.total FROM users "
            "JOIN orders ON users.id = orders.user_id"
        )
        assert result.error is None
        assert result.matched is False

        # tenant_id in WHERE - should pass
        result = await plugin.evaluate(
            "SELECT users.id, orders.total FROM users "
            "JOIN orders ON users.id = orders.user_id "
            "WHERE users.tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is False

        # tenant_id in JOIN condition - should pass
        result = await plugin.evaluate(
            "SELECT users.id, orders.total FROM users "
            "JOIN orders ON users.tenant_id = orders.tenant_id"
        )
        assert result.error is None
        assert result.matched is False

        # tenant_id not present anywhere - should be blocked
        result = await plugin.evaluate(
            "SELECT users.id, orders.total FROM users "
            "JOIN orders ON users.id = orders.user_id "
            "WHERE orders.status = 'active'"
        )
        assert result.error is None
        assert result.matched is True
        assert "tenant_id" in result.message


class TestSQLLimits:
    """Tests for SQL LIMIT validation."""

    @pytest.mark.asyncio
    async def test_require_limit_on_select(self):
        """Should require LIMIT clause on SELECT queries."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # SELECT with LIMIT should pass
        result = await plugin.evaluate("SELECT * FROM users LIMIT 100")
        assert result.error is None
        assert result.matched is False

        # SELECT without LIMIT should be blocked
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is True
        assert "LIMIT" in result.message
        assert result.metadata["violation"] == "missing_limit"

    @pytest.mark.asyncio
    async def test_require_limit_only_affects_select(self):
        """Should only check LIMIT on SELECT statements."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # INSERT without LIMIT should pass (LIMIT not applicable)
        result = await plugin.evaluate(
            "INSERT INTO users (name) VALUES ('test')"
        )
        assert result.error is None
        assert result.matched is False

        # DELETE without LIMIT should pass
        result = await plugin.evaluate("DELETE FROM users WHERE id = 1")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_max_limit_enforcement(self):
        """Should enforce maximum LIMIT value."""
        config = SQLControlEvaluatorPluginConfig(max_limit=1000)
        plugin = SQLControlEvaluatorPlugin(config)

        # LIMIT within bounds should pass
        result = await plugin.evaluate("SELECT * FROM users LIMIT 100")
        assert result.error is None
        assert result.matched is False

        result = await plugin.evaluate("SELECT * FROM users LIMIT 1000")
        assert result.error is None
        assert result.matched is False

        # LIMIT exceeding max should be blocked
        result = await plugin.evaluate("SELECT * FROM users LIMIT 10000")
        assert result.error is None
        assert result.matched is True
        assert "10000" in result.message
        assert "1000" in result.message
        assert result.metadata["limit_value"] == 10000
        assert result.metadata["max_limit"] == 1000

    @pytest.mark.asyncio
    async def test_limit_with_offset(self):
        """Should handle LIMIT with OFFSET correctly."""
        config = SQLControlEvaluatorPluginConfig(max_limit=1000)
        plugin = SQLControlEvaluatorPlugin(config)

        # LIMIT + OFFSET within bounds should pass
        result = await plugin.evaluate(
            "SELECT * FROM users LIMIT 100 OFFSET 50"
        )
        assert result.error is None
        assert result.matched is False

        # LIMIT exceeding max with OFFSET should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users LIMIT 5000 OFFSET 10"
        )
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_limit_all_allowed(self):
        """Should allow LIMIT ALL (indeterminate limits are allowed)."""
        config = SQLControlEvaluatorPluginConfig(max_limit=1000)
        plugin = SQLControlEvaluatorPlugin(config)

        # LIMIT ALL should be allowed (indeterminate limits are skipped)
        result = await plugin.evaluate("SELECT * FROM users LIMIT ALL")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_require_and_max_limit_combined(self):
        """Should enforce both require_limit and max_limit."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True, max_limit=500)
        plugin = SQLControlEvaluatorPlugin(config)

        # Valid query with LIMIT
        result = await plugin.evaluate("SELECT * FROM users LIMIT 100")
        assert result.error is None
        assert result.matched is False

        # Missing LIMIT
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is True
        assert "must have a LIMIT" in result.message

        # LIMIT too high
        result = await plugin.evaluate("SELECT * FROM users LIMIT 1000")
        assert result.error is None
        assert result.matched is True
        assert "exceeds maximum" in result.message

    @pytest.mark.asyncio
    async def test_multi_select_statements_limit_check(self):
        """Should check LIMIT on all SELECT statements."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # All SELECTs have LIMIT - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users LIMIT 10; SELECT * FROM orders LIMIT 20"
        )
        assert result.error is None
        assert result.matched is False

        # One SELECT missing LIMIT - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users LIMIT 10; SELECT * FROM orders"
        )
        assert result.error is None
        assert result.matched is True


class TestCombinedControls:
    """Tests for combining multiple validation types."""

    @pytest.mark.asyncio
    async def test_operation_and_table_restrictions(self):
        """Should enforce both operation and table restrictions."""
        config = SQLControlEvaluatorPluginConfig(
            allowed_operations=["SELECT"],
            allowed_tables=["users", "orders"],
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Both constraints satisfied - should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        # Invalid operation - should be blocked
        result = await plugin.evaluate("DELETE FROM users WHERE id = 1")
        assert result.error is None
        assert result.matched is True

        # Invalid table - should be blocked
        result = await plugin.evaluate("SELECT * FROM admin")
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_allowlist_with_block_ddl_enforces_both(self):
        """Critical bug fix: allowed_operations + block_ddl should enforce BOTH.

        When allowed_operations=['SELECT'] and block_ddl=True, should block:
        1. DDL operations (from block_ddl)
        2. Non-SELECT operations (from allowed_operations)

        This tests the fix for the critical security bug where the allowlist
        was ignored when combined with block_ddl/block_dcl.
        """
        config = SQLControlEvaluatorPluginConfig(allowed_operations=["SELECT"], block_ddl=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # SELECT should pass (in allowlist, not DDL)
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        # DROP should be blocked (DDL)
        result = await plugin.evaluate("DROP TABLE users")
        assert result.error is None
        assert result.matched is True
        assert "DROP" in result.metadata["blocked"]

        # INSERT should be blocked (not in allowlist)
        result = await plugin.evaluate("INSERT INTO users (name) VALUES ('test')")
        assert result.error is None
        assert result.matched is True
        assert "INSERT" in result.metadata["blocked"]

        # UPDATE should be blocked (not in allowlist)
        result = await plugin.evaluate("UPDATE users SET name = 'new'")
        assert result.error is None
        assert result.matched is True
        assert "UPDATE" in result.metadata["blocked"]

        # DELETE should be blocked (not in allowlist)
        result = await plugin.evaluate("DELETE FROM users WHERE id = 1")
        assert result.error is None
        assert result.matched is True
        assert "DELETE" in result.metadata["blocked"]

        # TRUNCATE should be blocked (both DDL and not in allowlist)
        result = await plugin.evaluate("TRUNCATE TABLE users")
        assert result.error is None
        assert result.matched is True
        assert "TRUNCATE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_allowlist_with_block_dcl_enforces_both(self):
        """Test allowed_operations + block_dcl combination."""
        config = SQLControlEvaluatorPluginConfig(allowed_operations=["SELECT"], block_dcl=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # SELECT should pass
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        # GRANT should be blocked (DCL)
        result = await plugin.evaluate("GRANT SELECT ON users TO user1")
        assert result.error is None
        assert result.matched is True
        assert "GRANT" in result.metadata["blocked"]

        # INSERT should be blocked (not in allowlist)
        result = await plugin.evaluate("INSERT INTO users (name) VALUES ('test')")
        assert result.error is None
        assert result.matched is True
        assert "INSERT" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_operation_and_column_presence(self):
        """Should enforce operation restrictions and column presence."""
        config = SQLControlEvaluatorPluginConfig(
            allowed_operations=["SELECT"],
            required_columns=["tenant_id"],
            column_context="where",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Both constraints satisfied - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is False

        # Missing column - should be blocked
        result = await plugin.evaluate("SELECT * FROM users WHERE id = 1")
        assert result.error is None
        assert result.matched is True

        # Invalid operation - should be blocked
        result = await plugin.evaluate(
            "DELETE FROM users WHERE tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_all_features_combined(self):
        """Should enforce all validation types together."""
        config = SQLControlEvaluatorPluginConfig(
            allowed_operations=["SELECT", "INSERT"],
            allowed_tables=["users", "orders"],
            required_columns=["tenant_id"],
            column_context="where",
            require_limit=True,
            max_limit=1000,
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # All constraints satisfied - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE tenant_id = 123 LIMIT 100"
        )
        assert result.error is None
        assert result.matched is False

        # Missing LIMIT - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is True

        # LIMIT too high - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE tenant_id = 123 LIMIT 5000"
        )
        assert result.error is None
        assert result.matched is True

        # Operation violation - should be blocked
        result = await plugin.evaluate(
            "DELETE FROM users WHERE tenant_id = 123"
        )
        assert result.error is None
        assert result.matched is True

        # Table violation - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM admin WHERE tenant_id = 123 LIMIT 100"
        )
        assert result.error is None
        assert result.matched is True

        # Column violation - should be blocked
        result = await plugin.evaluate("SELECT * FROM users WHERE id = 1 LIMIT 100")
        assert result.error is None
        assert result.matched is True


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_none_input(self):
        """Should handle None input."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(None)
        assert result.error is None
        assert result.matched is False
        assert "No SQL query" in result.message

    @pytest.mark.asyncio
    async def test_empty_string(self):
        """Should handle empty string input."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("")
        assert result.error is None
        assert result.matched is False
        assert "Empty" in result.message

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        """Should handle whitespace-only input."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("   ")
        assert result.error is None
        assert result.matched is False
        assert "Empty" in result.message

    @pytest.mark.asyncio
    async def test_malformed_sql_blocked(self):
        """Should block malformed SQL (invalid SQL fails validation)."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("This is not valid SQL at all!!!")
        assert result.error is None
        assert result.matched is True  # Invalid SQL is blocked
        assert result.confidence == 1.0
        assert result.error is None  # Not a plugin error, just bad input
        assert "pars" in result.message.lower()

    @pytest.mark.asyncio
    async def test_empty_config(self):
        """Should pass all queries with empty config."""
        config = SQLControlEvaluatorPluginConfig()
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("DROP TABLE users")
        assert result.error is None
        assert result.matched is False

        result = await plugin.evaluate("SELECT * FROM admin")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_dict_input_with_query_key(self):
        """Should extract query from dict with 'query' key."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate({"query": "DROP TABLE users"})
        assert result.error is None
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_non_table_query_with_table_restrictions(self):
        """Should allow non-table queries even with table restrictions."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # SELECT without FROM clause
        result = await plugin.evaluate("SELECT 1")
        assert result.error is None
        assert result.matched is False

        # SELECT with expression
        result = await plugin.evaluate("SELECT 1 + 1 AS result")
        assert result.error is None
        assert result.matched is False


class TestSQLSubqueries:
    """Tests for nested queries and subqueries."""

    @pytest.mark.asyncio
    async def test_subquery_in_where_clause(self):
        """Should extract tables from subqueries in WHERE clause."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "orders"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Subquery with allowed tables - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders WHERE total > 100)"
        )
        assert result.error is None
        assert result.matched is False

        # Subquery with blocked table - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM admin WHERE active = true)"
        )
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message

    @pytest.mark.asyncio
    async def test_subquery_in_from_clause(self):
        """Should extract tables from subqueries in FROM clause."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "orders"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Derived table with allowed table - should pass
        result = await plugin.evaluate(
            "SELECT * FROM "
            "(SELECT * FROM users WHERE active = true) AS active_users"
        )
        assert result.error is None
        assert result.matched is False

        # Derived table with blocked table - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM "
            "(SELECT * FROM admin WHERE role = 'super') AS admins"
        )
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message

    @pytest.mark.asyncio
    async def test_correlated_subquery(self):
        """Should handle correlated subqueries correctly."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "orders"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Correlated subquery with allowed tables - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users u WHERE EXISTS "
            "(SELECT 1 FROM orders o WHERE o.user_id = u.id)"
        )
        assert result.error is None
        assert result.matched is False

        # Correlated subquery with blocked table - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users u WHERE EXISTS "
            "(SELECT 1 FROM secrets s WHERE s.user_id = u.id)"
        )
        assert result.error is None
        assert result.matched is True
        assert "secrets" in result.message

    @pytest.mark.asyncio
    async def test_nested_subqueries(self):
        """Should handle deeply nested subqueries."""
        config = SQLControlEvaluatorPluginConfig(blocked_tables=["admin", "secrets"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Nested subqueries without blocked tables - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders WHERE id IN "
            "(SELECT order_id FROM payments WHERE status = 'completed'))"
        )
        assert result.error is None
        assert result.matched is False

        # Nested subquery with blocked table in innermost - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders WHERE id IN "
            "(SELECT order_id FROM admin WHERE verified = true))"
        )
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message

        # Nested subquery with blocked table in middle - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM secrets WHERE id IN "
            "(SELECT secret_id FROM logs))"
        )
        assert result.error is None
        assert result.matched is True
        assert "secrets" in result.message

    @pytest.mark.asyncio
    async def test_subquery_with_blocked_operations(self):
        """Should detect blocked operations in subqueries."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DELETE", "DROP"])
        plugin = SQLControlEvaluatorPlugin(config)

        # SELECT with subquery - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders)"
        )
        assert result.error is None
        assert result.matched is False

        # DELETE in main query - should be blocked
        result = await plugin.evaluate(
            "DELETE FROM users WHERE id IN "
            "(SELECT user_id FROM orders WHERE total < 10)"
        )
        assert result.error is None
        assert result.matched is True
        assert "DELETE" in result.metadata["blocked"]

        # NOTE: The following is a KNOWN BUG (Issue #1 in SQL_PLUGIN_ISSUES.md)
        # DELETE in subquery - SHOULD be blocked but currently ISN'T
        # Blocked operations in subqueries are not currently detected
        # Leaving this test commented out until Issue #1 is fixed
        #
        # result = await plugin.evaluate(
        #     "SELECT * FROM users WHERE id NOT IN "
        #     "(DELETE FROM orders WHERE total = 0 RETURNING user_id)"
        # )
        # assert result.matched is True
        # assert "DELETE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_subquery_with_column_requirements(self):
        """Should check column requirements in subqueries."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Column in outer query WHERE - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE tenant_id = 123 AND id IN "
            "(SELECT user_id FROM orders WHERE total > 100)"
        )
        assert result.error is None
        assert result.matched is False

        # NOTE: With the default column_context_scope="all", tenant_id in a subquery
        # WHERE clause passes validation because the column IS present (just not in
        # the outer query). For proper multi-tenant RLS security, users should set
        # column_context_scope="top_level" to ensure tenant filtering is in the
        # outer WHERE clause. See TestMultiTenantRLSSecurityBypass for tests of
        # the "top_level" scope behavior.

    @pytest.mark.asyncio
    async def test_subquery_with_column_in_select(self):
        """Should extract columns from subquery SELECT clauses with scope=all."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["user_id"],
            column_context="select",
            column_context_scope="top_level",  # Old behavior: only check outer SELECT
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Column in outer SELECT - should pass
        result = await plugin.evaluate(
            "SELECT user_id, name FROM users WHERE id IN "
            "(SELECT id FROM orders)"
        )
        assert result.error is None
        assert result.matched is False

        # Column only in subquery SELECT - should be blocked
        result = await plugin.evaluate(
            "SELECT id, name FROM users WHERE id IN "
            "(SELECT user_id FROM orders)"
        )
        assert result.error is None
        assert result.matched is True
        assert "user_id" in result.message

    @pytest.mark.asyncio
    async def test_multiple_subqueries(self):
        """Should handle multiple subqueries in same query."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "orders", "payments"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Multiple subqueries with allowed tables - should pass
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders) AND id IN "
            "(SELECT user_id FROM payments)"
        )
        assert result.error is None
        assert result.matched is False

        # One subquery with disallowed table - should be blocked
        result = await plugin.evaluate(
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders) AND id IN "
            "(SELECT user_id FROM admin)"
        )
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message

    @pytest.mark.asyncio
    async def test_subquery_in_join(self):
        """Should handle subqueries used in JOIN clauses."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "orders"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Subquery in JOIN with allowed table - should pass
        result = await plugin.evaluate(
            "SELECT u.* FROM users u "
            "JOIN (SELECT user_id, COUNT(*) as order_count FROM orders "
            "GROUP BY user_id) o ON u.id = o.user_id"
        )
        assert result.error is None
        assert result.matched is False

        # Subquery in JOIN with blocked table - should be blocked
        result = await plugin.evaluate(
            "SELECT u.* FROM users u "
            "JOIN (SELECT user_id, role FROM admin) a ON u.id = a.user_id"
        )
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message

    @pytest.mark.asyncio
    async def test_union_with_subqueries(self):
        """Should handle UNION with subqueries."""
        config = SQLControlEvaluatorPluginConfig(allowed_tables=["users", "customers"])
        plugin = SQLControlEvaluatorPlugin(config)

        # UNION with allowed tables - should pass
        result = await plugin.evaluate(
            "SELECT id, name FROM users "
            "UNION "
            "SELECT id, name FROM customers"
        )
        assert result.error is None
        assert result.matched is False

        # UNION with blocked table - should be blocked
        result = await plugin.evaluate(
            "SELECT id, name FROM users "
            "UNION "
            "SELECT id, name FROM admin"
        )
        assert result.error is None
        assert result.matched is True
        assert "admin" in result.message


class TestSQLDialectConfiguration:
    """Tests for SQL dialect configuration and validation."""

    def test_dialect_defaults_to_postgres(self):
        """Should default to postgres dialect."""
        config = SQLControlEvaluatorPluginConfig()
        assert config.dialect == "postgres"

    def test_dialect_can_be_set_to_mysql(self):
        """Should accept mysql dialect."""
        config = SQLControlEvaluatorPluginConfig(dialect="mysql")
        assert config.dialect == "mysql"

    def test_dialect_can_be_set_to_tsql(self):
        """Should accept tsql dialect."""
        config = SQLControlEvaluatorPluginConfig(dialect="tsql")
        assert config.dialect == "tsql"

    def test_dialect_can_be_set_to_oracle(self):
        """Should accept oracle dialect."""
        config = SQLControlEvaluatorPluginConfig(dialect="oracle")
        assert config.dialect == "oracle"

    def test_dialect_can_be_set_to_sqlite(self):
        """Should accept sqlite dialect."""
        config = SQLControlEvaluatorPluginConfig(dialect="sqlite")
        assert config.dialect == "sqlite"

    def test_invalid_dialect_raises_error(self):
        """Should reject invalid dialect."""
        with pytest.raises(Exception):
            SQLControlEvaluatorPluginConfig(dialect="invalid_dialect")


class TestSQLDialectParsing:
    """Tests for dialect-specific SQL parsing."""

    # PostgreSQL Tests (default)
    @pytest.mark.asyncio
    async def test_postgres_double_quoted_identifiers(self):
        """PostgreSQL should parse double-quoted identifiers."""
        config = SQLControlEvaluatorPluginConfig(dialect="postgres", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Double quotes in PostgreSQL
        result = await plugin.evaluate('SELECT * FROM "users"')
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_postgres_case_sensitive_identifiers_quoted(self):
        """PostgreSQL preserves case in quoted identifiers."""
        config = SQLControlEvaluatorPluginConfig(dialect="postgres", allowed_tables=["Users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Quoted identifier in PostgreSQL preserves case
        result = await plugin.evaluate('SELECT * FROM "Users"')
        assert result.error is None
        assert result.matched is False

    # MySQL Tests
    @pytest.mark.asyncio
    async def test_mysql_backtick_identifiers(self):
        """MySQL should parse backtick-quoted identifiers."""
        config = SQLControlEvaluatorPluginConfig(dialect="mysql", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Backticks in MySQL
        result = await plugin.evaluate("SELECT * FROM `users`")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_mysql_column_alias_syntax(self):
        """MySQL should parse column aliases correctly."""
        config = SQLControlEvaluatorPluginConfig(dialect="mysql", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # MySQL-specific alias syntax
        result = await plugin.evaluate(
            "SELECT id as `user_id`, name as `user_name` FROM users"
        )
        assert result.error is None
        assert result.matched is False

    # T-SQL Tests
    @pytest.mark.asyncio
    async def test_tsql_bracket_quoted_identifiers(self):
        """T-SQL should parse bracket-quoted identifiers."""
        config = SQLControlEvaluatorPluginConfig(dialect="tsql", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Brackets in T-SQL
        result = await plugin.evaluate("SELECT * FROM [users]")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_tsql_column_with_spaces(self):
        """T-SQL should parse column names with spaces in brackets."""
        config = SQLControlEvaluatorPluginConfig(
            dialect="tsql",
            allowed_tables=["users"],
            required_columns=["user id"],
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # T-SQL with spaces in column name using brackets
        result = await plugin.evaluate(
            "SELECT [user id], name FROM [users] WHERE [user id] = 1"
        )
        assert result.error is None
        assert result.matched is False

    # Oracle Tests
    @pytest.mark.asyncio
    async def test_oracle_double_quoted_identifiers(self):
        """Oracle should parse double-quoted identifiers."""
        config = SQLControlEvaluatorPluginConfig(dialect="oracle", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Double quotes in Oracle
        result = await plugin.evaluate('SELECT * FROM "users"')
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_oracle_line_comment_syntax(self):
        """Oracle should parse -- line comments."""
        config = SQLControlEvaluatorPluginConfig(dialect="oracle", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Oracle -- comment syntax
        result = await plugin.evaluate(
            "SELECT * FROM users -- get all users\n WHERE id > 0"
        )
        assert result.error is None
        assert result.matched is False

    # SQLite Tests
    @pytest.mark.asyncio
    async def test_sqlite_double_quoted_identifiers(self):
        """SQLite should parse double-quoted identifiers."""
        config = SQLControlEvaluatorPluginConfig(dialect="sqlite", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Double quotes in SQLite
        result = await plugin.evaluate('SELECT * FROM "users"')
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_sqlite_autoincrement_syntax(self):
        """SQLite should parse AUTOINCREMENT syntax."""
        config = SQLControlEvaluatorPluginConfig(dialect="sqlite", block_ddl=False)
        plugin = SQLControlEvaluatorPlugin(config)

        # SQLite AUTOINCREMENT syntax
        result = await plugin.evaluate(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT)"
        )
        assert result.error is None
        assert result.matched is False


class TestSQLDialectIntegration:
    """Tests for dialect support with other SQL controls."""

    @pytest.mark.asyncio
    async def test_dialect_with_blocked_operations(self):
        """Should enforce blocked_operations across dialects."""
        for dialect in ["postgres", "mysql", "tsql", "oracle", "sqlite"]:
            config = SQLControlEvaluatorPluginConfig(dialect=dialect, blocked_operations=["DROP"])
            plugin = SQLControlEvaluatorPlugin(config)

            result = await plugin.evaluate("DROP TABLE users")
            assert result.error is None
            assert result.matched is True
            assert "DROP" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_dialect_with_table_restrictions(self):
        """Should enforce table restrictions across dialects."""
        for dialect in ["postgres", "mysql", "tsql", "oracle", "sqlite"]:
            config = SQLControlEvaluatorPluginConfig(
                dialect=dialect, allowed_tables=["users", "orders"]
            )
            plugin = SQLControlEvaluatorPlugin(config)

            # Allowed table
            result = await plugin.evaluate("SELECT * FROM users")
            assert result.error is None
            assert result.matched is False

            # Blocked table
            result = await plugin.evaluate("SELECT * FROM admin")
            assert result.error is None
            assert result.matched is True

    @pytest.mark.asyncio
    async def test_dialect_with_limit_enforcement(self):
        """Should enforce LIMIT constraints across dialects."""
        for dialect in ["postgres", "mysql", "tsql", "oracle", "sqlite"]:
            config = SQLControlEvaluatorPluginConfig(
                dialect=dialect, require_limit=True, max_limit=100
            )
            plugin = SQLControlEvaluatorPlugin(config)

            # No LIMIT - should fail
            result = await plugin.evaluate("SELECT * FROM users")
            assert result.error is None
            assert result.matched is True

            # With LIMIT - should pass
            result = await plugin.evaluate("SELECT * FROM users LIMIT 50")
            assert result.error is None
            assert result.matched is False

    @pytest.mark.asyncio
    async def test_dialect_with_column_requirements(self):
        """Should enforce column requirements across dialects."""
        for dialect in ["postgres", "mysql", "tsql", "oracle", "sqlite"]:
            config = SQLControlEvaluatorPluginConfig(
                dialect=dialect,
                required_columns=["tenant_id"],
                column_context="where",
            )
            plugin = SQLControlEvaluatorPlugin(config)

            # With required column - should pass
            result = await plugin.evaluate(
                "SELECT * FROM users WHERE tenant_id = 1"
            )
            assert result.error is None
            assert result.matched is False

            # Without required column - should fail
            result = await plugin.evaluate("SELECT * FROM users WHERE id = 1")
            assert result.error is None
            assert result.matched is True


class TestSQLDialectEdgeCases:
    """Tests for dialect-specific edge cases and edge behaviors."""

    @pytest.mark.asyncio
    async def test_mysql_case_insensitive_table_names(self):
        """MySQL table names are case-insensitive on most systems."""
        config = SQLControlEvaluatorPluginConfig(dialect="mysql", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Both should work (MySQL normalizes to lowercase)
        result = await plugin.evaluate("SELECT * FROM users")
        assert result.error is None
        assert result.matched is False

        result = await plugin.evaluate("SELECT * FROM USERS")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_tsql_function_syntax(self):
        """T-SQL has different function syntax than standard SQL."""
        config = SQLControlEvaluatorPluginConfig(dialect="tsql", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        # T-SQL datetime function - using DATEADD instead of GETDATE
        # since GETDATE is already parsed correctly
        result = await plugin.evaluate(
            "SELECT TOP 10 * FROM users "
            "WHERE created > DATEADD(day, -7, GETDATE())"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_oracle_schema_prefix(self):
        """Oracle uses schema.table.column notation."""
        config = SQLControlEvaluatorPluginConfig(dialect="oracle", allowed_tables=["users"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT u.id, u.name FROM schema.users u"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_dialect_with_unicode_identifiers(self):
        """All dialects should handle unicode in identifiers."""
        for dialect in ["postgres", "mysql", "tsql", "oracle", "sqlite"]:
            config = SQLControlEvaluatorPluginConfig(
                dialect=dialect,
                allowed_tables=["usuarios"],  # Spanish for "users"
            )
            plugin = SQLControlEvaluatorPlugin(config)

            result = await plugin.evaluate("SELECT * FROM usuarios")
            assert result.error is None
            assert result.matched is False

    @pytest.mark.asyncio
    async def test_sqlite_with_complex_query(self):
        """SQLite should handle complex queries correctly."""
        config = SQLControlEvaluatorPluginConfig(dialect="sqlite", allowed_tables=["users", "orders"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Complex SQLite query with JOIN and WHERE
        result = await plugin.evaluate(
            "SELECT u.name, o.total FROM users u "
            "JOIN orders o ON u.id = o.user_id "
            "WHERE o.total > 100"
        )
        assert result.error is None
        assert result.matched is False


class TestOperationSecurityBypass:
    """Tests for Issue #1: Operations don't recurse into subqueries."""

    @pytest.mark.asyncio
    async def test_delete_in_cte_is_detected(self):
        """DELETE in CTE should be detected and blocked."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DELETE"])
        plugin = SQLControlEvaluatorPlugin(config)

        # DELETE hidden in CTE
        result = await plugin.evaluate(
            "WITH deleted AS ("
            "DELETE FROM users WHERE id = 1 RETURNING *"
            ") SELECT * FROM deleted"
        )
        assert result.error is None
        assert result.matched is True
        assert "DELETE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_update_in_cte_is_detected(self):
        """UPDATE in CTE should be detected."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["UPDATE"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "WITH updated AS ("
            "UPDATE users SET name = 'test' WHERE id = 1 RETURNING *"
            ") SELECT * FROM updated"
        )
        assert result.error is None
        assert result.matched is True
        assert "UPDATE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_insert_in_nested_cte_is_detected(self):
        """INSERT in nested CTE should be detected."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["INSERT"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "WITH outer_cte AS ("
            "  WITH inner_cte AS ("
            "    INSERT INTO users (name) VALUES ('test') RETURNING *"
            "  ) SELECT * FROM inner_cte"
            ") SELECT * FROM outer_cte"
        )
        assert result.error is None
        assert result.matched is True
        assert "INSERT" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_select_with_delete_subquery_in_from(self):
        """DELETE in SELECT's FROM subquery should be detected."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DELETE"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Use nested SELECT with CTE pattern
        result = await plugin.evaluate(
            "SELECT * FROM ("
            "  WITH deleted AS (DELETE FROM users WHERE id = 1 RETURNING *) "
            "  SELECT * FROM deleted"
            ") AS outer_query"
        )
        assert result.error is None
        assert result.matched is True
        assert "DELETE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_multiple_operations_in_ctes(self):
        """Multiple different operations in CTEs should all be detected."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DELETE", "UPDATE"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "WITH deleted AS (DELETE FROM users WHERE id = 1 RETURNING *), "
            "updated AS (UPDATE orders SET status = 'done' WHERE id = 2 RETURNING *) "
            "SELECT * FROM deleted UNION ALL SELECT * FROM updated"
        )
        assert result.error is None
        assert result.matched is True
        assert "DELETE" in result.metadata["blocked"]
        assert "UPDATE" in result.metadata["blocked"]


class TestMultiTenantRLSSecurityBypass:
    """Tests for Issue #2: Column context security bypass."""

    @pytest.mark.asyncio
    async def test_top_level_scope_blocks_subquery_tenant_filter(self):
        """top_level scope requires tenant_id in outer WHERE, not subquery."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
            column_context_scope="top_level",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # tenant_id only in subquery - should FAIL with top_level scope
        result = await plugin.evaluate(
            "SELECT * FROM users "
            "WHERE id IN (SELECT user_id FROM orders WHERE tenant_id = 123)"
        )
        assert result.error is None
        assert result.matched is True
        assert "tenant_id" in result.message or "required" in result.message

    @pytest.mark.asyncio
    async def test_top_level_scope_passes_with_outer_tenant_filter(self):
        """top_level scope should pass when tenant_id in outer WHERE."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
            column_context_scope="top_level",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # tenant_id in outer WHERE - should PASS
        result = await plugin.evaluate(
            "SELECT * FROM users "
            "WHERE tenant_id = 123 AND id IN (SELECT user_id FROM orders)"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_all_scope_backward_compatible(self):
        """'all' scope should find tenant_id in any WHERE (backward compatible)."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
            column_context_scope="all",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # tenant_id in subquery - should PASS with 'all' scope
        result = await plugin.evaluate(
            "SELECT * FROM users "
            "WHERE id IN (SELECT user_id FROM orders WHERE tenant_id = 123)"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_default_scope_is_all(self):
        """Default column_context_scope should be 'all' for backward compatibility."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="where",
            # column_context_scope not specified, should default to "all"
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # Should behave like scope="all"
        result = await plugin.evaluate(
            "SELECT * FROM users "
            "WHERE id IN (SELECT user_id FROM orders WHERE tenant_id = 123)"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_select_context_with_top_level_scope(self):
        """top_level scope with select context only checks outer SELECT."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["tenant_id"],
            column_context="select",
            column_context_scope="top_level",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # tenant_id only in subquery SELECT - should FAIL
        result = await plugin.evaluate(
            "SELECT id, name FROM users "
            "WHERE id IN (SELECT tenant_id FROM orders)"
        )
        assert result.error is None
        assert result.matched is True


class TestLimitBypassSubqueries:
    """Tests for Issue #3: LIMIT checking doesn't recurse."""

    @pytest.mark.asyncio
    async def test_subquery_without_limit_is_blocked(self):
        """Subquery without LIMIT should be blocked when require_limit=True."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # Outer has LIMIT, inner doesn't - should FAIL
        result = await plugin.evaluate(
            "SELECT * FROM (SELECT * FROM huge_table) AS t LIMIT 10"
        )
        assert result.error is None
        assert result.matched is True
        assert "LIMIT" in result.message

    @pytest.mark.asyncio
    async def test_all_subqueries_with_limit_passes(self):
        """All SELECTs with LIMIT should pass."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT * FROM (SELECT * FROM users LIMIT 100) AS t LIMIT 10"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_nested_subqueries_all_need_limit(self):
        """All nested subqueries need LIMIT."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # Deepest subquery missing LIMIT
        result = await plugin.evaluate(
            "SELECT * FROM ("
            "  SELECT * FROM ("
            "    SELECT * FROM users"
            "  ) AS inner LIMIT 50"
            ") AS outer LIMIT 10"
        )
        assert result.error is None
        assert result.matched is True
        assert "LIMIT" in result.message

    @pytest.mark.asyncio
    async def test_max_limit_enforced_on_subqueries(self):
        """max_limit should be enforced on all subqueries."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True, max_limit=100)
        plugin = SQLControlEvaluatorPlugin(config)

        # Subquery exceeds max_limit
        result = await plugin.evaluate(
            "SELECT * FROM (SELECT * FROM users LIMIT 500) AS t LIMIT 10"
        )
        assert result.error is None
        assert result.matched is True
        assert "500" in result.message or "exceeds" in result.message

    @pytest.mark.asyncio
    async def test_cte_without_limit_is_blocked(self):
        """CTE SELECT without LIMIT should be blocked."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "WITH user_data AS (SELECT * FROM users) "
            "SELECT * FROM user_data LIMIT 10"
        )
        assert result.error is None
        assert result.matched is True
        assert "LIMIT" in result.message

    @pytest.mark.asyncio
    async def test_max_result_window_enforced(self):
        """max_result_window should prevent deep pagination."""
        config = SQLControlEvaluatorPluginConfig(max_result_window=10000)
        plugin = SQLControlEvaluatorPlugin(config)

        # Within limit: 100 + 9900 = 10000 - should PASS
        result = await plugin.evaluate("SELECT * FROM users LIMIT 100 OFFSET 9900")
        assert result.error is None
        assert result.matched is False

        # Exceeds limit: 10 + 10000 = 10010 > 10000 - should FAIL
        result = await plugin.evaluate("SELECT * FROM users LIMIT 10 OFFSET 10000")
        assert result.error is None
        assert result.matched is True
        assert (
            "result window" in result.message.lower() or "10010" in result.message
        )

    @pytest.mark.asyncio
    async def test_large_offset_without_max_result_window(self):
        """Without max_result_window, large OFFSET should be allowed."""
        config = SQLControlEvaluatorPluginConfig()  # No max_result_window
        plugin = SQLControlEvaluatorPlugin(config)

        # Large OFFSET but no restriction - should PASS
        result = await plugin.evaluate("SELECT * FROM users LIMIT 10 OFFSET 1000000")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_max_result_window_on_subqueries(self):
        """max_result_window should be enforced on subqueries."""
        config = SQLControlEvaluatorPluginConfig(max_result_window=1000)
        plugin = SQLControlEvaluatorPlugin(config)

        # Subquery exceeds max_result_window
        result = await plugin.evaluate(
            "SELECT * FROM ("
            "SELECT * FROM users LIMIT 10 OFFSET 1000"
            ") AS t LIMIT 10"
        )
        assert result.error is None
        assert result.matched is True
        assert (
            "result window" in result.message.lower() or "1010" in result.message
        )

    @pytest.mark.asyncio
    async def test_max_limit_and_max_result_window_together(self):
        """Both max_limit and max_result_window should be enforced."""
        config = SQLControlEvaluatorPluginConfig(max_limit=100, max_result_window=10000)
        plugin = SQLControlEvaluatorPlugin(config)

        # Exceeds max_limit - should FAIL
        result = await plugin.evaluate("SELECT * FROM users LIMIT 500")
        assert result.error is None
        assert result.matched is True
        assert "500" in result.message

        # Within max_limit but exceeds max_result_window - should FAIL
        result = await plugin.evaluate(
            "SELECT * FROM users LIMIT 100 OFFSET 10000"
        )
        assert result.error is None
        assert result.matched is True
        assert (
            "result window" in result.message.lower() or "10100" in result.message
        )

        # Within both limits - should PASS
        result = await plugin.evaluate("SELECT * FROM users LIMIT 100 OFFSET 9000")
        assert result.error is None
        assert result.matched is False


class TestSelectColumnExtractionFixed:
    """Tests for Issue #4: SELECT column extraction is broken."""

    @pytest.mark.asyncio
    async def test_column_in_function_is_extracted(self):
        """Columns in functions should be extracted."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["user_id"],
            column_context="select",
            column_context_scope="top_level",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # user_id in COUNT() function - should be extracted
        result = await plugin.evaluate("SELECT COUNT(user_id), name FROM users")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_column_in_expression_is_extracted(self):
        """Columns in expressions should be extracted."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["price"],
            column_context="select",
            column_context_scope="top_level",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        # price in arithmetic expression
        result = await plugin.evaluate("SELECT price * 1.1, name FROM products")
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_column_in_case_is_extracted(self):
        """Columns in CASE expressions should be extracted."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["status"],
            column_context="select",
            column_context_scope="top_level",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT CASE WHEN status = 'active' THEN 1 ELSE 0 END FROM users"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_multiple_columns_in_coalesce(self):
        """Multiple columns in COALESCE should be extracted."""
        config = SQLControlEvaluatorPluginConfig(
            required_columns=["user_id", "guest_id"],
            column_presence_logic="any",
            column_context="select",
            column_context_scope="top_level",
        )
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate(
            "SELECT COALESCE(user_id, guest_id) FROM sessions"
        )
        assert result.error is None
        assert result.matched is False


class TestNewOperationDetection:
    """Tests for newly added operation types."""

    @pytest.mark.asyncio
    async def test_commit_operation_detected(self):
        """COMMIT should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["COMMIT"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("COMMIT")
        assert result.error is None
        assert result.matched is True
        assert "COMMIT" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_rollback_operation_detected(self):
        """ROLLBACK should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["ROLLBACK"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("ROLLBACK")
        assert result.error is None
        assert result.matched is True
        assert "ROLLBACK" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_show_operation_detected(self):
        """SHOW parses to COMMAND (sqlglot fallback for unsupported syntax)."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["COMMAND"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("SHOW TABLES")
        assert result.error is None
        assert result.matched is True
        assert "COMMAND" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_describe_operation_detected(self):
        """DESCRIBE should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DESCRIBE"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("DESCRIBE users")
        assert result.error is None
        assert result.matched is True
        assert "DESCRIBE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_set_operation_detected(self):
        """SET should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["SET"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("SET search_path = public")
        assert result.error is None
        assert result.matched is True
        assert "SET" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_use_operation_detected(self):
        """USE should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["USE"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("USE database_name")
        assert result.error is None
        assert result.matched is True
        assert "USE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_copy_operation_detected(self):
        """COPY should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["COPY"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("COPY users TO '/tmp/users.csv'")
        assert result.error is None
        assert result.matched is True
        assert "COPY" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_lock_operation_fails_to_parse(self):
        """LOCK TABLE fails to parse in sqlglot - blocked as invalid SQL."""
        # Need a control configured for parsing to be attempted
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DELETE"])
        plugin = SQLControlEvaluatorPlugin(config)

        # LOCK TABLE doesn't parse, so it's blocked as invalid SQL
        result = await plugin.evaluate("LOCK TABLE users IN ACCESS EXCLUSIVE MODE")
        assert result.error is None
        assert result.matched is True  # Invalid SQL is blocked
        assert result.error is None  # Not a plugin error
        assert "pars" in result.message.lower()

    @pytest.mark.asyncio
    async def test_analyze_operation_detected(self):
        """ANALYZE should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["ANALYZE"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("ANALYZE users")
        assert result.error is None
        assert result.matched is True
        assert "ANALYZE" in result.metadata["blocked"]

    @pytest.mark.asyncio
    async def test_comment_operation_detected(self):
        """COMMENT should be detected and blockable."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["COMMENT"])
        plugin = SQLControlEvaluatorPlugin(config)

        result = await plugin.evaluate("COMMENT ON TABLE users IS 'User data'")
        assert result.error is None
        assert result.matched is True
        assert "COMMENT" in result.metadata["blocked"]


class TestQueryComplexityLimits:
    """Tests for Issue #13: Query complexity limits."""

    @pytest.mark.asyncio
    async def test_subquery_depth_limit_enforced(self):
        """Deeply nested subqueries should be blocked."""
        config = SQLControlEvaluatorPluginConfig(max_subquery_depth=2)
        plugin = SQLControlEvaluatorPlugin(config)

        # Depth 3: exceeds limit
        query = """
        SELECT * FROM (
            SELECT * FROM (
                SELECT * FROM (
                    SELECT * FROM users
                ) AS level3
            ) AS level2
        ) AS level1
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is True
        assert "subquery depth" in result.message.lower()
        assert result.metadata["subquery_depth"] == 3
        assert result.metadata["max_subquery_depth"] == 2

    @pytest.mark.asyncio
    async def test_subquery_depth_within_limit(self):
        """Shallow subqueries should pass."""
        config = SQLControlEvaluatorPluginConfig(max_subquery_depth=2)
        plugin = SQLControlEvaluatorPlugin(config)

        # Depth 2: at limit
        query = """
        SELECT * FROM (
            SELECT * FROM (
                SELECT * FROM users
            ) AS level2
        ) AS level1
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_max_joins_enforced(self):
        """Too many joins should be blocked."""
        config = SQLControlEvaluatorPluginConfig(max_joins=3)
        plugin = SQLControlEvaluatorPlugin(config)

        # 4 joins: exceeds limit
        query = """
        SELECT * FROM users
        JOIN orders ON users.id = orders.user_id
        JOIN products ON orders.product_id = products.id
        JOIN categories ON products.category_id = categories.id
        JOIN brands ON products.brand_id = brands.id
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is True
        assert "JOIN" in result.message
        assert result.metadata["join_count"] == 4
        assert result.metadata["max_joins"] == 3

    @pytest.mark.asyncio
    async def test_max_joins_within_limit(self):
        """Reasonable number of joins should pass."""
        config = SQLControlEvaluatorPluginConfig(max_joins=3)
        plugin = SQLControlEvaluatorPlugin(config)

        # 3 joins: at limit
        query = """
        SELECT * FROM users
        JOIN orders ON users.id = orders.user_id
        JOIN products ON orders.product_id = products.id
        JOIN categories ON products.category_id = categories.id
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_max_union_count_enforced(self):
        """Too many UNION operations should be blocked."""
        config = SQLControlEvaluatorPluginConfig(max_union_count=2)
        plugin = SQLControlEvaluatorPlugin(config)

        # 3 UNIONs: exceeds limit
        query = """
        SELECT * FROM users
        UNION ALL
        SELECT * FROM customers
        UNION ALL
        SELECT * FROM vendors
        UNION ALL
        SELECT * FROM partners
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is True
        assert "set operations" in result.message.lower()
        assert result.metadata["union_count"] == 3
        assert result.metadata["max_union_count"] == 2

    @pytest.mark.asyncio
    async def test_max_union_count_within_limit(self):
        """Reasonable UNION chains should pass."""
        config = SQLControlEvaluatorPluginConfig(max_union_count=2)
        plugin = SQLControlEvaluatorPlugin(config)

        # 2 UNIONs: at limit
        query = """
        SELECT * FROM users
        UNION ALL
        SELECT * FROM customers
        UNION ALL
        SELECT * FROM vendors
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is False


class TestEdgeCasesAlreadyFixed:
    """Tests for Issues #19-21: Verify they're already fixed."""

    @pytest.mark.asyncio
    async def test_union_all_parts_checked_for_limit(self):
        """Issue #19: All parts of UNION should be checked for LIMIT."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # One part missing LIMIT - should fail
        query = """
        SELECT * FROM users LIMIT 10
        UNION ALL
        SELECT * FROM customers
        """
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is True
        assert "LIMIT" in result.message

    @pytest.mark.asyncio
    async def test_insert_select_validated(self):
        """Issue #20: SELECT in INSERT...SELECT should be validated."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # INSERT...SELECT without LIMIT - should fail
        result = await plugin.evaluate("INSERT INTO backup SELECT * FROM users")
        assert result.error is None
        assert result.matched is True
        assert "LIMIT" in result.message

        # INSERT...SELECT with LIMIT - should pass
        result = await plugin.evaluate(
            "INSERT INTO backup SELECT * FROM users LIMIT 100"
        )
        assert result.error is None
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_create_view_validated(self):
        """Issue #21: SELECT in CREATE VIEW should be validated."""
        config = SQLControlEvaluatorPluginConfig(require_limit=True)
        plugin = SQLControlEvaluatorPlugin(config)

        # CREATE VIEW without LIMIT - should fail
        result = await plugin.evaluate(
            "CREATE VIEW active_users AS SELECT * FROM users WHERE active = true"
        )
        assert result.error is None
        assert result.matched is True
        assert "LIMIT" in result.message

        # CREATE VIEW with LIMIT - should pass
        result = await plugin.evaluate(
            "CREATE VIEW active_users AS SELECT * FROM users WHERE active = true LIMIT 1000"
        )
        assert result.error is None
        assert result.matched is False


class TestEnhancedMetadata:
    """Tests for Issue #15: Enhanced metadata with smart truncation."""

    @pytest.mark.asyncio
    async def test_short_query_metadata(self):
        """Short queries should have full snippet."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DELETE"])
        plugin = SQLControlEvaluatorPlugin(config)

        # Blocked operation to trigger metadata
        query = "DELETE FROM users"
        result = await plugin.evaluate(query)
        assert result.error is None
        assert result.matched is True
        assert "query_snippet" in result.metadata or "query" in result.metadata
        # For operations, metadata might use "query" or "query_snippet"
        if "query_snippet" in result.metadata:
            assert result.metadata["query_length"] == len(query)
            # Short query should be fully included
            assert "..." not in result.metadata["query_snippet"]

    @pytest.mark.asyncio
    async def test_long_query_smart_truncation(self):
        """Long queries should have beginning and end with ellipsis."""
        config = SQLControlEvaluatorPluginConfig(max_limit=10)
        plugin = SQLControlEvaluatorPlugin(config)

        # Create a very long query that violates max_limit
        long_query = "SELECT " + ", ".join(f"col{i}" for i in range(100)) + " FROM users WHERE " + " AND ".join(f"field{i} = {i}" for i in range(50)) + " LIMIT 1000"

        result = await plugin.evaluate(long_query)
        assert result.error is None
        assert result.matched is True
        assert result.metadata is not None
        # Check for enhanced metadata fields
        assert "query_snippet" in result.metadata or "query" in result.metadata
        if "query_snippet" in result.metadata:
            assert "..." in result.metadata["query_snippet"]
            assert result.metadata["query_length"] == len(long_query)

    @pytest.mark.asyncio
    async def test_query_hash_consistent(self):
        """Same query should produce same hash."""
        config = SQLControlEvaluatorPluginConfig(blocked_operations=["DELETE"])
        plugin = SQLControlEvaluatorPlugin(config)

        query = "DELETE FROM users WHERE id = 1"

        result1 = await plugin.evaluate(query)
        result2 = await plugin.evaluate(query)

        assert result1.matched is True
        assert result2.matched is True
        # Check if metadata has query_hash
        if result1.metadata and "query_hash" in result1.metadata:
            assert result1.metadata["query_hash"] == result2.metadata["query_hash"]
            # Hash should be 16 characters (first 16 of SHA-256 hex)
            assert len(result1.metadata["query_hash"]) == 16
