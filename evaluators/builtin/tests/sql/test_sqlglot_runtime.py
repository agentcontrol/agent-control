"""SQLGlot runtime integration tests."""

from sqlglot import exp

from agent_control_evaluators.sql import SQLEvaluator, SQLEvaluatorConfig


def test_sqlglot_public_imports_support_sql_evaluator():
    """SQLGlot's public API should remain importable with the native extra installed."""
    # Given: the SQL evaluator package imports SQLGlot's public expression module
    assert exp.Select is not None

    # When: constructing the SQL evaluator
    evaluator = SQLEvaluator(SQLEvaluatorConfig(blocked_operations=["DROP"]))

    # Then: the evaluator can be created without SQLGlot import shadowing failures
    assert evaluator.metadata.name == "sql"
