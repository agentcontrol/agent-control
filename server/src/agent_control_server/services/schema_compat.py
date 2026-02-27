"""JSON Schema compatibility checking for evaluator schemas.

Determines if a new schema is backward-compatible with an existing schema.
Used during initAgent to reject breaking changes.

Compatibility Rules:
- Adding new optional properties -> compatible
- Adding new required properties -> incompatible
- Removing properties -> incompatible
- Changing property types -> incompatible
- Changing required to optional -> compatible
- Changing optional to required -> incompatible
- Nested object changes checked recursively
"""

from typing import Any


def check_schema_compatibility(
    old_schema: dict[str, Any],
    new_schema: dict[str, Any],
    path: str = "",
) -> tuple[bool, list[str]]:
    """Check if new_schema is backward-compatible with old_schema.

    Args:
        old_schema: Existing JSON Schema
        new_schema: New JSON Schema to compare
        path: Property path for error messages (used in recursion)

    Returns:
        Tuple of (is_compatible, list of error messages)
    """
    # Short-circuit for identical schemas
    if old_schema == new_schema:
        return True, []

    errors: list[str] = []

    # Empty schemas are always compatible
    if not old_schema:
        return True, []

    # Get properties from both schemas
    old_props = old_schema.get("properties", {})
    new_props = new_schema.get("properties", {})
    old_required = set(old_schema.get("required", []))
    new_required = set(new_schema.get("required", []))

    def _prop_path(name: str) -> str:
        return f"{path}.{name}" if path else name

    # Check for removed properties
    removed = set(old_props.keys()) - set(new_props.keys())
    for prop in sorted(removed):
        errors.append(f"Removed property: '{_prop_path(prop)}'")

    # Check for type changes and nested compatibility on existing properties
    for prop_name in old_props:
        if prop_name not in new_props:
            continue  # Already reported as removed

        old_prop = old_props[prop_name]
        new_prop = new_props[prop_name]
        prop_path = _prop_path(prop_name)

        old_type = _get_type(old_prop)
        new_type = _get_type(new_prop)

        if old_type != new_type:
            errors.append(
                f"Property '{prop_path}' type changed from '{old_type}' to '{new_type}'"
            )
        elif old_type == "object":
            # Recursively check nested object compatibility
            _, nested_errors = check_schema_compatibility(old_prop, new_prop, prop_path)
            errors.extend(nested_errors)
        elif old_type.startswith("array<object>"):
            # Check array item schema compatibility
            old_items = old_prop.get("items", {})
            new_items = new_prop.get("items", {})
            _, nested_errors = check_schema_compatibility(
                old_items, new_items, f"{prop_path}[]"
            )
            errors.extend(nested_errors)

    # Check for new required properties (breaking)
    new_required_props = new_required - old_required
    for prop in new_required_props:
        prop_path = _prop_path(prop)
        if prop not in old_props:
            errors.append(f"Added required property: '{prop_path}'")
        else:
            errors.append(f"Property '{prop_path}' changed from optional to required")

    is_compatible = len(errors) == 0
    return is_compatible, errors


def _get_type(prop_schema: dict[str, Any]) -> str:
    """Extract type from a property schema."""
    if "type" in prop_schema:
        t = prop_schema["type"]
        if t == "array" and "items" in prop_schema:
            items_type = _get_type(prop_schema["items"])
            return f"array<{items_type}>"
        return str(t)
    if "enum" in prop_schema:
        return f"enum({len(prop_schema['enum'])})"
    if "$ref" in prop_schema:
        return f"$ref:{prop_schema['$ref']}"
    if "anyOf" in prop_schema:
        return "anyOf"
    if "oneOf" in prop_schema:
        return "oneOf"
    return "unknown"


def format_compatibility_error(evaluator_name: str, errors: list[str]) -> str:
    """Format a user-friendly error message for incompatible schema change.

    Args:
        evaluator_name: Name of the evaluator with incompatible change
        errors: List of specific compatibility errors

    Returns:
        Formatted error message
    """
    error_list = "; ".join(errors)
    return (
        f"Evaluator '{evaluator_name}' schema change is not backward compatible. "
        f"Changes detected: {error_list}. "
        "To make breaking changes, create a new agent with a different name."
    )
