"""Temporal behavioral drift evaluator for Agent Control.

Detects gradual behavioral degradation that point-in-time evaluators miss
by tracking numeric scores over time and comparing recent windows to baselines.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult

from agent_control_evaluator_drift.drift.config import DriftEvaluatorConfig

logger = logging.getLogger(__name__)


def _load_history(path: Path) -> list[float]:
    """Load observation history from a JSON file.

    Args:
        path: Path to the history file.

    Returns:
        List of float scores, or empty list if file doesn't exist.
    """
    if not path.exists():
        return []
    try:
        with path.open("r") as fh:
            data = json.load(fh)
            scores = data.get("scores", [])
            return [float(s) for s in scores if isinstance(s, (int, float))]
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("Failed to load drift history from %s: %s", path, exc)
        return []


def _save_history(path: Path, scores: list[float]) -> None:
    """Persist observation history to a JSON file.

    Args:
        path: Path to the history file.
        scores: List of float scores to persist.

    Raises:
        OSError: If the file cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        json.dump({"scores": scores}, fh)


def _compute_drift(
    scores: list[float],
    window_size: int,
    baseline_size: int,
    drift_threshold: float,
    min_observations: int,
) -> dict[str, Any]:
    """Compute drift metrics from a score history.

    Args:
        scores: Full list of observations (oldest first).
        window_size: Number of recent observations for current window.
        baseline_size: Number of initial observations for baseline.
        drift_threshold: Drop magnitude that triggers alert.
        min_observations: Minimum observations before detection activates.

    Returns:
        Dict with keys: status, baseline_avg, recent_avg, drift_magnitude,
        observation_count, matched, confidence, message.
    """
    n = len(scores)

    if n < min_observations:
        return {
            "status": "insufficient_data",
            "observation_count": n,
            "baseline_avg": None,
            "recent_avg": None,
            "drift_magnitude": None,
            "matched": False,
            "confidence": 0.0,
            "message": f"Insufficient data: {n}/{min_observations} observations",
        }

    if n < baseline_size:
        return {
            "status": "baseline_building",
            "observation_count": n,
            "baseline_avg": round(sum(scores) / n, 4),
            "recent_avg": None,
            "drift_magnitude": None,
            "matched": False,
            "confidence": 0.0,
            "message": f"Building baseline: {n}/{baseline_size} observations collected",
        }

    baseline_scores = scores[:baseline_size]
    recent_scores = scores[-window_size:]

    baseline_avg = sum(baseline_scores) / len(baseline_scores)
    recent_avg = sum(recent_scores) / len(recent_scores)
    drift_magnitude = baseline_avg - recent_avg  # positive = drop

    matched = drift_magnitude >= drift_threshold

    if matched:
        status = "drift_detected"
        message = (
            f"Drift detected: baseline {baseline_avg:.3f} → recent {recent_avg:.3f} "
            f"(drop of {drift_magnitude:.3f}, threshold {drift_threshold:.3f})"
        )
        confidence = 1.0
    else:
        status = "stable"
        message = (
            f"Stable: baseline {baseline_avg:.3f}, recent {recent_avg:.3f} "
            f"(gap {drift_magnitude:.3f} < threshold {drift_threshold:.3f})"
        )
        confidence = 0.0

    return {
        "status": status,
        "observation_count": n,
        "baseline_avg": round(baseline_avg, 4),
        "recent_avg": round(recent_avg, 4),
        "drift_magnitude": round(drift_magnitude, 4),
        "matched": matched,
        "confidence": confidence,
        "message": message,
    }


@register_evaluator
class DriftEvaluator(Evaluator[DriftEvaluatorConfig]):
    """Temporal behavioral drift evaluator.

    Tracks a numeric behavioral score over time per agent and flags when
    recent performance diverges from an established baseline by more than
    the configured threshold.

    This evaluator fills the gap between point-in-time evaluators (which
    answer "is this response OK now?") and longitudinal reliability analysis
    (which answers "is this agent getting worse over time?").

    No external API or service required — history is stored as local JSON.

    Instance Caching Note:
        Per the base class contract, this evaluator stores only immutable
        config state in ``__init__``. All file I/O happens inside
        ``evaluate()`` using local variables, making it safe to reuse
        across concurrent requests (each call reads and writes atomically
        via a per-agent file lock-free JSON write).

    Example:
        ```python
        config = DriftEvaluatorConfig(
            agent_id="customer-support",
            drift_threshold=0.10,
        )
        evaluator = DriftEvaluator(config)
        result = await evaluator.evaluate(0.92)  # Pass current score
        ```
    """

    metadata = EvaluatorMetadata(
        name="drift.temporal",
        version="1.0.0",
        description=(
            "Temporal behavioral drift detection. Tracks numeric scores over time "
            "and alerts when recent performance drops below baseline. "
            "No external API required."
        ),
        requires_api_key=False,
        timeout_ms=1000,  # Local file I/O only — fast
    )
    config_model = DriftEvaluatorConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Record a behavioral score and check for drift.

        Args:
            data: Numeric score (float or int, 0.0–1.0) representing the
                agent's behavioral quality for this interaction. Higher is better.
                Typically sourced from a primary evaluator's confidence or
                extracted from agent output via a selector.

        Returns:
            EvaluatorResult where matched=True indicates drift detected.
        """
        # Validate and extract score
        try:
            score = float(data)
            if not (0.0 <= score <= 1.0):
                logger.warning(
                    "DriftEvaluator received score %.4f outside [0,1]; clamping.",
                    score,
                )
                score = max(0.0, min(1.0, score))
        except (TypeError, ValueError) as exc:
            logger.error("DriftEvaluator: cannot parse score from %r: %s", data, exc)
            matched = self.config.on_error == "deny"
            return EvaluatorResult(
                matched=matched,
                confidence=0.0,
                message=f"Invalid score value: {data!r}",
                metadata={
                    "error": str(exc),
                    "agent_id": self.config.agent_id,
                    "fallback_action": self.config.on_error,
                },
            )

        # Determine storage path
        storage_dir = Path(self.config.storage_path)
        history_path = storage_dir / f"{self.config.agent_id}.json"

        # Load existing history
        try:
            scores = _load_history(history_path)
        except Exception as exc:
            logger.error("DriftEvaluator: failed to load history: %s", exc)
            matched = self.config.on_error == "deny"
            return EvaluatorResult(
                matched=matched,
                confidence=0.0,
                message=f"Storage error (load): {exc}",
                metadata={
                    "error": str(exc),
                    "agent_id": self.config.agent_id,
                    "fallback_action": self.config.on_error,
                },
            )

        # Append new score
        scores.append(score)

        # Persist updated history
        try:
            _save_history(history_path, scores)
        except Exception as exc:
            logger.error("DriftEvaluator: failed to save history: %s", exc)
            # Still compute drift from in-memory scores even if save fails
            matched_on_error = self.config.on_error == "deny"
            if matched_on_error:
                return EvaluatorResult(
                    matched=True,
                    confidence=0.0,
                    message=f"Storage error (save): {exc}",
                    metadata={
                        "error": str(exc),
                        "agent_id": self.config.agent_id,
                        "fallback_action": self.config.on_error,
                    },
                )

        # Compute drift metrics
        metrics = _compute_drift(
            scores=scores,
            window_size=self.config.window_size,
            baseline_size=self.config.baseline_size,
            drift_threshold=self.config.drift_threshold,
            min_observations=self.config.min_observations,
        )

        return EvaluatorResult(
            matched=metrics["matched"],
            confidence=metrics["confidence"],
            message=metrics["message"],
            metadata={
                "agent_id": self.config.agent_id,
                "observation_count": metrics["observation_count"],
                "baseline_avg": metrics["baseline_avg"],
                "recent_avg": metrics["recent_avg"],
                "drift_magnitude": metrics["drift_magnitude"],
                "status": metrics["status"],
                "current_score": round(score, 4),
            },
        )
