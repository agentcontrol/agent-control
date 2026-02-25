"""Agent Control Models - Shared data models for server and SDK."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agent-control-models")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

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
    EvaluatorResult,
    EvaluatorSpec,
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
from .health import HealthResponse
from .observability import (
    BatchEventsRequest,
    BatchEventsResponse,
    ControlExecutionEvent,
    ControlStats,
    ControlStatsResponse,
    EventQueryRequest,
    EventQueryResponse,
    StatsRequest,
    StatsResponse,
    StatsTotals,
    TimeseriesBucket,
)
from .policy import Policy
from .server import (
    AgentRef,
    AgentSummary,
    ConflictMode,
    ControlSummary,
    CreateEvaluatorConfigRequest,
    DeleteControlResponse,
    DeleteEvaluatorConfigResponse,
    EvaluatorConfigItem,
    EvaluatorSchema,
    GetPolicyControlsResponse,
    InitAgentEvaluatorRemoval,
    InitAgentOverwriteChanges,
    ListAgentsResponse,
    ListControlsResponse,
    ListEvaluatorConfigsResponse,
    PaginationInfo,
    PatchControlRequest,
    PatchControlResponse,
    StepKey,
    UpdateEvaluatorConfigRequest,
    ValidateControlDataRequest,
    ValidateControlDataResponse,
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
    "EvaluatorSpec",
    "EvaluatorResult",
    # Error models
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
    "AgentRef",
    "AgentSummary",
    "ConflictMode",
    "ControlSummary",
    "CreateEvaluatorConfigRequest",
    "DeleteEvaluatorConfigResponse",
    "DeleteControlResponse",
    "EvaluatorConfigItem",
    "EvaluatorSchema",
    "GetPolicyControlsResponse",
    "InitAgentEvaluatorRemoval",
    "InitAgentOverwriteChanges",
    "ListAgentsResponse",
    "ListControlsResponse",
    "ListEvaluatorConfigsResponse",
    "PaginationInfo",
    "PatchControlRequest",
    "PatchControlResponse",
    "StepKey",
    "UpdateEvaluatorConfigRequest",
    "ValidateControlDataRequest",
    "ValidateControlDataResponse",
    # Observability models
    "ControlExecutionEvent",
    "BatchEventsRequest",
    "BatchEventsResponse",
    "EventQueryRequest",
    "EventQueryResponse",
    "ControlStats",
    "ControlStatsResponse",
    "StatsRequest",
    "StatsResponse",
    "StatsTotals",
    "TimeseriesBucket",
]
