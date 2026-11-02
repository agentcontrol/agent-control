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
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from agent_control_evaluators._base import Evaluator, EvaluatorMetadata
from agent_control_evaluators._registry import register_evaluator
from agent_control_models import EvaluatorResult, GatewayModelCandidate

from .config import BudgetEvaluatorConfig, GatewayRoutingConfig, ModelPricing
from .memory_store import InMemoryBudgetStore, _scope_matches
from .store import BudgetStore

logger = logging.getLogger(__name__)


def _resolve_package_version() -> str:
    """Return the installed package version, or a dev fallback during local imports."""
    try:
        return version("agent-control-evaluator-budget")
    except PackageNotFoundError:
        return "0.0.0.dev"


_PACKAGE_VERSION = _resolve_package_version()

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
            input_tokens = _extract_non_negative_int(inp)
            output_tokens = _extract_non_negative_int(out)
            if input_tokens is not None and output_tokens is not None:
                return input_tokens, output_tokens
            total = usage.get("total_tokens")
            if isinstance(total, int) and not isinstance(total, bool) and total > 0:
                return 0, max(0, total)
    return 0, 0


def _extract_non_negative_int(value: Any) -> int | None:
    """Return a non-negative integer or None for invalid token values."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return max(0, value)


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


def _gateway_route_metadata(
    data: Any,
    routing: GatewayRoutingConfig | None,
    snapshots: list[dict[str, Any]],
    *,
    over_limit: bool,
) -> dict[str, Any] | None:
    """Select a configured candidate using task tier and accumulated token use."""
    if routing is None:
        return None
    request_data = data if isinstance(data, dict) else {}
    task_type = request_data.get("task_type", "default")
    if not isinstance(task_type, str):
        task_type = "default"
    budget_snapshot = next(
        (snapshot for snapshot in snapshots if snapshot.get("limit_unit") == "tokens"), {}
    )
    used_tokens = int(budget_snapshot.get("spent_tokens", 0))
    limit_tokens = int(budget_snapshot.get("limit", 0))
    utilization = float(budget_snapshot.get("utilization", 0.0))
    threshold_reached = utilization >= routing.threshold
    task_tier = routing.task_tiers.get(task_type, routing.task_tiers.get("default"))
    selected_tier = (
        routing.threshold_tier
        if threshold_reached and routing.threshold_tier is not None
        else task_tier
    )
    reason = ""
    candidate: GatewayModelCandidate | None = None
    if over_limit:
        reason = "The configured token budget is exhausted."
    elif selected_tier is None:
        reason = f"No model tier is configured for task type '{task_type}'."
    else:
        raw_candidates = request_data.get("candidate_models", [])
        candidates: set[tuple[str, str, str]] = set()
        legacy_model = request_data.get("model")
        if isinstance(raw_candidates, list):
            for raw_candidate in raw_candidates:
                if isinstance(raw_candidate, dict):
                    try:
                        parsed = GatewayModelCandidate.model_validate(raw_candidate)
                    except ValueError:
                        continue
                    candidates.add((parsed.provider, parsed.model, parsed.protocol))
        if not candidates and isinstance(legacy_model, str):
            candidates = {
                (configured.provider, configured.model, configured.protocol)
                for configured in routing.tiers[selected_tier].models
                if configured.model == legacy_model
            }
        candidate = next(
            (
                configured
                for configured in routing.tiers[selected_tier].models
                if (configured.provider, configured.model, configured.protocol) in candidates
                and (not isinstance(legacy_model, str) or configured.model == legacy_model)
            ),
            None,
        )
        reason = (
            f"Budget threshold reached; routed to the '{selected_tier}' tier."
            if threshold_reached
            else f"Task type '{task_type}' routed to the '{selected_tier}' tier."
        ) if candidate is not None else (
            f"No compatible model candidate is available in tier '{selected_tier}'."
        )
    return {
        "allowed": candidate is not None and not over_limit,
        "provider": candidate.provider if candidate is not None and not over_limit else None,
        "model": candidate.model if candidate is not None and not over_limit else None,
        "protocol": candidate.protocol if candidate is not None and not over_limit else None,
        "task_type": task_type,
        "tier": selected_tier,
        "budget": {
            "used_tokens": used_tokens,
            "limit_tokens": limit_tokens,
            "utilization": min(utilization, 1.0),
            "threshold": routing.threshold,
            "threshold_reached": threshold_reached,
            "over_limit": over_limit,
        },
        "reason": reason,
    }


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
        version=_PACKAGE_VERSION,
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
        model_path = self.config.model_path
        model_path_configured = bool(model_path)
        if model_path:
            val = _extract_by_path(data, model_path)
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
                    block_reason = f"Model not found at path '{model_path}'"
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
            route_metadata = _gateway_route_metadata(
                data, self.config.gateway_routing, all_snaps, over_limit=True
            )
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
                    **({"gateway_route": route_metadata} if route_metadata is not None else {}),
                },
            )

        max_util = max((s["utilization"] for s in all_snaps), default=0.0)
        route_metadata = _gateway_route_metadata(
            data, self.config.gateway_routing, all_snaps, over_limit=False
        )
        return EvaluatorResult(
            matched=(
                self.config.gateway_routing is not None
                or bool(route_metadata and route_metadata.get("allowed"))
            ),
            confidence=1.0,
            message=(
                str(route_metadata.get("reason"))
                if route_metadata
                else f"Within budget (utilization={max_util:.0%})"
            ),
            metadata={
                "all_snapshots": all_snaps,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": round(cost, 6),
                "max_utilization": round(max_util, 4),
                **({"gateway_route": route_metadata} if route_metadata is not None else {}),
            },
        )
