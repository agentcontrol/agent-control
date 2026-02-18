import json
import os
from typing import Any

import httpx
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult

from .config import LLMRelevanceConfig


_SYSTEM_PROMPT = (
    "You are a strict evaluator. Given a QUESTION and an ANSWER, "
    "score how relevant the answer is to the question on a 0 to 1 scale. "
    "Return JSON with keys: score (float 0-1), rationale (string)."
)


@register_evaluator
class LLMRelevanceEvaluator(Evaluator[LLMRelevanceConfig]):
    """LLM-as-judge relevance evaluator (OpenAI-compatible API)."""

    metadata = EvaluatorMetadata(
        name="acme.llm-relevance",
        version="1.0.0",
        description="LLM-as-judge relevance scoring (0-1)",
        requires_api_key=True,
        timeout_ms=30000,
    )
    config_model = LLMRelevanceConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        try:
            question, answer = _extract_qa(data)
            if not question or not answer:
                return EvaluatorResult(
                    matched=True,
                    confidence=1.0,
                    message="Missing question or answer",
                )

            api_key = os.getenv(self.config.api_key_env, "")
            if not api_key:
                return _error_result(
                    "Missing API key",
                    on_error=self.config.on_error,
                )

            payload = {
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"QUESTION:\n{question}\n\nANSWER:\n{answer}",
                    },
                ],
                "temperature": 0,
            }

            headers = {"Authorization": f"Bearer {api_key}"}
            url = self.config.base_url.rstrip("/") + "/chat/completions"

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            score, rationale = _parse_score(content)

            if score is None:
                return _error_result("Could not parse score", on_error=self.config.on_error)

            matched = score < self.config.threshold
            msg = (
                f"Relevance score {score:.2f} (threshold {self.config.threshold:.2f})"
            )
            return EvaluatorResult(
                matched=matched,
                confidence=score,
                message=msg,
                metadata={"score": score, "rationale": rationale},
            )

        except Exception as e:
            return _error_result(str(e), on_error=self.config.on_error)


def _extract_qa(data: Any) -> tuple[str, str]:
    """Extract question/answer from input payload."""
    if isinstance(data, dict):
        question = data.get("input") or data.get("question") or ""
        answer = data.get("output") or data.get("answer") or ""
        # If input is nested dict, try common keys
        if isinstance(question, dict):
            question = (
                question.get("question")
                or question.get("query")
                or question.get("prompt")
                or str(question)
            )
        return str(question), str(answer)

    # If raw string, treat as answer only
    return "", str(data)


def _parse_score(content: str) -> tuple[float | None, str]:
    """Parse JSON response to extract score + rationale."""
    try:
        obj = json.loads(content)
        score = float(obj.get("score"))
        rationale = str(obj.get("rationale", ""))
        return score, rationale
    except Exception:
        return None, ""


def _error_result(error_msg: str, *, on_error: str) -> EvaluatorResult:
    matched = on_error == "deny"
    return EvaluatorResult(
        matched=matched,
        confidence=0.0,
        message=f"LLM relevance evaluator error: {error_msg}",
        error=error_msg,
    )
