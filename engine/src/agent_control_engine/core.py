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
from agent_control_evaluators import get_evaluator_instance
from agent_control_models import (
    ConditionNode,
    ControlAction,
    ControlMatch,
    ControlScope,
    EvaluationRequest,
    EvaluationResponse,
    EvaluatorResult,
)

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


class ControlDefinitionLike(Protocol):
    """Runtime control shape required by the engine."""

    enabled: bool
    execution: Literal["server", "sdk"]
    scope: ControlScope
    condition: ConditionNode
    action: ControlAction


class ControlWithIdentity(Protocol):
    """Protocol for a control with identity information."""

    @property
    def id(self) -> int:
        """Database identity for the control."""

    @property
    def name(self) -> str:
        """Human-readable name for the control."""

    @property
    def control(self) -> ControlDefinitionLike:
        """Runtime control payload used during evaluation."""


@dataclass
class _EvalTask:
    """Internal container for evaluation task context."""

    item: ControlWithIdentity
    task: asyncio.Task[None] | None = None
    result: EvaluatorResult | None = None


@dataclass
class _ConditionEvaluation:
    """Internal result for recursive condition evaluation."""

    result: EvaluatorResult
    trace: dict[str, Any]


class ControlEngine:
    """Executes controls against requests with parallel evaluation.

    Controls are evaluated in parallel using asyncio. On the first
    deny match, remaining tasks are cancelled for efficiency.

    Args:
        controls: Sequence of controls to evaluate.
        context: Execution context. 'sdk' runs controls with execution="sdk",
                 'server' runs controls with execution="server".
    """

    def __init__(
        self,
        controls: Sequence[ControlWithIdentity],
        context: Literal["sdk", "server"] = "server",
    ):
        self.controls = controls
        self.context = context

    @staticmethod
    def _truncated_message(message: str | None) -> str | None:
        """Truncate long evaluator messages in condition traces."""
        if not message:
            return None
        if len(message) <= 200:
            return message
        return f"{message[:197]}..."

    @staticmethod
    def _format_exception(error: BaseException) -> str:
        """Format exceptions consistently for result.error fields."""
        return f"{type(error).__name__}: {error}"

    @staticmethod
    def _build_error_result(
        error: str,
        *,
        message_prefix: str = "Evaluation failed",
    ) -> EvaluatorResult:
        """Create a failed evaluator result from an internal error string."""
        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"{message_prefix}: {error}",
            error=error,
        )

    def _skipped_trace(self, node: ConditionNode, reason: str) -> dict[str, Any]:
        """Build an unevaluated trace subtree for short-circuited branches."""
        trace: dict[str, Any] = {
            "type": node.kind(),
            "evaluated": False,
            "matched": None,
            "short_circuit_reason": reason,
        }
        if node.is_leaf():
            leaf_parts = node.leaf_parts()
            if leaf_parts is None:
                raise ValueError("Leaf condition must contain selector and evaluator")
            selector, evaluator = leaf_parts
            trace["selector_path"] = selector.path
            trace["evaluator_name"] = evaluator.name
            trace["confidence"] = None
            trace["error"] = None
            return trace

        trace["children"] = [
            self._skipped_trace(child, reason) for child in node.children_in_order()
        ]
        return trace

    async def _evaluate_leaf(
        self,
        item: ControlWithIdentity,
        node: ConditionNode,
        request: EvaluationRequest,
        semaphore: asyncio.Semaphore,
    ) -> _ConditionEvaluation:
        """Evaluate a leaf selector/evaluator pair.

        The shared semaphore limits concurrent leaf evaluator executions across
        the entire engine run. Composite conditions evaluate serially, so a
        single control only holds one semaphore slot at a time, but multi-leaf
        controls may acquire and release that shared slot more than once while
        traversing their tree.
        """
        leaf_parts = node.leaf_parts()
        if leaf_parts is None:
            raise ValueError("Leaf condition must contain selector and evaluator")
        selector, evaluator_spec = leaf_parts

        selector_path = selector.path or "*"
        data = select_data(request.step, selector_path)

        try:
            async with semaphore:
                evaluator = get_evaluator_instance(evaluator_spec)
                timeout = evaluator.get_timeout_seconds()
                if timeout <= 0:
                    timeout = DEFAULT_EVALUATOR_TIMEOUT

                result = await asyncio.wait_for(
                    evaluator.evaluate(data),
                    timeout=timeout,
                )
        except TimeoutError:
            error_msg = f"TimeoutError: Evaluator exceeded {timeout}s timeout"
            logger.warning(
                "Evaluator timeout for control '%s' (evaluator: %s): %s",
                item.name,
                evaluator_spec.name,
                error_msg,
                exc_info=True,
            )
            result = self._build_error_result(error_msg)
        except Exception as e:
            error_msg = self._format_exception(e)
            logger.error(
                "Evaluator error for control '%s' (evaluator: %s): %s",
                item.name,
                evaluator_spec.name,
                error_msg,
                exc_info=True,
            )
            result = self._build_error_result(error_msg)

        trace = {
            "type": "leaf",
            "evaluated": True,
            "matched": result.matched,
            "selector_path": selector_path,
            "evaluator_name": evaluator_spec.name,
            "confidence": result.confidence,
            "error": result.error,
            "message": self._truncated_message(result.message),
        }
        metadata = dict(result.metadata or {})
        metadata["condition_trace"] = trace
        return _ConditionEvaluation(
            result=result.model_copy(update={"metadata": metadata}),
            trace=trace,
        )

    def _build_composite_result(
        self,
        *,
        matched: bool,
        confidence: float,
        trace: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> EvaluatorResult:
        """Create a composite evaluator result with a condition trace."""
        result_metadata = dict(metadata or {})
        result_metadata["condition_trace"] = trace

        if error is not None:
            return EvaluatorResult(
                matched=False,
                confidence=0.0,
                message=(
                    "Condition evaluation aborted due to a child evaluator error: "
                    f"{error}"
                ),
                metadata=result_metadata,
                error=error,
            )

        message = "Condition tree matched" if matched else "Condition tree did not match"
        return EvaluatorResult(
            matched=matched,
            confidence=confidence,
            message=message,
            metadata=result_metadata,
        )

    @staticmethod
    def _composite_metadata(
        child_evaluations: Sequence[_ConditionEvaluation],
        *,
        matched: bool,
    ) -> dict[str, Any] | None:
        """Select stable child metadata to preserve on composite results."""
        source_result: EvaluatorResult | None = None
        if matched:
            source_result = next(
                (
                    evaluation.result
                    for evaluation in child_evaluations
                    if evaluation.result.matched
                ),
                None,
            )
        if source_result is None and child_evaluations:
            source_result = child_evaluations[0].result
        if source_result is None or source_result.metadata is None:
            return None
        return dict(source_result.metadata)

    async def _evaluate_condition(
        self,
        item: ControlWithIdentity,
        node: ConditionNode,
        request: EvaluationRequest,
        semaphore: asyncio.Semaphore,
    ) -> _ConditionEvaluation:
        """Evaluate a recursive condition tree."""
        if node.is_leaf():
            return await self._evaluate_leaf(item, node, request, semaphore)

        kind = node.kind()
        children = node.children_in_order()
        child_evaluations: list[_ConditionEvaluation] = []

        if kind == "not":
            child_eval = await self._evaluate_condition(item, children[0], request, semaphore)
            trace = {
                "type": "not",
                "evaluated": True,
                "matched": None if child_eval.result.error else (not child_eval.result.matched),
                "children": [child_eval.trace],
            }
            if child_eval.result.error:
                return _ConditionEvaluation(
                    result=self._build_composite_result(
                        matched=False,
                        confidence=0.0,
                        trace=trace,
                        metadata=child_eval.result.metadata,
                        error=child_eval.result.error,
                    ),
                    trace=trace,
                )

            result = self._build_composite_result(
                matched=not child_eval.result.matched,
                confidence=child_eval.result.confidence,
                trace=trace,
                metadata=child_eval.result.metadata,
            )
            return _ConditionEvaluation(result=result, trace=trace)

        for index, child in enumerate(children):
            child_eval = await self._evaluate_condition(item, child, request, semaphore)
            child_evaluations.append(child_eval)

            if child_eval.result.error:
                remaining = children[index + 1 :]
                trace = {
                    "type": kind,
                    "evaluated": True,
                    "matched": None,
                    "children": [
                        evaluation.trace for evaluation in child_evaluations
                    ]
                    + [self._skipped_trace(rest, "error") for rest in remaining],
                    "short_circuit_reason": "error",
                }
                return _ConditionEvaluation(
                    result=self._build_composite_result(
                        matched=False,
                        confidence=0.0,
                        trace=trace,
                        metadata=child_eval.result.metadata,
                        error=child_eval.result.error,
                    ),
                    trace=trace,
                )

            should_short_circuit = (
                kind == "and" and not child_eval.result.matched
            ) or (kind == "or" and child_eval.result.matched)
            if should_short_circuit:
                remaining = children[index + 1 :]
                matched = child_eval.result.matched if kind == "or" else False
                trace = {
                    "type": kind,
                    "evaluated": True,
                    "matched": matched,
                    "children": [
                        evaluation.trace for evaluation in child_evaluations
                    ]
                    + [
                        self._skipped_trace(
                            rest,
                            "or_matched" if kind == "or" else "and_failed",
                        )
                        for rest in remaining
                    ],
                    "short_circuit_reason": (
                        "or_matched" if kind == "or" else "and_failed"
                    ),
                }
                confidence = min(
                    evaluation.result.confidence for evaluation in child_evaluations
                )
                result = self._build_composite_result(
                    matched=matched,
                    confidence=confidence,
                    trace=trace,
                    metadata=child_eval.result.metadata,
                )
                return _ConditionEvaluation(result=result, trace=trace)

        confidence = min(evaluation.result.confidence for evaluation in child_evaluations)
        matched = all(
            evaluation.result.matched for evaluation in child_evaluations
        ) if kind == "and" else any(
            evaluation.result.matched for evaluation in child_evaluations
        )
        trace = {
            "type": kind,
            "evaluated": True,
            "matched": matched,
            "children": [evaluation.trace for evaluation in child_evaluations],
        }
        result = self._build_composite_result(
            matched=matched,
            confidence=confidence,
            trace=trace,
            metadata=self._composite_metadata(child_evaluations, matched=matched),
        )
        return _ConditionEvaluation(result=result, trace=trace)

    def get_applicable_controls(
        self,
        request: EvaluationRequest,
        selector_errors: list[ControlMatch] | None = None,
    ) -> list[ControlWithIdentity]:
        """Get all controls that apply to the current request."""
        applicable = []
        step = request.step
        step_type = step.type
        step_name = step.name

        for item in self.controls:
            control_def = item.control

            if not control_def.enabled:
                continue

            scope = control_def.scope
            if scope.stages and request.stage not in scope.stages:
                continue
            if scope.step_types and step_type not in scope.step_types:
                continue

            # Filter by locality based on context
            if control_def.execution != self.context:
                continue

            # Optional step name scoping
            if scope.step_names or scope.step_name_regex:
                match = False
                if scope.step_names and step_name in scope.step_names:
                    match = True
                if not match and scope.step_name_regex:
                    try:
                        if _compile_regex(scope.step_name_regex).search(step_name) is not None:
                            match = True
                    except re2.error as e:
                        # Invalid pattern should have been caught at model validation;
                        # skip defensively but surface an error if requested.
                        if selector_errors is not None:
                            selector_errors.append(
                                ControlMatch(
                                    control_id=item.id,
                                    control_name=item.name,
                                    action=control_def.action.decision,
                                    result=EvaluatorResult(
                                        matched=False,
                                        confidence=0.0,
                                        message=(
                                            "Control skipped due to invalid step_name_regex: "
                                            f"'{scope.step_name_regex}'"
                                        ),
                                        error=f"Invalid step_name_regex: {e}",
                                    ),
                                    steering_context=control_def.action.steering_context,
                                )
                            )
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
            request: The evaluation request containing step and context

        Returns:
            EvaluationResponse with is_safe status and any matches
        """
        precheck_errors: list[ControlMatch] = []
        applicable = self.get_applicable_controls(request, selector_errors=precheck_errors)

        if not applicable:
            confidence = 0.0 if precheck_errors else 1.0
            return EvaluationResponse(
                is_safe=True,
                confidence=confidence,
                matches=None,
                errors=precheck_errors or None,
            )

        # Prepare evaluation tasks
        eval_tasks: list[_EvalTask] = [_EvalTask(item=item) for item in applicable]

        # Run evaluations in parallel with cancel-on-deny
        matches: list[ControlMatch] = []
        is_safe = True
        deny_found = asyncio.Event()
        # The concurrency cap applies to visited leaf evaluator executions, not
        # whole top-level controls. Composite trees are still walked serially.
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EVALUATIONS)

        async def evaluate_control(eval_task: _EvalTask) -> None:
            """Evaluate a single control, respecting cancellation and timeout."""
            try:
                evaluation = await self._evaluate_condition(
                    eval_task.item,
                    eval_task.item.control.condition,
                    request,
                    semaphore,
                )
                eval_task.result = evaluation.result

                if (
                    eval_task.result.matched
                    and eval_task.item.control.action.decision == "deny"
                ):
                    deny_found.set()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                error_msg = self._format_exception(error)
                logger.exception(
                    "Unexpected condition evaluation error for control '%s': %s",
                    eval_task.item.name,
                    error_msg,
                )
                eval_task.result = self._build_error_result(
                    error_msg,
                    message_prefix="Condition evaluation failed",
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
        errors: list[ControlMatch] = list(precheck_errors)
        non_matches: list[ControlMatch] = []
        successful_count = 0
        evaluated_count = 0  # Controls that ran (not cancelled)
        deny_errored = False
        steer_errored = False
        deny_matched = False

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
                        steering_context=eval_task.item.control.action.steering_context,
                    )
                )
                # Track if a deny or steer control errored
                decision = eval_task.item.control.action.decision
                if decision == "deny":
                    deny_errored = True
                elif decision == "steer":
                    steer_errored = True
                continue

            # Count successful evaluations
            successful_count += 1

            # Collect successful matches
            if eval_task.result.matched:
                steer_ctx = eval_task.item.control.action.steering_context
                matches.append(
                    ControlMatch(
                        control_id=eval_task.item.id,
                        control_name=eval_task.item.name,
                        action=eval_task.item.control.action.decision,
                        result=eval_task.result,
                        steering_context=steer_ctx,
                    )
                )

                if eval_task.item.control.action.decision in ("deny", "steer"):
                    is_safe = False
                    if eval_task.item.control.action.decision == "deny":
                        deny_matched = True
            else:
                # Collect non-matches (evaluated but did not match)
                non_matches.append(
                    ControlMatch(
                        control_id=eval_task.item.id,
                        control_name=eval_task.item.name,
                        action=eval_task.item.control.action.decision,
                        result=eval_task.result,
                        steering_context=eval_task.item.control.action.steering_context,
                    )
                )

        # Fail closed if a deny control errored (couldn't verify safety)
        if deny_errored:
            is_safe = False

        # Log steer errors for observability (non-blocking)
        if steer_errored:
            steer_error_names = [
                e.control_name for e in errors
                if e.action == "steer" and e.result.error
            ]
            logger.warning(
                f"Steer control evaluation failed (non-blocking): {', '.join(steer_error_names)}"
            )

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
            non_matches=non_matches if non_matches else None,
        )
