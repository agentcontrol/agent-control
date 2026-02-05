"""DeepEval GEval evaluator implementation.

This evaluator demonstrates how to extend the base Evaluator class to integrate
DeepEval's GEval metric for custom LLM-based evaluations.

Based on DeepEval documentation: https://deepeval.com/docs/metrics-llm-evals
"""

import logging
from typing import Any

from agent_control_models import (
    Evaluator,
    EvaluatorMetadata,
    EvaluatorResult,
    register_evaluator,
)

from config import DeepEvalEvaluatorConfig

logger = logging.getLogger(__name__)

# Check if deepeval is available
try:
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCase, LLMTestCaseParams

    DEEPEVAL_AVAILABLE = True
except ImportError:
    DEEPEVAL_AVAILABLE = False
    GEval = None  # type: ignore
    LLMTestCase = None  # type: ignore
    LLMTestCaseParams = None  # type: ignore


@register_evaluator
class DeepEvalEvaluator(Evaluator[DeepEvalEvaluatorConfig]):
    """DeepEval GEval evaluator for custom LLM-based evaluations.

    This evaluator uses DeepEval's GEval metric, which leverages LLM-as-a-judge
    with chain-of-thoughts (CoT) to evaluate LLM outputs based on custom criteria.

    Features:
        - Custom evaluation criteria or step-by-step evaluation logic
        - Multiple test case parameters (input, output, context, etc.)
        - Configurable LLM model for judging
        - Binary or continuous scoring modes
        - Automatic chain-of-thought generation

    Example:
        ```python
        from examples.deepeval import DeepEvalEvaluator, DeepEvalEvaluatorConfig

        # Create config
        config = DeepEvalEvaluatorConfig(
            name="Coherence",
            criteria="Determine if the response is coherent and logically consistent.",
            evaluation_params=["actual_output"],
            threshold=0.7,
            model="gpt-4o",
        )

        # Create evaluator
        evaluator = DeepEvalEvaluator(config)

        # Evaluate
        result = await evaluator.evaluate({
            "actual_output": "The sky is blue because of Rayleigh scattering."
        })
        ```

    Environment Variables:
        OPENAI_API_KEY: Required for GPT model usage.
    """

    metadata = EvaluatorMetadata(
        name="deepeval-geval",
        version="1.0.0",
        description="DeepEval GEval custom LLM-based evaluator",
        requires_api_key=True,
        timeout_ms=30000,
    )
    config_model = DeepEvalEvaluatorConfig

    @classmethod
    def is_available(cls) -> bool:
        """Check if deepeval dependency is installed."""
        return DEEPEVAL_AVAILABLE

    def __init__(self, config: DeepEvalEvaluatorConfig) -> None:
        """Initialize DeepEval evaluator with configuration.

        Args:
            config: Validated DeepEvalEvaluatorConfig instance.

        Raises:
            ValueError: If required configuration is invalid.
        """
        super().__init__(config)

        # Create the GEval metric instance (immutable, safe for instance caching)
        self._metric = self._create_geval_metric()

    def _create_geval_metric(self) -> Any:
        """Create and configure the GEval metric.

        Returns:
            Configured GEval metric instance.
        """
        # Convert string evaluation params to LLMTestCaseParams enum
        evaluation_params = [
            getattr(LLMTestCaseParams, param.upper())
            for param in self.config.evaluation_params
        ]

        # Build GEval kwargs
        geval_kwargs = {
            "name": self.config.name,
            "evaluation_params": evaluation_params,
            "threshold": self.config.threshold,
            "model": self.config.model,
            "strict_mode": self.config.strict_mode,
            "async_mode": self.config.async_mode,
            "verbose_mode": self.config.verbose_mode,
        }

        # Add either criteria or evaluation_steps
        if self.config.criteria:
            geval_kwargs["criteria"] = self.config.criteria
        elif self.config.evaluation_steps:
            geval_kwargs["evaluation_steps"] = self.config.evaluation_steps

        logger.debug(f"[DeepEval] Creating GEval metric with config: {geval_kwargs}")
        return GEval(**geval_kwargs)

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Evaluate data using DeepEval GEval.

        Args:
            data: The data to evaluate. Should be a dict with keys matching
                  the evaluation_params (e.g., {"actual_output": "text"}).

        Returns:
            EvaluatorResult with matched status and metadata.
        """
        try:
            logger.debug(f"[DeepEval] Evaluating data: {data}")

            # Prepare test case from data
            test_case = self._prepare_test_case(data)

            # Run the GEval metric
            if self.config.async_mode:
                await self._metric.a_measure(test_case)
            else:
                self._metric.measure(test_case)

            # Parse the results
            result = self._parse_metric_result()

            logger.debug(
                f"[DeepEval] Evaluation complete: matched={result.matched}, "
                f"score={result.confidence}, reason={result.message}"
            )

            return result

        except Exception as e:
            logger.error(f"DeepEval evaluation error: {e}", exc_info=True)
            return self._handle_error(e)

    def _prepare_test_case(self, data: Any) -> Any:
        """Prepare LLMTestCase from input data.

        Args:
            data: Input data dict with test case parameters.
                 May contain: input, output, question, actual_output, etc.

        Returns:
            LLMTestCase instance.
        """
        # Handle both dict and string inputs
        if isinstance(data, str):
            # If data is a string, treat it as actual_output by default
            data = {"actual_output": data}
        elif not isinstance(data, dict):
            data = {"actual_output": str(data)}

        # Map agent-control data structure to DeepEval LLMTestCase parameters
        # Agent-control may provide: {"input": {...}, "output": "..."}
        # DeepEval expects: {"input": "...", "actual_output": "..."}
        mapped_data = {}

        # Handle output mapping
        if "actual_output" in data:
            mapped_data["actual_output"] = data["actual_output"]
        elif "output" in data:
            mapped_data["actual_output"] = data["output"]

        # Handle input mapping
        if "input" in data:
            input_val = data["input"]
            # If input is a dict (e.g., function arguments), extract the question
            if isinstance(input_val, dict):
                # Try common field names
                mapped_data["input"] = (
                    input_val.get("question") or
                    input_val.get("query") or
                    input_val.get("prompt") or
                    str(input_val)
                )
            else:
                mapped_data["input"] = str(input_val)
        elif "question" in data:
            mapped_data["input"] = data["question"]

        # Handle other DeepEval parameters
        for key in ["expected_output", "context", "retrieval_context", "tools"]:
            if key in data:
                mapped_data[key] = data[key]

        # Build test case kwargs
        # Note: LLMTestCase requires 'input' and 'actual_output' as mandatory fields
        # So we always provide them, even if not in evaluation_params
        test_case_kwargs = {}

        # Always include mandatory fields for LLMTestCase
        test_case_kwargs["input"] = mapped_data.get("input", "")
        test_case_kwargs["actual_output"] = mapped_data.get("actual_output", "")

        # Add any additional params from evaluation_params
        for param in self.config.evaluation_params:
            if param not in test_case_kwargs:  # Skip if already added above
                if param in mapped_data:
                    test_case_kwargs[param] = mapped_data[param]
                else:
                    logger.warning(f"[DeepEval] Missing parameter '{param}', using empty string")
                    test_case_kwargs[param] = ""

        logger.debug(f"[DeepEval] Original data keys: {list(data.keys())}")
        logger.debug(f"[DeepEval] Mapped data keys: {list(mapped_data.keys())}")
        logger.debug(f"[DeepEval] Test case kwargs: {test_case_kwargs}")
        return LLMTestCase(**test_case_kwargs)

    def _parse_metric_result(self) -> EvaluatorResult:
        """Parse GEval metric results into EvaluatorResult.

        Returns:
            EvaluatorResult with evaluation results.
        """
        # Get score and reason from the metric
        score = self._metric.score
        reason = self._metric.reason
        is_successful = self._metric.is_successful()

        # NOTE: matched=True means the control should trigger (block the request)
        # In DeepEval, is_successful=True means quality is GOOD (score >= threshold)
        # So we want to trigger (matched=True) when quality is BAD (not is_successful)
        return EvaluatorResult(
            matched=not is_successful,  # Invert: trigger when quality fails
            confidence=score if score is not None else 0.0,
            message=reason if reason else f"GEval {self.config.name}: score={score}",
            metadata={
                "metric_name": self.config.name,
                "score": score,
                "threshold": self.config.threshold,
                "model": self.config.model,
                "strict_mode": self.config.strict_mode,
                **(self.config.metadata or {}),
            },
        )

    def _handle_error(self, error: Exception) -> EvaluatorResult:
        """Handle errors from DeepEval evaluation.

        Args:
            error: The exception that occurred.

        Returns:
            EvaluatorResult indicating error state.
        """
        error_action = self.config.on_error

        return EvaluatorResult(
            matched=(error_action == "deny"),  # Fail closed if configured
            confidence=0.0,
            message=f"DeepEval evaluation error: {str(error)}",
            metadata={
                "error": str(error),
                "error_type": type(error).__name__,
                "metric_name": self.config.name,
                "fallback_action": error_action,
            },
        )
