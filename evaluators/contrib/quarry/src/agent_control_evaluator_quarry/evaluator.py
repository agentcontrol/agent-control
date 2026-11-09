"""Local Quarry scans through the standard Agent Control evaluator interface."""

from __future__ import annotations

import asyncio
from importlib.metadata import version
from typing import Any, Literal

from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult, Step
from pydantic import ValidationError
from quarry import ConversationValidationError, IncompleteScanError, SafetyLimits, compile_policy
from quarry.config import QuarryConfig

from .config import QuarryEvaluatorConfig
from .conversion import StepConversionError, conversations_from_step


@register_evaluator
class QuarryEvaluator(Evaluator[QuarryEvaluatorConfig]):
    """Compile one local rule per cached instance; keep all scan state request-local."""

    metadata = EvaluatorMetadata(
        name="quarry.policy",
        version=version("agent-control-evaluator-quarry"),
        description="Local symbolic Quarry policy evaluation over trace/session steps",
        requires_api_key=False,
        timeout_ms=10000,
    )
    config_model = QuarryEvaluatorConfig

    def __init__(self, config: QuarryEvaluatorConfig) -> None:
        """Compile before accepting scans; reject invalid rules and missing resources.

        No models, adapters, text files, or stub probers are configured. Rules requiring
        these resources fail at construction. Agent Control's evaluator factory caches
        the instance by configuration, including the rule source and limits.

        Args:
            config: Validated rule source, limits, and session semantics.

        Raises:
            ValueError: If the rule cannot compile as a local symbolic policy.
        """
        super().__init__(config)
        runtime = QuarryConfig(
            config_version=2,
            safety_limits=SafetyLimits(
                rule_timeout=self.get_timeout_seconds(),
                max_messages=config.max_messages,
                enforce_limits=True,
            ),
        )
        try:
            self._policy = compile_policy(config.rule, runtime_config=runtime)
            if self._policy.parameter_schema:
                raise ValueError("Parameterized rules are not supported by this integration.")
        except Exception as exc:
            raise ValueError(
                "Quarry rule could not compile. Supply exactly one valid symbolic rule "
                "without parameters, model, text-file, or prober dependencies."
            ) from exc

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate a complete Step or its serialized object.

        Args:
            data: Trace/session Step or its serialized object; empty input is a non-match.

        Returns:
            A policy decision, or an error for invalid or incomplete evaluation.
        """
        if data is None or (isinstance(data, (str, list, dict)) and not data):
            return self._empty_result()
        try:
            step = data if isinstance(data, Step) else Step.model_validate(data)
        except ValidationError:
            return self._error("A complete trace/session Step is required.", "invalid")
        return await self._evaluate_step(step)

    async def evaluate_with_context(self, data: Any, step: Step) -> EvaluatorResult:
        """Scan the complete runtime Step, independent of selector-selected scalar data.

        Controls should use selector path ``*`` and scope to trace/session. The complete
        hierarchy is authoritative; a missing selected field does not suppress its scan.

        Args:
            data: Selector-selected value; the complete step takes precedence.
            step: Authoritative trace/session hierarchy for this request.

        Returns:
            A policy decision, or an error for invalid or incomplete evaluation.
        """
        return await self._evaluate_step(step)

    async def _evaluate_step(self, step: Step) -> EvaluatorResult:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.get_timeout_seconds()
        try:
            conversations = conversations_from_step(
                step, session_mode=self.config.session_mode, max_messages=self.config.max_messages
            )
            if loop.time() >= deadline:
                raise TimeoutError
            if not conversations:
                return self._empty_result()
            matches: set[str] = set()
            # All traces must finish authoritatively, even after an earlier trace matched.
            async with asyncio.timeout_at(deadline):
                for conversation in conversations:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError
                    result = await self._policy.scan_async(
                        conversation, deadline_seconds=remaining
                    )
                    result.raise_for_status()
                    if loop.time() >= deadline:
                        raise TimeoutError
                    matches.update(result.rule_matches)
            return EvaluatorResult(
                matched=bool(matches),
                confidence=1.0,
                message="Quarry policy matched." if matches else "Quarry policy did not match.",
                metadata={
                    "completion_state": "complete",
                    "matched_rules": sorted(matches),
                    "scan_count": len(conversations),
                    "session_mode": self.config.session_mode if step.type == "session" else None,
                    "policy_digest": self._policy.policy_digest,
                },
            )
        except StepConversionError as exc:
            return self._error(str(exc), "invalid")
        except ConversationValidationError:
            return self._error("Quarry rejected an invalid conversation.", "invalid")
        except IncompleteScanError:
            return self._error(
                "Quarry scan incomplete: a rule failed, timed out, was skipped, or hit a limit.",
                "incomplete",
            )
        except TimeoutError:
            return self._error("Quarry evaluation timed out.", "incomplete")
        except Exception:
            # Upstream diagnostics can contain conversation data. Do not expose them.
            return self._error("Quarry evaluation failed.", "incomplete")

    @staticmethod
    def _empty_result() -> EvaluatorResult:
        return EvaluatorResult(
            matched=False,
            confidence=1.0,
            message="No conversation messages to scan.",
            metadata={"completion_state": "complete", "matched_rules": [], "scan_count": 0},
        )

    @staticmethod
    def _error(message: str, state: Literal["invalid", "incomplete"]) -> EvaluatorResult:
        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=message,
            error=message,
            metadata={"completion_state": state},
        )
