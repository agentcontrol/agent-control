"""Targeted tests for SQLRuleConfig validate_config branches."""

from __future__ import annotations

import warnings

import pytest
from agent_control_rules.sql.config import SQLRuleConfig


class TestConflictingRestrictions:
    """Mutually-exclusive allow/block lists must be rejected at config time."""

    def test_blocked_and_allowed_operations_conflict(self):
        with pytest.raises(ValueError, match="blocked_operations and allowed_operations"):
            SQLRuleConfig(
                blocked_operations=["DELETE"],
                allowed_operations=["SELECT"],
            )

    def test_blocked_and_allowed_tables_conflict(self):
        with pytest.raises(ValueError, match="allowed_tables and blocked_tables"):
            SQLRuleConfig(
                allowed_tables=["users"],
                blocked_tables=["secrets"],
            )

    def test_blocked_and_allowed_schemas_conflict(self):
        with pytest.raises(ValueError, match="allowed_schemas and blocked_schemas"):
            SQLRuleConfig(
                allowed_schemas=["public"],
                blocked_schemas=["internal"],
            )


class TestLimitBounds:
    """Numeric controls must be positive."""

    def test_max_limit_must_be_positive(self):
        with pytest.raises(ValueError, match="max_limit must be a positive integer"):
            SQLRuleConfig(max_limit=0)

    def test_max_limit_negative_rejected(self):
        with pytest.raises(ValueError, match="max_limit must be a positive integer"):
            SQLRuleConfig(max_limit=-5)

    def test_max_statements_must_be_positive(self):
        with pytest.raises(ValueError, match="max_statements must be a positive integer"):
            SQLRuleConfig(
                allow_multi_statements=True,
                max_statements=0,
            )


class TestColumnControls:
    """Column-level validators cover required_column_values shape rules."""

    def test_column_context_without_required_columns_warns(self):
        with pytest.warns(UserWarning, match="column_context is set but required_columns"):
            SQLRuleConfig(column_context="where")

    def test_required_column_values_rejects_empty_column_ref(self):
        with pytest.raises(ValueError, match="empty column reference"):
            SQLRuleConfig(
                required_columns=["tenant_id"],
                required_column_values={"   ": "tenant_id"},
            )

    def test_required_column_values_rejects_malformed_qualified_ref(self):
        with pytest.raises(
            ValueError, match="'table.column' format when qualified"
        ):
            SQLRuleConfig(
                required_columns=["tenant_id"],
                required_column_values={"users.": "tenant_id"},
            )

    def test_required_column_values_rejects_blank_qualified_table_side(self):
        with pytest.raises(
            ValueError, match="'table.column' format when qualified"
        ):
            SQLRuleConfig(
                required_columns=["tenant_id"],
                required_column_values={".tenant_id": "tenant_id"},
            )

    def test_required_column_values_rejects_empty_context_key(self):
        with pytest.raises(ValueError, match="empty context key"):
            SQLRuleConfig(
                required_columns=["tenant_id"],
                required_column_values={"users.tenant_id": "   "},
            )

    def test_valid_required_column_values_accepted(self):
        """Sanity check: a valid combination passes without raising."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # promote any warning to a failure
            config = SQLRuleConfig(
                required_columns=["tenant_id"],
                column_context="where",
                required_column_values={"users.tenant_id": "tenant_id"},
            )
        assert config.required_column_values == {"users.tenant_id": "tenant_id"}
