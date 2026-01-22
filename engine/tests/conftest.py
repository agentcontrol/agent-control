"""Pytest configuration and fixtures for engine tests."""

import pytest
from agent_control_engine.discovery import reset_discovery
from agent_control_engine.evaluators import clear_evaluator_cache
from agent_control_models import clear_plugins


@pytest.fixture(autouse=True)
def clean_plugin_state() -> None:
    """Clean up plugin registry and discovery state before each test.

    This fixture runs automatically for all tests to ensure isolation.
    Tests that mock entry_points won't pollute the registry for other tests.
    """
    clear_plugins()
    reset_discovery()
    clear_evaluator_cache()
