"""Galileo Luna scorer client — re-exported from shared implementation."""

# ruff: noqa: F401
import httpx

from agent_control_evaluator_galileo._shared.client import (
    DEFAULT_CLIENT_POOL_SIZE,
    DEFAULT_KEEPALIVE_EXPIRY_SECS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
    DEFAULT_TIMEOUT_SECS,
    GalileoExecutionContext,
    GalileoScorerClient,
    ScorerInvokeInputs,
    ScorerInvokeRecord,
    ScorerInvokeRequest,
    ScorerInvokeResponse,
    _as_float_or_none,
    _effective_scorer_timeout,
    _has_value,
    _internal_auth_token,
    _normalize_scorer_invoke_url,
    _orbit_record_from_step,
    _validate_connection_config,
)

# Public alias: GalileoLunaClient is the named export users and tests reference.
GalileoLunaClient = GalileoScorerClient
