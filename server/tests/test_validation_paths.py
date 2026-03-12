"""Tests for nested validation field path formatting."""

from agent_control_server.services.validation_paths import format_field_path


def test_format_field_path_renders_dot_and_bracket_notation() -> None:
    assert (
        format_field_path(
            ("data", "condition", "and", 0, "evaluator", "config", "logic")
        )
        == "data.condition.and[0].evaluator.config.logic"
    )


def test_format_field_path_empty_sequence_returns_none() -> None:
    assert format_field_path(()) is None
