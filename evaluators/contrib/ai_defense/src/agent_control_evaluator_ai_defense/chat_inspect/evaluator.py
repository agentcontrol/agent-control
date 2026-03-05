from __future__ import annotations

from typing import Any

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .client import REGION_BASE_URLS, AIDefenseClient, build_endpoint
from .config import ChatInspectEvaluatorConfig


def _load_api_key(env_name: str) -> str:
    import os

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
class ChatInspectEvaluator(Evaluator[ChatInspectEvaluatorConfig]):
    """Cisco AI Defense Chat Inspection evaluator.

    Maps InspectResponse.is_safe to EvaluatorResult.matched.
    """

    metadata = EvaluatorMetadata(
        name="ai_defense.chat_inspect",
        version="0.1.0",
        description="Cisco AI Defense Chat Inspection integration",
        requires_api_key=True,
        timeout_ms=15000,
    )

    config_model = ChatInspectEvaluatorConfig

    def __init__(self, config: ChatInspectEvaluatorConfig) -> None:
        self.config = config
        self._client: AIDefenseClient | None = None
        self._current_api_key: str | None = None
        self._current_endpoint_url: str | None = None
        self._current_timeout_s: float | None = None

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

        # Resolve API key and endpoint
        try:
            api_key = _load_api_key(self.config.api_key_env)
        except Exception as e:  # noqa: BLE001
            # Respect on_error behavior for missing API key
            fallback = self.config.on_error
            matched = fallback == "deny"
            return EvaluatorResult(
                matched=matched,
                confidence=0.0,
                message=str(e),
                metadata={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "fallback_action": fallback,
                },
                # On fail-closed, expose details via metadata only
                error=None if matched else str(e),
            )

        # Derive endpoint from region or explicit api_url
        if self.config.api_url:
            endpoint_url = self.config.api_url
        else:
            base_url = REGION_BASE_URLS.get(self.config.region or "us", REGION_BASE_URLS["us"])
            endpoint_url = build_endpoint(base_url)

        # Prepare or reuse client
        timeout_s = max(0.001, float(self.config.timeout_ms) / 1000.0)
        needs_new_client = (
            self._client is None
            or self._current_api_key != api_key
            or self._current_endpoint_url != endpoint_url
            or self._current_timeout_s != timeout_s
        )
        if needs_new_client:
            # Close any prior client
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
            self._client = AIDefenseClient(
                api_key=api_key,
                endpoint_url=endpoint_url,
                timeout_s=timeout_s,
            )
            self._current_api_key = api_key
            self._current_endpoint_url = endpoint_url
            self._current_timeout_s = timeout_s

        # Call REST API for Chat Inspection
        try:
            client = self._client
            assert client is not None
            response: dict[str, Any] = await client.chat_inspect(
                messages=messages,
                metadata=self.config.metadata,
                inspect_config=self.config.inspect_config,
            )

            # Map is_safe to matched
            is_safe = response.get("is_safe")
            if isinstance(is_safe, bool):
                matched = not is_safe
                msg = "Content is unsafe" if matched else "Content is safe"
                return EvaluatorResult(
                    matched=matched,
                    confidence=1.0,
                    message=msg,
                    metadata={
                        "raw": response,
                        "severity": response.get("severity"),
                        "classifications": response.get("classifications"),
                        "rules": response.get("rules"),
                        "attack_technique": response.get("attack_technique"),
                        "event_id": response.get("event_id"),
                    },
                )

            # If no boolean is present, consider it an evaluator error
            fallback = self.config.on_error
            return EvaluatorResult(
                matched=(fallback == "deny"),
                confidence=0.0,
                message="Cisco AI Defense response missing 'is_safe'",
                metadata={"raw": response, "fallback_action": fallback},
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
                error=None if matched else str(e),
            )
