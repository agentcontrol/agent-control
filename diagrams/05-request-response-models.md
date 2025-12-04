# Request & Response Models

API contracts for the Agent Control Server endpoints.

## Agent Models

```mermaid
classDiagram
    class Agent {
        +agent_id: UUID
        +agent_name: string
        +agent_description: string | null
        +agent_created_at: string | null
        +agent_updated_at: string | null
        +agent_version: string | null
        +agent_metadata: dict | null
    }

    class AgentTool {
        +tool_name: string
        +arguments: dict
        +output_schema: dict
    }

    class InitAgentRequest {
        +agent: Agent
        +tools: list~AgentTool~
    }

    class InitAgentResponse {
        +created: bool
        +controls: list~Control~
    }

    class GetAgentResponse {
        +agent: Agent
        +tools: list~AgentTool~
    }

    InitAgentRequest *-- Agent
    InitAgentRequest *-- AgentTool
    InitAgentResponse *-- Control
    GetAgentResponse *-- Agent
    GetAgentResponse *-- AgentTool
```

## Evaluation Models

```mermaid
classDiagram
    class EvaluationRequest {
        +agent_uuid: UUID
        +check_stage: "pre" | "post"
        +payload: LlmCall | ToolCall
    }

    class LlmCall {
        +input: string | null
        +output: string | null
    }

    class ToolCall {
        +tool_name: string
        +arguments: dict
        +result: any | null
    }

    class EvaluationResponse {
        +is_safe: bool
        +confidence: float
        +matches: list~ControlMatch~ | null
    }

    class ControlMatch {
        +control_id: int
        +control_name: string
        +action: string
        +result: EvaluatorResult
    }

    class EvaluatorResult {
        +matched: bool
        +confidence: float
        +message: string | null
        +metadata: dict | null
    }

    EvaluationRequest *-- LlmCall
    EvaluationRequest *-- ToolCall
    EvaluationResponse *-- ControlMatch
    ControlMatch *-- EvaluatorResult
```

## Policy & Control Management Models

```mermaid
classDiagram
    class CreatePolicyRequest {
        +name: string
    }
    class CreatePolicyResponse {
        +policy_id: int
    }

    class CreateControlSetRequest {
        +name: string
    }
    class CreateControlSetResponse {
        +control_set_id: int
    }

    class CreateControlRequest {
        +name: string
    }
    class CreateControlResponse {
        +control_id: int
    }

    class SetControlDataRequest {
        +data: ControlDefinition
    }
    class SetControlDataResponse {
        +success: bool
    }

    class AssocResponse {
        +success: bool
    }

    class SetPolicyResponse {
        +success: bool
        +old_policy_id: int | null
    }
```

## API Request/Response Flow

```mermaid
sequenceDiagram
    participant Client
    participant Server
    participant DB

    rect rgb(227, 242, 253)
        Note over Client,DB: Agent Registration
        Client->>Server: POST /agents/initAgent<br/>InitAgentRequest
        Server->>DB: Upsert Agent
        Server-->>Client: InitAgentResponse
    end

    rect rgb(243, 229, 245)
        Note over Client,DB: Policy Assignment
        Client->>Server: POST /agents/{id}/policy/{policy_id}
        Server->>DB: Update Agent.policy_id
        Server-->>Client: SetPolicyResponse
    end

    rect rgb(255, 243, 224)
        Note over Client,DB: Evaluation
        Client->>Server: POST /evaluation<br/>EvaluationRequest
        Server->>DB: Fetch Agent's Controls
        Server->>Server: Run Control Engine
        Server-->>Client: EvaluationResponse
    end
```

## Payload Discrimination

The `EvaluationRequest.payload` field is a discriminated union:

```mermaid
flowchart LR
    payload["payload"]
    
    check{"Has tool_name<br/>field?"}
    
    llm["LlmCall<br/>━━━━━━━━<br/>input: string<br/>output: string"]
    tool["ToolCall<br/>━━━━━━━━<br/>tool_name: string<br/>arguments: dict<br/>result: any"]

    payload --> check
    check -->|No| llm
    check -->|Yes| tool

    style llm fill:#e8f5e9,stroke:#388e3c
    style tool fill:#fff3e0,stroke:#ef6c00
```

## Control Model (API Response)

```mermaid
classDiagram
    class Control {
        +id: int
        +name: string
        +control: dict
    }

    class ControlSet {
        +id: int
        +name: string
        +controls: list~Control~
    }

    class Policy {
        +id: int
        +name: string
        +control_sets: list~ControlSet~
    }

    Policy *-- ControlSet
    ControlSet *-- Control

    note for Control "control field contains ControlDefinition"
```
