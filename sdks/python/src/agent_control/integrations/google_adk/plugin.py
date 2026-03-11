"""Agent Control plugin integration for Google ADK."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import weakref
from collections.abc import Callable, Iterable
from typing import Any, Literal, cast
from uuid import uuid4

from agent_control_models.server import GetAgentResponse

import agent_control
from agent_control import AgentControlClient, agents
from agent_control._control_registry import StepSchemaDict
from agent_control._schema_derivation import derive_schemas
from agent_control._state import state
from agent_control.integrations._core import _evaluate_and_enforce
from agent_control.validation import ensure_agent_name

try:
    from google.adk.agents.callback_context import CallbackContext  # type: ignore[import-not-found]
    from google.adk.models import LlmRequest, LlmResponse  # type: ignore[import-not-found]
    from google.adk.plugins import BasePlugin  # type: ignore[import-not-found]
    from google.adk.tools import BaseTool  # type: ignore[import-not-found]
    from google.adk.tools.tool_context import ToolContext  # type: ignore[import-not-found]
except Exception as exc:  # pragma: no cover - optional dependency
    raise RuntimeError(
        "Google ADK integration requires google-adk. "
        "Install with: agent-control-sdk[google-adk]."
    ) from exc

from ._extractors import (
    build_blocked_llm_response,
    build_blocked_tool_response,
    extract_request_text,
    extract_response_text,
    resolve_agent_name,
    resolve_tool_agent_name,
    resolve_tool_name,
)

logger = logging.getLogger(__name__)

_ALL_HOOKS = {"before_model", "after_model", "before_tool", "after_tool"}
_SYNC_TIMEOUT_SECONDS = 30


class AgentControlPlugin(BasePlugin):
    """Google ADK plugin that enforces Agent Control across model and tool hooks."""

    name = "agent-control-google-adk"

    def __init__(
        self,
        agent_name: str,
        *,
        enabled_hooks: set[str] | None = None,
        blocked_message_template: str | None = None,
        step_name_overrides: dict[str, str] | None = None,
        step_name_resolver: Callable[..., str | None] | None = None,
        context_extractor: Callable[..., dict[str, Any] | None] | None = None,
        on_violation_callback: Callable[[dict[str, Any], Any], None] | None = None,
        enable_logging: bool = True,
    ) -> None:
        try:
            # Galileo's local ADK plugin code uses BasePlugin(name=...), but keep
            # a fallback for older/mock BasePlugin implementations that only
            # accept a no-arg constructor.
            super().__init__(name=self.name)
        except TypeError:
            super().__init__()

        normalized_name = ensure_agent_name(agent_name)
        current = state.current_agent
        if current is not None and current.agent_name != normalized_name:
            raise ValueError(
                "AgentControlPlugin agent_name must match the currently initialized "
                "agent_control agent."
            )

        self.agent_name = normalized_name
        self.enabled_hooks = set(enabled_hooks or _ALL_HOOKS)
        self.blocked_message_template = blocked_message_template
        self.step_name_overrides = dict(step_name_overrides or {})
        self.step_name_resolver = step_name_resolver
        self.context_extractor = context_extractor
        self.on_violation_callback = on_violation_callback
        self.enable_logging = enable_logging
        self._generated_invocation_ids: weakref.WeakKeyDictionary[object, str] = (
            weakref.WeakKeyDictionary()
        )
        self._generated_invocation_ids_by_context_id: dict[int, str] = {}
        self._generated_context_ids_by_invocation_id: dict[str, int] = {}
        self._request_text_by_call_key: dict[tuple[str, str], str] = {}
        self._request_object_ids_by_call_key: dict[tuple[str, str], int] = {}
        self._current_llm_call_ids: dict[str, list[str]] = {}
        self._stored_llm_call_ids: dict[int, str] = {}
        self._known_steps: dict[tuple[str, str], StepSchemaDict] = {}
        self._synced_step_keys: set[tuple[str, str]] = set()
        self._step_sync_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}

    def bind(self, agent: Any) -> None:
        """Pre-register known ADK steps before the runner starts."""

        steps = self._discover_steps(agent)
        self._remember_steps(steps)
        self._sync_steps_blocking(steps, raise_on_error=True)

    async def close(self) -> None:
        """Release per-run state and cancel any outstanding step-sync tasks."""

        pending_tasks = list(self._step_sync_tasks.values())
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        self._step_sync_tasks.clear()
        self._generated_invocation_ids.clear()
        self._generated_invocation_ids_by_context_id.clear()
        self._generated_context_ids_by_invocation_id.clear()
        self._request_text_by_call_key.clear()
        self._request_object_ids_by_call_key.clear()
        self._current_llm_call_ids.clear()
        self._stored_llm_call_ids.clear()

        base_close = getattr(super(), "close", None)
        if callable(base_close):
            result = base_close()
            if inspect.isawaitable(result):
                await result

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """Evaluate controls before an ADK model call."""

        if "before_model" not in self.enabled_hooks:
            return None

        step_name = self._resolve_llm_step_name(callback_context)
        request_text = extract_request_text(llm_request)
        invocation_id: str | None = None
        call_id: str | None = None
        if "after_model" in self.enabled_hooks:
            invocation_id = self._resolve_invocation_id(callback_context)
            call_id = self._register_llm_request(invocation_id, llm_request, request_text)
        self._ensure_step_known(
            self._build_llm_step_schema(step_name, callback_context=callback_context),
        )

        context = self._safe_context(
            step_type="llm",
            stage="pre",
            callback_context=callback_context,
            llm_request=llm_request,
        )

        try:
            await _evaluate_and_enforce(
                self.agent_name,
                step_name,
                input=request_text,
                context=context,
                step_type="llm",
                stage="pre",
            )
        except Exception as exc:
            response = self._handle_llm_exception(
                exc,
                callback_context=callback_context,
                llm_request=llm_request,
                step_name=step_name,
                stage="pre",
            )
            if response is not None and invocation_id is not None and call_id is not None:
                self._clear_pending_llm_state(invocation_id, call_id, llm_request=llm_request)
            return response
        return None

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        """Evaluate controls after an ADK model call."""

        if "after_model" not in self.enabled_hooks:
            return None

        step_name = self._resolve_llm_step_name(callback_context)
        invocation_id = self._resolve_invocation_id(callback_context)
        call_id = self._resolve_llm_call_id(llm_response, invocation_id)
        input_text = self._request_text_by_call_key.pop((invocation_id, call_id), "")
        self._clear_pending_llm_state(invocation_id, call_id, llm_response=llm_response)
        output_text = extract_response_text(llm_response)
        self._ensure_step_known(
            self._build_llm_step_schema(step_name, callback_context=callback_context),
        )

        context = self._safe_context(
            step_type="llm",
            stage="post",
            callback_context=callback_context,
            llm_response=llm_response,
        )

        try:
            await _evaluate_and_enforce(
                self.agent_name,
                step_name,
                input=input_text,
                output=output_text,
                context=context,
                step_type="llm",
                stage="post",
            )
        except Exception as exc:
            return self._handle_llm_exception(
                exc,
                callback_context=callback_context,
                llm_response=llm_response,
                step_name=step_name,
                stage="post",
            )
        return None

    async def on_model_error_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
        error: Exception,
    ) -> LlmResponse | None:
        """Clean up request correlation when ADK reports a model error."""

        _ = error
        invocation_id = self._resolve_invocation_id(callback_context)
        call_id = self._resolve_llm_call_id(llm_request, invocation_id)
        self._clear_pending_llm_state(invocation_id, call_id, llm_request=llm_request)
        return None

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        """Evaluate controls before an ADK tool call."""

        if "before_tool" not in self.enabled_hooks:
            return None

        step_name = self._resolve_tool_step_name(tool, tool_context=tool_context)
        self._ensure_step_known(self._build_tool_step_schema(tool, step_name))
        context = self._safe_context(
            step_type="tool",
            stage="pre",
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context,
        )

        try:
            await _evaluate_and_enforce(
                self.agent_name,
                step_name,
                input=tool_args,
                context=context,
                step_type="tool",
                stage="pre",
            )
        except Exception as exc:
            return self._handle_tool_exception(
                exc,
                tool=tool,
                tool_args=tool_args,
                tool_context=tool_context,
                step_name=step_name,
                stage="pre",
            )
        return None

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Evaluate controls after an ADK tool call."""

        if "after_tool" not in self.enabled_hooks:
            return None

        step_name = self._resolve_tool_step_name(tool, tool_context=tool_context)
        self._ensure_step_known(self._build_tool_step_schema(tool, step_name))
        context = self._safe_context(
            step_type="tool",
            stage="post",
            tool=tool,
            tool_args=tool_args,
            tool_context=tool_context,
            result=result,
        )

        try:
            await _evaluate_and_enforce(
                self.agent_name,
                step_name,
                input=tool_args,
                output=result,
                context=context,
                step_type="tool",
                stage="post",
            )
        except Exception as exc:
            return self._handle_tool_exception(
                exc,
                tool=tool,
                tool_args=tool_args,
                tool_context=tool_context,
                step_name=step_name,
                stage="post",
            )
        return None

    def _resolve_llm_step_name(self, callback_context: CallbackContext) -> str:
        raw_name = resolve_agent_name(callback_context)
        return self._resolve_step_name(
            raw_name,
            step_type="llm",
            callback_context=callback_context,
        )

    def _resolve_tool_step_name(
        self,
        tool: BaseTool,
        *,
        tool_context: ToolContext | None = None,
        agent_step_name: str | None = None,
    ) -> str:
        raw_name = resolve_tool_name(tool)
        resolved_agent_step_name = agent_step_name
        if resolved_agent_step_name is None:
            resolved_agent_step_name = self._resolve_tool_agent_step_name(tool_context)
        default_name = (
            f"{resolved_agent_step_name}.{raw_name}" if resolved_agent_step_name else raw_name
        )
        return self._resolve_step_name(
            default_name,
            step_type="tool",
            override_keys=(raw_name,),
            tool=tool,
            tool_context=tool_context,
            raw_name=raw_name,
            agent_step_name=resolved_agent_step_name,
        )

    def _resolve_step_name(
        self,
        default_name: str,
        *,
        step_type: Literal["llm", "tool"],
        override_keys: Iterable[str] = (),
        **kwargs: Any,
    ) -> str:
        candidate_names = [default_name, *override_keys]
        for candidate_name in candidate_names:
            override = self.step_name_overrides.get(candidate_name)
            if override:
                return override

        if self.step_name_resolver is not None:
            resolved = self.step_name_resolver(
                step_type=step_type,
                default_name=default_name,
                override_keys=tuple(candidate_names),
                **kwargs,
            )
            if isinstance(resolved, str) and resolved:
                return resolved

        return default_name

    def _resolve_tool_agent_step_name(self, tool_context: ToolContext | None) -> str | None:
        if tool_context is None:
            return None

        callback_context = getattr(tool_context, "callback_context", None)
        if callback_context is not None:
            return self._resolve_llm_step_name(callback_context)

        raw_agent_name = resolve_tool_agent_name(tool_context)
        if raw_agent_name is None:
            return None

        return self._resolve_step_name(
            raw_agent_name,
            step_type="llm",
            agent_name=raw_agent_name,
            tool_context=tool_context,
        )

    def _safe_context(
        self,
        *,
        step_type: Literal["llm", "tool"],
        stage: Literal["pre", "post"],
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if self.context_extractor is None:
            return None
        try:
            return self.context_extractor(step_type=step_type, stage=stage, **kwargs)
        except Exception:
            logger.warning("Google ADK context_extractor failed", exc_info=True)
            return None

    def _format_message(self, reason: str) -> str:
        if not self.blocked_message_template:
            return reason
        try:
            return self.blocked_message_template.format(reason=reason)
        except Exception:
            logger.warning("Invalid blocked_message_template; using raw reason", exc_info=True)
            return reason

    def _handle_llm_exception(
        self,
        exc: Exception,
        *,
        callback_context: CallbackContext,
        step_name: str,
        stage: Literal["pre", "post"],
        llm_request: LlmRequest | None = None,
        llm_response: LlmResponse | None = None,
    ) -> LlmResponse | None:
        self._invoke_callback(step_name, "llm", stage, exc)

        if (
            isinstance(exc, agent_control.ControlSteerError)
            and stage == "pre"
            and llm_request is not None
        ):
            if self._inject_steering_guidance(llm_request, exc.steering_context):
                return None

        if isinstance(exc, agent_control.ControlSteerError):
            message = exc.steering_context or exc.message
        elif isinstance(exc, agent_control.ControlViolationError):
            message = exc.message
        else:
            logger.error("Google ADK model control evaluation failed", exc_info=True)
            message = f"Agent Control could not evaluate the request safely: {exc}"

        return build_blocked_llm_response(self._format_message(message))

    def _handle_tool_exception(
        self,
        exc: Exception,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        step_name: str,
        stage: Literal["pre", "post"],
    ) -> dict[str, Any]:
        self._invoke_callback(step_name, "tool", stage, exc)

        if isinstance(exc, agent_control.ControlSteerError):
            message = exc.steering_context or exc.message
        elif isinstance(exc, agent_control.ControlViolationError):
            message = exc.message
        else:
            logger.error("Google ADK tool control evaluation failed", exc_info=True)
            message = f"Agent Control could not evaluate the request safely: {exc}"

        return build_blocked_tool_response(self._format_message(message))

    def _invoke_callback(
        self,
        step_name: str,
        step_type: Literal["llm", "tool"],
        stage: Literal["pre", "post"],
        exc: Exception,
    ) -> None:
        if self.on_violation_callback is None:
            return
        if not isinstance(
            exc,
            (agent_control.ControlViolationError, agent_control.ControlSteerError),
        ):
            return

        result_like = {
            "action": "steer" if isinstance(exc, agent_control.ControlSteerError) else "deny",
            "message": exc.message,
            "steering_context": (
                exc.steering_context if isinstance(exc, agent_control.ControlSteerError) else None
            ),
        }
        try:
            self.on_violation_callback(
                {
                    "agent": self.agent_name,
                    "step_name": step_name,
                    "step_type": step_type,
                    "stage": stage,
                },
                result_like,
            )
        except Exception:
            logger.warning("Google ADK on_violation_callback failed", exc_info=True)

    def _inject_steering_guidance(self, llm_request: LlmRequest, guidance: str | None) -> bool:
        if not guidance:
            return False

        config = getattr(llm_request, "config", None)
        if config is None:
            return False

        current_instruction = getattr(config, "system_instruction", None)
        if isinstance(current_instruction, str) and current_instruction:
            new_instruction = f"{current_instruction}\n\nAgent Control guidance: {guidance}"
        else:
            new_instruction = f"Agent Control guidance: {guidance}"

        try:
            setattr(config, "system_instruction", new_instruction)
        except Exception:
            logger.debug("Could not inject steering guidance into ADK request", exc_info=True)
            return False
        return True

    def _build_llm_step_schema(
        self,
        step_name: str,
        *,
        callback_context: CallbackContext | None = None,
    ) -> StepSchemaDict:
        description = None
        if callback_context is not None:
            callback_agent = getattr(callback_context, "agent", None)
            description = getattr(callback_agent, "description", None)
        step: StepSchemaDict = {
            "type": "llm",
            "name": step_name,
            "input_schema": {"text": {"type": "string"}},
            "output_schema": {"text": {"type": "string"}},
            "metadata": {"framework": "google_adk"},
        }
        if isinstance(description, str) and description:
            step["description"] = description
        return step

    def _build_tool_step_schema(self, tool: Any, step_name: str) -> StepSchemaDict:
        description = getattr(tool, "description", None)
        schema_source = self._resolve_schema_source(tool)
        if schema_source is not None:
            schemas = derive_schemas(schema_source)
            input_schema = schemas.input_schema
            output_schema = schemas.output_schema
        else:
            input_schema = {"type": "object", "additionalProperties": True}
            output_schema = {}

        step: StepSchemaDict = {
            "type": "tool",
            "name": step_name,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "metadata": {"framework": "google_adk"},
        }
        if isinstance(description, str) and description:
            step["description"] = description
        return step

    def _resolve_schema_source(self, tool: Any) -> Callable[..., Any] | None:
        if callable(tool):
            return cast(Callable[..., Any], tool)

        for attr_name in ("run_async", "run", "func", "callback"):
            candidate = getattr(tool, attr_name, None)
            if callable(candidate):
                return cast(Callable[..., Any], candidate)
        return None

    def _discover_steps(self, agent: Any) -> list[StepSchemaDict]:
        steps: list[StepSchemaDict] = []
        for current_agent in self._iter_agents(agent):
            resolved_agent_name: str | None = None
            agent_name = getattr(current_agent, "name", None)
            if isinstance(agent_name, str) and agent_name:
                resolved_agent_name = self._resolve_step_name(
                    agent_name,
                    step_type="llm",
                    callback_context=None,
                    agent=current_agent,
                )
                steps.append(
                    self._build_llm_step_schema(resolved_agent_name),
                )

            for tool in self._iter_tools(current_agent):
                tool_name = self._resolve_tool_step_name(
                    tool,
                    agent_step_name=resolved_agent_name,
                )
                steps.append(self._build_tool_step_schema(tool, tool_name))

        deduped: dict[tuple[str, str], StepSchemaDict] = {}
        for step in steps:
            deduped[(step["type"], step["name"])] = step
        return list(deduped.values())

    def _iter_agents(self, root_agent: Any) -> Iterable[Any]:
        seen: set[int] = set()
        stack = [root_agent]
        while stack:
            current = stack.pop()
            identity = id(current)
            if identity in seen:
                continue
            seen.add(identity)
            yield current

            # ADK composite agents are not guaranteed to expose one uniform
            # child-agent attribute, so traverse a small set of observed names.
            # Extend this list if future ADK agent containers expose a different
            # stable child collection attribute.
            for attr_name in ("sub_agents", "agents", "children"):
                nested = getattr(current, attr_name, None)
                if isinstance(nested, dict):
                    stack.extend(nested.values())
                elif isinstance(nested, (list, tuple, set)):
                    stack.extend(nested)
                elif nested is not None and not isinstance(nested, (str, bytes)):
                    stack.append(nested)

    def _iter_tools(self, agent: Any) -> Iterable[Any]:
        tools = getattr(agent, "tools", None)
        if isinstance(tools, (list, tuple, set)):
            return tools
        return []

    def _remember_steps(self, steps: Iterable[StepSchemaDict]) -> None:
        for step in steps:
            key = (step["type"], step["name"])
            self._known_steps[key] = step

    def _ensure_step_known(self, step: StepSchemaDict) -> None:
        key = (step["type"], step["name"])
        self._known_steps[key] = step
        if key in self._synced_step_keys or key in self._step_sync_tasks:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._sync_steps_blocking([step], raise_on_error=False)
            return

        self._schedule_step_sync(loop, step)

    def _schedule_step_sync(
        self,
        loop: asyncio.AbstractEventLoop,
        step: StepSchemaDict,
    ) -> None:
        key = (step["type"], step["name"])
        task = loop.create_task(self._sync_steps_async([step]))
        self._step_sync_tasks[key] = task

        def _callback(completed_task: asyncio.Task[None]) -> None:
            self._on_step_sync_done(key, completed_task)

        task.add_done_callback(_callback)

    def _on_step_sync_done(
        self,
        step_key: tuple[str, str],
        task: asyncio.Task[None],
    ) -> None:
        self._step_sync_tasks.pop(step_key, None)
        if task.cancelled():
            return

        error = task.exception()
        if error is None:
            return

        logger.warning("Failed to sync Google ADK steps to Agent Control", exc_info=error)

    def _context_key(self, callback_context: CallbackContext) -> object:
        """Build a stable correlation key across model before/after hooks.

        Prefer the callback object itself when it is hashable so identity reuse
        cannot alias two different callback objects. Fall back to ``id()`` only
        for unhashable callback types, relying on ADK to keep the callback alive
        across the paired before/after callbacks.
        """
        try:
            hash(callback_context)
        except TypeError:
            return id(callback_context)
        return callback_context

    def _resolve_invocation_id(self, callback_context: CallbackContext) -> str:
        """Resolve the ADK invocation ID used to correlate model lifecycle hooks."""

        invocation_id = getattr(callback_context, "invocation_id", None)
        if invocation_id is not None:
            return str(invocation_id)

        try:
            cached = self._generated_invocation_ids.get(callback_context)
        except TypeError:
            cached = self._generated_invocation_ids_by_context_id.get(id(callback_context))
        if cached is not None:
            return cached

        generated = str(uuid4())
        try:
            self._generated_invocation_ids[callback_context] = generated
        except TypeError:
            context_id = id(callback_context)
            self._generated_invocation_ids_by_context_id[context_id] = generated
            self._generated_context_ids_by_invocation_id[generated] = context_id
        return generated

    def _resolve_llm_call_id(self, obj: Any, invocation_id: str | None = None) -> str:
        """Resolve a model call ID across before/after/error callbacks."""

        stored = self._stored_llm_call_ids.get(id(obj))
        if stored:
            return stored

        request_id = getattr(obj, "request_id", None)
        if request_id:
            return str(request_id)

        if invocation_id is not None:
            stack = self._current_llm_call_ids.get(invocation_id)
            if stack:
                return stack[-1]

        logger.debug("Google ADK LLM correlation fell back to object identity")
        return f"llm_{id(obj)}"

    def _register_llm_request(
        self,
        invocation_id: str,
        llm_request: LlmRequest,
        request_text: str,
    ) -> str:
        call_id = self._resolve_llm_call_id(llm_request, invocation_id)
        call_key = (invocation_id, call_id)
        self._stored_llm_call_ids[id(llm_request)] = call_id
        self._request_text_by_call_key[call_key] = request_text
        self._request_object_ids_by_call_key[call_key] = id(llm_request)
        self._current_llm_call_ids.setdefault(invocation_id, []).append(call_id)
        return call_id

    def _clear_pending_llm_state(
        self,
        invocation_id: str,
        call_id: str,
        *,
        llm_request: LlmRequest | None = None,
        llm_response: LlmResponse | None = None,
    ) -> None:
        call_key = (invocation_id, call_id)
        self._request_text_by_call_key.pop(call_key, None)

        request_object_id = self._request_object_ids_by_call_key.pop(call_key, None)
        if request_object_id is not None:
            self._stored_llm_call_ids.pop(request_object_id, None)

        if llm_request is not None:
            self._stored_llm_call_ids.pop(id(llm_request), None)

        if llm_response is not None:
            self._stored_llm_call_ids.pop(id(llm_response), None)

        self._clear_current_llm_call_id(invocation_id, call_id=call_id)

    def _clear_current_llm_call_id(
        self,
        invocation_id: str,
        *,
        call_id: str | None = None,
    ) -> None:
        stack = self._current_llm_call_ids.get(invocation_id)
        if not stack:
            return

        if call_id is None:
            stack.pop()
        else:
            for index in range(len(stack) - 1, -1, -1):
                if stack[index] == call_id:
                    del stack[index]
                    break

        if not stack:
            context_id = self._generated_context_ids_by_invocation_id.pop(invocation_id, None)
            if context_id is not None:
                self._generated_invocation_ids_by_context_id.pop(context_id, None)
            self._current_llm_call_ids.pop(invocation_id, None)

    def _sync_steps_blocking(
        self,
        steps: Iterable[StepSchemaDict],
        *,
        raise_on_error: bool,
    ) -> None:
        pending_steps = [
            step
            for step in steps
            if (step["type"], step["name"]) not in self._synced_step_keys
        ]
        if not pending_steps:
            return

        if raise_on_error:
            self._run_sync(self._sync_steps_async(pending_steps))
            return

        try:
            self._run_sync(self._sync_steps_async(pending_steps))
        except Exception:
            logger.warning("Failed to sync Google ADK steps to Agent Control", exc_info=True)

    async def _sync_steps_async(self, steps: list[StepSchemaDict]) -> None:
        current = state.current_agent
        if current is None or state.server_url is None:
            return
        if current.agent_name != self.agent_name:
            raise RuntimeError(
                "Google ADK step binding requires agent_control.init() to be called "
                "with the same agent_name as AgentControlPlugin."
            )

        async with AgentControlClient(base_url=state.server_url, api_key=state.api_key) as client:
            response = await agents.get_agent(client, self.agent_name)
            existing = GetAgentResponse.model_validate(response)
            existing_keys = {(step.type, step.name) for step in existing.steps}
            pending_steps = [
                step for step in steps if (step["type"], step["name"]) not in existing_keys
            ]
            if not pending_steps:
                self._synced_step_keys.update((step["type"], step["name"]) for step in steps)
                return

            register_response = await agents.register_agent(
                client,
                current,
                steps=[dict(step) for step in pending_steps],
                conflict_mode="strict",
            )
            controls = register_response.get("controls")
            if isinstance(controls, list):
                state.server_controls = list(controls)
            self._synced_step_keys.update((step["type"], step["name"]) for step in steps)

    def _run_sync(self, coro: Any) -> Any:
        """Run an async registration helper from sync setup paths."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result_box: dict[str, Any] = {}

        def _thread_worker() -> None:
            try:
                result_box["value"] = asyncio.run(coro)
            except Exception as exc:  # noqa: BLE001
                result_box["error"] = exc

        thread = threading.Thread(target=_thread_worker, daemon=True)
        thread.start()
        thread.join(timeout=_SYNC_TIMEOUT_SECONDS)

        if thread.is_alive():
            raise RuntimeError(
                "Timed out while syncing Google ADK steps to Agent Control."
            )

        if "error" in result_box:
            raise result_box["error"]
        return result_box.get("value")
