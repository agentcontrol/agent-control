"""Galileo LLM-as-judge scorer client — re-exported from shared implementation."""

from agent_control_evaluator_galileo._shared.client import (
    DEFAULT_TIMEOUT_SECS,
    GalileoExecutionContext,
    GalileoScorerClient,
    ScorerInvokeInputs,
    ScorerInvokeRecord,
    ScorerInvokeRequest,
    ScorerInvokeResponse,
)

# Public alias: GalileoLLMClient is the named export users and tests reference.
GalileoLLMClient = GalileoScorerClient

__all__ = [
    "DEFAULT_TIMEOUT_SECS",
    "GalileoExecutionContext",
    "GalileoLLMClient",
    "ScorerInvokeInputs",
    "ScorerInvokeRecord",
    "ScorerInvokeRequest",
    "ScorerInvokeResponse",
]
