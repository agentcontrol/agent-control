"""Agent Control Models - Shared data models for server and SDK."""

__version__ = "0.1.0"

from .agent import (
    BUILTIN_STEP_TYPES,
    STEP_TYPE_LLM,
    STEP_TYPE_TOOL,
    Agent,
    JSONObject,
    JSONValue,
    Step,
    StepSchema,
)
from .controls import (
    ControlAction,
    ControlDefinition,
    ControlMatch,
    ControlScope,
    ControlSelector,
    EvaluatorConfig,
    EvaluatorResult,
    JSONEvaluatorConfig,
    ListEvaluatorConfig,
    RegexEvaluatorConfig,
    SQLEvaluatorConfig,
)
from .errors import (
    ERROR_TITLES,
    ErrorCode,
    ErrorDetails,
    ErrorMetadata,
    ErrorReason,
    ProblemDetail,
    ValidationErrorItem,
    get_error_title,
    make_error_type,
)
from .evaluation import (
    EvaluationRequest,
    EvaluationResponse,
    EvaluationResult,
)
from .evaluator import (
    Evaluator,
    EvaluatorMetadata,
    clear_evaluators,
    get_all_evaluators,
    get_evaluator,
    register_evaluator,
)
from .health import HealthResponse
from .observability import (
    BatchEventsRequest,
    BatchEventsResponse,
    ControlExecutionEvent,
    ControlStats,
    EventQueryRequest,
    EventQueryResponse,
    StatsRequest,
    StatsResponse,
)
from .policy import Policy
from .server import (
    AgentSummary,
    ControlSummary,
    CreateEvaluatorConfigRequest,
    DeleteControlResponse,
    DeleteEvaluatorConfigResponse,
    EvaluatorConfigItem,
    EvaluatorSchema,
    GetPolicyControlsResponse,
    ListAgentsResponse,
    ListControlsResponse,
    ListEvaluatorConfigsResponse,
    PaginationInfo,
    PatchControlRequest,
    PatchControlResponse,
    StepKey,
    UpdateEvaluatorConfigRequest,
)

__all__ = [
    # Health
    "HealthResponse",
    # Agent
    "Agent",
    "StepSchema",
    "JSONValue",
    "JSONObject",
    "Step",
    "STEP_TYPE_TOOL",
    "STEP_TYPE_LLM",
    "BUILTIN_STEP_TYPES",
    # Policy
    "Policy",
    # Evaluation
    "EvaluationRequest",
    "EvaluationResponse",
    "EvaluationResult",
    # Controls
    "ControlDefinition",
    "ControlAction",
    "ControlMatch",
    "ControlScope",
    "ControlSelector",
    "EvaluatorConfig",
    "EvaluatorResult",
    # Evaluator configs
    "JSONEvaluatorConfig",
    "ListEvaluatorConfig",
    "RegexEvaluatorConfig",
    "SQLEvaluatorConfig",
    # Evaluator system
    "Evaluator",
    "EvaluatorMetadata",
    "register_evaluator",
    "get_evaluator",
    "get_all_evaluators",
    "clear_evaluators",
    # Error models (RFC 7807 / Kubernetes / GitHub-style)
    "ProblemDetail",
    "ErrorCode",
    "ErrorReason",
    "ErrorDetails",
    "ErrorMetadata",
    "ValidationErrorItem",
    "make_error_type",
    "get_error_title",
    "ERROR_TITLES",
    # Server models
    "AgentSummary",
    "ControlSummary",
    "CreateEvaluatorConfigRequest",
    "DeleteEvaluatorConfigResponse",
    "DeleteControlResponse",
    "EvaluatorConfigItem",
    "EvaluatorSchema",
    "GetPolicyControlsResponse",
    "ListAgentsResponse",
    "ListControlsResponse",
    "ListEvaluatorConfigsResponse",
    "PaginationInfo",
    "PatchControlRequest",
    "PatchControlResponse",
    "StepKey",
    "UpdateEvaluatorConfigRequest",
    # Observability models
    "ControlExecutionEvent",
    "BatchEventsRequest",
    "BatchEventsResponse",
    "EventQueryRequest",
    "EventQueryResponse",
    "ControlStats",
    "StatsRequest",
    "StatsResponse",
]
