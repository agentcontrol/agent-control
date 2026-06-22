"""DeepEval GEval rule example.

This module demonstrates how to extend the base Rule class to create
custom rules using external libraries like DeepEval.
"""

from config import DeepEvalRuleConfig, DeepEvalTestCaseParam
from rule import DeepEvalRule

__all__ = [
    "DeepEvalRule",
    "DeepEvalRuleConfig",
    "DeepEvalTestCaseParam",
]
