"""Tests for the temporal behavioral drift evaluator.

Tests are designed to run without external dependencies — all file I/O
is redirected to a temporary directory.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from agent_control_evaluators import Evaluator
from agent_control_models import EvaluatorResult
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestDriftEvaluatorConfig:
    """Tests for DriftEvaluatorConfig Pydantic model."""

    def test_defaults(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        config = DriftEvaluatorConfig()
        assert config.agent_id == "default"
        assert config.window_size == 10
        assert config.baseline_size == 20
        assert config.drift_threshold == 0.10
        assert config.min_observations == 5
        assert config.on_error == "allow"

    def test_custom_values(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="my-agent",
            window_size=5,
            baseline_size=15,
            drift_threshold=0.20,
            min_observations=3,
            on_error="deny",
        )
        assert config.agent_id == "my-agent"
        assert config.window_size == 5
        assert config.baseline_size == 15
        assert config.drift_threshold == 0.20
        assert config.min_observations == 3
        assert config.on_error == "deny"

    def test_window_cannot_exceed_baseline(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        with pytest.raises(ValidationError, match="window_size.*must be <="):
            DriftEvaluatorConfig(window_size=25, baseline_size=20)

    def test_window_equal_to_baseline_is_valid(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        config = DriftEvaluatorConfig(window_size=20, baseline_size=20)
        assert config.window_size == config.baseline_size

    def test_drift_threshold_bounds(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        # Below min
        with pytest.raises(ValidationError):
            DriftEvaluatorConfig(drift_threshold=0.0)

        # Above max
        with pytest.raises(ValidationError):
            DriftEvaluatorConfig(drift_threshold=1.1)

    def test_on_error_validation(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        DriftEvaluatorConfig(on_error="allow")
        DriftEvaluatorConfig(on_error="deny")

        with pytest.raises(ValidationError):
            DriftEvaluatorConfig(on_error="ignore")

    def test_baseline_size_minimum(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        with pytest.raises(ValidationError):
            DriftEvaluatorConfig(baseline_size=4)  # below ge=5

    def test_window_size_minimum(self):
        from agent_control_evaluator_drift.drift import DriftEvaluatorConfig

        with pytest.raises(ValidationError):
            DriftEvaluatorConfig(window_size=1)  # below ge=2


# ---------------------------------------------------------------------------
# Evaluator inheritance / metadata
# ---------------------------------------------------------------------------


class TestDriftEvaluatorInheritance:
    def test_extends_base_evaluator(self):
        from agent_control_evaluator_drift.drift import DriftEvaluator

        assert issubclass(DriftEvaluator, Evaluator)

    def test_metadata_fields(self):
        from agent_control_evaluator_drift.drift import DriftEvaluator

        meta = DriftEvaluator.metadata
        assert meta.name == "drift.temporal"
        assert meta.requires_api_key is False
        assert "drift" in meta.description.lower()

    def test_is_available(self):
        from agent_control_evaluator_drift.drift import DriftEvaluator

        assert DriftEvaluator.is_available() is True


# ---------------------------------------------------------------------------
# Core helper functions
# ---------------------------------------------------------------------------


class TestComputeDrift:
    def _compute(self, scores, window=5, baseline=10, threshold=0.10, min_obs=5):
        from agent_control_evaluator_drift.drift.evaluator import _compute_drift

        return _compute_drift(scores, window, baseline, threshold, min_obs)

    def test_insufficient_data(self):
        result = self._compute(scores=[0.9, 0.8, 0.7], min_obs=5)
        assert result["status"] == "insufficient_data"
        assert result["matched"] is False

    def test_baseline_building(self):
        scores = [0.9] * 7  # 7 obs, min_obs=5, baseline=10
        result = self._compute(scores=scores)
        assert result["status"] == "baseline_building"
        assert result["matched"] is False

    def test_stable_after_baseline(self):
        # 10 good baseline + 5 good recent → no drift
        scores = [0.9] * 10 + [0.88] * 5
        result = self._compute(scores=scores)
        assert result["status"] == "stable"
        assert result["matched"] is False
        assert result["baseline_avg"] == pytest.approx(0.9, abs=0.01)
        assert result["recent_avg"] == pytest.approx(0.88, abs=0.01)

    def test_drift_detected(self):
        # 10 good baseline, then 5 bad recent
        scores = [0.9] * 10 + [0.7] * 5
        result = self._compute(scores=scores, threshold=0.10)
        assert result["status"] == "drift_detected"
        assert result["matched"] is True
        assert result["drift_magnitude"] == pytest.approx(0.20, abs=0.01)

    def test_exactly_at_threshold_triggers(self):
        # Drop of exactly 0.10 should trigger (>= threshold)
        baseline = [1.0] * 10
        recent_window = [0.9] * 5
        scores = baseline + recent_window
        result = self._compute(scores=scores, threshold=0.10)
        assert result["matched"] is True

    def test_just_below_threshold_does_not_trigger(self):
        baseline = [1.0] * 10
        recent_window = [0.91] * 5
        scores = baseline + recent_window
        result = self._compute(scores=scores, threshold=0.10)
        assert result["matched"] is False

    def test_observation_count_returned(self):
        scores = [0.9] * 15
        result = self._compute(scores=scores)
        assert result["observation_count"] == 15


class TestHistoryIO:
    def test_load_missing_file_returns_empty(self, tmp_path):
        from agent_control_evaluator_drift.drift.evaluator import _load_history

        path = tmp_path / "nonexistent.json"
        assert _load_history(path) == []

    def test_save_and_load_roundtrip(self, tmp_path):
        from agent_control_evaluator_drift.drift.evaluator import _load_history, _save_history

        path = tmp_path / "scores.json"
        _save_history(path, [0.9, 0.85, 0.8])
        loaded = _load_history(path)
        assert loaded == pytest.approx([0.9, 0.85, 0.8])

    def test_save_creates_parent_dirs(self, tmp_path):
        from agent_control_evaluator_drift.drift.evaluator import _save_history

        path = tmp_path / "nested" / "deep" / "scores.json"
        _save_history(path, [0.5])
        assert path.exists()

    def test_load_corrupted_json_returns_empty(self, tmp_path):
        from agent_control_evaluator_drift.drift.evaluator import _load_history

        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{{")
        result = _load_history(path)
        assert result == []


# ---------------------------------------------------------------------------
# Full evaluator integration tests
# ---------------------------------------------------------------------------


class TestDriftEvaluatorIntegration:
    @pytest.mark.asyncio
    async def test_insufficient_data_returns_not_matched(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="test",
            storage_path=str(tmp_path),
            window_size=5,
            baseline_size=10,
            min_observations=5,
        )
        evaluator = DriftEvaluator(config)

        # Only 2 observations — below min_observations
        await evaluator.evaluate(0.9)
        result = await evaluator.evaluate(0.9)

        assert isinstance(result, EvaluatorResult)
        assert result.matched is False
        assert result.metadata["status"] == "insufficient_data"

    @pytest.mark.asyncio
    async def test_baseline_building_phase(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="test",
            storage_path=str(tmp_path),
            window_size=3,
            baseline_size=10,
            min_observations=5,
        )
        evaluator = DriftEvaluator(config)

        # Feed 7 observations (>= min_obs but < baseline_size)
        for _ in range(7):
            result = await evaluator.evaluate(0.9)

        assert result.matched is False
        assert result.metadata["status"] == "baseline_building"

    @pytest.mark.asyncio
    async def test_stable_agent_no_alert(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="stable",
            storage_path=str(tmp_path),
            window_size=5,
            baseline_size=10,
            drift_threshold=0.10,
            min_observations=5,
        )
        evaluator = DriftEvaluator(config)

        # 10 baseline + 5 stable recent
        for _ in range(15):
            result = await evaluator.evaluate(0.9)

        assert result.matched is False
        assert result.metadata["status"] == "stable"

    @pytest.mark.asyncio
    async def test_drifting_agent_triggers_alert(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="drifting",
            storage_path=str(tmp_path),
            window_size=5,
            baseline_size=10,
            drift_threshold=0.10,
            min_observations=5,
        )
        evaluator = DriftEvaluator(config)

        # Strong baseline
        for _ in range(10):
            await evaluator.evaluate(0.95)

        # Degraded recent window
        for _ in range(4):
            await evaluator.evaluate(0.70)

        result = await evaluator.evaluate(0.70)

        assert result.matched is True
        assert result.metadata["status"] == "drift_detected"
        assert result.metadata["baseline_avg"] == pytest.approx(0.95, abs=0.01)
        assert result.metadata["recent_avg"] == pytest.approx(0.70, abs=0.01)
        assert result.metadata["drift_magnitude"] == pytest.approx(0.25, abs=0.01)

    @pytest.mark.asyncio
    async def test_history_persists_across_evaluator_instances(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        def make_evaluator():
            return DriftEvaluator(
                DriftEvaluatorConfig(
                    agent_id="persist-test",
                    storage_path=str(tmp_path),
                    window_size=5,
                    baseline_size=10,
                    drift_threshold=0.10,
                    min_observations=5,
                )
            )

        # Instance 1: record 10 baseline observations
        ev1 = make_evaluator()
        for _ in range(10):
            await ev1.evaluate(0.9)

        # Instance 2: picks up history, records drift
        ev2 = make_evaluator()
        for _ in range(5):
            await ev2.evaluate(0.5)

        result = await ev2.evaluate(0.5)
        assert result.matched is True
        assert result.metadata["observation_count"] == 16

    @pytest.mark.asyncio
    async def test_score_clamped_outside_range(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="clamp",
            storage_path=str(tmp_path),
        )
        evaluator = DriftEvaluator(config)

        # Should not raise; score is clamped
        result = await evaluator.evaluate(1.5)
        assert isinstance(result, EvaluatorResult)
        assert result.metadata["current_score"] == 1.0

        result = await evaluator.evaluate(-0.5)
        assert result.metadata["current_score"] == 0.0

    @pytest.mark.asyncio
    async def test_invalid_score_fail_open(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="error",
            storage_path=str(tmp_path),
            on_error="allow",
        )
        evaluator = DriftEvaluator(config)

        result = await evaluator.evaluate("not-a-number")
        assert result.matched is False
        assert "Invalid score value" in result.message

    @pytest.mark.asyncio
    async def test_invalid_score_fail_closed(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="error-deny",
            storage_path=str(tmp_path),
            on_error="deny",
        )
        evaluator = DriftEvaluator(config)

        result = await evaluator.evaluate({"not": "a number"})
        assert result.matched is True
        assert result.metadata["fallback_action"] == "deny"

    @pytest.mark.asyncio
    async def test_separate_agent_ids_tracked_independently(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        def make_evaluator(agent_id):
            return DriftEvaluator(
                DriftEvaluatorConfig(
                    agent_id=agent_id,
                    storage_path=str(tmp_path),
                    window_size=5,
                    baseline_size=10,
                    drift_threshold=0.10,
                    min_observations=5,
                )
            )

        good_ev = make_evaluator("good-agent")
        bad_ev = make_evaluator("bad-agent")

        # Good agent stays stable
        for _ in range(15):
            await good_ev.evaluate(0.9)

        # Bad agent drifts
        for _ in range(10):
            await bad_ev.evaluate(0.9)
        for _ in range(5):
            await bad_ev.evaluate(0.5)

        good_result = await good_ev.evaluate(0.9)
        bad_result = await bad_ev.evaluate(0.5)

        assert good_result.matched is False
        assert bad_result.matched is True

    @pytest.mark.asyncio
    async def test_metadata_contains_required_fields(self, tmp_path):
        from agent_control_evaluator_drift.drift import DriftEvaluator, DriftEvaluatorConfig

        config = DriftEvaluatorConfig(
            agent_id="meta-test",
            storage_path=str(tmp_path),
            window_size=5,
            baseline_size=10,
        )
        evaluator = DriftEvaluator(config)

        result = await evaluator.evaluate(0.85)
        meta = result.metadata

        required_keys = {
            "agent_id",
            "observation_count",
            "status",
            "current_score",
        }
        assert required_keys.issubset(meta.keys())
        assert meta["agent_id"] == "meta-test"
        assert meta["current_score"] == pytest.approx(0.85, abs=0.001)
