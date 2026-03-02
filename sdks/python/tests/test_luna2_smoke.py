"""Smoke test for Luna2 SDK exports."""

import pytest


def test_luna2_exports_available_when_installed():
    """Verify SDK re-exports Luna2 types when package installed."""
    try:
        from agent_control.evaluators import (
            LUNA2_AVAILABLE,
            Luna2Evaluator,
            Luna2EvaluatorConfig,
        )

        assert LUNA2_AVAILABLE is True
        assert Luna2Evaluator is not None
        assert Luna2EvaluatorConfig is not None
    except ImportError:
        pytest.skip("agent-control-evaluator-galileo not installed")
