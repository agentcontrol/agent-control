"""Configuration model for the TypeSafe Jev (System One) evaluator.

One control declares a map of questions. Jev evaluates every question in a
single request, so asking several costs about the same latency as asking one.

Each question can carry its own operator and threshold. A question with a
threshold decides: it is an input to ``decide.combine``, which says whether
one deciding question tripping is enough, or whether all of them must trip.
A question without a threshold is asked and recorded only. It is not an input,
so it can neither fire the control nor stop it firing.

``any`` and ``all`` are the only way questions combine here. A rule that needs
more, such as different evaluators or nested logic, composes in the engine's
and/or/not condition trees instead.
"""

from __future__ import annotations

from typing import Literal

from agent_control_evaluators import EvaluatorConfig
from pydantic import BaseModel, ConfigDict, Field, model_validator

JevQuestionType = Literal["noul", "score", "choice"]
JevOperator = Literal["gt", "gte", "lt", "lte", "eq", "ne", "contains"]
JevPayloadField = Literal["input", "output"]

NUMERIC_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})
TEXT_OPERATORS = frozenset({"eq", "ne", "contains"})

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"


def coerce_number(value: object) -> float | None:
    """Return a float for JSON scalars that compare numerically, else None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


class JevQuestion(BaseModel):
    """One typed question sent to Jev.

    Attributes:
        type: Which TypeSafe primitive to ask.
        instructions: The question text.
        criteria: Meaning of each outcome. A noul takes an optional true/false
            mapping, a choice takes an option-to-description mapping, and a
            score takes an ordered list of rubric levels. The wording matters:
            a bare list of level names scores differently from a described one.
        operator: Comparison applied to this question's answer.
        threshold: Value the operator compares against. Leave it unset to ask
            the question for the record without letting it affect the decision.
    """

    model_config = ConfigDict(extra="forbid")

    type: JevQuestionType = Field(
        default="noul", description="Which TypeSafe primitive to ask: noul, score, or choice."
    )
    instructions: str = Field(min_length=1, description="The question text sent to Jev.")
    criteria: dict[str, str] | list[str] | None = Field(
        default=None,
        description=(
            "Meaning of each outcome. The shape depends on type. "
            'noul: {"true": "...", "false": "..."} and optional. '
            'score: ["level 0", "level 1", ...] and required. '
            'choice: {"option": "description", ...} and required.'
        ),
    )
    operator: JevOperator = Field(
        default="gte", description="Comparison applied to this question's answer."
    )
    threshold: float | int | str | None = Field(
        default=None,
        description=(
            "Value the operator compares against. Unset means the question is "
            "asked and recorded but does not affect the decision."
        ),
    )

    @model_validator(mode="after")
    def validate_question(self) -> JevQuestion:
        """Reject criteria and operator combinations the API or the answer rejects."""
        if self.type == "choice":
            if not isinstance(self.criteria, dict) or len(self.criteria) < 2:
                raise ValueError("a choice question requires criteria with 2 or more options")
            if self.threshold is not None and self.operator not in TEXT_OPERATORS:
                raise ValueError(
                    f"a choice question requires a text operator {sorted(TEXT_OPERATORS)}"
                )
        elif self.type == "score":
            if not isinstance(self.criteria, list) or len(self.criteria) < 2:
                raise ValueError("a score question requires criteria with 2 or more levels")
        elif self.criteria is not None:
            if not isinstance(self.criteria, dict) or set(self.criteria) != {"true", "false"}:
                raise ValueError(
                    "a noul question requires criteria with exactly 'true' and 'false'"
                )

        if self.type in ("noul", "score") and self.threshold is not None:
            if self.operator not in NUMERIC_OPERATORS:
                raise ValueError(
                    f"a {self.type} question requires a numeric operator "
                    f"{sorted(NUMERIC_OPERATORS)}"
                )
            if coerce_number(self.threshold) is None:
                raise ValueError(f"operator {self.operator!r} requires a numeric threshold")
        return self

    @property
    def decides(self) -> bool:
        """Whether this question takes part in the decision."""
        return self.threshold is not None


class DecideConfig(BaseModel):
    """How the deciding questions combine into one boolean."""

    model_config = ConfigDict(extra="forbid")

    combine: Literal["any", "all"] = Field(
        default="any",
        description=(
            "any: the control fires when any deciding question trips. "
            "all: every deciding question must trip."
        ),
    )


class TypeSafeJevConfig(EvaluatorConfig):
    """Configuration for one TypeSafe Jev control.

    Attributes:
        questions: Questions to ask, keyed by id. All are sent in one request.
        decide: How the deciding questions combine.
        payload_field: Which side to send when the selected data is a mapping
            that carries both an input and an output.
        api_key_env: Name of the environment variable holding the API key.
        base_url: API origin. Override for a proxy or a test double.
        model: Model identifier sent to the API.
        timeout_ms: Total budget for one evaluation, retries included.
        on_error: Decision applied when the call fails. ``allow`` fails open
            and ``deny`` fails closed.
    """

    questions: dict[str, JevQuestion] = Field(
        min_length=1,
        description="Questions to ask, keyed by id. All are sent in a single request.",
    )
    decide: DecideConfig = Field(
        default_factory=DecideConfig,
        description="How the deciding questions combine into one boolean.",
    )
    payload_field: JevPayloadField = Field(
        default="input",
        description="Which side to send when selected data carries input and output.",
    )
    api_key_env: str = Field(
        default="TYPESAFE_API_KEY",
        min_length=1,
        description="Environment variable name holding the TypeSafe API key.",
    )
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        min_length=1,
        description="API origin. Override for a proxy or a test double.",
    )
    model: str = Field(
        default=DEFAULT_MODEL, min_length=1, description="Model identifier sent to the API."
    )
    timeout_ms: int = Field(
        default=10000,
        ge=500,
        le=60000,
        description=(
            "Total budget for one evaluation in milliseconds, retries included. "
            "The engine applies its own timeout on top."
        ),
    )
    on_error: Literal["allow", "deny"] = Field(
        default="allow",
        description="Decision applied when the call fails. allow fails open.",
    )

    @model_validator(mode="after")
    def require_a_deciding_question(self) -> TypeSafeJevConfig:
        """At least one question must carry a threshold, or nothing can decide."""
        if not any(question.decides for question in self.questions.values()):
            raise ValueError(
                "at least one question needs a threshold, otherwise nothing decides"
            )
        return self
