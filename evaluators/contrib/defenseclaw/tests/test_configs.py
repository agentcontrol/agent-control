"""Contract tests for the DefenseClaw evaluator configurations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_control_evaluator_defenseclaw import (
    DefenseClawOpaPolicyConfig,
    DefenseClawRulePackConfig,
)


def _rule_pack_config() -> dict[str, object]:
    return {
        "schema_version": 1,
        "rule_pack": {
            "version": 1,
            "category": "agent-control",
            "rules": [
                {
                    "id": "AC-CMD-RM-RF",
                    "pattern": "rm\\s+-rf",
                    "title": "Recursive deletion",
                    "severity": "HIGH",
                    "confidence": 0.99,
                    "tags": ["filesystem"],
                }
            ],
        },
    }


def test_rule_pack_example_round_trips_with_fixed_fields() -> None:
    # Given: the supplied rule-pack example
    config = _rule_pack_config()

    # When: validating and serializing it
    serialized = DefenseClawRulePackConfig.model_validate(config).model_dump()

    # Then: fixed fields and nested rules are preserved
    assert serialized == config


def test_rule_pack_defaults_are_serialized() -> None:
    # Given: a rule pack omitting fields with fixed v1 defaults
    config = _rule_pack_config()
    config.pop("schema_version")
    rule_pack = config["rule_pack"]
    assert isinstance(rule_pack, dict)
    rule_pack.pop("version")
    rule_pack.pop("category")

    # When: validating and serializing it
    serialized = DefenseClawRulePackConfig.model_validate(config).model_dump()

    # Then: the wire-contract constants are materialized
    assert serialized["schema_version"] == 1
    assert serialized["rule_pack"]["version"] == 1
    assert serialized["rule_pack"]["category"] == "agent-control"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), 2),
        (("rule_pack", "version"), 2),
        (("rule_pack", "category"), "other"),
        (("rule_pack", "rules", 0, "severity"), "URGENT"),
        (("rule_pack", "rules", 0, "confidence"), -0.1),
        (("rule_pack", "rules", 0, "confidence"), 1.1),
    ],
)
def test_rule_pack_rejects_unsupported_values(path: tuple[object, ...], value: object) -> None:
    # Given: a valid config with one unsupported nested value
    config = _rule_pack_config()
    target: object = config
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]

    # When/Then: typed validation rejects it
    with pytest.raises(ValidationError):
        DefenseClawRulePackConfig.model_validate(config)


def test_rule_pack_rejects_empty_and_duplicate_rules() -> None:
    # Given: an empty rule list
    empty = _rule_pack_config()
    empty["rule_pack"]["rules"] = []  # type: ignore[index]

    # When/Then: at least one rule is required
    with pytest.raises(ValidationError):
        DefenseClawRulePackConfig.model_validate(empty)

    # Given: duplicate rule IDs
    duplicate = _rule_pack_config()
    first_rule = duplicate["rule_pack"]["rules"][0]  # type: ignore[index]
    duplicate["rule_pack"]["rules"].append(dict(first_rule))  # type: ignore[index,union-attr]

    # When/Then: duplicate IDs are rejected
    with pytest.raises(ValidationError, match="rule ids must be unique"):
        DefenseClawRulePackConfig.model_validate(duplicate)


def test_rule_pack_rejects_blank_strings_and_unknown_fields() -> None:
    # Given: whitespace-only required values and an unknown provider key
    config = _rule_pack_config()
    rule = config["rule_pack"]["rules"][0]  # type: ignore[index]
    rule["id"] = "   "
    rule["unknown"] = True

    # When/Then: strict validation rejects both errors
    with pytest.raises(ValidationError) as exc_info:
        DefenseClawRulePackConfig.model_validate(config)
    errors = exc_info.value.errors()
    assert any(error["loc"][-1] == "id" for error in errors)
    assert any(error["loc"][-1] == "unknown" for error in errors)


def test_opa_policy_example_and_defaults() -> None:
    # Given: the supplied policy example
    config = {
        "schema_version": 1,
        "policy": {
            "domain": "guardrail",
            "block_at": "HIGH",
            "alert_at": "MEDIUM",
            "cisco_trust_level": "full",
        },
    }

    # When: validating it and validating a default policy
    serialized = DefenseClawOpaPolicyConfig.model_validate(config).model_dump()
    defaults = DefenseClawOpaPolicyConfig.model_validate({"policy": {}}).model_dump()

    # Then: both serialize to the canonical policy envelope
    assert serialized == config
    assert defaults == config


@pytest.mark.parametrize(
    "policy",
    [
        {"domain": "other"},
        {"block_at": "URGENT"},
        {"alert_at": "URGENT"},
        {"cisco_trust_level": "partial"},
        {"unexpected": True},
    ],
)
def test_opa_policy_rejects_unsupported_values(policy: dict[str, object]) -> None:
    # Given/When/Then: an unsupported provider value is rejected
    with pytest.raises(ValidationError):
        DefenseClawOpaPolicyConfig.model_validate({"policy": policy})
