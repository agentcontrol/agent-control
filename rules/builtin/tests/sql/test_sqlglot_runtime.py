"""SQLGlot runtime integration tests."""

from sqlglot import exp

from agent_control_rules.sql import SQLRule, SQLRuleConfig


def test_sqlglot_public_imports_support_sql_rule():
    """SQLGlot's public API should remain importable with the native extra installed."""
    # Given: the SQL rule package imports SQLGlot's public expression module
    assert exp.Select is not None

    # When: constructing the SQL rule
    rule = SQLRule(SQLRuleConfig(blocked_operations=["DROP"]))

    # Then: the rule can be created without SQLGlot import shadowing failures
    assert rule.metadata.name == "sql"
