"""Direct tests for recursive condition-tree models."""

from __future__ import annotations

import pytest
from agent_control_models import ControlDefinition
from pydantic import ValidationError


def _leaf(
    path: str,
    evaluator_name: str = "regex",
    config: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "selector": {"path": path},
        "evaluator": {
            "name": evaluator_name,
            "config": config or {"pattern": "ok"},
        },
    }


def test_condition_leaf_requires_selector_and_evaluator() -> None:
    # Given: a leaf condition with only a selector
    with pytest.raises(
        ValidationError,
        match="Leaf condition requires both selector and evaluator",
    ):
        # When: validating the control definition
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {"selector": {"path": "input"}},
                "action": {"decision": "deny"},
            }
        )
    # Then: validation rejects the incomplete leaf shape


def test_condition_node_requires_exactly_one_shape() -> None:
    # Given: a condition node that mixes leaf and composite fields
    with pytest.raises(
        ValidationError,
        match="Condition node must contain exactly one of leaf, and, or, not",
    ):
        # When: validating the control definition
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {"name": "regex", "config": {"pattern": "ok"}},
                    "and": [_leaf("output")],
                },
                "action": {"decision": "deny"},
            }
        )
    # Then: validation rejects the ambiguous node shape


def test_legacy_leaf_payload_is_canonicalized() -> None:
    # Given: a legacy flat selector/evaluator payload
    legacy_payload = {
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {"name": "regex", "config": {"pattern": "ok"}},
        "action": {"decision": "deny"},
    }

    # When: validating the legacy payload
    control = ControlDefinition.model_validate(legacy_payload)

    # Then: the model dumps back out in canonical condition form
    dumped = control.model_dump(mode="json", exclude_none=True)
    assert "selector" not in dumped
    assert "evaluator" not in dumped
    assert dumped["condition"]["selector"]["path"] == "input"
    assert dumped["condition"]["evaluator"]["name"] == "regex"


def test_mixed_legacy_and_condition_fields_are_rejected() -> None:
    # Given: a payload that mixes canonical condition and legacy flat fields
    payload = {
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "condition": _leaf("input"),
        "selector": {"path": "output"},
        "evaluator": {"name": "regex", "config": {"pattern": "ok"}},
        "action": {"decision": "deny"},
    }

    with pytest.raises(
        ValidationError,
        match="Control definition mixes canonical condition fields "
        "with legacy selector/evaluator fields",
    ):
        # When: validating the mixed payload
        ControlDefinition.model_validate(payload)
    # Then: validation rejects the mixed shape


def test_condition_and_requires_at_least_one_child() -> None:
    # Given: an empty AND condition
    with pytest.raises(
        ValidationError,
        match="'and' must contain at least one child condition",
    ):
        # When: validating the control definition
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {"and": []},
                "action": {"decision": "deny"},
            }
        )
    # Then: validation rejects the empty composite


def test_condition_iter_leaves_preserves_left_to_right_order() -> None:
    # Given: a nested condition tree with leaves in several branches
    control = ControlDefinition.model_validate(
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": {
                "and": [
                    _leaf("input.user"),
                    {
                        "not": _leaf(
                            "input.role",
                            evaluator_name="list",
                            config={"values": ["admin"]},
                        )
                    },
                    {
                        "or": [
                            _leaf("output.first"),
                            _leaf("output.second"),
                        ]
                    },
                ]
            },
            "action": {"decision": "deny"},
        }
    )

    # When: iterating leaves and computing derived helpers
    paths = [
        leaf.leaf_parts()[0].path
        for leaf in control.iter_condition_leaves()
        if leaf.leaf_parts() is not None
    ]

    # Then: leaves are visited in evaluation order and tree helpers stay accurate
    assert paths == ["input.user", "input.role", "output.first", "output.second"]
    assert control.condition.max_depth() == 3
    assert control.primary_leaf() is None


def test_condition_depth_limit_is_enforced() -> None:
    # Given: a condition tree nested deeper than the allowed maximum
    too_deep = _leaf("input")
    for _ in range(6):
        too_deep = {"not": too_deep}

    with pytest.raises(
        ValidationError,
        match="Condition nesting depth exceeds maximum of 6",
    ):
        # When: validating the deep condition tree
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": too_deep,
                "action": {"decision": "deny"},
            }
        )
    # Then: validation rejects the over-nested tree


def test_composite_steer_requires_steering_context() -> None:
    # Given: a composite steer control without steering context
    with pytest.raises(
        ValidationError,
        match="Composite steer controls require action.steering_context",
    ):
        # When: validating the control definition
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "or": [
                        _leaf("input"),
                        _leaf("output"),
                    ]
                },
                "action": {"decision": "steer"},
            }
        )
    # Then: validation rejects the steer action without guidance


def test_single_leaf_control_returns_primary_leaf() -> None:
    # Given: a control whose entire condition is a single leaf
    control = ControlDefinition.model_validate(
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": _leaf("input.value"),
            "action": {"decision": "deny"},
        }
    )

    # When: asking for the primary leaf
    primary_leaf = control.primary_leaf()

    # Then: the original selector/evaluator pair is returned intact
    assert primary_leaf is not None
    leaf_parts = primary_leaf.leaf_parts()
    assert leaf_parts is not None
    selector, evaluator = leaf_parts
    assert selector.path == "input.value"
    assert evaluator.name == "regex"


def test_condition_observability_identity_uses_first_leaf_and_dedupes() -> None:
    # Given: a composite condition tree with repeated selectors/evaluators
    control = ControlDefinition.model_validate(
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": {
                "and": [
                    _leaf("input.user", evaluator_name="regex"),
                    _leaf("output.user", evaluator_name="regex"),
                    _leaf(
                        "output.user",
                        evaluator_name="list",
                        config={"values": ["blocked"]},
                    ),
                ]
            },
            "action": {"decision": "deny"},
        }
    )

    # When: deriving observability identity
    identity = control.observability_identity()

    # Then: the first leaf becomes the representative identity and full context stays ordered
    assert identity.selector_path == "input.user"
    assert identity.evaluator_name == "regex"
    assert identity.leaf_count == 3
    assert identity.all_evaluators == ["regex", "list"]
    assert identity.all_selector_paths == ["input.user", "output.user"]
