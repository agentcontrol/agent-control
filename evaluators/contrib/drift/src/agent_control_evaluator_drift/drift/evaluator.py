"""Temporal behavioral drift evaluator for Agent Control.

Detects gradual behavioral degradation that point-in-time evaluators miss
by tracking numeric scores over time and comparing recent windows to baselines.
"""

from __future__ import annotations

import fcntl
import json
import logging
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
        List of float scores, or empty list if file doesn't exist or cannot be read.
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


def _load_and_append_history(path: Path, score: float) -> list[float]:
    """Atomically load history, append a score, persist, and return the updated list.

    Uses an exclusive advisory lock (``fcntl.LOCK_EX``) on the history file so
    that concurrent workers for the same agent do not race on the
    read-modify-write cycle.  Without this, two simultaneous calls can both read
    the same stale list and the last writer silently drops the other's
    observation, causing drift detection to miss events.

    Args:
        path: Path to the per-agent JSON history file.
        score: New observation to append (already validated, in [0.0, 1.0]).

    Returns:
        Updated list of float scores (oldest first), including *score*.

    Raises:
        OSError: If the lock file or history file cannot be opened or written.
        json.JSONDecodeError: If the history file contains malformed JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")

    # Open (or create) the lock file and hold an exclusive lock for the
    # duration of the read-modify-write.  The lock is released automatically
    # when the file descriptor is closed at the end of this block.
    with lock_path.open("a") as lock_fh:
        fcntl.flock(lock_fh, fcntl.LOCK_EX)

        # Read existing scores under the lock.
        scores: list[float] = []
        if path.exists():
            try:
                with path.open("r") as fh:
                    data = json.load(fh)
                    scores = [
                        float(s)
                        for s in data.get("scores", [])
                        if isinstance(s, (int, float))
                    ]
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Corrupt drift history at %s; resetting. Error: %s", path, exc)
                scores = []

        # Append and persist while the lock is still held.
        scores.append(score)
        with path.open("w") as fh:
            json.dump({"scores": scores}, fh)

        # Lock released here when lock_fh closes.

    return scores


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

    # Round before threshold comparison to avoid float precision issues.
    # e.g. 1.0 - 0.9 evaluates to 0.09999999... in IEEE 754, which fails a
    # >= 0.10 check without rounding.  Rounding to 10 decimal places preserves
    # all meaningful precision while eliminating the ULP-level noise.
    matched = round(drift_magnitude, 10) >= drift_threshold

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

    Concurrency:
        Each ``evaluate()`` call uses an exclusive advisory file lock
        (``fcntl.LOCK_EX``) scoped to the read-modify-write cycle, ensuring
        that concurrent workers for the same ``agent_id`` never race on
        history updates.  The lock is per-agent (``<agent_id>.lock`` next to
        ``<agent_id>.json``), so different agents remain fully parallel.

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

        # Atomically load, append, and persist history under a file lock.
        try:
            scores = _load_and_append_history(history_path, score)
        except Exception as exc:
            logger.error("DriftEvaluator: storage error: %s", exc)
            matched = self.config.on_error == "deny"
            return EvaluatorResult(
                matched=matched,
                confidence=0.0,
                message=f"Storage error: {exc}",
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
