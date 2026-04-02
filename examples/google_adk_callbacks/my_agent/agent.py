"""Google ADK example using Agent Control callbacks."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import agent_control
from agent_control import AgentControlClient, ControlSteerError, ControlViolationError
from agent_control.evaluation import check_evaluation
from agent_control_models import Step
from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.adk.tools import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

load_dotenv()

AGENT_NAME = "google-adk-callbacks"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
MODEL_NAME = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")

CITY_DATA = {
    "new york": {
        "display_name": "New York",
        "local_time": "10:30 AM",
        "weather": "Sunny, 72 F",
    },
    "london": {
        "display_name": "London",
        "local_time": "3:30 PM",
        "weather": "Cloudy, 61 F",
    },
    "tokyo": {
        "display_name": "Tokyo",
        "local_time": "11:30 PM",
        "weather": "Clear, 68 F",
    },
    "testville": {
        "display_name": "Testville",
        "local_time": "9:00 AM",
        "weather": "Mild, 65 F",
    },
}


def _tool_input_schema() -> dict[str, Any]:
    return {"city": {"type": "string"}}


def _tool_output_schema() -> dict[str, Any]:
    return {
        "city": {"type": "string"},
        "value": {"type": "string"},
        "note": {"type": "string"},
    }


agent_control.init(
    agent_name=AGENT_NAME,
    agent_description="Google ADK example using Agent Control callbacks",
    server_url=SERVER_URL,
    steps=[
        {
            "type": "llm",
            "name": "root_agent",
            "description": "Primary Google ADK model call",
            "input_schema": {"text": {"type": "string"}},
            "output_schema": {"text": {"type": "string"}},
        },
        {
            "type": "tool",
            "name": "get_current_time",
            "description": "Get the current time for a city.",
            "input_schema": _tool_input_schema(),
            "output_schema": _tool_output_schema(),
        },
        {
            "type": "tool",
            "name": "get_weather",
            "description": "Get the weather for a city.",
            "input_schema": _tool_input_schema(),
            "output_schema": _tool_output_schema(),
        },
    ],
)


_RUN_SYNC_TIMEOUT = 30  # seconds


def _run_sync(coro: Any) -> Any:
    """Run async evaluation safely from sync ADK callbacks.

    ADK callbacks are synchronous, but the Agent Control SDK is async.
    When no event loop is running we can use ``asyncio.run`` directly.
    Otherwise we spawn a short-lived daemon thread with its own loop so
    that we never nest ``run`` calls inside an existing loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            result_box["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            result_box["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=_RUN_SYNC_TIMEOUT)

    if thread.is_alive():
        raise RuntimeError(
            f"Agent Control evaluation timed out after {_RUN_SYNC_TIMEOUT}s"
        )

    if "error" in result_box:
        raise result_box["error"]
    return result_box.get("value")


def _extract_text(parts: list[Any] | None) -> str:
    """Extract text from ADK content parts."""
    if not parts:
        return ""

    chunks: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _extract_request_text(llm_request: LlmRequest) -> str:
    """Extract the most recent text payload from an LLM request."""
    contents = getattr(llm_request, "contents", None) or []
    if not contents:
        return ""
    last_content = contents[-1]
    return _extract_text(getattr(last_content, "parts", None))


def _build_blocked_llm_response(message: str) -> LlmResponse:
    """Create a replacement model response when a request is blocked."""
    content = types.Content(role="model", parts=[types.Part(text=message)])
    return LlmResponse(content=content)


def _build_blocked_tool_response(message: str) -> dict[str, str]:
    """Create a replacement tool response when a call is blocked."""
    return {
        "status": "blocked",
        "message": message,
    }


async def _evaluate(step: Step, stage: str) -> Any:
    """Call the Agent Control evaluation API."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        return await check_evaluation(client, AGENT_NAME, step, stage)  # type: ignore[arg-type]


def _handle_result(result: Any) -> None:
    """Raise the appropriate Agent Control exception for evaluation results."""
    errors = result.errors or []
    if errors:
        details = "; ".join(
            (
                f"[{error.control_name}] "
                f"{error.result.error or error.result.message or 'Unknown error'}"
            )
            for error in errors
        )
        raise RuntimeError(f"Control evaluation failed on the server. {details}")

    matches = result.matches or []
    if not result.is_safe:
        for match in matches:
            if match.action != "deny":
                continue
            raise ControlViolationError(
                control_id=match.control_id,
                control_name=match.control_name,
                message=match.result.message or result.reason or "Control blocked",
                metadata=match.result.metadata or {},
            )

        for match in matches:
            if match.action != "steer":
                continue
            steering_context = None
            if match.steering_context is not None:
                steering_context = match.steering_context.message
            raise ControlSteerError(
                control_id=match.control_id,
                control_name=match.control_name,
                message=match.result.message or result.reason or "Control steered",
                metadata=match.result.metadata or {},
                steering_context=steering_context,
            )

        # Defensive: if is_safe is False but no deny/steer match was found,
        # fail closed rather than silently allowing execution.
        raise RuntimeError(
            f"Evaluation returned is_safe=False with no deny/steer match: "
            f"{result.reason or 'unknown reason'}"
        )

    for match in matches:
        if match.action == "observe":
            print(f"Agent Control observe [{match.control_name}]: {match.result.message}")


def _resolve_agent_step_name(callback_context: CallbackContext) -> str:
    """Resolve the ADK agent name for LLM evaluation steps."""
    callback_agent = getattr(callback_context, "agent", None)
    agent_name = getattr(callback_agent, "name", None)
    if isinstance(agent_name, str) and agent_name:
        return agent_name
    fallback = getattr(callback_context, "agent_name", None)
    if isinstance(fallback, str) and fallback:
        return fallback
    return "root_agent"


def _city_record(city: str) -> dict[str, str]:
    """Get deterministic city data for the example tools."""
    return CITY_DATA.get(
        city.lower(),
        {
            "display_name": city.title() or "Unknown City",
            "local_time": "Unknown",
            "weather": "Unavailable",
        },
    )


def _note_for_city(city: str) -> str:
    """Return a deterministic note used by the post-tool demo control."""
    if city.lower() == "testville":
        return "Internal escalation contact: support@internal.example"
    return "Public city information only."


def get_current_time(city: str) -> dict[str, str]:
    """Get the current time in a city."""
    record = _city_record(city)
    return {
        "city": record["display_name"],
        "value": record["local_time"],
        "note": _note_for_city(city),
    }


def get_weather(city: str) -> dict[str, str]:
    """Get the weather in a city."""
    record = _city_record(city)
    return {
        "city": record["display_name"],
        "value": record["weather"],
        "note": _note_for_city(city),
    }


def before_model_callback(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """Block unsafe model requests before the LLM executes."""
    step = Step(
        type="llm",
        name=_resolve_agent_step_name(callback_context),
        input=_extract_request_text(llm_request),
    )

    try:
        result = _run_sync(_evaluate(step, "pre"))
        _handle_result(result)
    except ControlViolationError as exc:
        return _build_blocked_llm_response(
            f"Request blocked by Agent Control: {exc.message}"
        )
    except ControlSteerError as exc:
        return _build_blocked_llm_response(exc.steering_context or exc.message)
    except Exception as exc:
        return _build_blocked_llm_response(
            f"Agent Control could not evaluate the request safely: {exc}"
        )
    return None


def before_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> dict[str, Any] | None:
    """Block unsafe tool calls before execution."""
    tool_name = getattr(tool, "name", tool.__class__.__name__)
    step = Step(type="tool", name=tool_name, input=args)

    try:
        result = _run_sync(_evaluate(step, "pre"))
        _handle_result(result)
    except ControlViolationError as exc:
        return _build_blocked_tool_response(
            f"Tool call blocked by Agent Control: {exc.message}"
        )
    except ControlSteerError as exc:
        return _build_blocked_tool_response(exc.steering_context or exc.message)
    except Exception as exc:
        return _build_blocked_tool_response(
            f"Tool call blocked because Agent Control could not evaluate safely: {exc}"
        )
    return None


def after_tool_callback(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict[str, Any],
) -> dict[str, Any] | None:
    """Filter unsafe tool output after execution."""
    tool_name = getattr(tool, "name", tool.__class__.__name__)
    step = Step(type="tool", name=tool_name, input=args, output=tool_response)

    try:
        result = _run_sync(_evaluate(step, "post"))
        _handle_result(result)
    except ControlViolationError as exc:
        return _build_blocked_tool_response(
            f"Tool output blocked by Agent Control: {exc.message}"
        )
    except ControlSteerError as exc:
        return _build_blocked_tool_response(exc.steering_context or exc.message)
    except Exception as exc:
        return _build_blocked_tool_response(
            f"Tool output blocked because Agent Control could not evaluate safely: {exc}"
        )
    return None


root_agent = LlmAgent(
    name="root_agent",
    model=MODEL_NAME,
    description="City guide agent protected by Agent Control callbacks.",
    instruction=(
        "You are a city guide assistant. Use the available tools for city time or weather. "
        "If a tool returns status=blocked, apologize and explain the message without retrying. "
        "Do not invent internal contacts or unsupported city data."
    ),
    tools=[get_current_time, get_weather],
    before_model_callback=before_model_callback,
    before_tool_callback=before_tool_callback,
    after_tool_callback=after_tool_callback,
)
