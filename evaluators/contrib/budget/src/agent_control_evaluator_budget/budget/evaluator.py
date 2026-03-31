"""Budget evaluator -- tracks cumulative LLM token/cost usage.

Deterministic evaluator: confidence is always 1.0, matched is True when
any configured limit is exceeded. Utilization ratio and spend breakdown
are returned in result metadata, not in confidence.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from agent_control_evaluators._base import Evaluator, EvaluatorMetadata
from agent_control_evaluators._registry import register_evaluator
from agent_control_models import EvaluatorResult

from .config import BudgetEvaluatorConfig
from .memory_store import InMemoryBudgetStore

logger = logging.getLogger(__name__)


def _extract_by_path(data: Any, path: str) -> Any:
    """Extract a value from nested data using dot-notation path."""
    current = data
    for part in path.split("."):
        if part.startswith("__"):
            return None
        if isinstance(current, dict):
            current = current.get(part)
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None
        if current is None:
            return None
    return current


def _extract_tokens(data: Any, token_path: str | None) -> tuple[int, int]:
    """Extract (input_tokens, output_tokens) from step data.

    Tries token_path first, then standard field names.
    Returns (0, 0) if no token information found.
    """
    if data is None:
        return 0, 0

    if token_path:
        val = _extract_by_path(data, token_path)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            return 0, val
        if isinstance(val, dict):
            data = val

    if isinstance(data, dict):
        usage = data.get("usage", data)
        if isinstance(usage, dict):
            inp = usage.get("input_tokens")
            if inp is None:
                inp = usage.get("prompt_tokens")
            out = usage.get("output_tokens")
            if out is None:
                out = usage.get("completion_tokens")
            inp_ok = isinstance(inp, int) and not isinstance(inp, bool)
            out_ok = isinstance(out, int) and not isinstance(out, bool)
            if inp_ok and out_ok:
                return max(0, inp), max(0, out)
            total = usage.get("total_tokens")
            if isinstance(total, int) and not isinstance(total, bool) and total > 0:
                return 0, max(0, total)
    return 0, 0


def _estimate_cost(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, dict[str, float]] | None,
) -> int:
    """Estimate cost in minor units from model pricing table. Returns 0 if unknown."""
    if not model or not pricing:
        return 0
    rates = pricing.get(model)
    if not rates:
        return 0
    input_rate = rates.get("input_per_1k", 0.0)
    output_rate = rates.get("output_per_1k", 0.0)
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1000.0
    if not math.isfinite(cost) or cost < 0:
        return 0
    return math.ceil(cost)


def _extract_metadata(data: Any, metadata_paths: dict[str, str]) -> dict[str, str]:
    """Extract metadata fields from step data using configured paths."""
    result: dict[str, str] = {}
    for field_name, path in metadata_paths.items():
        val = _extract_by_path(data, path)
        if val is not None:
            result[field_name] = str(val)
    return result


@register_evaluator
class BudgetEvaluator(Evaluator[BudgetEvaluatorConfig]):
    """Tracks cumulative LLM token and cost usage per scope and time window.

    Deterministic evaluator: matched=True when any configured limit is
    exceeded, confidence=1.0 always.

    The evaluator is stateful -- it accumulates usage in a BudgetStore.
    The store is created per evaluator config and is thread-safe.
    """

    metadata = EvaluatorMetadata(
        name="budget",
        version="2.0.0",
        description="Cumulative LLM token and cost budget tracking",
    )
    config_model = BudgetEvaluatorConfig

    def __init__(self, config: BudgetEvaluatorConfig) -> None:
        super().__init__(config)
        self._store = InMemoryBudgetStore(rules=config.limits)

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate step data against all configured budget limits."""
        if data is None:
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No data to evaluate",
            )

        input_tokens, output_tokens = _extract_tokens(data, self.config.token_path)

        model: str | None = None
        if self.config.model_path:
            val = _extract_by_path(data, self.config.model_path)
            if val is not None:
                model = str(val)

        cost = _estimate_cost(model, input_tokens, output_tokens, self.config.pricing)

        step_metadata = _extract_metadata(data, self.config.metadata_paths)

        snapshots = self._store.record_and_check(
            scope=step_metadata,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )

        breached: list[dict[str, Any]] = []
        all_snaps: list[dict[str, Any]] = []

        for i, snap in enumerate(snapshots):
            snap_info = {
                "spent": snap.spent,
                "spent_tokens": snap.spent_tokens,
                "limit": snap.limit,
                "limit_tokens": snap.limit_tokens,
                "utilization": round(snap.utilization, 4),
                "exceeded": snap.exceeded,
            }
            all_snaps.append(snap_info)
            if snap.exceeded:
                breached.append(snap_info)

        if breached:
            first = breached[0]
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=f"Budget exceeded (utilization={first['utilization']:.0%})",
                metadata={
                    "breached_rules": breached,
                    "all_snapshots": all_snaps,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost": cost,
                },
            )

        max_util = max((s["utilization"] for s in all_snaps), default=0.0)
        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message=f"Within budget (utilization={max_util:.0%})",
            metadata={
                "all_snapshots": all_snaps,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "max_utilization": round(max_util, 4),
            },
        )
