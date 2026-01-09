// Package agentcontrol provides a Go client for the Agent Control API.
//
// Agent Control is a runtime guardrailing system for AI agents that enables
// policy-based control over agent actions (tool calls, LLM calls) without
// requiring code changes.
package agentcontrol

import (
	"github.com/google/uuid"
)

// Agent represents agent metadata for registration and tracking.
type Agent struct {
	ID          uuid.UUID              `json:"agent_id"`
	Name        string                 `json:"agent_name"`
	Description string                 `json:"agent_description,omitempty"`
	Version     string                 `json:"agent_version,omitempty"`
	Metadata    map[string]interface{} `json:"agent_metadata,omitempty"`
}

// AgentTool represents a tool schema for agent capabilities.
type AgentTool struct {
	Name         string                 `json:"tool_name"`
	Arguments    map[string]interface{} `json:"arguments"`
	OutputSchema map[string]interface{} `json:"output_schema"`
}

// EvaluatorSchema represents a custom evaluator registered with an agent.
type EvaluatorSchema struct {
	Name         string                 `json:"name"`
	ConfigSchema map[string]interface{} `json:"config_schema,omitempty"`
	Description  string                 `json:"description,omitempty"`
}

// ToolCall represents a tool invocation by the agent.
type ToolCall struct {
	ToolName  string                 `json:"tool_name"`
	Arguments map[string]interface{} `json:"arguments"`
	Output    interface{}            `json:"output,omitempty"`
	Context   map[string]interface{} `json:"context,omitempty"`
}

// LlmCall represents an LLM interaction by the agent.
type LlmCall struct {
	Input   interface{}            `json:"input"`
	Output  interface{}            `json:"output,omitempty"`
	Context map[string]interface{} `json:"context,omitempty"`
}

// CheckStage indicates when to execute a control check.
type CheckStage string

const (
	// PreCheck runs before the tool/LLM execution.
	PreCheck CheckStage = "pre"
	// PostCheck runs after the tool/LLM execution.
	PostCheck CheckStage = "post"
)

// EvaluationRequest is the request model for control evaluation.
type EvaluationRequest struct {
	AgentUUID  uuid.UUID  `json:"agent_uuid"`
	Payload    interface{} `json:"payload"` // ToolCall or LlmCall
	CheckStage CheckStage `json:"check_stage"`
}

// EvaluatorResult contains the result from a control evaluator.
type EvaluatorResult struct {
	Matched    bool                   `json:"matched"`
	Confidence float64                `json:"confidence"`
	Message    string                 `json:"message,omitempty"`
	Metadata   map[string]interface{} `json:"metadata,omitempty"`
	Error      string                 `json:"error,omitempty"`
}

// ControlMatch represents a control that matched during evaluation.
type ControlMatch struct {
	ControlID   int             `json:"control_id"`
	ControlName string          `json:"control_name"`
	Action      string          `json:"action"` // "allow", "deny", "warn", "log"
	Result      EvaluatorResult `json:"result"`
}

// EvaluationResponse is the response from control evaluation.
type EvaluationResponse struct {
	IsSafe     bool           `json:"is_safe"`
	Confidence float64        `json:"confidence"`
	Reason     string         `json:"reason,omitempty"`
	Matches    []ControlMatch `json:"matches,omitempty"`
	Errors     []ControlMatch `json:"errors,omitempty"`
}

// IsConfident checks if the result confidence exceeds a threshold.
func (r *EvaluationResponse) IsConfident(threshold float64) bool {
	return r.Confidence >= threshold
}

// Control represents a control definition with identity.
type Control struct {
	ID      int                    `json:"id"`
	Name    string                 `json:"name"`
	Control map[string]interface{} `json:"control"`
}

// InitAgentRequest is the request to initialize or update an agent.
type InitAgentRequest struct {
	Agent        Agent             `json:"agent"`
	Tools        []AgentTool       `json:"tools,omitempty"`
	Evaluators   []EvaluatorSchema `json:"evaluators,omitempty"`
	ForceReplace bool              `json:"force_replace,omitempty"`
}

// InitAgentResponse is the response from agent initialization.
type InitAgentResponse struct {
	Created  bool      `json:"created"`
	Controls []Control `json:"controls,omitempty"`
}

// GetAgentResponse contains agent details and registered tools.
type GetAgentResponse struct {
	Agent      Agent             `json:"agent"`
	Tools      []AgentTool       `json:"tools"`
	Evaluators []EvaluatorSchema `json:"evaluators,omitempty"`
}

// HealthResponse contains the health check response.
type HealthResponse struct {
	Status string `json:"status"`
}
