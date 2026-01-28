"""Galileo Luna-2 evaluator for agent-control.

This evaluator integrates with Galileo's Luna-2 enterprise runtime protection system
using direct HTTP API calls (no SDK dependency required).

Installation:
    pip install agent-control-evaluators[luna2]

Environment Variables:
    GALILEO_API_KEY: Your Galileo API key (required)
    GALILEO_CONSOLE_URL: Optional, for custom deployments

Documentation:
    https://v2docs.galileo.ai/concepts/protect/overview
    https://v2docs.galileo.ai/sdk-api/python/reference/protect
"""

from .config import Luna2EvaluatorConfig, Luna2Metric, Luna2Operator
from .evaluator import LUNA2_AVAILABLE, Luna2Evaluator

__all__ = [
    "Luna2EvaluatorConfig",
    "Luna2Metric",
    "Luna2Operator",
    "Luna2Evaluator",
    "LUNA2_AVAILABLE",
]

# Export client classes when available
if LUNA2_AVAILABLE:
    from .client import (
        GalileoProtectClient,
        PassthroughAction,
        Payload,
        ProtectResponse,
        Rule,
        Ruleset,
        TraceMetadata,
    )

    __all__.extend([
        "GalileoProtectClient",
        "PassthroughAction",
        "Payload",
        "ProtectResponse",
        "Rule",
        "Ruleset",
        "TraceMetadata",
    ])
