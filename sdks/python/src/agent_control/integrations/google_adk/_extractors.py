"""Google ADK extraction helpers for Agent Control."""

from __future__ import annotations

import json
from typing import Any, cast

try:
    from google.genai import types  # type: ignore[import-not-found]
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "Google ADK integration requires google-adk. "
        "Install with: agent-control-sdk[google-adk]."
    ) from exc


def _extract_text_from_parts(parts: Any) -> str:
    """Extract text blocks from an ADK parts collection."""

    if not isinstance(parts, list):
        return ""

    chunks: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            chunks.append(text)
            continue

        if isinstance(part, dict):
            dict_text = part.get("text")
            if isinstance(dict_text, str) and dict_text:
                chunks.append(dict_text)
                continue
            json_value = part.get("json")
            if json_value is not None:
                chunks.append(json.dumps(json_value))

    return "\n".join(chunks).strip()


def extract_request_text(llm_request: Any) -> str:
    """Extract the most recent text payload from an ADK LLM request."""

    contents = getattr(llm_request, "contents", None)
    if not isinstance(contents, list) or not contents:
        return ""
    last_content = contents[-1]
    return _extract_text_from_parts(getattr(last_content, "parts", None))


def extract_response_text(llm_response: Any) -> str:
    """Extract text from an ADK LLM response."""

    content = getattr(llm_response, "content", None)
    if content is None:
        return ""
    return _extract_text_from_parts(getattr(content, "parts", None))


def resolve_agent_name(callback_context: Any) -> str:
    """Resolve the currently executing ADK agent name."""

    callback_agent = getattr(callback_context, "agent", None)
    agent_name = getattr(callback_agent, "name", None)
    if isinstance(agent_name, str) and agent_name:
        return agent_name

    fallback = getattr(callback_context, "agent_name", None)
    if isinstance(fallback, str) and fallback:
        return fallback

    return "root_agent"


def resolve_tool_name(tool: Any) -> str:
    """Resolve an ADK tool name."""

    tool_name = getattr(tool, "name", None)
    if isinstance(tool_name, str) and tool_name:
        return tool_name
    class_name = getattr(tool.__class__, "__name__", None)
    if isinstance(class_name, str) and class_name:
        return class_name
    return "tool"


def build_blocked_llm_response(message: str) -> Any:
    """Create a replacement model response when a request is blocked."""

    content = types.Content(role="model", parts=[types.Part(text=message)])
    return _build_llm_response(content)


def _build_llm_response(content: Any) -> Any:
    """Construct an LLM response from a content payload."""

    response_type = _resolve_llm_response_type()
    return response_type(content=content)


def _resolve_llm_response_type() -> type[Any]:
    """Resolve the google.adk.models.LlmResponse class lazily."""

    try:
        from google.adk.models import LlmResponse  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Google ADK integration requires google-adk. "
            "Install with: agent-control-sdk[google-adk]."
        ) from exc
    return cast(type[Any], LlmResponse)


def build_blocked_tool_response(message: str) -> dict[str, str]:
    """Create a replacement tool response when a call is blocked."""

    return {
        "status": "blocked",
        "message": message,
    }
