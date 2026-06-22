"""Utilities for working with rule references.

Rule Type Name Formats:
    - Built-in: "regex", "list", "json", "sql"
    - External: "galileo.luna", "nvidia.nemo" (dot separator)
    - Agent-scoped: "my-agent:pii-detector" (colon separator)

The key distinction is:
    - Built-in and external rules are global (available to all agents)
    - Agent-scoped rules are custom implementations deployed with a specific agent
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from jsonschema_rs import validator_for


@dataclass
class ParsedRuleRef:
    """Parsed rule reference with type information.

    Attributes:
        type: The rule category ("builtin", "external", or "agent")
        name: The full rule name (e.g., "regex", "galileo.luna", "my-agent:pii")
        namespace: For external rules, the provider name; for agent-scoped, the agent name
        local_name: The rule name without namespace prefix
    """

    type: Literal["builtin", "external", "agent"]
    name: str
    namespace: str | None
    local_name: str


def parse_rule_ref_full(rule_ref: str) -> ParsedRuleRef:
    """Parse rule reference into structured form with type detection.

    Determines the rule type based on the name format:
    - Contains ":" → agent-scoped (split on first ":")
    - Contains "." → external (split on first ".")
    - Otherwise → built-in

    Args:
        rule_ref: Rule reference string

    Returns:
        ParsedRuleRef with type, namespace, and local name

    Examples:
        >>> parse_rule_ref_full("regex")
        ParsedRuleRef(type="builtin", name="regex", ...)

        >>> parse_rule_ref_full("galileo.luna")
        ParsedRuleRef(type="external", namespace="galileo", ...)

        >>> parse_rule_ref_full("my-agent:pii-detector")
        ParsedRuleRef(type="agent", namespace="my-agent", ...)
    """
    if ":" in rule_ref:
        # Agent-scoped: "my-agent:pii-detector"
        agent, local_name = rule_ref.split(":", 1)
        return ParsedRuleRef(
            type="agent",
            name=rule_ref,
            namespace=agent,
            local_name=local_name,
        )
    elif "." in rule_ref:
        # External: "galileo.luna"
        provider, local_name = rule_ref.split(".", 1)
        return ParsedRuleRef(
            type="external",
            name=rule_ref,
            namespace=provider,
            local_name=local_name,
        )
    else:
        # Built-in: "regex"
        return ParsedRuleRef(
            type="builtin",
            name=rule_ref,
            namespace=None,
            local_name=rule_ref,
        )


def is_agent_scoped(rule_ref: str) -> bool:
    """Check if a rule reference is agent-scoped.

    Agent-scoped rules use the "agent:name" format and reference
    custom implementations deployed with a specific agent.

    Args:
        rule_ref: Rule reference string

    Returns:
        True if agent-scoped, False for built-in or external rules
    """
    return ":" in rule_ref


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
