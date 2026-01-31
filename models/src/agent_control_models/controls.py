"""Control definition models for agent protection."""

import warnings
from typing import Any, Literal, Self
from uuid import uuid4

import re2
from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import BaseModel


class ControlSelector(BaseModel):
    """Selects data from a Step payload.

    - path: which slice of the Step to feed into the evaluator. Optional, defaults to "*"
      meaning the entire Step object.
    """

    path: str | None = Field(
        default="*",
        description=(
            "Path to data using dot notation. "
            "Examples: 'input', 'output', 'context.user_id', 'name', 'type', '*'"
        ),
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str | None) -> str:
        """Validate path; None becomes '*', empty string raises."""
        if v is None:
            return "*"
        if v == "":
            raise ValueError(
                "Path cannot be empty string. Use '*' for root or omit the field."
            )

        # Valid root fields
        valid_roots = {"input", "output", "name", "type", "context", "*"}
        root = v.split(".")[0]

        if root not in valid_roots:
            raise ValueError(
                f"Invalid path root '{root}'. "
                f"Must be one of: {', '.join(sorted(valid_roots))}"
            )
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"path": "output"},
                {"path": "context.user_id"},
                {"path": "input"},
                {"path": "*"},
                {"path": "name"},
                {"path": "output"},
            ]
        }
    }


class ControlScope(BaseModel):
    """Defines when a control applies to a Step."""

    step_types: list[str] | None = Field(
        default=None,
        description=(
            "Step types this control applies to (omit to apply to all types). "
            "Built-in types are 'tool' and 'llm'."
        ),
    )
    step_names: list[str] | None = Field(
        default=None,
        description="Exact step names this control applies to",
    )
    step_name_regex: str | None = Field(
        default=None,
        description="RE2 pattern matched with search() against step name",
    )
    stages: list[Literal["pre", "post"]] | None = Field(
        default=None,
        description="Evaluation stages this control applies to",
    )

    @field_validator("step_types")
    @classmethod
    def validate_step_types(
        cls, v: list[str] | None
    ) -> list[str] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError(
                "step_types cannot be an empty list. Use None/omit the field to apply to all types."
            )
        if any((not isinstance(x, str) or not x) for x in v):
            raise ValueError("step_types must be a list of non-empty strings")
        return v

    @field_validator("step_names")
    @classmethod
    def validate_step_names(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError(
                "step_names cannot be an empty list. Use None/omit the field to apply to all steps."
            )
        if any((not isinstance(x, str) or not x) for x in v):
            raise ValueError("step_names must be a list of non-empty strings")
        return v

    @field_validator("step_name_regex")
    @classmethod
    def validate_step_name_regex(
        cls, v: str | None, info: ValidationInfo
    ) -> str | None:
        if v is None:
            return v
        if info.context and info.context.get("allow_invalid_step_name_regex"):
            return v
        try:
            re2.compile(v)
        except re2.error as e:
            raise ValueError(f"Invalid step_name_regex: {e}") from e
        return v

    @field_validator("stages")
    @classmethod
    def validate_stages(
        cls, v: list[Literal["pre", "post"]] | None
    ) -> list[Literal["pre", "post"]] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError(
                "stages cannot be an empty list. Use None/omit the field to apply to all stages."
            )
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"step_types": ["tool"], "stages": ["pre"]},
                {"step_names": ["search_db", "fetch_user"]},
                {"step_name_regex": "^db_.*"},
                {"step_types": ["llm"], "stages": ["post"]},
            ]
        }
    }


# =============================================================================
# Evaluator Config Models (used by evaluator implementations)
# =============================================================================


class RegexEvaluatorConfig(BaseModel):
    """Configuration for regex evaluator."""

    pattern: str = Field(..., description="Regular expression pattern")
    flags: list[str] | None = Field(default=None, description="Regex flags")

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """Validate that the pattern is a valid regex."""
        try:
            re2.compile(v)
        except re2.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e
        return v


class ListEvaluatorConfig(BaseModel):
    """Configuration for list evaluator."""

    values: list[str | int | float] = Field(
        ..., description="List of values to match against"
    )
    logic: Literal["any", "all"] = Field(
        "any", description="Matching logic: any item matches vs all items match"
    )
    match_on: Literal["match", "no_match"] = Field(
        "match", description="Trigger rule on match or no match"
    )
    match_mode: Literal["exact", "contains"] = Field(
        "exact",
        description="'exact' for full string match, 'contains' for keyword/substring match",
    )
    case_sensitive: bool = Field(False, description="Whether matching is case sensitive")


class JSONEvaluatorConfig(BaseModel):
    """Configuration for JSON validation evaluator.

    Multiple validation checks can be combined. Checks are evaluated in this order (fail-fast):
    1. JSON syntax/validity (always - ensures data is valid JSON)
    2. JSON Schema validation (if schema provided) - comprehensive structure validation
    3. Required fields check (if required_fields provided) - ensures critical fields exist
    4. Type checking (if field_types provided) - validates field types are correct
    5. Field constraints (if field_constraints provided) - validates ranges, enums, string length
    6. Pattern matching (if field_patterns provided) - validates field values match patterns

    This order makes sense because:
    - Check syntax first (can't do anything with invalid JSON)
    - Check schema next (comprehensive structural validation)
    - Check required fields (fail fast if missing critical fields)
    - Check types (verify data types before checking constraints)
    - Check constraints (validate value ranges/enums after type is confirmed)
    - Check patterns last (most specific regex validation)
    """

    # Validation Options (all optional, can be combined)
    json_schema: dict[str, Any] | None = Field(
        default=None, description="JSON Schema specification (Draft 7 or later)"
    )

    required_fields: list[str] | None = Field(
        default=None,
        description="List of field paths that must be present (dot notation)",
    )

    field_types: dict[str, str] | None = Field(
        default=None,
        description=(
            "Map of field paths to expected JSON types "
            "(string, number, integer, boolean, array, object, null)"
        ),
    )

    field_constraints: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="Field-level constraints: numeric ranges (min/max), enums, string length",
    )

    field_patterns: dict[str, str | dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Map of field paths to RE2 regex patterns. "
            "Can be string (pattern only) or dict with 'pattern' and optional 'flags'"
        ),
    )

    # Validation Behavior
    allow_extra_fields: bool = Field(
        default=True,
        description="If False, fail if extra fields exist beyond those specified in field_types",
    )

    allow_null_required: bool = Field(
        default=False,
        description=(
            "If True, required fields can be present but null. "
            "If False, null is treated as missing"
        ),
    )

    pattern_match_logic: Literal["all", "any"] = Field(
        default="all",
        description=(
            "For field_patterns: 'all' requires all patterns to match, "
            "'any' requires at least one"
        ),
    )

    case_sensitive_enums: bool = Field(
        default=True,
        description="If False, enum value matching is case-insensitive",
    )

    # Error Handling
    allow_invalid_json: bool = Field(
        default=False,
        description=(
            "If True, treat invalid JSON as non-match and allow. "
            "If False, block invalid JSON"
        ),
    )

    @field_validator("json_schema")
    @classmethod
    def validate_json_schema(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Ensure the JSON schema itself is valid."""
        if v is None:
            return v
        from jsonschema import Draft7Validator

        Draft7Validator.check_schema(v)
        return v

    @field_validator("field_types")
    @classmethod
    def validate_type_names(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        """Ensure type names are valid JSON types."""
        if v is None:
            return v
        valid_types = {
            "string",
            "number",
            "integer",
            "boolean",
            "array",
            "object",
            "null",
        }
        for path, type_name in v.items():
            if type_name not in valid_types:
                raise ValueError(f"Invalid type '{type_name}' for field '{path}'")
        return v

    @field_validator("field_patterns")
    @classmethod
    def validate_patterns(
        cls, v: dict[str, str | dict[str, Any]] | None
    ) -> dict[str, str | dict[str, Any]] | None:
        """Validate all regex patterns compile."""
        if v is None:
            return v

        for path, pattern_config in v.items():
            # Support both string (simple) and dict (with flags) formats
            if isinstance(pattern_config, str):
                pattern = pattern_config
                flags = None
            elif isinstance(pattern_config, dict):
                if "pattern" not in pattern_config:
                    raise ValueError(
                        f"Pattern config for field '{path}' must have 'pattern' key"
                    )
                pattern = pattern_config["pattern"]
                flags = pattern_config.get("flags")

                # Validate flags if provided
                if flags is not None:
                    if not isinstance(flags, list):
                        raise ValueError(f"Flags for field '{path}' must be a list")
                    valid_flags = {"IGNORECASE"}
                    for flag in flags:
                        if flag not in valid_flags:
                            raise ValueError(
                                f"Invalid flag '{flag}' for field '{path}'. "
                                f"Valid flags: {valid_flags}"
                            )
            else:
                raise ValueError(
                    f"Pattern for field '{path}' must be string or dict"
                )

            # Validate pattern compiles
            try:
                re2.compile(pattern)
            except re2.error as e:
                raise ValueError(f"Invalid regex for field '{path}': {e}") from e

        return v

    @field_validator("field_constraints")
    @classmethod
    def validate_constraints(
        cls, v: dict[str, dict[str, Any]] | None
    ) -> dict[str, dict[str, Any]] | None:
        """Validate constraint definitions."""
        if v is None:
            return v

        for field_path, constraints in v.items():
            # Must have at least one constraint type
            valid_keys = {"type", "min", "max", "enum", "min_length", "max_length"}
            if not any(k in constraints for k in valid_keys):
                raise ValueError(
                    f"Constraint for '{field_path}' must specify at least one constraint"
                )

            # Validate numeric constraints
            if "min" in constraints or "max" in constraints:
                if "type" in constraints and constraints["type"] not in (
                    "number",
                    "integer",
                ):
                    raise ValueError(
                        f"min/max constraints require type 'number' or 'integer' for '{field_path}'"
                    )

            # Validate enum
            if "enum" in constraints:
                if (
                    not isinstance(constraints["enum"], list)
                    or len(constraints["enum"]) == 0
                ):
                    raise ValueError(
                        f"enum constraint must be a non-empty list for '{field_path}'"
                    )

            # Validate string length
            if "min_length" in constraints or "max_length" in constraints:
                if "min_length" in constraints and not isinstance(
                    constraints["min_length"], int
                ):
                    raise ValueError(
                        f"min_length must be an integer for '{field_path}'"
                    )
                if "max_length" in constraints and not isinstance(
                    constraints["max_length"], int
                ):
                    raise ValueError(
                        f"max_length must be an integer for '{field_path}'"
                    )

        return v

    @model_validator(mode="after")
    def validate_has_checks(self) -> Self:
        """Ensure at least one validation check is configured."""
        if not any(
            [
                self.json_schema,
                self.field_types,
                self.required_fields,
                self.field_constraints,
                self.field_patterns,
            ]
        ):
            raise ValueError(
                "At least one validation check must be configured: "
                "json_schema, field_types, required_fields, field_constraints, or field_patterns"
            )
        return self


class SQLEvaluatorConfig(BaseModel):
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
            "(SQL injection prevention). "
            "When False, queries with multiple statements are blocked. "
            "Cannot be used with max_statements (use one or the other)."
        ),
    )
    max_statements: int | None = Field(
        default=None,
        description=(
            "Maximum number of statements allowed (e.g., 2 allows up to 2 statements). "
            "Only applicable when allow_multi_statements=True. "
            "Must be a positive integer. "
            "Use this to allow controlled multi-statement queries while preventing abuse."
        ),
    )

    # Operations
    blocked_operations: list[str] | None = Field(
        default=None,
        description=(
            "SQL operations to block (e.g., ['DROP', 'DELETE', 'TRUNCATE']). "
            "Cannot be used with allowed_operations. "
            "Use this for blocklist mode where most operations are allowed except specific ones."
        ),
    )
    allowed_operations: list[str] | None = Field(
        default=None,
        description=(
            "SQL operations to allow (e.g., ['SELECT'] for read-only). "
            "Cannot be used with blocked_operations. "
            "When set, all operations NOT in this list are blocked (allowlist mode). "
            "Can be combined with block_ddl/block_dcl for stricter control "
            "(e.g., allowed_operations=['SELECT'] + block_ddl=True enforces both)."
        ),
    )
    block_ddl: bool = Field(
        default=False,
        description=(
            "Block all DDL operations (CREATE, ALTER, DROP, TRUNCATE, RENAME, COMMENT). "
            "Adds DDL operations to the blocklist. "
            "Can be combined with either blocked_operations or allowed_operations (but not both, "
            "since those are mutually exclusive). "
            "Example: allowed_operations=['SELECT'] + block_ddl=True = read-only with DDL blocked."
        ),
    )
    block_dcl: bool = Field(
        default=False,
        description=(
            "Block all DCL operations (GRANT, REVOKE). "
            "Adds DCL operations to the blocklist. "
            "Can be combined with either blocked_operations or allowed_operations (but not both, "
            "since those are mutually exclusive). "
            "Useful for preventing privilege escalation even with allowed operations."
        ),
    )

    # Table/Schema Access
    allowed_tables: list[str] | None = Field(
        default=None,
        description=(
            "Table names allowed (e.g., ['users', 'orders']). "
            "Cannot be used with blocked_tables. "
            "When set, all tables NOT in this list are blocked (allowlist mode). "
            "Case sensitivity controlled by case_sensitive field."
        ),
    )
    blocked_tables: list[str] | None = Field(
        default=None,
        description=(
            "Table names to block (e.g., ['sensitive_data', 'admin_users']). "
            "Cannot be used with allowed_tables. "
            "Use this for blocklist mode where most tables are allowed except specific ones. "
            "Case sensitivity controlled by case_sensitive field."
        ),
    )
    allowed_schemas: list[str] | None = Field(
        default=None,
        description=(
            "Schema names allowed (e.g., ['public', 'analytics']). "
            "Cannot be used with blocked_schemas. "
            "When set, all schemas NOT in this list are blocked (allowlist mode). "
            "Case sensitivity controlled by case_sensitive field."
        ),
    )
    blocked_schemas: list[str] | None = Field(
        default=None,
        description=(
            "Schema names to block (e.g., ['system', 'admin', 'internal']). "
            "Cannot be used with allowed_schemas. "
            "Use this for blocklist mode where most schemas are allowed except specific ones. "
            "Case sensitivity controlled by case_sensitive field."
        ),
    )

    # Column Presence
    required_columns: list[str] | None = Field(
        default=None,
        description=(
            "Columns that must be present in the query "
            "(e.g., ['tenant_id'] for multi-tenant security). "
            "Use with column_presence_logic to control 'any' vs 'all' matching. "
            "Use with column_context to restrict where columns must appear "
            "(WHERE, SELECT, or anywhere). "
            "Case sensitivity controlled by case_sensitive field."
        ),
    )
    column_presence_logic: Literal["any", "all"] = Field(
        default="any",
        description=(
            "Matching logic for required_columns. "
            "'any': at least one required column must be present (OR logic). "
            "'all': all required columns must be present (AND logic). "
            "Only applicable when required_columns is set."
        ),
    )
    column_context: Literal["select", "where"] | None = Field(
        default=None,
        description=(
            "Where required columns must appear. "
            "'select': columns must appear in SELECT clause. "
            "'where': columns must appear in WHERE clause (common for tenant_id filtering). "
            "None: columns can appear anywhere in the query. "
            "Only applicable when required_columns is set."
        ),
    )
    column_context_scope: Literal["top_level", "all"] = Field(
        default="all",
        description=(
            "Scope for column_context checking when set to 'where' or 'select'. "
            "top_level: Only check columns in the top-level WHERE/SELECT clause "
            "(recommended for multi-tenant RLS security). "
            "all: Check columns in all WHERE/SELECT clauses including subqueries "
            "(default for backward compatibility). "
            "Only applies when column_context is 'where' or 'select'. "
            "For multi-tenant security, use column_context='where' with "
            "column_context_scope='top_level' to ensure tenant filtering is in "
            "the outer query, not just subqueries."
        ),
    )

    # Limits
    require_limit: bool = Field(
        default=False,
        description=(
            "Require SELECT queries to have a LIMIT clause. "
            "Prevents accidentally pulling millions of rows. "
            "Only applies to SELECT queries; INSERT/UPDATE/DELETE are unaffected. "
            "Combine with max_limit to enforce a maximum value."
        ),
    )
    max_limit: int | None = Field(
        default=None,
        description=(
            "Maximum allowed LIMIT value (e.g., 1000 prevents LIMIT 10000). "
            "Only applies to SELECT queries with a LIMIT clause. "
            "Must be a positive integer. "
            "If LIMIT value cannot be determined (e.g., LIMIT ALL), behavior depends on fail_safe."
        ),
    )
    max_result_window: int | None = Field(
        default=None,
        description=(
            "Maximum value of (LIMIT + OFFSET) for pagination control. "
            "Prevents deep pagination attacks where large OFFSET values can "
            "cause expensive queries. Similar to Elasticsearch's max_result_window. "
            "Example: max_result_window=10000 allows 'LIMIT 100 OFFSET 9900' "
            "but blocks 'LIMIT 10 OFFSET 10000'. "
            "None (default): No limit on pagination depth. "
            "Recommended: Set to 10000 or similar value to prevent abuse."
        ),
    )

    # Options
    case_sensitive: bool = Field(
        default=False,
        description=(
            "Whether table/column/schema name matching is case sensitive. "
            "False (default): 'Users' matches 'users'. "
            "True: 'Users' does NOT match 'users'. "
            "Applies to allowed_tables, blocked_tables, allowed_schemas, "
            "blocked_schemas, and required_columns."
        ),
    )
    dialect: Literal["postgres", "mysql", "tsql", "oracle", "sqlite"] = Field(
        default="postgres",
        description=(
            "SQL dialect to use for parsing. "
            "Affects how sqlglot interprets SQL syntax. "
            "postgres (default): Standard SQL, case-insensitive identifiers, "
            "quoted with \", most ANSI-compliant. "
            "mysql: MySQL-specific syntax, case-sensitive on Unix/Linux, "
            "backtick-quoted identifiers. "
            "tsql: T-SQL/SQL Server, bracket-quoted identifiers [like_this], "
            "supports CAST differently. "
            "oracle: Oracle-specific syntax, quoted identifiers with \", "
            "supports -- comments. "
            "sqlite: Lightweight SQL, double-quoted identifiers, supports "
            "AUTOINCREMENT and datetime functions. "
            "Choose based on the target database system."
        ),
    )

    # Query Complexity Limits (Issue #13)
    max_subquery_depth: int | None = Field(
        default=None,
        description=(
            "Maximum nesting depth for subqueries. "
            "Prevents DoS via deeply nested queries like SELECT FROM (SELECT FROM (SELECT...)). "
            "None (default): No limit. "
            "Recommended: 5-10 for typical applications."
        ),
    )
    max_joins: int | None = Field(
        default=None,
        description=(
            "Maximum number of JOIN operations in a single query. "
            "Prevents cartesian product attacks and expensive multi-way joins. "
            "None (default): No limit. "
            "Recommended: 10-20 depending on use case."
        ),
    )
    max_union_count: int | None = Field(
        default=None,
        description=(
            "Maximum number of UNION/UNION ALL/INTERSECT/EXCEPT operations. "
            "Prevents DoS via massive UNION chains. "
            "None (default): No limit. "
            "Recommended: 10-50 depending on use case."
        ),
    )

    @model_validator(mode="after")
    def validate_config(self) -> Self:
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

        # Validate LIMIT controls
        if self.max_limit and not self.require_limit:
            warnings.warn(
                "max_limit is set but require_limit is False - "
                "max_limit only enforced if LIMIT clause exists"
            )

        return self


# =============================================================================
# Unified Evaluator Config (used in API)
# =============================================================================


class EvaluatorConfig(BaseModel):
    """Evaluator configuration. See GET /evaluators for available evaluators and schemas.

    Evaluator reference formats:
    - Built-in: "regex", "list"
    - Agent-scoped: "my-agent:my-evaluator" (validated in endpoint, not here)
    """

    name: str = Field(
        ...,
        description="Evaluator name or agent-scoped reference (agent:evaluator)",
        examples=["regex", "list", "my-agent:pii-detector"],
    )
    config: dict[str, Any] = Field(
        ...,
        description="Evaluator-specific configuration",
        examples=[
            {"pattern": r"\d{3}-\d{2}-\d{4}"},
            {"values": ["admin"], "logic": "any"},
        ],
    )

    @model_validator(mode="after")
    def validate_evaluator_config(self) -> Self:
        """Validate config against evaluator's schema if evaluator is registered.

        Agent-scoped evaluators (format: agent:evaluator) are validated in the
        endpoint where we have database access to look up the agent's schema.
        """
        # Agent-scoped evaluators: defer validation to endpoint (needs DB access)
        if ":" in self.name:
            return self

        # Built-in evaluators: validate config against evaluator's config_model
        from .evaluator import get_evaluator

        evaluator_cls = get_evaluator(self.name)
        if evaluator_cls:
            evaluator_cls.config_model(**self.config)
        # If evaluator not found, allow it (might be a server-side registered evaluator)
        return self


class ControlAction(BaseModel):
    """What to do when control matches."""

    decision: Literal["allow", "deny", "warn", "log"] = Field(
        ..., description="Action to take when control is triggered"
    )


class ControlDefinition(BaseModel):
    """A control definition to evaluate agent interactions.

    This model contains only the logic and configuration.
    Identity fields (id, name) are managed by the database.
    """

    description: str | None = Field(None, description="Detailed description of the control")
    enabled: bool = Field(True, description="Whether this control is active")
    execution: Literal["server", "sdk"] = Field(
        ..., description="Where this control executes"
    )

    # When to apply
    scope: ControlScope = Field(
        default_factory=ControlScope,
        description="Which steps and stages this control applies to",
    )

    # What to check
    selector: ControlSelector = Field(..., description="What data to select from the payload")

    # How to check (unified evaluator-based system)
    evaluator: EvaluatorConfig = Field(..., description="How to evaluate the selected data")

    # What to do
    action: ControlAction = Field(..., description="What action to take when control matches")

    # Metadata
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "Block outputs containing US Social Security Numbers",
                    "enabled": True,
                    "execution": "server",
                    "scope": {"step_types": ["llm"], "stages": ["post"]},
                    "selector": {"path": "output"},
                    "evaluator": {
                        "name": "regex",
                        "config": {
                            "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
                        },
                    },
                    "action": {
                        "decision": "deny",
                    },
                    "tags": ["pii", "compliance"],
                }
            ]
        }
    }


class EvaluatorResult(BaseModel):
    """Result from a control evaluator.

    The `error` field indicates evaluator failures, NOT validation failures:
    - Set `error` for: evaluator crashes, timeouts, missing dependencies, external service errors
    - Do NOT set `error` for: invalid input, syntax errors, schema violations, constraint failures

    When `error` is set, `matched` must be False (fail-open on evaluator errors).
    When `error` is None, `matched` reflects the actual validation result.

    This distinction allows:
    - Clients to distinguish "data violated rules" from "evaluator is broken"
    - Observability systems to monitor evaluator health separately from validation outcomes
    """

    matched: bool = Field(..., description="Whether the pattern matched")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in the evaluation"
    )
    message: str | None = Field(default=None, description="Explanation of the result")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional result metadata")
    error: str | None = Field(
        default=None,
        description=(
            "Error message if evaluation failed internally. "
            "When set, matched=False is due to error, not actual evaluation."
        ),
    )

    @model_validator(mode="after")
    def error_implies_not_matched(self) -> Self:
        """Ensure matched=False when error is set (fail-open on errors)."""
        if self.error is not None and self.matched:
            raise ValueError("matched must be False when error is set")
        return self


class ControlMatch(BaseModel):
    """Represents a control evaluation result (match, non-match, or error)."""

    control_execution_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique ID for this control execution (generated by engine)",
    )
    control_id: int = Field(..., description="Database ID of the control")
    control_name: str = Field(..., description="Name of the control")
    action: Literal["allow", "deny", "warn", "log"] = Field(
        ..., description="Action configured for this control"
    )
    result: EvaluatorResult = Field(
        ..., description="Evaluator result (confidence, message, metadata)"
    )
