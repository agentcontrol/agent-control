"""Core logic for the control engine.

Evaluates controls in parallel with cancel-on-deny for efficiency.
"""

import asyncio
import functools
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import re2
from agent_control_models import (
    ControlDefinition,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
    EvaluatorResult,
    ToolCall,
)

from .evaluators import get_evaluator
from .selectors import select_data

logger = logging.getLogger(__name__)

# Default timeout for evaluator execution (seconds)
DEFAULT_EVALUATOR_TIMEOUT = float(os.environ.get("EVALUATOR_TIMEOUT_SECONDS", "30"))

# Max concurrent evaluations (limits task spawning overhead for large policies)
MAX_CONCURRENT_EVALUATIONS = int(os.environ.get("MAX_CONCURRENT_EVALUATIONS", "3"))


@functools.lru_cache(maxsize=256)
def _compile_regex(pattern: str) -> Any:
    """Compile and cache RE2 regex patterns.

    Caching avoids recompiling the same pattern on every request.
    """
    return re2.compile(pattern)


class ControlWithIdentity(Protocol):
    """Protocol for a control with identity information."""

    id: int
    name: str
    control: ControlDefinition


@dataclass
class _EvalTask:
    """Internal container for evaluation task context."""

    item: ControlWithIdentity
    data: Any
    task: asyncio.Task[None] | None = None
    result: EvaluatorResult | None = None


class ControlEngine:
    """Executes controls against requests with parallel evaluation.

    Controls are evaluated in parallel using asyncio. On the first
    deny match, remaining tasks are cancelled for efficiency.

    Args:
        controls: Sequence of controls to evaluate.
        context: Execution context. 'sdk' runs only local=True controls,
                 'server' runs only local=False controls.
    """

    def __init__(
        self,
        controls: Sequence[ControlWithIdentity],
        context: Literal["sdk", "server"] = "server",
    ):
        self.controls = controls
        self.context = context

    def get_applicable_controls(
        self, request: EvaluationRequest
    ) -> list[ControlWithIdentity]:
        """Get all controls that apply to the current request."""
        applicable = []
        payload_is_tool = isinstance(request.payload, ToolCall)

        for item in self.controls:
            control_def = item.control

            if not control_def.enabled:
                continue

            if control_def.check_stage != request.check_stage:
                continue

            if control_def.applies_to == "tool_call" and not payload_is_tool:
                continue
            if control_def.applies_to == "llm_call" and payload_is_tool:
                continue

            # Filter by locality based on context
            control_local = getattr(control_def, "local", False)
            if self.context == "sdk" and not control_local:
                continue
            if self.context == "server" and control_local:
                continue

            # Optional tool scoping for ToolCall payloads
            if payload_is_tool:
                sel = control_def.selector
                names = getattr(sel, "tool_names", None)
                pattern = getattr(sel, "tool_name_regex", None)
                if names or pattern:
                    tool_name = getattr(request.payload, "tool_name", None)
                    if tool_name is None:
                        continue
                    match = False
                    if names and tool_name in names:
                        match = True
                    if not match and pattern:
                        try:
                            if _compile_regex(pattern).search(tool_name) is not None:
                                match = True
                        except re2.error:
                            # Invalid pattern should have been caught at model validation;
                            # skip defensively.
                            continue
                    if not match:
                        continue

            applicable.append(item)

        return applicable

    async def process(self, request: EvaluationRequest) -> EvaluationResponse:
        """Process controls in parallel with cancel-on-deny.

        All applicable controls are evaluated concurrently. If any control
        matches with action=deny, remaining evaluations are cancelled.

        Args:
            request: The evaluation request containing payload and context

        Returns:
            EvaluationResponse with is_safe status and any matches
        """
        applicable = self.get_applicable_controls(request)

        if not applicable:
            return EvaluationResponse(is_safe=True, confidence=1.0, matches=None)

        # Prepare evaluation tasks
        eval_tasks: list[_EvalTask] = []
        for item in applicable:
            control_def = item.control
            sel_path = control_def.selector.path or "*"
            data = select_data(request.payload, sel_path)
            eval_tasks.append(_EvalTask(item=item, data=data))

        # Run evaluations in parallel with cancel-on-deny
        matches: list[ControlMatch] = []
        is_safe = True
        deny_found = asyncio.Event()
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EVALUATIONS)

        async def evaluate_control(eval_task: _EvalTask) -> None:
            """Evaluate a single control, respecting cancellation and timeout."""
            async with semaphore:
                try:
                    evaluator = get_evaluator(eval_task.item.control.evaluator)
                    # Use plugin's timeout or fall back to default
                    timeout = evaluator.get_timeout_seconds()
                    if timeout <= 0:
                        timeout = DEFAULT_EVALUATOR_TIMEOUT

                    eval_task.result = await asyncio.wait_for(
                        evaluator.evaluate(eval_task.data),
                        timeout=timeout,
                    )

                    # Signal if this is a blocking match match (deny or human_review)
                    if (
                        eval_task.result.matched
                        and eval_task.item.control.action.decision in ["deny", "human_review"]
                    ):
                        deny_found.set()
                except asyncio.CancelledError:
                    # Task was cancelled due to another deny - that's OK
                    raise
                except TimeoutError:
                    # Evaluator timed out
                    error_msg = f"TimeoutError: Evaluator exceeded {timeout}s timeout"
                    logger.warning(
                        f"Evaluator timeout for control '{eval_task.item.name}' "
                        f"(plugin: {eval_task.item.control.evaluator.plugin}): {error_msg}"
                    )
                    eval_task.result = EvaluatorResult(
                        matched=False,
                        confidence=0.0,
                        message=f"Evaluation failed: {error_msg}",
                        error=error_msg,
                    )
                except Exception as e:
                    # Evaluation error - fail open but mark as error
                    # The error field signals to callers that this was not a real evaluation
                    error_msg = f"{type(e).__name__}: {e}"
                    logger.warning(
                        f"Evaluator error for control '{eval_task.item.name}' "
                        f"(plugin: {eval_task.item.control.evaluator.plugin}): {error_msg}"
                    )
                    eval_task.result = EvaluatorResult(
                        matched=False,
                        confidence=0.0,
                        message=f"Evaluation failed: {error_msg}",
                        error=error_msg,
                    )

        # Create and start all tasks
        for eval_task in eval_tasks:
            eval_task.task = asyncio.create_task(evaluate_control(eval_task))

        # Wait for completion or first deny
        all_tasks = [et.task for et in eval_tasks if et.task is not None]

        async def wait_for_deny() -> None:
            """Wait for deny signal then cancel remaining tasks."""
            await deny_found.wait()
            for et in eval_tasks:
                if et.task and not et.task.done():
                    et.task.cancel()

        # Race: all tasks complete OR deny found
        cancel_task = asyncio.create_task(wait_for_deny())

        try:
            # Wait for all evaluation tasks (some may get cancelled)
            await asyncio.gather(*all_tasks, return_exceptions=True)
        finally:
            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass

        # Collect results and errors
        errors: list[ControlMatch] = []
        successful_count = 0
        evaluated_count = 0  # Controls that ran (not cancelled)
        deny_errored = False
        deny_matched = False
        human_review_matched = False # track human review separately

        for eval_task in eval_tasks:
            if eval_task.result is None:
                # Task was cancelled (early exit on deny) - not counted
                continue

            evaluated_count += 1

            # Collect errored evaluations
            if eval_task.result.error:
                errors.append(
                    ControlMatch(
                        control_id=eval_task.item.id,
                        control_name=eval_task.item.name,
                        action=eval_task.item.control.action.decision,
                        result=eval_task.result,
                    )
                )
                # Track if a deny or human_review control errored (fail closed)
                if eval_task.item.control.action.decision in ["deny", "human_review"]:
                    deny_errored = True
                continue

            # Count successful evaluations
            successful_count += 1

            # Collect successful matches
            if eval_task.result.matched:
                matches.append(
                    ControlMatch(
                        control_id=eval_task.item.id,
                        control_name=eval_task.item.name,
                        action=eval_task.item.control.action.decision,
                        result=eval_task.result,
                    )
                )

                if eval_task.item.control.action.decision == "deny":
                    is_safe = False
                    deny_matched = True
                elif eval_task.item.control.action.decision == "human_review":
                    is_safe = False
                    human_review_matched = True

        # Fail closed if a deny control errored (couldn't verify safety)
        if deny_errored:
            is_safe = False

        # Calculate confidence
        if deny_errored:
            # Deny control failed - can't be confident in safety assessment
            confidence = 0.0
        elif deny_matched:
            # Definitive deny - full confidence in the decision
            confidence = 1.0
        elif evaluated_count == 0:
            # All controls were cancelled (shouldn't happen without deny)
            confidence = 0.0
        elif successful_count == 0:
            # All evaluated controls errored - no real evaluation occurred
            confidence = 0.0
        else:
            # Proportional confidence based on successful vs evaluated
            confidence = successful_count / evaluated_count

        return EvaluationResponse(
            is_safe=is_safe,
            confidence=confidence,
            matches=matches if matches else None,
            errors=errors if errors else None,
            human_review_required=human_review_matched
        )
