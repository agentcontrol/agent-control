"""JSON validation evaluator with schema, type, required field, constraint, and pattern checks."""

import asyncio
import json
from typing import Any

import re2
from agent_control_models import (
    Evaluator,
    EvaluatorMetadata,
    EvaluatorResult,
    JSONEvaluatorConfig,
    register_evaluator,
)
from jsonschema import Draft7Validator


@register_evaluator
class JSONEvaluator(Evaluator[JSONEvaluatorConfig]):
    """Comprehensive JSON validation evaluator.

    Validates JSON data in this order (fail-fast, simple to complex):
    1. JSON syntax/validity - Parse and validate JSON structure
    2. JSON Schema validation (if configured) - Comprehensive structure check
    3. Required fields (if configured) - Ensure critical fields exist
    4. Type checking (if configured) - Validate field types
    5. Field constraints (if configured) - Validate ranges, enums, string length
    6. Pattern matching (if configured) - Validate field value patterns

    This order ensures:
    - Fast failure on basic issues (invalid JSON, missing required fields)
    - Type is validated before checking value constraints
    - Clear error messages indicating which check failed
    - Developers can easily understand and predict validation behavior

    Example configs:
        # JSON Schema validation
        {"json_schema": {"type": "object", "required": ["id", "name"]}}

        # Type checking
        {"field_types": {"user.id": "string", "user.age": "integer"}}

        # Required fields
        {"required_fields": ["id", "email", "created_at"]}

        # Field constraints - numeric ranges
        {"field_constraints": {"score": {"min": 0.0, "max": 1.0}}}

        # Field constraints - enums
        {"field_constraints": {"status": {"enum": ["active", "inactive"]}}}

        # Pattern matching
        {"field_patterns": {"email": "^[a-z0-9._%+-]+@[a-z0-9.-]+\\\\.[a-z]+$"}}
    """

    metadata = EvaluatorMetadata(
        name="json",
        version="1.0.0",
        description=(
            "Comprehensive JSON validation: schema, types, required fields, "
            "constraints, and patterns"
        ),
        timeout_ms=15000,  # Longer timeout for schema validation
    )
    config_model = JSONEvaluatorConfig

    def __init__(self, config: JSONEvaluatorConfig) -> None:
        super().__init__(config)

        # Pre-compile schema validator (thread-safe, immutable)
        if config.json_schema:
            self._schema_validator = Draft7Validator(config.json_schema)
        else:
            self._schema_validator = None

        # Pre-compile regex patterns (thread-safe, immutable)
        if config.field_patterns:
            self._compiled_patterns = {}
            for path, pattern_config in config.field_patterns.items():
                # Support both string and dict formats
                if isinstance(pattern_config, str):
                    pattern = pattern_config
                    flags = None
                else:
                    pattern = pattern_config["pattern"]
                    flags = pattern_config.get("flags")

                # Compile with flags
                if flags and "IGNORECASE" in flags:
                    opts = re2.Options()
                    opts.case_sensitive = False
                    compiled = re2.compile(pattern, opts)
                else:
                    compiled = re2.compile(pattern)

                self._compiled_patterns[path] = compiled
        else:
            self._compiled_patterns = None

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate JSON data against all configured validation checks.

        Evaluation order (fail-fast from simple to complex):
        1. JSON syntax/validity
        2. JSON Schema (if configured)
        3. Required fields (if configured)
        4. Type checking (if configured)
        5. Field constraints (if configured)
        6. Pattern matching (if configured)

        Note: Validation is offloaded to a thread executor to avoid blocking
        the event loop for large payloads, since all validation logic is synchronous.
        """
        # Offload synchronous validation to thread to avoid blocking event loop
        return await asyncio.to_thread(self._evaluate_sync, data)

    def _evaluate_sync(self, data: Any) -> EvaluatorResult:
        """Synchronous validation logic (called via thread executor)."""

        # 1. JSON Syntax/Validity Check
        parsed_data, parse_error = self._parse_json(data)
        if parse_error:
            return self._handle_parse_error(parse_error)

        # 2. JSON Schema Validation (comprehensive structure check)
        if self._schema_validator:
            schema_result = self._check_schema(parsed_data)
            if schema_result:
                return schema_result

        # 3. Required Fields Check (fail fast on missing critical fields)
        if self.config.required_fields:
            required_result = self._check_required(parsed_data)
            if required_result:
                return required_result

        # 4. Type Checking (validate data types)
        if self.config.field_types:
            type_result = self._check_types(parsed_data)
            if type_result:
                return type_result

        # 5. Field Constraints (validate ranges, enums, string length)
        if self.config.field_constraints:
            constraints_result = self._check_constraints(parsed_data)
            if constraints_result:
                return constraints_result

        # 6. Pattern Matching (validate field value patterns)
        if self._compiled_patterns:
            pattern_result = self._check_patterns(parsed_data)
            if pattern_result:
                return pattern_result

        # All checks passed
        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="JSON validation passed all checks",
        )

    def _parse_json(self, data: Any) -> tuple[dict | list | None, str | None]:
        """Parse input to JSON. Returns (parsed_data, error_message)."""
        if data is None:
            return None, "Input data is None"

        # Already parsed
        if isinstance(data, (dict, list)):
            return data, None

        # Parse JSON string
        if isinstance(data, str):
            try:
                return json.loads(data), None
            except json.JSONDecodeError as e:
                return None, f"Invalid JSON: {e}"

        # Unsupported type
        return None, f"Unsupported data type: {type(data).__name__}"

    def _handle_parse_error(self, error: str) -> EvaluatorResult:
        """Handle JSON parse errors based on allow_invalid_json config."""
        if self.config.allow_invalid_json:
            # Allow invalid JSON through as non-match
            return EvaluatorResult(
                matched=False,
                confidence=0.0,
                message=f"Invalid JSON allowed: {error}",
            )
        else:
            # Block invalid JSON
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=f"Invalid JSON blocked: {error}",
            )

    def _check_schema(self, data: dict | list) -> EvaluatorResult | None:
        """Validate against JSON Schema. Returns error result or None."""
        errors = list(self._schema_validator.iter_errors(data))

        if not errors:
            return None  # Validation passed

        # Build error message
        error_messages = []
        for error in errors[:3]:
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            error_messages.append(f"{path}: {error.message}")

        message = f"Schema validation failed: {'; '.join(error_messages)}"
        if len(errors) > 3:
            message += f" (+{len(errors) - 3} more errors)"

        return EvaluatorResult(
            matched=True,
            confidence=1.0,
            message=message,
            metadata={"error_count": len(errors), "errors": error_messages},
        )

    def _check_types(self, data: dict | list) -> EvaluatorResult | None:
        """Validate field types. Returns error result or None."""
        if not isinstance(data, dict):
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Type checking requires a JSON object, got array/primitive",
            )

        errors = []

        for field_path, expected_type in self.config.field_types.items():
            value, found = self._get_nested_value(data, field_path)

            if not found:
                errors.append(f"{field_path}: field not found")
                continue

            actual_type = self._get_json_type(value)
            if actual_type != expected_type:
                errors.append(
                    f"{field_path}: expected {expected_type}, got {actual_type}"
                )

        # Check for extra fields if not allowed
        if not self.config.allow_extra_fields:
            # Get only leaf paths to avoid flagging parent containers
            actual_paths = self._get_all_paths(data, leaves_only=True)

            # Include both field_types and required_fields as allowed paths
            specified_paths = set(self.config.field_types.keys())
            if self.config.required_fields:
                specified_paths.update(self.config.required_fields)

            extra_paths = actual_paths - specified_paths
            if extra_paths:
                errors.append(
                    f"Extra fields not allowed: {', '.join(sorted(extra_paths)[:3])}"
                )

        if not errors:
            return None  # Validation passed

        return EvaluatorResult(
            matched=True,
            confidence=1.0,
            message=f"Type validation failed: {'; '.join(errors[:3])}",
            metadata={"error_count": len(errors), "errors": errors},
        )

    def _check_required(self, data: dict | list) -> EvaluatorResult | None:
        """Validate required fields are present. Returns error result or None."""
        if not isinstance(data, dict):
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Required field checking requires a JSON object, got array/primitive",
            )

        missing = []

        for field_path in self.config.required_fields:
            value, found = self._get_nested_value(data, field_path)

            if not found:
                missing.append(field_path)
            elif not self.config.allow_null_required and value is None:
                missing.append(f"{field_path} (null not allowed)")

        if not missing:
            return None  # Validation passed

        return EvaluatorResult(
            matched=True,
            confidence=1.0,
            message=f"Missing required fields: {', '.join(missing[:5])}",
            metadata={"missing_count": len(missing), "missing_fields": missing},
        )

    def _check_constraints(self, data: dict | list) -> EvaluatorResult | None:
        """Validate field constraints (ranges, enums, string length).

        Returns error result or None.
        """
        if not isinstance(data, dict):
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Constraint checking requires a JSON object, got array/primitive",
            )

        errors = []

        for field_path, constraints in self.config.field_constraints.items():
            value, found = self._get_nested_value(data, field_path)

            if not found:
                errors.append(f"{field_path}: field not found")
                continue

            # Numeric range constraints
            if "min" in constraints or "max" in constraints:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"{field_path}: expected numeric value for range check")
                    continue

                if "min" in constraints and value < constraints["min"]:
                    errors.append(
                        f"{field_path}: value {value} below minimum {constraints['min']}"
                    )
                    continue

                if "max" in constraints and value > constraints["max"]:
                    errors.append(
                        f"{field_path}: value {value} above maximum {constraints['max']}"
                    )
                    continue

            # Enum constraints
            if "enum" in constraints:
                # Case-insensitive matching if configured
                if self.config.case_sensitive_enums:
                    # Case-sensitive (default behavior)
                    if value not in constraints["enum"]:
                        allowed = ", ".join(str(v) for v in constraints["enum"][:5])
                        errors.append(
                            f"{field_path}: value '{value}' not in allowed values: {allowed}"
                        )
                        continue
                else:
                    # Case-insensitive matching
                    # Convert to lowercase for comparison (only for strings)
                    if isinstance(value, str):
                        value_lower = value.lower()
                        enum_lower = [
                            v.lower() if isinstance(v, str) else v
                            for v in constraints["enum"]
                        ]
                        if value_lower not in enum_lower:
                            allowed = ", ".join(str(v) for v in constraints["enum"][:5])
                            errors.append(
                                f"{field_path}: value '{value}' not in allowed values: "
                                f"{allowed} (case-insensitive)"
                            )
                            continue
                    else:
                        # Non-string values: exact match only
                        if value not in constraints["enum"]:
                            allowed = ", ".join(str(v) for v in constraints["enum"][:5])
                            errors.append(
                                f"{field_path}: value '{value}' not in allowed values: {allowed}"
                            )
                            continue

            # String length constraints
            if "min_length" in constraints or "max_length" in constraints:
                if not isinstance(value, str):
                    errors.append(f"{field_path}: expected string for length check")
                    continue

                str_len = len(value)
                if "min_length" in constraints and str_len < constraints["min_length"]:
                    errors.append(
                        f"{field_path}: length {str_len} below minimum {constraints['min_length']}"
                    )
                    continue

                if "max_length" in constraints and str_len > constraints["max_length"]:
                    errors.append(
                        f"{field_path}: length {str_len} above maximum {constraints['max_length']}"
                    )
                    continue

        if not errors:
            return None  # Validation passed

        return EvaluatorResult(
            matched=True,
            confidence=1.0,
            message=f"Constraint validation failed: {'; '.join(errors[:3])}",
            metadata={"error_count": len(errors), "errors": errors},
        )

    def _check_patterns(self, data: dict | list) -> EvaluatorResult | None:
        """Validate field values match patterns. Returns error result or None."""
        if not isinstance(data, dict):
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Pattern matching requires a JSON object, got array/primitive",
            )

        matches = []
        failures = []

        for field_path, compiled_pattern in self._compiled_patterns.items():
            value, found = self._get_nested_value(data, field_path)

            if not found:
                failures.append(f"{field_path}: field not found")
                continue

            value_str = str(value) if value is not None else ""
            if compiled_pattern.search(value_str):
                matches.append(field_path)
            else:
                failures.append(f"{field_path}: pattern did not match")

        # Determine match based on logic
        if self.config.pattern_match_logic == "all":
            success = len(failures) == 0
            message = (
                None
                if success
                else f"Pattern validation failed: {'; '.join(failures[:3])}"
            )
        else:  # any
            success = len(matches) > 0
            message = None if success else "No patterns matched"

        if success:
            return None  # Validation passed

        return EvaluatorResult(
            matched=True,
            confidence=1.0,
            message=message,
            metadata={
                "matches": matches,
                "failures": failures,
                "match_logic": self.config.pattern_match_logic,
            },
        )

    # Helper methods

    def _get_nested_value(self, data: dict, path: str) -> tuple[Any, bool]:
        """Get nested value using dot notation. Returns (value, found)."""
        parts = path.split(".")
        current = data

        for part in parts:
            if not isinstance(current, dict):
                return None, False
            if part not in current:
                return None, False
            current = current[part]

        return current, True

    def _get_json_type(self, value: Any) -> str:
        """Get JSON type name for a Python value."""
        if value is None:
            return "null"
        if isinstance(value, bool):  # Must check before int
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "unknown"

    def _get_all_paths(
        self, data: dict, prefix: str = "", leaves_only: bool = False
    ) -> set[str]:
        """Recursively get all field paths in nested dict.

        Args:
            data: The dictionary to traverse
            prefix: Current path prefix for nested traversal
            leaves_only: If True, only return paths to leaf values (non-dict values).
                        This avoids flagging parent containers as extra fields.
        """
        paths = set()
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                # Recurse into nested dicts
                paths.update(self._get_all_paths(value, path, leaves_only))
                # Only add container path if not leaves_only
                if not leaves_only:
                    paths.add(path)
            else:
                # Always add leaf paths (non-dict values)
                paths.add(path)
        return paths
