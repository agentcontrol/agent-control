"""Budget evaluator -- tracks cumulative LLM token/cost usage.

Deterministic evaluator: confidence is always 1.0, matched is True when
any configured limit is exceeded. Utilization ratio and spend breakdown
are returned in result metadata, not in confidence.

The evaluator is stateless. Budget state lives in a module-level store
registry, independent of the evaluator instance cache in _factory.py.
This prevents silent state loss on LRU eviction and avoids cross-control
leakage when different controls use different budget_id values.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Any

from agent_control_evaluators._base import Evaluator, EvaluatorMetadata
from agent_control_evaluators._registry import register_evaluator
from agent_control_models import EvaluatorResult

from .config import BudgetEvaluatorConfig, ModelPricing
from .memory_store import InMemoryBudgetStore, _scope_matches
from .store import BudgetStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level store registry
#
# Decoupled from the evaluator instance cache so that LRU eviction in
# _factory.py does not destroy accumulated budget state. The registry
# is keyed by budget_id. Controls with the same budget_id intentionally
# share accumulated spend; different budget_id values are isolated.
# ---------------------------------------------------------------------------

# NOTE: The registry is unbounded. In practice a deployment has a finite
# set of budget configs. If dynamic config generation becomes a concern,
# add a max-size cap with LRU eviction here.
_STORE_REGISTRY: dict[str, BudgetStore] = {}
_STORE_REGISTRY_LOCK = threading.Lock()


def get_or_create_store(config: BudgetEvaluatorConfig) -> BudgetStore:
    """Get or create a store for the given config, thread-safe."""
    key = f"budget:{config.budget_id}"
    with _STORE_REGISTRY_LOCK:
        store = _STORE_REGISTRY.get(key)
        if store is None:
            store = InMemoryBudgetStore()
            _STORE_REGISTRY[key] = store
        return store


def clear_budget_stores() -> None:
    """Clear all budget stores. Useful for testing."""
    with _STORE_REGISTRY_LOCK:
        _STORE_REGISTRY.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
            # When token_path resolves to a single int we cannot distinguish
            # input vs output. Attribute the whole count to output because
            # output rates are typically higher than input rates in pricing
            # tables, so this over-estimates cost rather than under-estimates.
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
    pricing: dict[str, ModelPricing] | None,
) -> float:
    """Estimate cost in cents (USD) from model pricing table.

    Returns a float for precision. Rounding happens at snapshot time,
    not per call.
    """
    if not model or not pricing:
        return 0.0
    rates = pricing.get(model)
    if not rates:
        return 0.0
    input_rate = rates.input_per_1k
    output_rate = rates.output_per_1k
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1000.0
    if not math.isfinite(cost) or cost < 0:
        return 0.0
    return cost


def _extract_metadata(data: Any, metadata_paths: dict[str, str]) -> dict[str, str]:
    """Extract metadata fields from step data using configured paths."""
    result: dict[str, str] = {}
    for field_name, path in metadata_paths.items():
        val = _extract_by_path(data, path)
        if val is not None:
            result[field_name] = str(val)
    return result


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


@register_evaluator
class BudgetEvaluator(Evaluator[BudgetEvaluatorConfig]):
    """Tracks cumulative LLM token and cost usage per scope and time window.

    Deterministic evaluator: matched=True when any configured limit is
    exceeded, confidence=1.0 always.

    The evaluator is stateless. Budget state is managed by a module-level
    store registry (get_or_create_store), not by the evaluator instance.
    """

    metadata = EvaluatorMetadata(
        name="budget",
        version="3.0.0",
        description="Cumulative LLM token and cost budget tracking",
    )
    config_model = BudgetEvaluatorConfig

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
        model_path_configured = bool(self.config.model_path)
        if model_path_configured:
            val = _extract_by_path(data, self.config.model_path)
            if val is not None:
                model = str(val)

        cost = _estimate_cost(model, input_tokens, output_tokens, self.config.pricing)

        step_metadata = _extract_metadata(data, self.config.metadata_paths)

        if model_path_configured and model is None:
            model_known = False
        else:
            model_known = (
                model is None or self.config.pricing is None or model in self.config.pricing
            )
        if not model_known:
            has_matching_cost_rule = any(
                rule.limit_unit == "usd_cents"
                and _scope_matches(rule, step_metadata)
                for rule in self.config.limits
            )
            if has_matching_cost_rule:
                if model is None:
                    block_reason = (
                        f"Model not found at path '{self.config.model_path}'"
                    )
                else:
                    block_reason = f"Unknown model: {model}"
                if self.config.unknown_model_behavior == "block":
                    return EvaluatorResult(
                        matched=True,
                        confidence=1.0,
                        message=f"{block_reason} (blocked)",
                        metadata={
                            "unknown_model": model,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        },
                    )
                logger.warning(
                    "Budget evaluator: %s, treating cost as 0 "
                    "(unknown_model_behavior=warn)",
                    block_reason,
                )

        store = get_or_create_store(self.config)
        snapshots = await store.record_and_check(
            rules=self.config.limits,
            scope=step_metadata,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
        )

        breached: list[dict[str, Any]] = []
        all_snaps: list[dict[str, Any]] = []

        for snap in snapshots:
            snap_info = {
                "spent": snap.spent,
                "spent_tokens": snap.spent_tokens,
                "limit": snap.limit,
                "limit_unit": snap.limit_unit,
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
                    "cost": round(cost, 6),
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
                "cost": round(cost, 6),
                "max_utilization": round(max_util, 4),
            },
        )
