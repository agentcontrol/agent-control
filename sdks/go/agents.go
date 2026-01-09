package agentcontrol

import (
	"context"
	"fmt"
	"net/http"

	"github.com/google/uuid"
)

// InitAgent registers or updates an agent with the server.
//
// This is the primary way to register an agent and its tools with Agent Control.
// If the agent already exists, it will be updated with the new information.
//
// Example:
//
//	client := agentcontrol.NewClient()
//
//	agent := agentcontrol.Agent{
//	    ID:          uuid.New(),
//	    Name:        "my-agent",
//	    Description: "My AI agent",
//	    Version:     "1.0.0",
//	}
//
//	tools := []agentcontrol.AgentTool{
//	    {
//	        Name: "search",
//	        Arguments: map[string]interface{}{
//	            "query": map[string]interface{}{"type": "string"},
//	        },
//	        OutputSchema: map[string]interface{}{
//	            "results": map[string]interface{}{"type": "array"},
//	        },
//	    },
//	}
//
//	resp, err := client.InitAgent(ctx, agent, tools, nil)
//	if err != nil {
//	    log.Fatal(err)
//	}
//	fmt.Printf("Created: %v, Controls: %d\n", resp.Created, len(resp.Controls))
func (c *Client) InitAgent(ctx context.Context, agent Agent, tools []AgentTool, evaluators []EvaluatorSchema) (*InitAgentResponse, error) {
	req := InitAgentRequest{
		Agent:      agent,
		Tools:      tools,
		Evaluators: evaluators,
	}

	var result InitAgentResponse
	if err := c.doRequest(ctx, http.MethodPost, "/api/v1/agents/initAgent", req, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

// GetAgent retrieves agent details by UUID.
//
// Example:
//
//	agent, err := client.GetAgent(ctx, agentUUID)
//	if err != nil {
//	    if apiErr, ok := err.(*agentcontrol.APIError); ok && apiErr.IsNotFound() {
//	        fmt.Println("Agent not found")
//	    }
//	}
func (c *Client) GetAgent(ctx context.Context, agentID uuid.UUID) (*GetAgentResponse, error) {
	var result GetAgentResponse
	path := fmt.Sprintf("/api/v1/agents/%s", agentID.String())
	if err := c.doRequest(ctx, http.MethodGet, path, nil, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

// GetAgentControls retrieves the controls assigned to an agent via its policy.
//
// Example:
//
//	controls, err := client.GetAgentControls(ctx, agentUUID)
//	for _, ctrl := range controls {
//	    fmt.Printf("Control: %s (ID: %d)\n", ctrl.Name, ctrl.ID)
//	}
func (c *Client) GetAgentControls(ctx context.Context, agentID uuid.UUID) ([]Control, error) {
	var result struct {
		Controls []Control `json:"controls"`
	}
	path := fmt.Sprintf("/api/v1/agents/%s/controls", agentID.String())
	if err := c.doRequest(ctx, http.MethodGet, path, nil, &result); err != nil {
		return nil, err
	}
	return result.Controls, nil
}
