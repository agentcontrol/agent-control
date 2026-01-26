"""Agent Control Models - Shared data models for server and SDK."""

__version__ = "0.1.0"

from .agent import (
    BUILTIN_STEP_TYPES,
    STEP_TYPE_LLM_INFERENCE,
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
    JSONControlEvaluatorPluginConfig,
    ListConfig,
    RegexConfig,
    SQLControlEvaluatorPluginConfig,
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
    EventQueryRequest,
    EventQueryResponse,
    StatsRequest,
    StatsResponse,
)
from .plugin import (
    PluginEvaluator,
    PluginMetadata,
    clear_plugins,
    get_all_plugins,
    get_plugin,
    register_plugin,
)
from .policy import Policy
from .server import (
    AgentSummary,
    ControlSummary,
    DeleteControlResponse,
    EvaluatorSchema,
    GetPolicyControlsResponse,
    ListAgentsResponse,
    ListControlsResponse,
    PaginationInfo,
    PatchControlRequest,
    PatchControlResponse,
    StepKey,
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
    "STEP_TYPE_LLM_INFERENCE",
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
    # Plugin configs
    "JSONControlEvaluatorPluginConfig",
    "ListConfig",
    "RegexConfig",
    "SQLControlEvaluatorPluginConfig",
    # Plugin system
    "PluginEvaluator",
    "PluginMetadata",
    "register_plugin",
    "get_plugin",
    "get_all_plugins",
    "clear_plugins",
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
    "DeleteControlResponse",
    "EvaluatorSchema",
    "GetPolicyControlsResponse",
    "ListAgentsResponse",
    "ListControlsResponse",
    "PaginationInfo",
    "PatchControlRequest",
    "PatchControlResponse",
    "StepKey",
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
