from typing import Any

from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult

from .config import TieredDiscountConfig


@register_evaluator
class TieredDiscountEvaluator(Evaluator[TieredDiscountConfig]):
    """Deny discounts above tier-specific limits.

    Expects data as a dict with keys:
      - tier: str (e.g., "standard", "premium")
      - discount_pct: int
    """

    metadata = EvaluatorMetadata(
        name="acme.tiered-discount",
        version="1.0.0",
        description="Blocks discounts above tier-specific limits",
    )
    config_model = TieredDiscountConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        if not isinstance(data, dict):
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Invalid input: expected object with tier and discount_pct",
            )

        tier = str(data.get("tier", "unknown")).lower()
        try:
            discount = int(data.get("discount_pct"))
        except Exception:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message="Invalid discount_pct",
            )

        limit = self.config.limits.get(tier, self.config.default_limit)

        if discount > limit:
            return EvaluatorResult(
                matched=True,
                confidence=1.0,
                message=(
                    f"Discount {discount}% exceeds {limit}% limit for tier '{tier}'"
                ),
                metadata={"tier": tier, "limit": limit, "discount": discount},
            )

        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="Discount within limit",
            metadata={"tier": tier, "limit": limit, "discount": discount},
        )
