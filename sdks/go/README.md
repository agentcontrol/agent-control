# Agent Control Go SDK

Go client library for the Agent Control API. This SDK provides a simple interface for integrating AI agents with Agent Control's runtime guardrailing system.

## Installation

```bash
go get github.com/rungalileo/agent-control/sdks/go
```

## Quick Start

```go
package main

import (
    "context"
    "fmt"
    "log"

    agentcontrol "github.com/rungalileo/agent-control/sdks/go"
    "github.com/google/uuid"
)

func main() {
    ctx := context.Background()

    // Create client (uses localhost:8000 by default)
    client := agentcontrol.NewClient()

    // Check server health
    health, err := client.HealthCheck(ctx)
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Server status: %s\n", health.Status)

    // Register an agent
    agent := agentcontrol.Agent{
        ID:          uuid.New(),
        Name:        "my-agent",
        Description: "My AI assistant",
        Version:     "1.0.0",
    }

    tools := []agentcontrol.AgentTool{
        {
            Name: "search_database",
            Arguments: map[string]interface{}{
                "query": map[string]interface{}{"type": "string"},
            },
            OutputSchema: map[string]interface{}{
                "results": map[string]interface{}{"type": "array"},
            },
        },
    }

    initResp, err := client.InitAgent(ctx, agent, tools, nil)
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Agent registered (created: %v)\n", initResp.Created)

    // Evaluate a tool call before execution
    result, err := client.EvaluateToolCall(
        ctx,
        agent.ID,
        "search_database",
        map[string]interface{}{"query": "SELECT * FROM users"},
        agentcontrol.PreCheck,
    )
    if err != nil {
        log.Fatal(err)
    }

    if result.IsSafe {
        fmt.Println("Tool call is safe, proceeding...")
    } else {
        fmt.Printf("Tool call blocked: %s\n", result.Reason)
    }
}
```

## Configuration

### Client Options

```go
// Custom base URL
client := agentcontrol.NewClient(
    agentcontrol.WithBaseURL("https://agent-control.example.com"),
)

// Custom timeout
client := agentcontrol.NewClient(
    agentcontrol.WithTimeout(60 * time.Second),
)

// API key authentication
client := agentcontrol.NewClient(
    agentcontrol.WithAPIKey("your-api-key"),
)

// Or use environment variable
os.Setenv("AGENT_CONTROL_API_KEY", "your-api-key")
client := agentcontrol.NewClient()
```

## API Reference

### Agent Registration

```go
// Register or update an agent
resp, err := client.InitAgent(ctx, agent, tools, evaluators)

// Get agent details
agent, err := client.GetAgent(ctx, agentUUID)

// Get controls assigned to agent
controls, err := client.GetAgentControls(ctx, agentUUID)
```

### Evaluation

```go
// Evaluate any payload (ToolCall or LlmCall)
result, err := client.Evaluate(ctx, agentUUID, payload, stage)

// Convenience methods for tool calls
result, err := client.EvaluateToolCall(ctx, agentUUID, "tool_name", args, agentcontrol.PreCheck)
result, err := client.EvaluateToolCallWithOutput(ctx, agentUUID, "tool_name", args, output)

// Convenience methods for LLM calls
result, err := client.EvaluateLlmCall(ctx, agentUUID, input, agentcontrol.PreCheck)
result, err := client.EvaluateLlmCallWithOutput(ctx, agentUUID, input, output)
```

### Check Stages

- `agentcontrol.PreCheck` - Evaluate before execution
- `agentcontrol.PostCheck` - Evaluate after execution (includes output)

### Error Handling

```go
result, err := client.GetAgent(ctx, agentUUID)
if err != nil {
    if apiErr, ok := err.(*agentcontrol.APIError); ok {
        if apiErr.IsNotFound() {
            fmt.Println("Agent not found")
        } else if apiErr.IsBadRequest() {
            fmt.Printf("Bad request: %s\n", apiErr.Message)
        }
    }
}
```

## Integration Example

Here's a complete example showing how to integrate Agent Control with an MCP tool server:

```go
package main

import (
    "context"
    "log"

    agentcontrol "github.com/rungalileo/agent-control/sdks/go"
    "github.com/google/uuid"
)

var (
    client    *agentcontrol.Client
    agentUUID uuid.UUID
)

func init() {
    client = agentcontrol.NewClient(
        agentcontrol.WithBaseURL("https://agent-control.internal"),
    )

    // Register agent on startup
    agent := agentcontrol.Agent{
        ID:   uuid.MustParse("550e8400-e29b-41d4-a716-446655440000"),
        Name: "webb-mcp",
    }
    _, err := client.InitAgent(context.Background(), agent, nil, nil)
    if err != nil {
        log.Fatalf("Failed to register agent: %v", err)
    }
    agentUUID = agent.ID
}

func handleToolCall(ctx context.Context, toolName string, args map[string]interface{}) (interface{}, error) {
    // Pre-check: Evaluate before execution
    result, err := client.EvaluateToolCall(ctx, agentUUID, toolName, args, agentcontrol.PreCheck)
    if err != nil {
        return nil, err
    }

    if !result.IsSafe {
        return map[string]interface{}{
            "error":   "blocked_by_control",
            "reason":  result.Reason,
            "matches": result.Matches,
        }, nil
    }

    // Execute the actual tool
    output, err := executeActualTool(ctx, toolName, args)
    if err != nil {
        return nil, err
    }

    // Post-check: Evaluate output before returning
    result, err = client.EvaluateToolCallWithOutput(ctx, agentUUID, toolName, args, output)
    if err != nil {
        return nil, err
    }

    if !result.IsSafe {
        return map[string]interface{}{
            "error":  "output_blocked",
            "reason": result.Reason,
        }, nil
    }

    return output, nil
}

func executeActualTool(ctx context.Context, name string, args map[string]interface{}) (interface{}, error) {
    // Your tool implementation
    return nil, nil
}
```

## License

Apache 2.0 - See LICENSE file in the repository root.
