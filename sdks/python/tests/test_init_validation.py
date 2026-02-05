"""Validation tests for agent_control.init()."""

import pytest

import agent_control


def test_init_rejects_invalid_uuid() -> None:
    with pytest.raises(ValueError, match="agent_id must be a valid UUID"):
        agent_control.init(agent_name="Invalid UUID Agent", agent_id="not-a-uuid")
