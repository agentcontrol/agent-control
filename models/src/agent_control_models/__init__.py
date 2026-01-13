"""Agent Control Models - Shared data models for server and SDK."""

__version__ = "0.1.0"

from .agent import Agent, AgentContext, AgentTool, LlmCall, ToolCall
from .controls import (
    ControlAction,
    ControlDefinition,
    ControlMatch,
    ControlSelector,
    EvaluatorConfig,
    EvaluatorResult,
    ListConfig,
    RegexConfig,
)
from .evaluation import (
    EvaluationRequest,
    EvaluationResponse,
    EvaluationResult,
)
from .health import HealthResponse
from .plugin import (
    PluginEvaluator,
    PluginMetadata,
    clear_plugins,
    get_plugin,
    list_plugins,
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
)

__all__ = [
    # Health
    "HealthResponse",
    # Agent
    "Agent",
    "AgentTool",
    "AgentContext",
    "LlmCall",
    "ToolCall",
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
    "ControlSelector",
    "EvaluatorConfig",
    "EvaluatorResult",
    # Plugin configs
    "RegexConfig",
    "ListConfig",
    # Plugin system
    "PluginEvaluator",
    "PluginMetadata",
    "register_plugin",
    "get_plugin",
    "list_plugins",
    "clear_plugins",
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
]

