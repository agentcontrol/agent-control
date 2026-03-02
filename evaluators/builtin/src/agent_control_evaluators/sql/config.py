"""Configuration for SQL validation evaluator."""

import warnings
from typing import Literal

from pydantic import Field, model_validator

from agent_control_evaluators._base import EvaluatorConfig


class SQLEvaluatorConfig(EvaluatorConfig):
    """Configuration for comprehensive SQL control evaluator.

    Validates SQL query strings using AST-based analysis via sqlglot.
    Controls are evaluated in order:
    syntax → multi-statement → operations → tables/schemas → columns → limits.
    """

    # Multi-Statement
    allow_multi_statements: bool = Field(
        default=True,
        description=(
            "Whether to allow multiple SQL statements in a single query. "
            "Set to False to prevent queries like 'SELECT x; DROP TABLE y' "
            "(SQL injection prevention)."
        ),
    )
    max_statements: int | None = Field(
        default=None,
        description=(
            "Maximum number of statements allowed (e.g., 2 allows up to 2 statements). "
            "Only applicable when allow_multi_statements=True."
        ),
    )

    # Operations
    blocked_operations: list[str] | None = Field(
        default=None,
        description=(
            "SQL operations to block (e.g., ['DROP', 'DELETE', 'TRUNCATE']). "
            "Cannot be used with allowed_operations."
        ),
    )
    allowed_operations: list[str] | None = Field(
        default=None,
        description=(
            "SQL operations to allow (e.g., ['SELECT'] for read-only). "
            "Cannot be used with blocked_operations."
        ),
    )
    block_ddl: bool = Field(
        default=False,
        description="Block all DDL operations (CREATE, ALTER, DROP, TRUNCATE, RENAME, COMMENT).",
    )
    block_dcl: bool = Field(
        default=False,
        description="Block all DCL operations (GRANT, REVOKE).",
    )

    # Table/Schema Access
    allowed_tables: list[str] | None = Field(
        default=None,
        description="Table names allowed (allowlist mode). Cannot be used with blocked_tables.",
    )
    blocked_tables: list[str] | None = Field(
        default=None,
        description="Table names to block (blocklist mode). Cannot be used with allowed_tables.",
    )
    allowed_schemas: list[str] | None = Field(
        default=None,
        description="Schema names allowed (allowlist mode). Cannot be used with blocked_schemas.",
    )
    blocked_schemas: list[str] | None = Field(
        default=None,
        description="Schema names to block (blocklist mode). Cannot be used with allowed_schemas.",
    )

    # Column Presence
    required_columns: list[str] | None = Field(
        default=None,
        description=(
            "Columns that must be present in the query "
            "(e.g., ['tenant_id'] for multi-tenant security)."
        ),
    )
    column_presence_logic: Literal["any", "all"] = Field(
        default="any",
        description="Matching logic for required_columns: 'any' or 'all'.",
    )
    column_context: Literal["select", "where"] | None = Field(
        default=None,
        description="Where required columns must appear: 'select', 'where', or None (anywhere).",
    )
    column_context_scope: Literal["top_level", "all"] = Field(
        default="all",
        description=(
            "Scope for column_context checking. "
            "'top_level': Only check top-level clause. "
            "'all': Check all clauses including subqueries."
        ),
    )
    required_column_values: dict[str, str] | None = Field(
        default=None,
        description=(
            "Map of column references to context keys for value-based tenant filtering. "
            "Each required column must appear in a top-level WHERE equality predicate "
            "with a literal value that matches the corresponding context value. "
            "Column references may be unqualified ('user_id') or table-qualified "
            "('users.user_id')."
        ),
    )

    # Limits
    require_limit: bool = Field(
        default=False,
        description="Require SELECT queries to have a LIMIT clause.",
    )
    max_limit: int | None = Field(
        default=None,
        description="Maximum allowed LIMIT value.",
    )
    max_result_window: int | None = Field(
        default=None,
        description="Maximum value of (LIMIT + OFFSET) for pagination control.",
    )

    # Options
    case_sensitive: bool = Field(
        default=False,
        description="Whether table/column/schema name matching is case sensitive.",
    )
    dialect: Literal["postgres", "mysql", "tsql", "oracle", "sqlite"] = Field(
        default="postgres",
        description="SQL dialect to use for parsing.",
    )

    # Query Complexity Limits
    max_subquery_depth: int | None = Field(
        default=None,
        description="Maximum nesting depth for subqueries.",
    )
    max_joins: int | None = Field(
        default=None,
        description="Maximum number of JOIN operations in a single query.",
    )
    max_union_count: int | None = Field(
        default=None,
        description="Maximum number of UNION/INTERSECT/EXCEPT operations.",
    )

    @model_validator(mode="after")
    def validate_config(self) -> "SQLEvaluatorConfig":
        """Validate configuration constraints."""
        # Validate operation restrictions
        if self.blocked_operations and self.allowed_operations:
            raise ValueError(
                "Cannot specify both blocked_operations and allowed_operations"
            )

        # Validate table restrictions
        if self.allowed_tables and self.blocked_tables:
            raise ValueError("Cannot specify both allowed_tables and blocked_tables")

        # Validate schema restrictions
        if self.allowed_schemas and self.blocked_schemas:
            raise ValueError(
                "Cannot specify both allowed_schemas and blocked_schemas"
            )

        # Validate limit controls
        if self.max_limit is not None and self.max_limit <= 0:
            raise ValueError("max_limit must be a positive integer")

        # Validate multi-statement controls
        if not self.allow_multi_statements and self.max_statements is not None:
            raise ValueError(
                "max_statements is only applicable when allow_multi_statements=True"
            )

        if self.max_statements is not None and self.max_statements <= 0:
            raise ValueError("max_statements must be a positive integer")

        # Validate column controls
        if self.column_context and not self.required_columns:
            warnings.warn(
                "column_context is set but required_columns is empty - "
                "column_context will be ignored"
            )
        if self.required_column_values:
            for column_ref, context_key in self.required_column_values.items():
                if not column_ref.strip():
                    raise ValueError(
                        "required_column_values contains an empty column reference"
                    )

                if "." in column_ref:
                    table_name, column_name = column_ref.split(".", 1)
                    if not table_name.strip() or not column_name.strip():
                        raise ValueError(
                            "required_column_values column references must use "
                            "'table.column' format when qualified"
                        )

                if not context_key.strip():
                    raise ValueError(
                        "required_column_values contains an empty context key"
                    )

            if self.column_context == "select":
                warnings.warn(
                    "required_column_values is configured with column_context='select' "
                    "- value checks only apply to WHERE predicates"
                )

        # Validate LIMIT controls
        if self.max_limit and not self.require_limit:
            warnings.warn(
                "max_limit is set but require_limit is False - "
                "max_limit only enforced if LIMIT clause exists"
            )

        return self
