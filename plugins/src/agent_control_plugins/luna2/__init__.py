"""Galileo Luna-2 plugin for agent-control.

This plugin integrates with Galileo's Luna-2 enterprise runtime protection system
using direct HTTP API calls (no SDK dependency required).

Installation:
    pip install agent-control-plugins[luna2]

Environment Variables:
    GALILEO_API_KEY: Your Galileo API key (required)
    GALILEO_CONSOLE_URL: Optional, for custom deployments

Documentation:
    https://v2docs.galileo.ai/concepts/protect/overview
    https://v2docs.galileo.ai/sdk-api/python/reference/protect
"""

from .config import Luna2Config, Luna2Metric, Luna2Operator
from .plugin import LUNA2_AVAILABLE, Luna2Plugin

__all__ = [
    "Luna2Config",
    "Luna2Metric",
    "Luna2Operator",
    "Luna2Plugin",
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
