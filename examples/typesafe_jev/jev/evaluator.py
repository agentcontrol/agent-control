"""TypeSafe Jev (System One) evaluator for Agent Control."""

from __future__ import annotations

import json
import logging
import os
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any, NamedTuple

from agent_control_evaluators import (
    Evaluator,
    EvaluatorMetadata,
    register_evaluator,
)
from agent_control_models import EvaluatorResult

from .client import TYPESAFE_HTTPX_AVAILABLE, TypeSafeClient, build_endpoint
from .config import JevQuestion, TypeSafeJevConfig, coerce_number

logger = logging.getLogger(__name__)

# A noul and a score answer with a number, a choice answers with an option name.
AnswerValue = float | str

# Every question's raw answer, keyed by the question id from the config. The
# ids are chosen by whoever writes the control, so this cannot be a TypedDict.
RawAnswers = dict[str, AnswerValue]


class Decision(NamedTuple):
    """How the deciding questions resolved into the one boolean a control needs.

    Attributes:
        matched: Whether the control fires.
        message: Human-readable explanation, surfaced on the control result.
        tripped: Ids of the questions that crossed their own threshold.
        deciding: Ids of every question that carried a threshold, tripped or not.
    """

    matched: bool
    message: str
    tripped: list[str]
    deciding: list[str]


def _resolve_package_version() -> str:
    """Return the installed package version, or a dev fallback during local imports."""
    try:
        return version("agent-control-typesafe-jev-example")
    except PackageNotFoundError:
        return "0.0.0.dev"


_PACKAGE_VERSION = _resolve_package_version()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


@register_evaluator
class TypeSafeJevEvaluator(Evaluator[TypeSafeJevConfig]):
    """Ask Jev a set of typed questions in one request and decide from the answers.

    Every configured question travels in a single call, because Jev evaluates
    them in parallel and charges only for the extra question tokens. Declaring
    one question is the degenerate case, not a different code path.

    A question with a threshold decides: it is an input to
    ``decide.combine``, which is either ``any`` or ``all``. A question without
    one is recorded only, and is not an input. Rules that ``any`` and ``all``
    cannot express compose in the engine's condition trees instead.
    """

    metadata = EvaluatorMetadata(
        name="typesafe.jev",
        version=_PACKAGE_VERSION,
        description="TypeSafe AI Jev System One typed-question evaluator",
        requires_api_key=True,
        timeout_ms=10000,
    )

    config_model = TypeSafeJevConfig

    def __init__(self, config: TypeSafeJevConfig) -> None:
        """Initialize with validated config.

        The HTTP client is created lazily and then reused. It holds no
        request-scoped state, and httpx.AsyncClient is safe to share across
        concurrent requests, so caching it here keeps the connection alive
        between evaluations instead of paying a TLS handshake per call.
        """
        super().__init__(config)
        self._client: TypeSafeClient | None = None

    @classmethod
    def is_available(cls) -> bool:
        """Report whether httpx is importable."""
        return TYPESAFE_HTTPX_AVAILABLE

    def _build_questions(self) -> dict[str, dict[str, Any]]:
        """Render every configured question into the API's wire shape."""
        questions: dict[str, dict[str, Any]] = {}
        for question_id, question in self.config.questions.items():
            payload: dict[str, Any] = {
                "type": question.type,
                "instructions": question.instructions,
            }
            if question.criteria is not None:
                payload["criteria"] = question.criteria
            questions[question_id] = payload
        return questions

    def _prepare_state(self, data: Any) -> Any:
        """Return the state to send.

        A mapping that carries both sides is narrowed to ``payload_field``.
        Anything else is passed through, because the API accepts a string, an
        object, or an array.
        """
        if isinstance(data, dict) and ("input" in data or "output" in data):
            selected = data.get(self.config.payload_field)
            if selected is not None:
                return selected
        return data

    def _get_client(self) -> TypeSafeClient:
        if self._client is None:
            api_key = os.getenv(self.config.api_key_env)
            if not api_key:
                raise RuntimeError(
                    f"Missing TypeSafe API key in env '{self.config.api_key_env}'. "
                    "Set it on the server."
                )
            self._client = TypeSafeClient(
                api_key=api_key,
                endpoint_url=build_endpoint(self.config.base_url),
                timeout_s=self.get_timeout_seconds(),
            )
        return self._client

    def _raw_answers(self, response: dict[str, Any]) -> RawAnswers:
        """Pull the raw value out of every answer.

        Each answer object carries its value under a key named after the
        question type: a noul under "noul", a score under "score", a choice
        under "choice".

        Args:
            response: The decoded body of one system_one call.

        Returns:
            Every configured question id mapped to its raw answer. A noul and a
            score give a float, a choice gives the chosen option name.

        Raises:
            RuntimeError: The response is missing an answer, or an answer is
                missing the value for its type.
        """
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise RuntimeError("TypeSafe response has no answers object")

        raw: RawAnswers = {}
        for question_id, question in self.config.questions.items():
            answer = answers.get(question_id)
            if not isinstance(answer, dict):
                raise RuntimeError(f"TypeSafe response has no answer for question {question_id!r}")
            if question.type not in answer:
                raise RuntimeError(
                    f"TypeSafe answer for {question_id!r} has no {question.type!r} field"
                )
            raw[question_id] = answer[question.type]
        return raw

    def _question_matches(self, question: JevQuestion, value: AnswerValue) -> bool:
        """Report whether one answer crosses the line its question was configured with.

        The comparison runs here rather than at the API, so a threshold can be
        retuned without asking the model again.

        Args:
            question: The configured question, carrying its operator and threshold.
            value: That question's raw answer.

        Returns:
            True when the answer satisfies the comparison, which is what makes
            the question count as tripped.

        Raises:
            ValueError: A numeric comparison was configured but the answer or
                the threshold is not a number.
        """
        operator = question.operator
        threshold = question.threshold

        if operator == "eq":
            return bool(value == threshold)
        if operator == "ne":
            return bool(value != threshold)
        if operator == "contains":
            return _stringify(threshold) in _stringify(value)

        value_number = coerce_number(value)
        threshold_number = coerce_number(threshold)
        if value_number is None:
            raise ValueError(f"TypeSafe answer {value!r} is not numeric")
        if threshold_number is None:
            raise ValueError(f"TypeSafe threshold {threshold!r} is not numeric")
        if operator == "gt":
            return value_number > threshold_number
        if operator == "gte":
            return value_number >= threshold_number
        if operator == "lt":
            return value_number < threshold_number
        if operator == "lte":
            return value_number <= threshold_number
        raise ValueError(f"Unsupported TypeSafe operator: {operator}")

    def _decide(self, raw: RawAnswers) -> Decision:
        """Combine the deciding questions into the one boolean a control needs.

        Questions without a threshold are asked and recorded but take no part
        here. Of the rest, ``any`` fires on the first that trips and ``all``
        needs every one.

        Args:
            raw: Every question's answer, from _raw_answers.

        Returns:
            The decision, plus which questions decided and which of them tripped.
        """
        tripped: list[str] = []
        deciding: list[str] = []

        for question_id, question in self.config.questions.items():
            if not question.decides:
                continue
            deciding.append(question_id)
            if self._question_matches(question, raw[question_id]):
                tripped.append(question_id)

        combine = self.config.decide.combine
        matched = bool(tripped) if combine == "any" else len(tripped) == len(deciding)

        if matched:
            detail = ", ".join(
                f"{qid}={raw[qid]!r} {self.config.questions[qid].operator} "
                f"{self.config.questions[qid].threshold!r}"
                for qid in tripped
            )
            message = f"TypeSafe {combine}: {detail}: control triggered."
        elif combine == "all" and tripped:
            missing = [qid for qid in deciding if qid not in tripped]
            message = (
                f"TypeSafe all: {', '.join(missing)} did not trip: control not triggered."
            )
        else:
            message = "TypeSafe: no question tripped: control not triggered."

        return Decision(matched=matched, message=message, tripped=tripped, deciding=deciding)

    def _base_metadata(self) -> dict[str, Any]:
        return {
            "evaluator": self.metadata.name,
            "model": self.config.model,
            "question_ids": sorted(self.config.questions),
            "combine": self.config.decide.combine,
            # What each question asked. With this, a reader can turn a raw
            # answer into the outcome it produced without also holding the
            # control's configuration.
            "questions": {
                question_id: {
                    "type": question.type,
                    "operator": question.operator,
                    "threshold": question.threshold,
                    "decides": question.decides,
                }
                for question_id, question in self.config.questions.items()
            },
        }

    def _handle_error(self, message: str, detail: str) -> EvaluatorResult:
        """Apply the configured error policy.

        ``EvaluatorResult`` forbids ``error`` together with ``matched=True``, so
        a fail-closed deny reports the detail in the message and metadata and
        leaves ``error`` unset. A fail-closed deny therefore does not appear in
        evaluator-health error rates.
        """
        fallback = self.config.on_error
        matched = fallback == "deny"
        metadata = self._base_metadata()
        metadata["error"] = detail
        metadata["fallback_action"] = fallback
        return EvaluatorResult(
            matched=matched,
            confidence=0.0,
            message=message,
            metadata=metadata,
            error=None if matched else detail,
        )

    def _confidence(self, response: dict[str, Any], raw: RawAnswers, decided_by: str) -> float:
        """Return a 0-1 confidence for the question that drove the decision.

        Score and choice answers carry the model's own ``confidence``. A noul
        answer does not, so report how decisive the probability is: a noul of
        0.99 or 0.01 is decisive, and 0.5 is a coin flip.
        """
        answers = response.get("answers") or {}
        answer = answers.get(decided_by) or {}
        reported = coerce_number(answer.get("confidence"))
        if reported is not None:
            return max(0.0, min(1.0, reported))
        question = self.config.questions.get(decided_by)
        if question is not None and question.type == "noul":
            probability = coerce_number(raw.get(decided_by))
            if probability is not None:
                return max(0.0, min(1.0, abs(probability - 0.5) * 2.0))
        return 1.0

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Ask every configured question in one request and decide from the answers.

        Args:
            data: Data selected by the control's selector.

        Returns:
            EvaluatorResult carrying the decision plus every raw answer, the
            routing detail, and token usage in metadata.
        """
        state = self._prepare_state(data)
        if not _stringify(state).strip():
            return EvaluatorResult(
                matched=False,
                confidence=1.0,
                message="No data to send to TypeSafe",
                metadata=self._base_metadata(),
            )

        started = time.monotonic()
        try:
            response = await self._get_client().system_one(
                state=state,
                questions=self._build_questions(),
                model=self.config.model,
            )
            elapsed_ms = int((time.monotonic() - started) * 1000)

            raw = self._raw_answers(response)
            decision = self._decide(raw)
            decided_by = (
                decision.tripped[0]
                if decision.tripped
                else (decision.deciding or [""])[0]
            )

            metadata = self._base_metadata()
            metadata.update(
                {
                    "tripped": decision.tripped,
                    "deciding": decision.deciding,
                    "answers": raw,
                    "response_model": response.get("model"),
                    "usage": response.get("usage"),
                    "latency_ms": elapsed_ms,
                }
            )
            return EvaluatorResult(
                matched=decision.matched,
                confidence=self._confidence(response, raw, decided_by),
                message=decision.message,
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("TypeSafe Jev evaluation error: %s", exc, exc_info=True)
            return self._handle_error(f"TypeSafe Jev evaluation error: {exc}", str(exc))

    async def aclose(self) -> None:
        """Close the shared HTTP connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
