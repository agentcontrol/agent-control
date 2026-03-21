"""Configuration model for the temporal drift evaluator."""

from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from pydantic import Field, model_validator


class DriftEvaluatorConfig(EvaluatorConfig):
    """Configuration for the temporal behavioral drift evaluator.

    Tracks a numeric score over time per agent and flags when recent
    performance diverges from an established baseline.

    Example:
        ```python
        config = DriftEvaluatorConfig(
            agent_id="sales-agent-prod",
            storage_path="/var/lib/agent-control/drift",
            window_size=10,
            baseline_size=20,
            drift_threshold=0.10,
        )
        ```

    Notes:
        - Drift detection activates only after ``min_observations`` runs.
        - During baseline building (first ``baseline_size`` observations),
          ``matched`` is always ``False``.
        - Storage is local JSON files; no external service required.
    """

    agent_id: str = Field(
        default="default",
        description="Unique identifier for the agent being tracked. "
        "Use distinct IDs to track multiple agents independently.",
    )
    storage_path: str = Field(
        default="/tmp/drift-history",
        description="Directory path for persisting observation history files. "
        "Each agent gets its own JSON file at <storage_path>/<agent_id>.json.",
    )
    window_size: int = Field(
        default=10,
        ge=2,
        le=100,
        description="Number of most-recent observations to use as the 'current' window "
        "when computing recent average. Must be >= 2.",
    )
    baseline_size: int = Field(
        default=20,
        ge=5,
        le=500,
        description="Number of initial observations used to compute the baseline average. "
        "Must be >= 5 (research finding: signals are noisy below 5 observations).",
    )
    drift_threshold: float = Field(
        default=0.10,
        ge=0.01,
        le=1.0,
        description="Minimum absolute drop in average score (0.0–1.0) from baseline "
        "to recent window that triggers a drift alert. Default 0.10 = 10 point drop.",
    )
    min_observations: int = Field(
        default=5,
        ge=1,
        description="Minimum total observations required before drift detection activates. "
        "Prevents false positives during ramp-up.",
    )
    on_error: Literal["allow", "deny"] = Field(
        default="allow",
        description="Behavior when storage read/write fails: "
        "'allow' (fail open, don't block) or 'deny' (fail closed, block).",
    )

    @model_validator(mode="after")
    def validate_window_vs_baseline(self) -> "DriftEvaluatorConfig":
        """Validate that window_size <= baseline_size."""
        if self.window_size > self.baseline_size:
            raise ValueError(
                f"window_size ({self.window_size}) must be <= "
                f"baseline_size ({self.baseline_size}). "
                "The recent window cannot be larger than the baseline."
            )
        return self
