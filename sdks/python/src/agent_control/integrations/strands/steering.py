"""Agent Control steering integration for Strands."""

from __future__ import annotations

import logging
from typing import Any

from agent_control_models.controls import ControlMatch

import agent_control
from agent_control import ControlViolationError

try:
    from strands.experimental.steering import (  # type: ignore[import-not-found]
        Guide,
        Proceed,
        SteeringHandler,
    )
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "Strands integration requires strands-agents. "
        "Install with: agent-control-sdk[strands-agents]."
    ) from exc

logger = logging.getLogger(__name__)


class AgentControlSteeringHandler(SteeringHandler):
    """Agent Control steering integration.

    Converts Agent Control steer matches into Strands Guide() actions.
    Deny matches raise ControlViolationError.
    """

    def __init__(self, agent_name: str, enable_logging: bool = True) -> None:
        super().__init__()
        self.agent_name = agent_name
        self.enable_logging = enable_logging
        self.steers_applied = 0
        self.last_steer_info: dict[str, Any] | None = None

    async def steer_after_model(
        self, *, agent: Any, message: Any, stop_reason: Any, **kwargs: Any
    ) -> Guide | Proceed:
        if self.enable_logging:
            logger.debug("agent=<%s> | steering evaluation started", self.agent_name)

        output_text = self._extract_output(message)

        if self.enable_logging:
            logger.debug(
                "agent=<%s>, output_len=<%d> | checking output",
                self.agent_name,
                len(output_text),
            )

        try:
            result = await agent_control.evaluate_controls(
                step_name="check_after_model",
                output=output_text,
                step_type="llm",
                stage="post",
                agent_name=self.agent_name,
            )

            steer_match = next((m for m in (result.matches or []) if m.action == "steer"), None)
            if steer_match:
                steering_message = self._build_steering_message(steer_match, result.reason)
                self.steers_applied += 1
                self.last_steer_info = {
                    "control_name": steer_match.control_name,
                    "steering_context": steering_message,
                    "from_agentcontrol": True,
                }
                if self.enable_logging:
                    logger.debug(
                        "agent=<%s>, control=<%s> | returning guide",
                        self.agent_name,
                        steer_match.control_name,
                    )
                return Guide(reason=steering_message)

            deny_match = next((m for m in (result.matches or []) if m.action == "deny"), None)
            if deny_match:
                msg = getattr(getattr(deny_match, "result", None), "message", None) or result.reason
                if self.enable_logging:
                    logger.debug(
                        "agent=<%s>, control=<%s> | deny raised",
                        self.agent_name,
                        deny_match.control_name,
                    )
                raise ControlViolationError(
                    control_id=deny_match.control_id,
                    control_name=deny_match.control_name,
                    message=msg or "Control violation",
                    metadata=getattr(deny_match.result, "metadata", None),
                )

        except ControlViolationError:
            raise
        except Exception:
            logger.warning(
                "agent=<%s> | steering evaluation failed; proceeding without enforcement",
                self.agent_name,
                exc_info=True,
            )

        self.last_steer_info = None
        return Proceed(reason="No Agent Control steer detected")

    def _build_steering_message(self, match: ControlMatch, fallback_reason: str | None) -> str:
        ctx = getattr(match, "steering_context", None)
        steering_message = getattr(ctx, "message", None) if ctx else None
        if not steering_message:
            steering_message = (
                getattr(getattr(match, "result", None), "message", None)
                or fallback_reason
            )
        if not steering_message:
            steering_message = f"Control '{match.control_name}' requires steering"
        return steering_message

    def _extract_output(self, message: Any) -> str:
        if not message:
            return ""

        if isinstance(message, dict):
            content = message.get("content", "")
        elif hasattr(message, "content"):
            content = message.content
        else:
            content = str(message)

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    text_parts.append(block["text"])
                elif hasattr(block, "text"):
                    text_parts.append(block.text)
                else:
                    text_parts.append(str(block))
            return " ".join(text_parts)

        return str(content) if content else ""
