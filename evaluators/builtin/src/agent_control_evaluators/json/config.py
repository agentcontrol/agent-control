"""Configuration for JSON validation evaluator."""

from typing import Any, Literal

import re2
from pydantic import Field, field_validator, model_validator

from agent_control_evaluators._base import EvaluatorConfig


class JSONEvaluatorConfig(EvaluatorConfig):
    """Configuration for JSON validation evaluator.

    Multiple validation checks can be combined. Checks are evaluated in this order (fail-fast):
    1. JSON syntax/validity (always - ensures data is valid JSON)
    2. JSON Schema validation (if schema provided) - comprehensive structure validation
    3. Required fields check (if required_fields provided) - ensures critical fields exist
    4. Type checking (if field_types provided) - validates field types are correct
    5. Field constraints (if field_constraints provided) - validates ranges, enums, string length
    6. Pattern matching (if field_patterns provided) - validates field values match patterns
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
    def validate_has_checks(self) -> "JSONEvaluatorConfig":
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
