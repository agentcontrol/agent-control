"""Behavior tests for the DefenseClaw no-op evaluators."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from agent_control_evaluator_defenseclaw import (
    DefenseClawOpaPolicyEvaluator,
    DefenseClawRulePackEvaluator,
)


def _rule_pack_config() -> dict[str, object]:
    return {
        "rule_pack": {
            "rules": [
                {
                    "id": "rule-1",
                    "pattern": "example",
                    "title": "Example",
                    "severity": "LOW",
                    "confidence": 1.0,
                    "tags": [],
                }
            ]
        }
    }


def test_metadata_names_are_distinct_public_identifiers() -> None:
    assert DefenseClawRulePackEvaluator.metadata.name == "defenseclaw.rule_pack"
    assert DefenseClawOpaPolicyEvaluator.metadata.name == "defenseclaw.opa_policy"
    assert DefenseClawRulePackEvaluator is not DefenseClawOpaPolicyEvaluator


def test_entry_points_match_public_metadata_names() -> None:
    # Given: the installed-package manifest contract
    manifest_path = Path(__file__).parent.parent / "pyproject.toml"
    manifest = tomllib.loads(manifest_path.read_text())

    # When: reading evaluator entry points
    entry_points = manifest["project"]["entry-points"]["agent_control.evaluators"]

    # Then: both exact global names resolve to their distinct classes
    assert entry_points == {
        "defenseclaw.rule_pack": (
            "agent_control_evaluator_defenseclaw.rule_pack:DefenseClawRulePackEvaluator"
        ),
        "defenseclaw.opa_policy": (
            "agent_control_evaluator_defenseclaw.opa_policy:DefenseClawOpaPolicyEvaluator"
        ),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, "", "selected data", {"tool": "rm"}])
async def test_rule_pack_evaluation_is_a_no_op(data: object) -> None:
    # Given: a valid rule-pack evaluator
    evaluator = DefenseClawRulePackEvaluator.from_dict(_rule_pack_config())

    # When: evaluating any selected data
    result = await evaluator.evaluate(data)

    # Then: execution is intentionally inert and healthy
    assert result.matched is False
    assert result.confidence == 1.0
    assert result.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, "", "selected data", {"tool": "rm"}])
async def test_opa_policy_evaluation_is_a_no_op(data: object) -> None:
    # Given: a valid OPA-policy evaluator
    evaluator = DefenseClawOpaPolicyEvaluator.from_dict({"policy": {}})

    # When: evaluating any selected data
    result = await evaluator.evaluate(data)

    # Then: execution is intentionally inert and healthy
    assert result.matched is False
    assert result.confidence == 1.0
    assert result.error is None
