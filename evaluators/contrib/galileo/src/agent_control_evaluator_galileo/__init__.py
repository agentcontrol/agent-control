"""Agent Control Evaluator - Galileo.

This package provides Galileo evaluators for agent-control.

Available evaluators:
    - galileo.luna: Galileo Luna direct scorer evaluation
    - galileo.llm:  Galileo LLM-as-judge direct scorer evaluation

Installation:
    pip install agent-control-evaluator-galileo

Or via the agent-control-evaluators convenience extra:
    pip install agent-control-evaluators[galileo]
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-evaluator-galileo")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

try:
    from agent_control_evaluator_galileo.llm import (
        LLM_AVAILABLE,
        GalileoLLMClient,
        LlmEvaluator,
        LlmEvaluatorConfig,
        LlmOperator,
    )
except ImportError:
    LLM_AVAILABLE = False  # type: ignore[assignment]
    GalileoLLMClient = None  # type: ignore[assignment,misc]
    LlmEvaluator = None  # type: ignore[assignment,misc]
    LlmEvaluatorConfig = None  # type: ignore[assignment]
    LlmOperator = None  # type: ignore[assignment]
from agent_control_evaluator_galileo.luna import (
    LUNA_AVAILABLE,
    GalileoLunaClient,
    LunaEvaluator,
    LunaEvaluatorConfig,
    LunaOperator,
    ScorerInvokeConfig,
    ScorerInvokeRecord,
    ScorerInvokeRequest,
    ScorerInvokeResponse,
)
from agent_control_evaluator_galileo.records import (
    GalileoRecord,
    GalileoRecordNormalizer,
    RecordFactoryError,
    UnsupportedStepTypeError,
    build_galileo_record,
    build_record,
    record_from_step,
)

__all__ = [
    # luna
    "GalileoLunaClient",
    "ScorerInvokeRequest",
    "ScorerInvokeConfig",
    "ScorerInvokeRecord",
    "ScorerInvokeResponse",
    "LunaEvaluator",
    "LunaEvaluatorConfig",
    "LunaOperator",
    "LUNA_AVAILABLE",
    # llm
    "GalileoLLMClient",
    "LlmEvaluator",
    "LlmEvaluatorConfig",
    "LlmOperator",
    "LLM_AVAILABLE",
    # records
    "GalileoRecord",
    "GalileoRecordNormalizer",
    "RecordFactoryError",
    "UnsupportedStepTypeError",
    "build_galileo_record",
    "build_record",
    "record_from_step",
]
