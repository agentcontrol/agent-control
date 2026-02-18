from typing import Dict

from agent_control_evaluators import EvaluatorConfig


class TieredDiscountConfig(EvaluatorConfig):
    """Config for tiered discount limits.

    limits: mapping of customer tier -> max discount percentage
    default_limit: used when tier is missing or unknown
    """

    limits: Dict[str, int]
    default_limit: int = 15
