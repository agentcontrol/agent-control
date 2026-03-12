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
    with pytest.raises(
        ValidationError,
        match="Leaf condition requires both selector and evaluator",
    ):
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {"selector": {"path": "input"}},
                "action": {"decision": "deny"},
            }
        )


def test_condition_node_requires_exactly_one_shape() -> None:
    with pytest.raises(
        ValidationError,
        match="Condition node must contain exactly one of leaf, and, or, not",
    ):
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


def test_legacy_leaf_payload_is_canonicalized() -> None:
    legacy_payload = {
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {"name": "regex", "config": {"pattern": "ok"}},
        "action": {"decision": "deny"},
    }

    control = ControlDefinition.model_validate(legacy_payload)

    dumped = control.model_dump(mode="json", exclude_none=True)
    assert "selector" not in dumped
    assert "evaluator" not in dumped
    assert dumped["condition"]["selector"]["path"] == "input"
    assert dumped["condition"]["evaluator"]["name"] == "regex"


def test_mixed_legacy_and_condition_fields_are_rejected() -> None:
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
        ControlDefinition.model_validate(payload)


def test_condition_and_requires_at_least_one_child() -> None:
    with pytest.raises(
        ValidationError,
        match="'and' must contain at least one child condition",
    ):
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {"and": []},
                "action": {"decision": "deny"},
            }
        )


def test_condition_iter_leaves_preserves_left_to_right_order() -> None:
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

    paths = [
        leaf.leaf_parts()[0].path
        for leaf in control.iter_condition_leaves()
        if leaf.leaf_parts() is not None
    ]

    assert paths == ["input.user", "input.role", "output.first", "output.second"]
    assert control.condition.max_depth() == 3
    assert control.primary_leaf() is None


def test_condition_depth_limit_is_enforced() -> None:
    too_deep = _leaf("input")
    for _ in range(6):
        too_deep = {"not": too_deep}

    with pytest.raises(
        ValidationError,
        match="Condition nesting depth exceeds maximum of 6",
    ):
        ControlDefinition.model_validate(
            {
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": too_deep,
                "action": {"decision": "deny"},
            }
        )


def test_composite_steer_requires_steering_context() -> None:
    with pytest.raises(
        ValidationError,
        match="Composite steer controls require action.steering_context",
    ):
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


def test_single_leaf_control_returns_primary_leaf() -> None:
    control = ControlDefinition.model_validate(
        {
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["pre"]},
            "condition": _leaf("input.value"),
            "action": {"decision": "deny"},
        }
    )

    primary_leaf = control.primary_leaf()

    assert primary_leaf is not None
    leaf_parts = primary_leaf.leaf_parts()
    assert leaf_parts is not None
    selector, evaluator = leaf_parts
    assert selector.path == "input.value"
    assert evaluator.name == "regex"
