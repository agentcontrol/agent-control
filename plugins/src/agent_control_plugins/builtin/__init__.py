"""Built-in plugins for agent-control.

These plugins are automatically registered when this module is imported.
"""

from .json import JSONControlEvaluatorPlugin
from .list import ListControlEvaluatorPlugin
from .regex import RegexControlEvaluatorPlugin
from .sql import SQLControlEvaluatorPlugin

__all__ = ["JSONControlEvaluatorPlugin", "ListControlEvaluatorPlugin", "RegexControlEvaluatorPlugin", "SQLControlEvaluatorPlugin"]
