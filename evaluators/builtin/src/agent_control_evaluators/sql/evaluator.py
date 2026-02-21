"""Comprehensive SQL validation evaluator.

Supports multi-statement, operation, table, column, and limit checking.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from agent_control_models import EvaluatorResult
from sqlglot import exp

from agent_control_evaluators._base import Evaluator, EvaluatorMetadata
from agent_control_evaluators._registry import register_evaluator
from agent_control_evaluators.sql.config import SQLEvaluatorConfig

logger = logging.getLogger(__name__)


@dataclass
class QueryAnalysis:
    """Pre-computed analysis of a SQL query structure.

    Collected in a single tree walk for performance optimization.
    """
    # Operations
    operations: set[str] = field(default_factory=set)

    # Tables
    tables: list[tuple[str | None, str]] = field(default_factory=list)

    # Columns by context
    all_columns: list[str] = field(default_factory=list)
    top_level_where_columns: list[str] = field(default_factory=list)
    all_where_columns: list[str] = field(default_factory=list)
    top_level_select_columns: list[str] = field(default_factory=list)
    all_select_columns: list[str] = field(default_factory=list)

    # SELECT nodes (for LIMIT checks)
    select_nodes: list[exp.Select] = field(default_factory=list)

    # Query complexity metrics
    join_count: int = 0
    union_count: int = 0
    max_subquery_depth: int = 0

    # CTEs defined in the query (for table access checks)
    defined_ctes: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RequiredColumnValueRule:
    """Preprocessed required column/value mapping rule."""

    raw_column: str
    table: str | None
    column: str
    context_key: str


@register_evaluator
class SQLEvaluator(Evaluator[SQLEvaluatorConfig]):
    """Comprehensive SQL validation evaluator.

    Validates SQL queries in this order:
    1. Multi-Statement: Control whether multiple SQL statements are allowed
    2. Operations: Block/allow specific SQL operations (DROP, DELETE, etc.)
    3. Table/Schema Access: Restrict which tables/schemas can be accessed
    4. Column Presence: Require specific columns in queries (e.g., tenant_id)
    5. Limits: Require LIMIT clause and enforce max LIMIT value on SELECT queries

    Examples:
        # Block multi-statement queries
        {"allow_multi_statements": False}

        # Block dangerous operations
        {"blocked_operations": ["DROP", "DELETE", "TRUNCATE"]}

        # Read-only mode
        {"allowed_operations": ["SELECT"]}

        # Restrict table access
        {"allowed_tables": ["users", "orders"]}

        # Multi-tenant security
        {"required_columns": ["tenant_id"], "column_context": "where"}

        # Prevent large result sets
        {"require_limit": True, "max_limit": 1000}

        # Combined validation
        {
            "allow_multi_statements": False,
            "allowed_operations": ["SELECT"],
            "allowed_tables": ["users", "orders"],
            "required_columns": ["tenant_id"],
            "column_context": "where",
            "require_limit": True,
            "max_limit": 1000
        }
    """

    metadata = EvaluatorMetadata(
        name="sql",
        version="1.0.0",
        description=(
            "Comprehensive SQL validation: multi-statement, operations, "
            "table access, column presence, and limits"
        ),
        timeout_ms=10000,
    )
    config_model = SQLEvaluatorConfig

    # SQL operation type mappings
    DDL_OPERATIONS = {
        "CREATE",
        "ALTER",
        "DROP",
        "RENAME",
        "TRUNCATE",
        "COMMENT",
    }
    DML_OPERATIONS = {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "MERGE",
        "CALL",
    }
    DCL_OPERATIONS = {
        "GRANT",
        "REVOKE",
    }
    TCL_OPERATIONS = {
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT",
        "SET TRANSACTION",
    }

    def __init__(self, config: SQLEvaluatorConfig) -> None:
        super().__init__(config)

        # Pre-process operation controls
        self._blocked_ops: set[str] | None = None
        self._allowed_ops: set[str] | None = None

        if config.blocked_operations:
            self._blocked_ops = {op.upper() for op in config.blocked_operations}
        elif config.allowed_operations:
            self._allowed_ops = {op.upper() for op in config.allowed_operations}

        # Add DDL/DCL to blocked if configured
        if config.block_ddl:
            self._blocked_ops = (self._blocked_ops or set()) | self.DDL_OPERATIONS
        if config.block_dcl:
            self._blocked_ops = (self._blocked_ops or set()) | self.DCL_OPERATIONS

        # Pre-process table/schema sets
        self._allowed_tables = self._build_set(
            config.allowed_tables, config.case_sensitive
        )
        self._blocked_tables = self._build_set(
            config.blocked_tables, config.case_sensitive
        )
        self._allowed_schemas = self._build_set(
            config.allowed_schemas, config.case_sensitive
        )
        self._blocked_schemas = self._build_set(
            config.blocked_schemas, config.case_sensitive
        )

        # Pre-process column sets
        self._required_columns = self._build_set(
            config.required_columns, config.case_sensitive
        )
        self._required_column_values = self._build_required_column_value_rules(
            config.required_column_values
        )

    def _build_set(self, items: list[str] | None, case_sensitive: bool) -> set[str] | None:
        """Build a set with proper casing."""
        if items is None:
            return None
        return {item if case_sensitive else item.lower() for item in items}

    def _normalize_name(self, name: str) -> str:
        """Normalize table/schema/column name for comparison."""
        return name if self.config.case_sensitive else name.lower()

    def _build_required_column_value_rules(
        self, rules: dict[str, str] | None
    ) -> list[RequiredColumnValueRule]:
        """Preprocess required column/value rules for fast matching."""
        if not rules:
            return []

        processed: list[RequiredColumnValueRule] = []
        for raw_column, context_key in rules.items():
            table_name: str | None = None
            column_name = raw_column

            if "." in raw_column:
                table_part, column_part = raw_column.split(".", 1)
                table_name = self._normalize_name(table_part.strip())
                column_name = column_part

            processed.append(
                RequiredColumnValueRule(
                    raw_column=raw_column,
                    table=table_name,
                    column=self._normalize_name(column_name.strip()),
                    context_key=context_key,
                )
            )

        return processed

    def _analyze_query_structure(self, stmt: exp.Expression) -> QueryAnalysis:
        """Analyze query structure in a single tree walk (performance optimization).

        Collects all necessary information for validation in one pass through the AST,
        avoiding multiple expensive tree traversals.

        Args:
            stmt: Parsed SQL statement (single statement)

        Returns:
            QueryAnalysis object with pre-computed metrics
        """
        analysis = QueryAnalysis()

        # Track top-level statement for context-aware column extraction
        top_level_select = stmt if isinstance(stmt, exp.Select) else None
        top_level_where = top_level_select.find(exp.Where) if top_level_select else None

        # Single tree walk to collect all metrics
        for node in stmt.walk():
            # Collect operations
            op_name = self._get_operation_name(node)
            if op_name:
                analysis.operations.add(op_name)

            # Collect SELECT nodes (for LIMIT checks)
            if isinstance(node, exp.Select):
                analysis.select_nodes.append(node)

            # Collect tables
            if isinstance(node, exp.Table):
                schema = node.db if node.db else None
                table_name = node.name if node.name else str(node)
                if table_name:
                    analysis.tables.append((schema, table_name))

            # Collect CTEs
            if isinstance(node, exp.CTE) and node.alias:
                analysis.defined_ctes.add(self._normalize_name(node.alias))

            # Count JOINs
            if isinstance(node, exp.Join):
                analysis.join_count += 1

            # Count set operations (UNION, INTERSECT, EXCEPT)
            if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
                analysis.union_count += 1

            # Collect columns
            if isinstance(node, exp.Column) and node.name:
                # All columns
                analysis.all_columns.append(node.name)

                # Top-level WHERE columns (excluding subqueries)
                if top_level_where and self._is_in_node_but_not_in_subqueries(
                    node, top_level_where
                ):
                    analysis.top_level_where_columns.append(node.name)

                # All WHERE columns (including subqueries)
                if self._is_in_where_clause(node):
                    analysis.all_where_columns.append(node.name)

                # Top-level SELECT columns
                if top_level_select and self._is_in_top_level_select(
                    node, top_level_select
                ):
                    analysis.top_level_select_columns.append(node.name)

                # All SELECT columns (including subqueries)
                if self._is_in_select_clause(node):
                    analysis.all_select_columns.append(node.name)

        # Calculate subquery depth
        analysis.max_subquery_depth = self._calculate_subquery_depth(stmt)

        return analysis

    def _is_in_node_but_not_in_subqueries(
        self, node: exp.Expression, target_node: exp.Expression
    ) -> bool:
        """Check if node is in target node but not in any nested SELECT subqueries."""
        # Walk up from node to see if we hit target_node before hitting a nested SELECT
        current = node.parent
        while current:
            if current is target_node:
                return True
            # If we hit a SELECT node before the target, node is in a subquery
            if isinstance(current, exp.Select) and current is not target_node:
                return False
            current = current.parent
        return False

    def _is_in_where_clause(self, column: exp.Column) -> bool:
        """Check if column is in any WHERE clause (including subqueries)."""
        current = column.parent
        while current:
            if isinstance(current, exp.Where):
                return True
            current = current.parent
        return False

    def _is_in_top_level_select(
        self, column: exp.Column, top_level_select: exp.Select
    ) -> bool:
        """Check if column is in top-level SELECT expressions (not subqueries)."""
        # Walk up from column to see if we're in the top-level SELECT
        current: exp.Expression | None = column
        while current:
            # If we hit the top-level SELECT, check if we're in its expressions
            if current is top_level_select:
                # Column is somewhere in this SELECT, but not in expressions list
                return False
            # If we're one of the top-level SELECT's expressions, we're top-level
            if current.parent is top_level_select and current in top_level_select.expressions:
                return True
            # If we hit another SELECT before the top-level, we're in a subquery
            if isinstance(current, exp.Select) and current is not top_level_select:
                return False
            current = current.parent
        return False

    def _is_in_select_clause(self, column: exp.Column) -> bool:
        """Check if column is in any SELECT clause (including subqueries)."""
        current: exp.Expression | None = column.parent
        while current:
            # Check if this column is in a SELECT's expressions
            if isinstance(current, exp.Select):
                for select_expr in current.expressions:
                    if self._is_descendant_of(column, select_expr):
                        return True
                return False
            current = current.parent
        return False

    def _is_descendant_of(
        self, node: exp.Expression, potential_ancestor: exp.Expression
    ) -> bool:
        """Check if node is a descendant of potential_ancestor."""
        current: exp.Expression | None = node
        while current:
            if current is potential_ancestor:
                return True
            current = current.parent
        return False

    def _is_top_level_select(self, select_node: exp.Select) -> bool:
        """Check if a SELECT node is top-level (not nested in another SELECT).

        A SELECT is considered top-level if it's not nested inside another SELECT.
        This properly handles cases like:
        - Simple SELECT: top-level
        - SELECT in subquery: not top-level
        - SELECT inside CTE definition: not top-level (has outer SELECT as ancestor)
        - Main SELECT with CTEs: top-level (the outer SELECT, not the CTE body)
        - SELECT in CREATE VIEW: not top-level
        - SELECT in INSERT SELECT: not top-level

        Args:
            select_node: SELECT node to check

        Returns:
            True if top-level, False if nested in another SELECT
        """
        # Walk up parent chain looking for another SELECT
        current = select_node.parent
        while current:
            # If we find another SELECT before reaching root, we're nested
            if isinstance(current, exp.Select):
                return False
            current = current.parent
        # Reached root without finding parent SELECT - we're top-level
        return True

    def _check_multi_statements(
        self, parsed: list, query: str
    ) -> EvaluatorResult | None:
        """Check multi-statement controls.

        Args:
            parsed: List of parsed SQL statements
            query: Original SQL query string

        Returns:
            EvaluatorResult if multi-statement rules are violated, None otherwise
        """
        stmt_count = len([stmt for stmt in parsed if stmt is not None])

        # Check if multi-statements are disallowed
        if not self.config.allow_multi_statements and stmt_count > 1:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=f"Multiple SQL statements not allowed (found {stmt_count} statements)",
                metadata={"statement_count": stmt_count, "query": query[:100]},
            )

        # Check max_statements limit
        if self.config.max_statements and stmt_count > self.config.max_statements:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=(
                    f"Too many SQL statements: {stmt_count} "
                    f"(max: {self.config.max_statements})"
                ),
                metadata={
                    "statement_count": stmt_count,
                    "max_statements": self.config.max_statements,
                    "query": query[:100],
                },
            )

        return None

    def _check_limits(
        self, analyses: list[QueryAnalysis], query: str
    ) -> EvaluatorResult | None:
        """Check LIMIT clause requirements for all SELECT queries.

        Recursively checks all SELECT statements including subqueries to ensure
        resource limits cannot be bypassed.

        Args:
            analyses: Pre-computed query analyses
            query: Original SQL query string

        Returns:
            EvaluatorResult if LIMIT rules are violated, None otherwise
        """
        for analysis in analyses:
            # Use pre-computed SELECT nodes
            for select_node in analysis.select_nodes:
                # Use args.get() to get direct LIMIT child, not find() which searches descendants
                # This prevents a subquery's LIMIT from being attributed to the outer query
                limit_node = select_node.args.get("limit")

                # Check if LIMIT is required but missing
                if self.config.require_limit and not limit_node:
                    # Determine if this is a subquery or top-level using AST parent relationships
                    is_top_level = self._is_top_level_select(select_node)
                    violation_type = (
                        "missing_limit"
                        if is_top_level
                        else "missing_limit_in_subquery"
                    )
                    message = (
                        "SELECT query must have a LIMIT clause"
                        if is_top_level
                        else "All SELECT queries (including subqueries) must have a LIMIT clause"
                    )

                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=message,
                        metadata={
                            "query": query[:100],
                            "violation": violation_type,
                        },
                    )

                # Check max_limit and max_result_window if LIMIT exists
                if limit_node:
                    limit_value = self._extract_limit_value(limit_node)

                    # Extract OFFSET value if present (use args.get() for direct child only)
                    offset_node = select_node.args.get("offset")
                    offset_value = 0
                    if offset_node:
                        offset_value = self._extract_offset_value(offset_node) or 0

                    # Check LIMIT value (skip if indeterminate)
                    if limit_value is not None:
                        # Check max_limit
                        if (
                            self.config.max_limit
                            and limit_value > self.config.max_limit
                        ):
                            return EvaluatorResult(
                                matched=True,
                                confidence=1.0,
                                message=(
                                    f"LIMIT value {limit_value} exceeds maximum "
                                    f"allowed {self.config.max_limit}"
                                ),
                                metadata={
                                    "limit_value": limit_value,
                                    "max_limit": self.config.max_limit,
                                    "query": query[:100],
                                },
                            )

                        # Check max_result_window (LIMIT + OFFSET)
                        if (
                            self.config.max_result_window
                            and offset_value is not None
                        ):
                            result_window = limit_value + offset_value
                            if result_window > self.config.max_result_window:
                                return EvaluatorResult(
                                    matched=True,
                                    confidence=1.0,
                                    message=(
                                        f"Result window (LIMIT + OFFSET = {result_window}) "
                                        f"exceeds maximum allowed {self.config.max_result_window}"
                                    ),
                                    metadata={
                                        "limit_value": limit_value,
                                        "offset_value": offset_value,
                                        "result_window": result_window,
                                        "max_result_window": self.config.max_result_window,
                                        "query": query[:100],
                                    },
                                )

        return None

    def _extract_limit_value(self, limit_node: exp.Limit) -> int | None:
        """Extract numeric LIMIT value from LIMIT node.

        Args:
            limit_node: sqlglot LIMIT expression

        Returns:
            Integer LIMIT value, or None if cannot be determined
        """
        if not limit_node.expression:
            return None

        # Handle literal numeric values
        if isinstance(limit_node.expression, exp.Literal):
            try:
                return int(limit_node.expression.this)
            except (ValueError, TypeError):
                return None

        # Cannot determine (ALL, NULL, parameters, expressions)
        return None

    def _extract_offset_value(self, offset_node: exp.Offset) -> int | None:
        """Extract numeric OFFSET value from OFFSET node.

        Args:
            offset_node: sqlglot OFFSET expression

        Returns:
            Integer OFFSET value, or None if cannot be determined
        """
        if not offset_node.expression:
            return None

        # Handle literal numeric values
        if isinstance(offset_node.expression, exp.Literal):
            try:
                return int(offset_node.expression.this)
            except (ValueError, TypeError):
                return None

        # Cannot determine (parameters, expressions)
        return None

    def _check_complexity(
        self, analyses: list[QueryAnalysis], query: str
    ) -> EvaluatorResult | None:
        """Check query complexity limits.

        Checks for:
        - Subquery nesting depth
        - Number of JOIN operations
        - Number of UNION/INTERSECT/EXCEPT operations

        Args:
            analyses: Pre-computed query analyses
            query: Original SQL query string

        Returns:
            EvaluatorResult if complexity limits are violated, None otherwise
        """
        for analysis in analyses:
            # Check subquery depth (pre-computed)
            if self.config.max_subquery_depth:
                max_depth = analysis.max_subquery_depth
                if max_depth > self.config.max_subquery_depth:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            f"Query exceeds maximum subquery depth: {max_depth} "
                            f"(max: {self.config.max_subquery_depth})"
                        ),
                        metadata={
                            "subquery_depth": max_depth,
                            "max_subquery_depth": self.config.max_subquery_depth,
                            "query": query[:100],
                        },
                    )

            # Check number of JOINs (pre-computed)
            if self.config.max_joins:
                join_count = analysis.join_count
                if join_count > self.config.max_joins:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            f"Query exceeds maximum number of JOINs: {join_count} "
                            f"(max: {self.config.max_joins})"
                        ),
                        metadata={
                            "join_count": join_count,
                            "max_joins": self.config.max_joins,
                            "query": query[:100],
                        },
                    )

            # Check number of UNION/INTERSECT/EXCEPT operations (pre-computed)
            if self.config.max_union_count:
                union_count = analysis.union_count
                if union_count > self.config.max_union_count:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            f"Query exceeds maximum number of set operations: "
                            f"{union_count} (max: {self.config.max_union_count})"
                        ),
                        metadata={
                            "union_count": union_count,
                            "max_union_count": self.config.max_union_count,
                            "query": query[:100],
                        },
                    )

        return None

    def _calculate_subquery_depth(self, node: exp.Expression) -> int:
        """Calculate maximum subquery nesting depth recursively.

        Depth is the number of nested SELECT layers:
        - SELECT ... FROM table -> depth 0
        - SELECT ... FROM (SELECT ...) -> depth 1
        - SELECT ... FROM (SELECT ... FROM (SELECT ...)) -> depth 2

        Args:
            node: Current AST node

        Returns:
            Maximum nesting depth found (0 for no subqueries)
        """
        # Find maximum depth across all children
        max_depth = 0

        for child in node.iter_expressions():
            if isinstance(child, exp.Select):
                # Direct child SELECT found - this is a nested subquery
                # Calculate its depth and add 1 for this nesting level
                child_depth = self._calculate_subquery_depth(child)
                max_depth = max(max_depth, child_depth + 1)
            else:
                # Not a SELECT but might contain nested SELECTs
                # Recurse without adding depth
                child_depth = self._calculate_subquery_depth(child)
                max_depth = max(max_depth, child_depth)

        return max_depth

    def _create_query_metadata(
        self, query: str, additional_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create enhanced metadata for query validation.

        Provides smart truncation for long queries and includes a query hash
        for tracking without exposing full query content.

        Args:
            query: Original SQL query string
            additional_data: Additional metadata fields to include

        Returns:
            Dict with query snippet, hash, length, and any additional data
        """
        metadata: dict[str, Any] = {}

        # Smart truncation: show beginning and end for long queries
        max_snippet_length = 200
        if len(query) > max_snippet_length:
            # Show first 100 and last 100 characters with ellipsis
            query_snippet = query[:100] + "..." + query[-100:]
        else:
            query_snippet = query

        metadata["query_snippet"] = query_snippet
        metadata["query_length"] = len(query)

        # Add query hash for tracking (first 16 chars of SHA-256)
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        metadata["query_hash"] = query_hash

        # Add any additional metadata
        if additional_data:
            metadata.update(additional_data)

        return metadata

    def _extract_query_and_context(self, data: Any) -> tuple[str, dict[str, Any]]:
        """Extract SQL query and optional runtime context from evaluation payload."""
        if isinstance(data, str):
            return data, {}

        if not isinstance(data, dict):
            return str(data), {}

        context_data = data.get("context")
        context = context_data if isinstance(context_data, dict) else {}

        if "input" in data and "type" in data:
            # Full step payload selected by selector="*"
            input_data = data.get("input")
            if isinstance(input_data, str):
                return input_data, context

            if isinstance(input_data, dict):
                query_data = input_data.get("query", "")
                if query_data is None:
                    return "", context
                return (
                    query_data if isinstance(query_data, str) else str(query_data),
                    context,
                )

            if input_data is None:
                return "", context

            return str(input_data), context

        query_data = data.get("query", "")
        if query_data is None:
            return "", context
        return query_data if isinstance(query_data, str) else str(query_data), context

    def _is_scalar_context_value(self, value: Any) -> bool:
        """Return True when context value is scalar and comparable to SQL literals."""
        return isinstance(value, (str, int, float, bool))

    def _statement_accesses_physical_tables(self, analysis: QueryAnalysis) -> bool:
        """Return True when statement references at least one non-CTE table."""
        for _schema, table_name in analysis.tables:
            if self._normalize_name(table_name) not in analysis.defined_ctes:
                return True
        return False

    def _get_top_level_where_clause(self, stmt: exp.Expression) -> exp.Where | None:
        """Get top-level WHERE node for statement when present."""
        where_node = stmt.args.get("where")
        return where_node if isinstance(where_node, exp.Where) else None

    def _has_ancestor_of_type(
        self,
        node: exp.Expression,
        stop_node: exp.Expression,
        ancestor_type: type[exp.Expression],
    ) -> bool:
        """Check whether node has a specific ancestor before reaching stop_node."""
        current = node.parent
        while current and current is not stop_node:
            if isinstance(current, ancestor_type):
                return True
            current = current.parent
        return False

    def _build_alias_to_base_table_map(
        self, stmt: exp.Expression, analysis: QueryAnalysis
    ) -> tuple[dict[str, str], set[str]]:
        """Build alias/base-table map for top-level table references."""
        alias_to_base: dict[str, str] = {}
        base_tables: set[str] = set()

        for table_node in stmt.find_all(exp.Table):
            if not table_node.name:
                continue
            if not self._is_in_node_but_not_in_subqueries(table_node, stmt):
                continue

            base_table = self._normalize_name(table_node.name)
            if base_table in analysis.defined_ctes:
                continue

            base_tables.add(base_table)
            alias_to_base[base_table] = base_table

            alias_name = table_node.alias_or_name
            if alias_name:
                alias_to_base[self._normalize_name(alias_name)] = base_table

        return alias_to_base, base_tables

    def _extract_column_literal_from_eq(
        self, eq_node: exp.EQ
    ) -> tuple[exp.Column, exp.Literal] | None:
        """Extract (column, literal) from EQ regardless of operand side order."""
        if isinstance(eq_node.this, exp.Column) and isinstance(eq_node.expression, exp.Literal):
            return eq_node.this, eq_node.expression
        if isinstance(eq_node.expression, exp.Column) and isinstance(eq_node.this, exp.Literal):
            return eq_node.expression, eq_node.this
        return None

    def _column_matches_rule(
        self,
        column_expr: exp.Column,
        rule: RequiredColumnValueRule,
        alias_to_base: dict[str, str],
    ) -> bool:
        """Check whether column expression matches configured rule reference."""
        if self._normalize_name(column_expr.name) != rule.column:
            return False

        if rule.table is None:
            return True

        column_qualifier = column_expr.table
        if not column_qualifier:
            return False

        qualifier_norm = self._normalize_name(column_qualifier)
        resolved_base = alias_to_base.get(qualifier_norm, qualifier_norm)
        return resolved_base == rule.table

    def _check_column_values(
        self,
        parsed_statements: list[exp.Expression],
        analyses: list[QueryAnalysis],
        query: str,
        context: dict[str, Any],
    ) -> EvaluatorResult | None:
        """Check required column equality/value rules for multi-tenant filtering."""
        if not self._required_column_values:
            return None

        for statement_index, (stmt, analysis) in enumerate(
            zip(parsed_statements, analyses, strict=False)
        ):
            if not self._statement_accesses_physical_tables(analysis):
                continue

            top_level_where = self._get_top_level_where_clause(stmt)
            if top_level_where is None:
                return EvaluatorResult(
                    matched=True,
                    confidence=1.0,
                    message=(
                        "Table-accessing statement is missing top-level WHERE clause required "
                        "for required_column_values"
                    ),
                    metadata=self._create_query_metadata(
                        query,
                        {
                            "violation": "missing_top_level_where",
                            "statement_index": statement_index,
                        },
                    ),
                )

            alias_to_base, base_tables = self._build_alias_to_base_table_map(stmt, analysis)

            for rule in self._required_column_values:
                if rule.context_key not in context:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            "Missing context value for required_column_values rule "
                            f"'{rule.raw_column}'. Use selector '*' so step context is available."
                        ),
                        metadata=self._create_query_metadata(
                            query,
                            {
                                "violation": "missing_context_value",
                                "required_column": rule.raw_column,
                                "context_key": rule.context_key,
                                "statement_index": statement_index,
                            },
                        ),
                    )

                expected_value = context[rule.context_key]
                if not self._is_scalar_context_value(expected_value):
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            "required_column_values context value must be scalar "
                            f"(str/int/float/bool) for key '{rule.context_key}'"
                        ),
                        metadata=self._create_query_metadata(
                            query,
                            {
                                "violation": "invalid_context_value_type",
                                "required_column": rule.raw_column,
                                "context_key": rule.context_key,
                                "context_value_type": type(expected_value).__name__,
                                "statement_index": statement_index,
                            },
                        ),
                    )

                if rule.table is None and len(base_tables) > 1:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            "Table qualification is required for required_column_values "
                            "when query references multiple tables"
                        ),
                        metadata=self._create_query_metadata(
                            query,
                            {
                                "violation": "ambiguous_unqualified_column",
                                "required_column": rule.raw_column,
                                "base_tables": sorted(base_tables),
                                "statement_index": statement_index,
                            },
                        ),
                    )

                found_valid_predicate = False
                expected_literal = str(expected_value)
                for eq_node in top_level_where.find_all(exp.EQ):
                    if not self._is_in_node_but_not_in_subqueries(eq_node, top_level_where):
                        continue
                    if self._has_ancestor_of_type(eq_node, top_level_where, exp.Not):
                        continue
                    if self._has_ancestor_of_type(eq_node, top_level_where, exp.Or):
                        continue

                    column_and_literal = self._extract_column_literal_from_eq(eq_node)
                    if not column_and_literal:
                        continue

                    column_expr, literal_expr = column_and_literal
                    if not self._column_matches_rule(column_expr, rule, alias_to_base):
                        continue

                    if str(literal_expr.this) != expected_literal:
                        continue

                    found_valid_predicate = True
                    break

                if not found_valid_predicate:
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=(
                            "Required equality predicate not found in top-level WHERE: "
                            f"'{rule.raw_column}' must equal context['{rule.context_key}']"
                        ),
                        metadata=self._create_query_metadata(
                            query,
                            {
                                "violation": "missing_or_invalid_value_predicate",
                                "required_column": rule.raw_column,
                                "context_key": rule.context_key,
                                "statement_index": statement_index,
                            },
                        ),
                    )

        return None

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate SQL query against all configured controls.

        Offloads CPU-bound validation to a thread to avoid blocking the event loop.

        Args:
            data: SQL query string or dict with 'query' key

        Returns:
            EvaluatorResult with matched=True if any control triggers
        """
        try:
            return await asyncio.to_thread(self._evaluate_sync, data)
        except Exception as e:
            # Unexpected evaluator error - fail open with error field set
            logger.error(
                "SQL evaluator unexpected error",
                exc_info=True,
                extra={"error_type": type(e).__name__},
            )
            return EvaluatorResult(
                matched=False,
                confidence=0.0,
                message="SQL evaluator encountered an unexpected error",
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )

    def _evaluate_sync(self, data: Any) -> EvaluatorResult:
        """Synchronous implementation of SQL validation logic.

        Args:
            data: SQL query string or dict with 'query' key

        Returns:
            EvaluatorResult with matched=True if any control triggers
        """
        # Extract SQL query
        if data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No SQL query provided",
            )

        query, context = self._extract_query_and_context(data)

        if not query.strip():
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="Empty SQL query",
            )

        # 1. Parse SQL (for all AST-based controls)
        # Skip parsing if no AST-based controls are configured
        needs_parsing = any([
            self._blocked_ops,
            self._allowed_ops,
            self._allowed_tables,
            self._blocked_tables,
            self._allowed_schemas,
            self._blocked_schemas,
            self._required_columns,
            self._required_column_values,
            self.config.require_limit,
            self.config.max_limit is not None,
            self.config.max_result_window is not None,
            self.config.max_subquery_depth is not None,
            self.config.max_joins is not None,
            self.config.max_union_count is not None,
            not self.config.allow_multi_statements,
            self.config.max_statements is not None,
        ])

        if not needs_parsing:
            # No controls triggered
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No SQL controls triggered",
            )

        # Parse the SQL
        try:
            parsed = sqlglot.parse(query, read=self.config.dialect, error_level=None)
        except Exception as e:
            # Parsing failed - log the error with stack trace
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
            logger.warning(
                "SQL parsing failed",
                exc_info=True,  # Include full stack trace
                extra={
                    "query_hash": query_hash,
                    "query_length": len(query),
                    "dialect": self.config.dialect,
                    "error_type": type(e).__name__,
                },
            )

            # Invalid SQL fails validation (not an evaluator error, just bad input)
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=f"SQL parsing failed: {str(e)[:200]}",
                metadata=self._create_query_metadata(query),
            )

        if not parsed or all(stmt is None for stmt in parsed):
            # Invalid SQL fails validation
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Could not parse SQL query: no valid statements found",
                metadata=self._create_query_metadata(query),
            )

        parsed_statements = [stmt for stmt in parsed if stmt is not None]

        # 2. Check multi-statements
        if not self.config.allow_multi_statements or self.config.max_statements:
            multi_stmt_result = self._check_multi_statements(parsed, query)
            if multi_stmt_result:
                return multi_stmt_result

        # 3. Analyze query structure once (single tree walk for performance)
        # This avoids multiple expensive tree traversals
        analyses = [self._analyze_query_structure(stmt) for stmt in parsed_statements]

        # 4. Check operations
        if self._blocked_ops or self._allowed_ops:
            operation_result = self._check_operations(analyses, query)
            if operation_result:
                return operation_result

        # 5. Check tables/schemas (objects)
        if (
            self._allowed_tables
            or self._blocked_tables
            or self._allowed_schemas
            or self._blocked_schemas
        ):
            table_result = self._check_tables(analyses, query)
            if table_result:
                return table_result

        # 6. Check column presence
        if self._required_columns:
            column_result = self._check_columns(analyses, query)
            if column_result:
                return column_result

        # 6.5. Check column value constraints
        if self._required_column_values:
            column_value_result = self._check_column_values(
                parsed_statements=parsed_statements,
                analyses=analyses,
                query=query,
                context=context,
            )
            if column_value_result:
                return column_value_result

        # 7. Check LIMIT constraints
        if (
            self.config.require_limit
            or self.config.max_limit
            or self.config.max_result_window
        ):
            limit_result = self._check_limits(analyses, query)
            if limit_result:
                return limit_result

        # 8. Check query complexity limits
        if (
            self.config.max_subquery_depth
            or self.config.max_joins
            or self.config.max_union_count
        ):
            complexity_result = self._check_complexity(analyses, query)
            if complexity_result:
                return complexity_result

        # No controls triggered
        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="SQL query passed all controls",
        )

    def _check_operations(
        self, analyses: list[QueryAnalysis], query: str
    ) -> EvaluatorResult | None:
        """Check SQL operations against blocked/allowed lists.

        When both blocked and allowed operations are configured (e.g., via
        allowed_operations + block_ddl), BOTH checks are enforced. An operation
        must pass both checks to be allowed.

        Args:
            analyses: Pre-computed query analyses
            query: Original SQL query string

        Returns:
            EvaluatorResult if operations violate rules, None otherwise
        """
        # Collect all operations from all analyses
        operations = set()
        for analysis in analyses:
            operations.update(analysis.operations)

        if not operations:
            # No operations detected - block unknown/unsupported SQL
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Could not extract operations from SQL query",
                metadata=self._create_query_metadata(query),
            )

        # Check against rules - enforce BOTH blocked and allowed if both are set
        blocked_found = []

        # First check: Blocked operations
        if self._blocked_ops:
            for op in operations:
                if op in self._blocked_ops:
                    blocked_found.append(op)

        # Second check: Allowed operations (independent of blocked check)
        # This ensures allowed_operations is enforced even when block_ddl/block_dcl is used
        if self._allowed_ops:
            for op in operations:
                if op not in self._allowed_ops and op not in blocked_found:
                    # Operation not in allowlist and not already blocked
                    blocked_found.append(op)

        if blocked_found:
            msg = f"Blocked SQL operations detected: {', '.join(sorted(blocked_found))}"
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=msg,
                metadata=self._create_query_metadata(
                    query,
                    {
                        "operations": list(operations),
                        "blocked": blocked_found,
                    },
                ),
            )

        return None

    def _extract_operations(self, parsed: list) -> list[str]:
        """Extract operation types from parsed SQL.

        Recursively walks the entire query tree to detect all operations,
        including those in subqueries, CTEs, and nested expressions.
        """
        operations = []

        for stmt in parsed:
            if stmt is None:
                continue

            # Walk entire query tree to find all operations
            for node in stmt.walk():
                op_name = self._get_operation_name(node)
                if op_name and op_name not in operations:
                    operations.append(op_name)

        return operations

    def _get_operation_name(self, stmt: exp.Expression) -> str | None:
        """Map sqlglot expression to operation name.

        Returns the SQL operation type for the given expression node.
        Covers all major SQL operations including DML, DDL, DCL, and TCL.

        Note: Some SQL commands (SHOW, LOCK, etc.) may parse to exp.Command
        which is sqlglot's fallback type for unsupported syntax.
        """
        type_map = {
            # DML (Data Manipulation Language)
            exp.Select: "SELECT",
            exp.Insert: "INSERT",
            exp.Update: "UPDATE",
            exp.Delete: "DELETE",
            exp.Merge: "MERGE",
            # DDL (Data Definition Language)
            exp.Create: "CREATE",
            exp.Drop: "DROP",
            exp.Alter: "ALTER",
            exp.TruncateTable: "TRUNCATE",
            exp.Comment: "COMMENT",
            # DCL (Data Control Language)
            exp.Grant: "GRANT",
            exp.Revoke: "REVOKE",
            # TCL (Transaction Control Language)
            exp.Commit: "COMMIT",
            exp.Rollback: "ROLLBACK",
            # Utility Commands
            exp.Set: "SET",
            exp.Show: "SHOW",
            exp.Use: "USE",
            exp.Describe: "DESCRIBE",
            exp.Copy: "COPY",
            exp.Lock: "LOCK",
            exp.Analyze: "ANALYZE",
            # Fallback for unsupported commands
            exp.Command: "COMMAND",
        }

        for expr_type, op_name in type_map.items():
            if isinstance(stmt, expr_type):
                return op_name

        return None

    def _check_tables(
        self, analyses: list[QueryAnalysis], query: str
    ) -> EvaluatorResult | None:
        """Check table/schema access against restrictions.

        Args:
            analyses: Pre-computed query analyses
            query: Original SQL query string

        Returns:
            EvaluatorResult if tables violate rules, None otherwise
        """
        # Collect all tables from all analyses
        tables = []
        defined_ctes = set()
        for analysis in analyses:
            tables.extend(analysis.tables)
            defined_ctes.update(analysis.defined_ctes)

        if not tables and (self._allowed_tables or self._allowed_schemas):
            # No tables detected but restrictions are in place
            # This might be a non-table query (e.g., SELECT 1) which is fine
            return None

        # Check restrictions
        violations = []

        for schema, table in tables:
            schema_norm = self._normalize_name(schema) if schema else None
            table_norm = self._normalize_name(table)

            # Ignore if it's a CTE defined in the query
            if not schema_norm and table_norm in defined_ctes:
                continue

            # Check schema restrictions
            if schema_norm:
                if self._blocked_schemas and schema_norm in self._blocked_schemas:
                    violations.append(f"{schema}.{table} (blocked schema)")
                    continue

                if self._allowed_schemas and schema_norm not in self._allowed_schemas:
                    violations.append(f"{schema}.{table} (schema not allowed)")
                    continue

            # Check table restrictions
            if self._blocked_tables and table_norm in self._blocked_tables:
                violations.append(f"{table} (blocked table)")
                continue

            if self._allowed_tables and table_norm not in self._allowed_tables:
                violations.append(f"{table} (table not allowed)")
                continue

        if violations:
            msg = f"Table access violations: {', '.join(violations[:3])}"
            if len(violations) > 3:
                msg += f" (+{len(violations) - 3} more)"

            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=msg,
                metadata=self._create_query_metadata(
                    query,
                    {
                        "tables_accessed": [
                            {"schema": s, "table": t} for s, t in tables
                        ],
                        "violations": violations,
                    },
                ),
            )

        return None

    def _extract_tables(self, parsed: list) -> list[tuple[str | None, str]]:
        """Extract (schema, table) tuples from parsed SQL."""
        tables = []

        for stmt in parsed:
            if stmt is None:
                continue

            # Find all table references in the AST
            for table in stmt.find_all(exp.Table):
                schema = table.db if table.db else None
                table_name = table.name if table.name else str(table)

                if table_name:
                    tables.append((schema, table_name))

        return tables

    def _check_columns(
        self, analyses: list[QueryAnalysis], query: str
    ) -> EvaluatorResult | None:
        """Check column presence requirements.

        Args:
            analyses: Pre-computed query analyses
            query: Original SQL query string

        Returns:
            EvaluatorResult if required columns are missing, None otherwise
        """
        # Early return if no required columns (caller should check, but be defensive)
        if not self._required_columns:
            return None

        # Collect columns from all analyses based on context and scope
        columns = []
        for analysis in analyses:
            if self.config.column_context == "where":
                if self.config.column_context_scope == "top_level":
                    columns.extend(analysis.top_level_where_columns)
                else:  # all
                    columns.extend(analysis.all_where_columns)
            elif self.config.column_context == "select":
                if self.config.column_context_scope == "top_level":
                    columns.extend(analysis.top_level_select_columns)
                else:  # all
                    columns.extend(analysis.all_select_columns)
            else:  # None - anywhere
                columns.extend(analysis.all_columns)

        if not columns:
            # No columns detected - required columns are missing
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=f"Required columns not found: {', '.join(self._required_columns)}",
                metadata=self._create_query_metadata(
                    query,
                    {
                        "required_columns": list(self._required_columns),
                        "column_context": self.config.column_context,
                    },
                ),
            )

        # Normalize columns
        columns_norm = {self._normalize_name(col) for col in columns}

        # Check if required columns are present
        if self.config.column_presence_logic == "any":
            # At least one required column must be present
            has_required = bool(self._required_columns & columns_norm)
        else:  # all
            # All required columns must be present
            has_required = self._required_columns.issubset(columns_norm)

        if not has_required:
            missing = self._required_columns - columns_norm
            msg = f"Required columns missing: {', '.join(missing)}"

            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=msg,
                metadata=self._create_query_metadata(
                    query,
                    {
                        "required_columns": list(self._required_columns),
                        "found_columns": list(columns_norm),
                        "missing_columns": list(missing),
                        "column_context": self.config.column_context,
                    },
                ),
            )

        return None

    def _extract_columns(
        self, parsed: list, context: str | None
    ) -> list[str]:
        """Extract column names from parsed SQL based on context.

        Args:
            parsed: Parsed SQL statements
            context: 'select', 'where', or None (anywhere)

        Returns:
            List of column names

        Notes:
            - For multi-tenant RLS, use context='where' with
              column_context_scope='top_level' to ensure tenant filtering
              is in the outer query.
            - column_context_scope controls whether to check only top-level
              clauses or all clauses including subqueries.
        """
        columns = []

        for stmt in parsed:
            if stmt is None:
                continue

            if context == "where":
                # Check WHERE clause(s) based on scope
                if self.config.column_context_scope == "top_level":
                    # Only check top-level WHERE for security
                    # Must exclude columns from subqueries within the WHERE
                    where_clause = stmt.find(exp.Where)
                    if where_clause:
                        # Collect all columns from the WHERE clause
                        all_where_columns = {
                            col
                            for col in where_clause.find_all(exp.Column)
                            if col.name
                        }

                        # Collect columns that are inside subqueries within the WHERE
                        subquery_columns = set()
                        for subquery in where_clause.find_all(exp.Select):
                            for col in subquery.find_all(exp.Column):
                                if col.name:
                                    subquery_columns.add(col)

                        # Only include columns that are NOT in subqueries
                        top_level_where_columns = all_where_columns - subquery_columns
                        for column in top_level_where_columns:
                            columns.append(column.name)
                else:
                    # Check all WHERE clauses (backward compatible)
                    for where in stmt.find_all(exp.Where):
                        for column in where.find_all(exp.Column):
                            if column.name:
                                columns.append(column.name)

            elif context == "select":
                # Check SELECT clause based on scope
                if isinstance(stmt, exp.Select):
                    if self.config.column_context_scope == "top_level":
                        # Only check top-level SELECT expressions
                        for select_expr in stmt.expressions:
                            # Find all columns in each expression
                            # (not just bare columns)
                            for column in select_expr.find_all(exp.Column):
                                if column.name:
                                    columns.append(column.name)
                    else:
                        # Check all SELECT clauses including subqueries
                        for select_node in stmt.find_all(exp.Select):
                            for select_expr in select_node.expressions:
                                for column in select_expr.find_all(exp.Column):
                                    if column.name:
                                        columns.append(column.name)

            else:
                # Extract all columns anywhere in query
                for column in stmt.find_all(exp.Column):
                    if column.name:
                        columns.append(column.name)

        return columns
