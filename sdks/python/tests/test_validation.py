"""Unit tests for SDK validation helpers."""

import pytest

from agent_control.validation import ensure_agent_name


def test_ensure_agent_name_normalizes_to_lowercase() -> None:
    assert ensure_agent_name("Agent-Name_123") == "agent-name_123"


def test_ensure_agent_name_rejects_too_short() -> None:
    with pytest.raises(ValueError, match="at least 10 characters"):
        ensure_agent_name("short")


def test_ensure_agent_name_rejects_invalid_characters() -> None:
    with pytest.raises(ValueError, match="may only contain"):
        ensure_agent_name("agent name with spaces")


def test_ensure_agent_name_respects_field_name() -> None:
    with pytest.raises(ValueError, match="custom_field must be at least 10 characters"):
        ensure_agent_name("small", field_name="custom_field")
