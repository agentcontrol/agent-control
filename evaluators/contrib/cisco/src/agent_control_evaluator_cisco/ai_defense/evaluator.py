from __future__ import annotations

from typing import Any
import os

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .client import REGION_BASE_URLS, AIDefenseClient, build_endpoint, AI_DEFENSE_HTTPX_AVAILABLE
from .config import CiscoAIDefenseConfig


def _load_api_key(env_name: str) -> str:
    key = os.getenv(env_name)
    if not key:
        raise RuntimeError(
            f"Missing Cisco AI Defense API key in env '{env_name}'. Set it on the server."
        )
    return key


def _build_messages(
    data: Any,
    strategy: str,
    payload_field: str | None,
) -> list[dict[str, str]]:
    """Build Chat Inspection messages from selected data.

    - history: pass-through if data has 'messages' list; else fallback to single
    - single: synthesize one message with role based on payload_field
    """
    if strategy == "history":
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            msgs: list[dict[str, str]] = []
            for m in data["messages"]:
                if isinstance(m, dict) and "content" in m:
                    role = str(m.get("role", "user"))
                    content = str(m.get("content", ""))
                    msgs.append({"role": role, "content": content})
            if msgs:
                return msgs
        # Fallback to single

    role = "assistant" if payload_field == "output" else "user"
    content = "" if data is None else str(data)
    return [{"role": role, "content": content}]


@register_evaluator
class CiscoAIDefenseEvaluator(Evaluator[CiscoAIDefenseConfig]):
    """Cisco AI Defense evaluator.

    Maps InspectResponse.is_safe to EvaluatorResult.matched.
    """

    metadata = EvaluatorMetadata(
        name="cisco.ai_defense",
        version="0.1.0",
        description="Cisco AI Defense Chat Inspection integration",
        requires_api_key=True,
        timeout_ms=15000,
    )

    config_model = CiscoAIDefenseConfig

    @classmethod
    def is_available(cls) -> bool:
        """Evaluator is available only if httpx dependency exists."""
        return AI_DEFENSE_HTTPX_AVAILABLE

    def __init__(self, config: CiscoAIDefenseConfig) -> None:
        self.config = config

        # Validate and resolve configuration eagerly to avoid per-call work.
        # API key
        try:
            api_key = _load_api_key(self.config.api_key_env)
        except Exception as e:  # noqa: BLE001
            # Fail fast during construction so misconfiguration is caught early.
            raise ValueError(str(e)) from e

        # Endpoint
        if self.config.api_url:
            endpoint_url = self.config.api_url
        else:
            base_url = REGION_BASE_URLS.get(self.config.region or "us", REGION_BASE_URLS["us"])
            endpoint_url = build_endpoint(base_url)

        # Timeout
        timeout_s = float(self.config.timeout_ms) / 1000.0

        # Create a single client instance for reuse.
        self._client: AIDefenseClient = AIDefenseClient(
            api_key=api_key,
            endpoint_url=endpoint_url,
            timeout_s=timeout_s,
        )

    async def evaluate(self, data: Any) -> EvaluatorResult:  # noqa: D401
        # Null input: do not call external service; treat as no data
        if data is None:
            return EvaluatorResult(matched=False, confidence=1.0, message="No data")

        messages = _build_messages(
            data,
            strategy=self.config.messages_strategy,
            payload_field=self.config.payload_field,
        )
        if not messages:
            return EvaluatorResult(matched=False, confidence=1.0, message="No data to inspect")

        # Call REST API for Chat Inspection
        try:
            response: dict[str, Any] = await self._client.chat_inspect(
                messages=messages,
                metadata=self.config.metadata,
                inspect_config=self.config.inspect_config,
            )

            # Map is_safe to matched
            is_safe = response.get("is_safe")
            if isinstance(is_safe, bool):
                matched = not is_safe
                msg = "Content is unsafe" if matched else "Content is safe"
                meta: dict[str, Any] = {
                    "severity": response.get("severity"),
                    "classifications": response.get("classifications"),
                    "rules": response.get("rules"),
                    "attack_technique": response.get("attack_technique"),
                    "event_id": response.get("event_id"),
                }
                if self.config.include_raw_response:
                    meta["raw"] = response
                return EvaluatorResult(
                    matched=matched,
                    confidence=1.0,
                    message=msg,
                    metadata=meta,
                )

            # If no boolean is present, consider it an evaluator error
            fallback = self.config.on_error
            meta2: dict[str, Any] = {"fallback_action": fallback}
            if self.config.include_raw_response:
                meta2["raw"] = response
            return EvaluatorResult(
                matched=(fallback == "deny"),
                confidence=0.0,
                message="Cisco AI Defense response missing 'is_safe'",
                metadata=meta2,
            )
        except Exception as e:  # noqa: BLE001
            fallback = self.config.on_error
            matched = fallback == "deny"
            # Pydantic model enforces: if error is set, matched must be False.
            # Expose details via metadata always; set error field only on fail-open.
            return EvaluatorResult(
                matched=matched,
                confidence=0.0,
                message=f"Cisco AI Defense evaluation error: {e}",
                metadata={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "fallback_action": fallback,
                },
            )
