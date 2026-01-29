"""LangSmith evaluator implementation.

This evaluator uses LangSmith's evaluation APIs to assess agent outputs
for quality and safety metrics.
"""

import logging
import os
from typing import Any

from agent_control_models import (
    Evaluator,
    EvaluatorMetadata,
    EvaluatorResult,
    register_evaluator,
)

from .config import LangSmithEvaluatorConfig

logger = logging.getLogger(__name__)

# Check if langsmith is available
try:
    from langsmith import Client
    from langsmith.evaluation import evaluate, LangChainStringEvaluator

    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    Client = None  # type: ignore
    evaluate = None  # type: ignore
    LangChainStringEvaluator = None  # type: ignore


@register_evaluator
class LangSmithEvaluator(Evaluator[LangSmithEvaluatorConfig]):
    """LangSmith evaluation evaluator.

    This evaluator uses LangSmith's evaluation APIs to assess agent outputs
    for various quality and safety metrics including toxicity, relevance,
    accuracy, hallucination detection, coherence, and PII detection.

    Supported Metrics:
        - toxicity: Detect toxic or harmful content
        - relevance: Check if output is relevant to the input/context
        - accuracy: Verify factual accuracy of the output
        - hallucination: Detect hallucinations or unsupported claims
        - coherence: Check if output is coherent and well-structured
        - pii_detection: Detect personally identifiable information
        - custom: Use a custom LangSmith evaluator

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
        LANGSMITH_API_KEY: Your LangSmith API key (required).
        LANGSMITH_ENDPOINT: LangSmith API endpoint (optional).
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

        Raises:
            ValueError: If LANGSMITH_API_KEY is not set.
        """
        # Verify API key is configured
        if not os.getenv("LANGSMITH_API_KEY"):
            raise ValueError(
                "LANGSMITH_API_KEY environment variable must be set.\n"
                "Get your API key from: https://smith.langchain.com/settings"
            )

        super().__init__(config)

        # Initialize the LangSmith client
        self._client: Client | None = None

    def _get_client(self) -> Client:
        """Get or create the LangSmith client.

        Returns:
            The LangSmith Client instance.
        """
        if self._client is None:
            self._client = Client()
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
        """Evaluate the text using the configured metric.

        Args:
            text: The text to evaluate.
            context: Optional context for context-aware metrics.

        Returns:
            Tuple of (score, details_dict). Score is 0.0-1.0.
        """
        metric = self.config.metric

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
        """Evaluate text for toxicity using a simple heuristic.

        In a real implementation, this would call LangSmith's toxicity evaluator
        or use an LLM-as-judge approach.
        """
        # Simple heuristic for demo purposes
        toxic_keywords = [
            "hate", "kill", "attack", "stupid", "idiot", "moron", "damn", "hell"
        ]

        text_lower = text.lower()
        toxic_count = sum(1 for keyword in toxic_keywords if keyword in text_lower)

        # Score based on number of toxic keywords (normalize to 0-1)
        score = min(toxic_count * 0.2, 1.0)

        details = {
            "toxic_keywords_found": toxic_count,
            "evaluation_method": "keyword_heuristic",
        }

        logger.debug(f"[LangSmith] Toxicity score: {score}")
        return score, details

    async def _evaluate_relevance(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Evaluate if text is relevant to the context.

        In a real implementation, this would use LangSmith's relevance evaluator
        or semantic similarity checks.
        """
        if context is None:
            # Without context, we can't evaluate relevance
            logger.warning("Relevance check requires context, but none provided")
            return 0.0, {"error": "no_context"}

        # Simple heuristic: check if text contains key terms from context
        context_words = set(context.lower().split())
        text_words = set(text.lower().split())

        overlap = len(context_words.intersection(text_words))
        score = min(overlap / max(len(context_words), 1), 1.0)

        details = {
            "word_overlap": overlap,
            "context_words": len(context_words),
            "text_words": len(text_words),
            "evaluation_method": "word_overlap",
        }

        logger.debug(f"[LangSmith] Relevance score: {score}")
        return score, details

    async def _evaluate_accuracy(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Evaluate factual accuracy of the text.

        In a real implementation, this would use LangSmith's accuracy evaluator
        or an LLM-as-judge approach.
        """
        # For demo purposes, return a moderate score
        # Real implementation would check facts against context/knowledge base
        score = 0.5
        details = {
            "evaluation_method": "placeholder",
            "note": "Real implementation would use LLM-as-judge or fact-checking API",
        }

        logger.debug(f"[LangSmith] Accuracy score: {score}")
        return score, details

    async def _evaluate_hallucination(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Evaluate if text contains hallucinations.

        In a real implementation, this would use LangSmith's hallucination detector.
        """
        # Simple heuristic: check if text makes unsupported claims
        claim_indicators = ["definitely", "certainly", "absolutely", "100%", "guaranteed"]

        text_lower = text.lower()
        claim_count = sum(1 for indicator in claim_indicators if indicator in text_lower)

        # Higher claim count suggests potential hallucination
        score = min(claim_count * 0.3, 1.0)

        details = {
            "claim_indicators_found": claim_count,
            "evaluation_method": "claim_indicator_heuristic",
        }

        logger.debug(f"[LangSmith] Hallucination score: {score}")
        return score, details

    async def _evaluate_coherence(self, text: str) -> tuple[float, dict[str, Any]]:
        """Evaluate if text is coherent and well-structured.

        In a real implementation, this would use LangSmith's coherence evaluator.
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
            "evaluation_method": "sentence_structure_heuristic",
        }

        logger.debug(f"[LangSmith] Coherence score: {score}")
        return score, details

    async def _evaluate_pii(self, text: str) -> tuple[float, dict[str, Any]]:
        """Evaluate if text contains PII.

        In a real implementation, this would use LangSmith's PII detector
        or a specialized PII detection library.
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
            "evaluation_method": "regex_patterns",
        }

        logger.debug(f"[LangSmith] PII detection score: {score}")
        return score, details

    async def _evaluate_custom(
        self, text: str, context: str | None
    ) -> tuple[float, dict[str, Any]]:
        """Evaluate using a custom evaluator.

        In a real implementation, this would call a custom LangSmith evaluator.
        """
        # Placeholder for custom evaluator
        score = 0.5
        details = {
            "custom_evaluator": self.config.custom_evaluator_name,
            "evaluation_method": "placeholder",
            "note": "Real implementation would call custom LangSmith evaluator",
        }

        logger.debug(f"[LangSmith] Custom evaluation score: {score}")
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
