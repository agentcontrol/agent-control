"""Core logic for the control engine.

Evaluates controls in parallel with cancel-on-deny for efficiency.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from agent_control_models import (
    ControlDefinition,
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
    EvaluatorResult,
)

from .evaluators import get_evaluator
from .selectors import select_data


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
    """

    def __init__(self, controls: Sequence[ControlWithIdentity]):
        self.controls = controls

    def get_applicable_controls(
        self, request: EvaluationRequest
    ) -> list[ControlWithIdentity]:
        """Get all controls that apply to the current request."""
        applicable = []
        payload_is_tool = hasattr(request.payload, "tool_name")

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
            data = select_data(request.payload, control_def.selector.path)
            eval_tasks.append(_EvalTask(item=item, data=data))

        # Run evaluations in parallel with cancel-on-deny
        matches: list[ControlMatch] = []
        is_safe = True
        deny_found = asyncio.Event()

        async def evaluate_control(eval_task: _EvalTask) -> None:
            """Evaluate a single control, respecting cancellation."""
            try:
                evaluator = get_evaluator(eval_task.item.control.evaluator)
                eval_task.result = await evaluator.evaluate(eval_task.data)

                # Signal if this is a deny match
                if (
                    eval_task.result.matched
                    and eval_task.item.control.action.decision == "deny"
                ):
                    deny_found.set()
            except asyncio.CancelledError:
                # Task was cancelled due to another deny - that's OK
                raise
            except Exception as e:
                # Evaluation error - treat as error result
                eval_task.result = EvaluatorResult(
                    matched=False,
                    confidence=0.0,
                    message=f"Evaluation error: {e}",
                    metadata={"error": str(e)},
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

        # Collect results
        for eval_task in eval_tasks:
            if eval_task.result is None:
                continue

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

        return EvaluationResponse(
            is_safe=is_safe,
            confidence=1.0,
            matches=matches if matches else None,
        )
