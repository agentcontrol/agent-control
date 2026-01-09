package agentcontrol

import (
	"context"
	"net/http"

	"github.com/google/uuid"
)

// Evaluate checks if an agent interaction is safe according to assigned controls.
//
// This is the main method for runtime control evaluation. It sends the tool call
// or LLM call to the server, which evaluates it against all controls assigned
// to the agent via its policy.
//
// The check_stage parameter determines when the check is performed:
//   - PreCheck ("pre"): Before the tool/LLM execution
//   - PostCheck ("post"): After the tool/LLM execution
//
// Example (pre-check before tool execution):
//
//	client := agentcontrol.NewClient()
//
//	toolCall := agentcontrol.ToolCall{
//	    ToolName: "search_database",
//	    Arguments: map[string]interface{}{
//	        "query": "SELECT * FROM users",
//	    },
//	}
//
//	result, err := client.Evaluate(ctx, agentUUID, toolCall, agentcontrol.PreCheck)
//	if err != nil {
//	    log.Fatal(err)
//	}
//
//	if !result.IsSafe {
//	    fmt.Printf("Action blocked: %s\n", result.Reason)
//	    return
//	}
//
// Example (post-check after LLM response):
//
//	llmCall := agentcontrol.LlmCall{
//	    Input:  "What is the user's SSN?",
//	    Output: "The user's SSN is 123-45-6789",
//	}
//
//	result, err := client.Evaluate(ctx, agentUUID, llmCall, agentcontrol.PostCheck)
func (c *Client) Evaluate(ctx context.Context, agentUUID uuid.UUID, payload interface{}, stage CheckStage) (*EvaluationResponse, error) {
	req := EvaluationRequest{
		AgentUUID:  agentUUID,
		Payload:    payload,
		CheckStage: stage,
	}

	var result EvaluationResponse
	if err := c.doRequest(ctx, http.MethodPost, "/api/v1/evaluation", req, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

// EvaluateToolCall is a convenience method for evaluating tool calls.
//
// Example:
//
//	result, err := client.EvaluateToolCall(ctx, agentUUID, "search", args, agentcontrol.PreCheck)
func (c *Client) EvaluateToolCall(ctx context.Context, agentUUID uuid.UUID, toolName string, arguments map[string]interface{}, stage CheckStage) (*EvaluationResponse, error) {
	toolCall := ToolCall{
		ToolName:  toolName,
		Arguments: arguments,
	}
	return c.Evaluate(ctx, agentUUID, toolCall, stage)
}

// EvaluateToolCallWithOutput is a convenience method for post-check evaluation with output.
//
// Example:
//
//	result, err := client.EvaluateToolCallWithOutput(ctx, agentUUID, "search", args, output)
func (c *Client) EvaluateToolCallWithOutput(ctx context.Context, agentUUID uuid.UUID, toolName string, arguments map[string]interface{}, output interface{}) (*EvaluationResponse, error) {
	toolCall := ToolCall{
		ToolName:  toolName,
		Arguments: arguments,
		Output:    output,
	}
	return c.Evaluate(ctx, agentUUID, toolCall, PostCheck)
}

// EvaluateLlmCall is a convenience method for evaluating LLM calls.
//
// Example:
//
//	result, err := client.EvaluateLlmCall(ctx, agentUUID, "What is 2+2?", agentcontrol.PreCheck)
func (c *Client) EvaluateLlmCall(ctx context.Context, agentUUID uuid.UUID, input interface{}, stage CheckStage) (*EvaluationResponse, error) {
	llmCall := LlmCall{
		Input: input,
	}
	return c.Evaluate(ctx, agentUUID, llmCall, stage)
}

// EvaluateLlmCallWithOutput is a convenience method for post-check evaluation with output.
//
// Example:
//
//	result, err := client.EvaluateLlmCallWithOutput(ctx, agentUUID, "What is 2+2?", "4")
func (c *Client) EvaluateLlmCallWithOutput(ctx context.Context, agentUUID uuid.UUID, input, output interface{}) (*EvaluationResponse, error) {
	llmCall := LlmCall{
		Input:  input,
		Output: output,
	}
	return c.Evaluate(ctx, agentUUID, llmCall, PostCheck)
}
