from __future__ import annotations

from typing import Any, Literal
from pydantic import Field

from agent_control_evaluators import EvaluatorConfig


class CiscoAIDefenseConfig(EvaluatorConfig):
    """Configuration for Cisco AI Defense evaluator (REST).

    Attributes:
        api_key_env: Env var name for API key
        region: Optional server region (us, ap, eu); ignored if api_url set
        api_url: Optional full endpoint override
        timeout_ms: Request timeout (milliseconds)
        on_error: Error policy (allow=fail-open, deny=fail-closed)
        payload_field: Force single-message role: input→user, output→assistant
        messages_strategy: "single" (synthesize) or "history" (pass-through messages)
        metadata: Optional metadata object to include (OpenAPI spec)
        inspect_config: Optional Inspect API config passthrough (see OpenAPI spec)
    """

    api_key_env: str = "AI_DEFENSE_API_KEY"
    region: Literal["us", "ap", "eu"] | None = "us"
    api_url: str | None = None
    timeout_ms: int = Field(default=15_000, ge=1)
    on_error: Literal["allow", "deny"] = "allow"
    payload_field: Literal["input", "output"] | None = None
    messages_strategy: Literal["single", "history"] = "history"
    metadata: dict[str, Any] | None = None
    inspect_config: dict[str, Any] | None = None
    include_raw_response: bool = False
