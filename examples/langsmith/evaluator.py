"""LangSmith evaluator implementation.

This evaluator uses LangSmith's LLM-as-judge pattern with OpenAI to assess
agent outputs for quality and safety metrics. All evaluations are traced in
LangSmith for monitoring and analysis.

The evaluator uses OpenAI GPT-4 as the judge LLM and traces all evaluations
to LangSmith for observability. Fallback heuristics are used when the API
is unavailable.
"""

import logging
from typing import Any

from agent_control_models import (
    Evaluator,
    EvaluatorMetadata,
    EvaluatorResult,
    register_evaluator,
)

from client import HTTPX_AVAILABLE, LangSmithClient
from config import LangSmithEvaluatorConfig

logger = logging.getLogger(__name__)

# Evaluator is available if httpx is installed (for client)
LANGSMITH_AVAILABLE = HTTPX_AVAILABLE


@register_evaluator
class LangSmithEvaluator(Evaluator[LangSmithEvaluatorConfig]):
    """LangSmith evaluation evaluator using LLM-as-judge pattern.

    This evaluator uses LangSmith's LLM-as-judge pattern with OpenAI GPT-4
    to assess agent outputs for various quality and safety metrics. All
    evaluations are traced in LangSmith for observability and analysis.

    The evaluator calls OpenAI's API with carefully crafted prompts for each
    metric, and traces all requests through LangSmith. If the API is unavailable,
    it falls back to simple heuristic methods.

    Supported Metrics:
        - toxicity: Detect toxic or harmful content using LLM judgment
        - relevance: Check if output is relevant to the input/context
        - accuracy: Verify factual accuracy against provided context
        - hallucination: Detect hallucinations or unsupported claims
        - coherence: Check if output is coherent and well-structured
        - pii_detection: Detect personally identifiable information
        - custom: Use a custom evaluation prompt

    Example:
        ```python
        from langsmith_evaluator import LangSmithEvaluator, LangSmithEvaluatorConfig

        config = LangSmithEvaluatorConfig(
            metric="toxicity",
            threshold=0.8,
            langsmith_project="my-project",
        )

        evaluator = LangSmithEvaluator(config)
        result = await evaluator.evaluate("some potentially toxic text")
        ```

    Environment Variables:
        LANGSMITH_API_KEY: Your LangSmith API key (for tracing).
        OPENAI_API_KEY: Your OpenAI API key (required for LLM-as-judge).
    """

    metadata = EvaluatorMetadata(
        name="langsmith",
        version="1.0.0",
        description="LangSmith evaluation API integration",
        requires_api_key=True,
        timeout_ms=10000,
    )
    config_model = LangSmithEvaluatorConfig

    @classmethod
    def is_available(cls) -> bool:
        """Check if langsmith dependency is installed."""
        return LANGSMITH_AVAILABLE

    def __init__(self, config: LangSmithEvaluatorConfig) -> None:
        """Initialize LangSmith evaluator with configuration.

        Args:
            config: Validated LangSmithEvaluatorConfig instance.

        Note:
            API key is optional for demo mode. In production, you would
            require LANGSMITH_API_KEY to be set.
        """
        super().__init__(config)

        # Initialize the LangSmith HTTP client
        self._client: LangSmithClient | None = None

        logger.debug(
            f"[LangSmithEvaluator] Initialized with metric={config.metric}, "
            f"threshold={config.threshold}"
        )

    def _get_client(self) -> LangSmithClient:
        """Get or create the LangSmith HTTP client.

        Returns:
            The LangSmithClient instance.
        """
        if self._client is None:
            self._client = LangSmithClient(
                project_name=self.config.langsmith_project,
            )
            logger.debug("[LangSmithEvaluator] Created LangSmith client")
        return self._client

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate data using LangSmith.

        Args:
            data: The data to evaluate. Can be:
                - str: Direct text to evaluate
                - dict: Must contain the text and optionally context

        Returns:
            EvaluatorResult with matched status and metadata.
        """
        try:
            # Extract text and context from data
            text, context = self._extract_text_and_context(data)

            # Perform evaluation based on metric
            score, details = await self._evaluate_metric(text, context)

            # Determine if threshold is exceeded
            matched = score > self.config.threshold

            return EvaluatorResult(
                matched=matched,
                confidence=score,
                message=self._build_message(matched, score, details),
                metadata={
                    "metric": self.config.metric,
                    "score": score,
                    "threshold": self.config.threshold,
                    "details": details,
                    "project": self.config.langsmith_project,
                },
            )

        except Exception as e:
            logger.error(f"LangSmith evaluation error: {e}", exc_info=True)
            return self._handle_error(e)

    def _extract_text_and_context(self, data: Any) -> tuple[str, str | None]:
        """Extract text and context from the input data.

        Args:
            data: The input data to evaluate.

        Returns:
            Tuple of (text, context). Context may be None.
        """
        if isinstance(data, str):
            return data, None

        if isinstance(data, dict):
            # Try to find the main text field
            text = data.get("output") or data.get("text") or data.get("input") or str(data)

            # Try to find context if required
            context = None
            if self.config.require_context:
                context = data.get(self.config.context_key)
                if context is None:
                    logger.warning(
                        f"Context required but '{self.config.context_key}' not found in data"
                    )

            return str(text), context

        # Fallback: convert to string
        return str(data), None

    async def _evaluate_metric(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Evaluate the text using the configured metric with LangSmith APIs.

        Args:
            text: The text to evaluate.
            context: Optional context for context-aware metrics.

        Returns:
            Tuple of (score, details_dict). Score is 0.0-1.0.
        """
        metric = self.config.metric

        # Get LangSmith client
        client = self._get_client()

        try:
            # Call LangSmith evaluation API (LLM-as-judge)
            response = await client.evaluate(
                text=text,
                metric=metric,
                context=context,
                project_name=self.config.langsmith_project,
                metadata={
                    "evaluator": "langsmith",
                    "threshold": self.config.threshold,
                }
            )

            if response.status == "error":
                logger.error(f"[LangSmithEvaluator] Evaluation failed: {response.metrics.details.get('error')}")
                # Fallback to heuristic methods
                return await self._evaluate_metric_fallback(text, context, metric)

            score = response.metrics.score
            details = response.metrics.details

            logger.debug(
                f"[LangSmithEvaluator] {metric} evaluation: score={score:.3f}, "
                f"execution_time={response.execution_time_ms:.1f}ms"
            )

            return score, details

        except Exception as e:
            logger.warning(
                f"[LangSmithEvaluator] API evaluation failed, using fallback: {e}"
            )
            # Fallback to heuristic methods
            return await self._evaluate_metric_fallback(text, context, metric)

    async def _evaluate_metric_fallback(
        self, text: str, context: str | None, metric: str
    ) -> tuple[float, dict[str, Any]]:
        """Fallback evaluation using heuristics when API is unavailable.

        Args:
            text: The text to evaluate.
            context: Optional context for context-aware metrics.
            metric: The metric to evaluate.

        Returns:
            Tuple of (score, details_dict). Score is 0.0-1.0.
        """
        logger.debug(f"[LangSmithEvaluator] Using fallback heuristic for {metric}")

        if metric == "toxicity":
            return await self._evaluate_toxicity(text)
        elif metric == "relevance":
            return await self._evaluate_relevance(text, context)
        elif metric == "accuracy":
            return await self._evaluate_accuracy(text, context)
        elif metric == "hallucination":
            return await self._evaluate_hallucination(text, context)
        elif metric == "coherence":
            return await self._evaluate_coherence(text)
        elif metric == "pii_detection":
            return await self._evaluate_pii(text)
        elif metric == "custom":
            return await self._evaluate_custom(text, context)
        else:
            raise ValueError(f"Unsupported metric: {metric}")

    async def _evaluate_toxicity(self, text: str) -> tuple[float, dict[str, Any]]:
        """Fallback toxicity evaluation using keyword heuristic.

        This is a fallback method used when LangSmith API is unavailable.
        The primary evaluation uses LLM-as-judge via LangSmith.
        """
        # Simple heuristic for fallback
        toxic_keywords = [
            "hate", "kill", "attack", "stupid", "idiot", "moron", "damn", "hell"
        ]

        text_lower = text.lower()
        toxic_count = sum(1 for keyword in toxic_keywords if keyword in text_lower)

        # Score based on number of toxic keywords (normalize to 0-1)
        score = min(toxic_count * 0.2, 1.0)

        details = {
            "toxic_keywords_found": toxic_count,
            "evaluation_method": "keyword_heuristic_fallback",
        }

        logger.debug(f"[LangSmith] Toxicity score (fallback): {score}")
        return score, details

    async def _evaluate_relevance(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Fallback relevance evaluation using word overlap heuristic.

        This is a fallback method used when LangSmith API is unavailable.
        The primary evaluation uses LLM-as-judge via LangSmith.
        """
        if context is None:
            logger.warning("Relevance check requires context, but none provided")
            return 0.0, {"error": "no_context", "evaluation_method": "fallback"}

        # Simple heuristic: check if text contains key terms from context
        context_words = set(context.lower().split())
        text_words = set(text.lower().split())

        overlap = len(context_words.intersection(text_words))
        score = min(overlap / max(len(context_words), 1), 1.0)

        details = {
            "word_overlap": overlap,
            "context_words": len(context_words),
            "text_words": len(text_words),
            "evaluation_method": "word_overlap_fallback",
        }

        logger.debug(f"[LangSmith] Relevance score (fallback): {score}")
        return score, details

    async def _evaluate_accuracy(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Fallback accuracy evaluation.

        This is a fallback method used when LangSmith API is unavailable.
        The primary evaluation uses LLM-as-judge via LangSmith.
        """
        # Note: context parameter available but not used in fallback
        _ = context  # Acknowledge parameter

        # Return moderate score as fallback
        score = 0.5
        details = {
            "evaluation_method": "fallback",
            "note": "Using fallback - primary method uses LLM-as-judge",
        }

        logger.debug(f"[LangSmith] Accuracy score (fallback): {score}")
        return score, details

    async def _evaluate_hallucination(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Fallback hallucination evaluation using claim indicators.

        This is a fallback method used when LangSmith API is unavailable.
        The primary evaluation uses LLM-as-judge via LangSmith.
        """
        # Simple heuristic: check if text makes unsupported claims
        claim_indicators = ["definitely", "certainly", "absolutely", "100%", "guaranteed"]

        text_lower = text.lower()
        claim_count = sum(1 for indicator in claim_indicators if indicator in text_lower)

        # Higher claim count suggests potential hallucination
        score = min(claim_count * 0.3, 1.0)

        details = {
            "claim_indicators_found": claim_count,
            "evaluation_method": "claim_indicator_heuristic_fallback",
        }

        logger.debug(f"[LangSmith] Hallucination score (fallback): {score}")
        return score, details

    async def _evaluate_coherence(self, text: str) -> tuple[float, dict[str, Any]]:
        """Fallback coherence evaluation using sentence structure.

        This is a fallback method used when LangSmith API is unavailable.
        The primary evaluation uses LLM-as-judge via LangSmith.
        """
        # Simple heuristic: check for reasonable sentence structure
        sentences = text.split(".")
        avg_sentence_length = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)

        # Incoherent text often has very short or very long sentences
        if avg_sentence_length < 3 or avg_sentence_length > 50:
            score = 0.7  # Potentially incoherent
        else:
            score = 0.2  # Likely coherent

        details = {
            "avg_sentence_length": avg_sentence_length,
            "sentence_count": len(sentences),
            "evaluation_method": "sentence_structure_heuristic_fallback",
        }

        logger.debug(f"[LangSmith] Coherence score (fallback): {score}")
        return score, details

    async def _evaluate_pii(self, text: str) -> tuple[float, dict[str, Any]]:
        """Fallback PII detection using regex patterns.

        This is a fallback method used when LangSmith API is unavailable.
        The primary evaluation uses LLM-as-judge via LangSmith.
        """
        import re

        # Simple patterns for common PII
        patterns = {
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
            "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
            "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        }

        pii_found = {}
        for pii_type, pattern in patterns.items():
            matches = re.findall(pattern, text)
            if matches:
                pii_found[pii_type] = len(matches)

        # Score based on amount of PII found
        score = min(sum(pii_found.values()) * 0.3, 1.0)

        details = {
            "pii_types_found": pii_found,
            "evaluation_method": "regex_patterns_fallback",
        }

        logger.debug(f"[LangSmith] PII detection score (fallback): {score}")
        return score, details

    async def _evaluate_custom(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Fallback custom evaluator.

        This is a fallback method used when LangSmith API is unavailable.
        The primary evaluation uses LLM-as-judge via LangSmith.
        """
        # Fallback for custom evaluator
        score = 0.5
        details = {
            "custom_evaluator": self.config.custom_evaluator_name,
            "evaluation_method": "fallback",
            "note": "Using fallback - primary method uses LangSmith API",
        }

        logger.debug(f"[LangSmith] Custom evaluation score (fallback): {score}")
        return score, details

    def _build_message(
        self, matched: bool, score: float, details: dict[str, Any]
    ) -> str:
        """Build a human-readable message about the evaluation result.

        Args:
            matched: Whether the threshold was exceeded.
            score: The evaluation score.
            details: Additional details about the evaluation.

        Returns:
            A formatted message string.
        """
        metric_name = self.config.metric.replace("_", " ").title()

        if matched:
            return (
                f"{metric_name} check failed: Score {score:.2f} exceeds "
                f"threshold {self.config.threshold:.2f}"
            )
        else:
            return (
                f"{metric_name} check passed: Score {score:.2f} below "
                f"threshold {self.config.threshold:.2f}"
            )

    def _handle_error(self, error: Exception) -> EvaluatorResult:
        """Handle errors from LangSmith evaluation.

        Args:
            error: The exception that occurred.

        Returns:
            EvaluatorResult indicating error state.
        """
        error_action = self.config.on_error

        return EvaluatorResult(
            matched=(error_action == "deny"),  # Fail closed if configured
            confidence=0.0,
            message=f"LangSmith evaluation error: {str(error)}",
            metadata={
                "error": str(error),
                "error_type": type(error).__name__,
                "metric": self.config.metric,
                "fallback_action": error_action,
            },
        )
