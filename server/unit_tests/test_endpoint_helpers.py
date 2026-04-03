"""Unit tests for endpoint helpers that don't require the DB test fixture."""

from types import SimpleNamespace

from agent_control_models import ControlDefinition, ControlMatch, EvaluatorResult
from agent_control_server.endpoints.agents import (
    _find_referencing_controls_for_removed_evaluators,
)
from agent_control_server.endpoints.evaluation import (
    ControlAdapter,
    _sanitize_control_match,
)


def test_find_referencing_controls_dedupes_composite_matches() -> None:
    # Given: two leaves in the same control reference the same evaluator
    controls = [
        SimpleNamespace(
            name="composite-ctrl",
            control=ControlDefinition(
                execution="server",
                condition={
                    "and": [
                        {
                            "selector": {"path": "input"},
                            "evaluator": {"name": "agent-123456:custom", "config": {}},
                        },
                        {
                            "selector": {"path": "output"},
                            "evaluator": {"name": "agent-123456:custom", "config": {}},
                        },
                    ]
                },
                action={"decision": "deny"},
            ),
        )
    ]

    # When: scanning for references to the evaluator being removed
    referencing_controls = _find_referencing_controls_for_removed_evaluators(
        controls,
        "agent-123456",
        {"custom"},
    )

    # Then: the same control/evaluator pair is reported only once
    assert referencing_controls == [("composite-ctrl", "custom")]


def test_sanitize_control_match_redacts_nested_condition_trace_errors() -> None:
    # Given: a composite control whose condition trace includes a raw evaluator error
    _ = ControlAdapter(
        id=1,
        name="composite-ctrl",
        control=ControlDefinition(
            execution="server",
            condition={
                "and": [
                    {
                        "selector": {"path": "input"},
                        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    },
                    {
                        "selector": {"path": "output"},
                        "evaluator": {"name": "list", "config": {"values": ["done"]}},
                    },
                ]
            },
            action={"decision": "observe"},
        ),
    )
    match = ControlMatch(
        control_id=1,
        control_name="composite-ctrl",
        action="observe",
        result=EvaluatorResult(
            matched=False,
            confidence=0.9,
            error="RuntimeError: secret evaluator failure",
            metadata={
                "condition_trace": {
                    "type": "and",
                    "children": [
                        {
                            "type": "leaf",
                            "error": "RuntimeError: secret evaluator failure",
                            "message": "Evaluation failed: RuntimeError: secret evaluator failure",
                        }
                    ],
                }
            },
        ),
    )

    # When: sanitizing the control match for API output
    sanitized = _sanitize_control_match(match)

    # Then: top-level and nested errors are redacted to the safe public message
    assert sanitized.result.error is not None
    assert "secret evaluator failure" not in sanitized.result.error
    trace = sanitized.result.metadata["condition_trace"]
    child = trace["children"][0]
    assert child["error"] == sanitized.result.error
    assert child["message"] == sanitized.result.error
