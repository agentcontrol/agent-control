"""Pytest configuration and fixtures for engine tests."""

import pytest

from agent_control_engine import clear_rule_cache, reset_rule_discovery
from agent_control_rules import clear_rules


@pytest.fixture(autouse=True)
def clean_rule_state() -> None:
    """Clean up rule registry and discovery state before each test.

    This fixture runs automatically for all tests to ensure isolation.
    Tests that mock entry_points won't pollute the registry for other tests.
    """
    clear_rules()
    reset_rule_discovery()
    clear_rule_cache()
