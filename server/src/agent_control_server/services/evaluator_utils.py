"""Utilities for working with evaluator references."""

import json
from functools import lru_cache
from typing import Any

from jsonschema_rs import validator_for


def parse_evaluator_ref(evaluator_ref: str) -> tuple[str | None, str]:
    """Parse evaluator reference into (agent_name, evaluator_name).

    Built-in evaluators have no prefix, agent-scoped evaluators use {agent}:{name} format.

    Args:
        evaluator_ref: Evaluator reference string (e.g., "regex" or "my-agent:pii-detector")

    Returns:
        Tuple of (agent_name, evaluator_name):
        - (None, "regex") for built-in evaluators
        - ("my-agent", "pii-detector") for agent-scoped evaluators
    """
    if ":" in evaluator_ref:
        agent, name = evaluator_ref.split(":", 1)
        return agent, name
    return None, evaluator_ref


def _canonicalize_schema(schema: dict[str, Any]) -> str:
    """Return a canonical JSON string for a schema used as cache key."""
    return json.dumps(schema, sort_keys=True, separators=(",", ":"))


@lru_cache(maxsize=256)
def _get_compiled_validator(schema_json: str) -> Any:
    """Compile and cache a validator for the given canonicalized schema."""
    schema = json.loads(schema_json)
    return validator_for(schema)


def validate_config_against_schema(config: dict[str, Any], schema: dict[str, Any]) -> None:
    """Validate a config dict against a JSON Schema using jsonschema-rs.

    Compiles validators once per distinct schema and reuses them.

    Raises:
        ValidationError: If config doesn't match schema
    """
    if not schema:
        return  # Empty schema accepts anything

    schema_key = _canonicalize_schema(schema)
    validator = _get_compiled_validator(schema_key)
    # Raises jsonschema_rs.ValidationError on failure
    validator.validate(config)
