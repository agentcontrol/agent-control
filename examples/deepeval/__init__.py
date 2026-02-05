"""DeepEval GEval evaluator example.

This module demonstrates how to extend the base Evaluator class to create
custom evaluators using external libraries like DeepEval.
"""

from config import DeepEvalEvaluatorConfig, DeepEvalTestCaseParam
from evaluator import DeepEvalEvaluator

__all__ = [
    "DeepEvalEvaluator",
    "DeepEvalEvaluatorConfig",
    "DeepEvalTestCaseParam",
]
