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

    name = "agent-control-steering"

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

        input_text = self._extract_input(kwargs)
        context = self._extract_context(kwargs)
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
                input=input_text,
                output=output_text,
                context=context,
                step_type="llm",
                stage="post",
                agent_name=self.agent_name,
            )

            if result.errors:
                error_names = ", ".join(
                    e.control_name for e in result.errors if getattr(e, "control_name", None)
                )
                logger.error(
                    "agent=<%s> | steering evaluation failed; blocking execution",
                    self.agent_name,
                )
                raise RuntimeError(
                    "Steering evaluation failed; execution blocked for safety. "
                    f"Errors: {error_names or 'unknown'}"
                )

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

        except ControlViolationError:
            raise
        except RuntimeError:
            raise
        except Exception as exc:
            logger.error(
                "agent=<%s> | steering evaluation failed; blocking execution",
                self.agent_name,
                exc_info=True,
            )
            raise RuntimeError(
                "Steering evaluation failed; execution blocked for safety."
            ) from exc

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

    def _extract_input(self, kwargs: dict[str, Any]) -> str:
        if "input" in kwargs:
            return self._extract_content_text(kwargs["input"])

        messages = kwargs.get("messages")
        if isinstance(messages, list):
            return self._extract_user_message_from_list(messages)

        invocation_state = kwargs.get("invocation_state") or {}
        if isinstance(invocation_state, dict):
            if "messages" in invocation_state:
                return self._extract_user_message_from_list(invocation_state["messages"])
            if "input" in invocation_state:
                return self._extract_content_text(invocation_state["input"])

        return ""

    def _extract_context(self, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        invocation_state = kwargs.get("invocation_state")
        if isinstance(invocation_state, dict):
            ctx = invocation_state.get("context")
            if isinstance(ctx, dict):
                return ctx
        return None

    def _extract_user_message_from_list(self, messages: list | None) -> str:
        if not messages:
            return ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                return self._extract_content_text(msg.get("content", ""))
        return ""

    def _extract_output(self, message: Any) -> str:
        if not message:
            return ""

        if isinstance(message, dict):
            content = message.get("content", "")
        elif hasattr(message, "content"):
            content = message.content
        else:
            content = message

        return self._extract_content_text(content)

    def _extract_content_text(self, content: Any) -> str:
        if not content:
            return ""

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        text_parts.append(block["text"])
                    elif "content" in block:
                        nested = self._extract_content_text(block["content"])
                        if nested:
                            text_parts.append(nested)
                    elif "citationsContent" in block:
                        citations_block = block["citationsContent"]
                        if "content" in citations_block:
                            for citation_item in citations_block["content"]:
                                if isinstance(citation_item, dict) and "text" in citation_item:
                                    text_parts.append(citation_item["text"])
                    elif "toolUse" in block:
                        tool_name = block["toolUse"].get("name", "unknown")
                        text_parts.append(f"[tool_use: {tool_name}]")
                    elif "toolResult" in block:
                        result_content = block["toolResult"].get("content", [])
                        result_text = self._extract_content_text(result_content)
                        if result_text:
                            text_parts.append(result_text)
                    elif "json" in block:
                        import json

                        text_parts.append(json.dumps(block["json"]))
                elif hasattr(block, "text"):
                    text_parts.append(str(block.text))
                else:
                    text_parts.append(str(block))
            return "\n".join(text_parts)

        if isinstance(content, dict):
            if "text" in content:
                return str(content["text"])
            if "content" in content:
                return self._extract_content_text(content["content"])
            if "json" in content:
                import json

                return json.dumps(content["json"])

        return str(content)
