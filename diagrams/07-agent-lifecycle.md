# Agent Lifecycle

How agents are registered, configured, and protected throughout their lifecycle.

## Lifecycle Overview

```mermaid
stateDiagram-v2
    [*] --> Unregistered
    
    Unregistered --> Registered: Register Agent
    Registered --> Protected: Assign Policy
    Protected --> Registered: Remove Policy
    Protected --> Protected: Update Policy
    Registered --> Registered: Update Tools
    
    note right of Unregistered: Agent exists in code only
    note right of Registered: Agent known to server,\nno active controls
    note right of Protected: Agent has policy,\ncontrols are active
```

## Registration Flow

```mermaid
sequenceDiagram
    participant App as Application
    participant SDK as Agent Control SDK
    participant Server as Server
    participant DB as Database

    App->>SDK: Initialize agent

    SDK->>Server: POST /agents/initAgent<br/>{agent, tools}
    
    Server->>DB: Check if agent name exists
    
    alt Agent is new
        DB-->>Server: Not found
        Server->>DB: INSERT agent record
        Server->>Server: Generate tool schema
        Server-->>SDK: {created: true, controls: []}
    else Agent exists (same UUID)
        DB-->>Server: Found
        Server->>DB: UPDATE tools if changed
        Server->>DB: Fetch current policy controls
        Server-->>SDK: {created: false, controls: [...]}
    else Agent exists (different UUID)
        DB-->>Server: Found with different UUID
        Server-->>SDK: 409 Conflict
    end

    SDK-->>App: Registration result
```

## Policy Assignment Flow

```mermaid
sequenceDiagram
    participant Admin as Administrator
    participant Server as Server
    participant DB as Database

    rect rgb(243, 229, 245)
        Note over Admin,DB: Setup Phase (One-time)
        Admin->>Server: PUT /controls {name}
        Server->>DB: Create control
        Admin->>Server: PUT /controls/{id}/data {definition}
        Server->>DB: Store control config
        
        Admin->>Server: PUT /control-sets {name}
        Server->>DB: Create control set
        Admin->>Server: POST /control-sets/{id}/controls/{control_id}
        Server->>DB: Link control to set
        
        Admin->>Server: PUT /policies {name}
        Server->>DB: Create policy
        Admin->>Server: POST /policies/{id}/control_sets/{set_id}
        Server->>DB: Link control set to policy
    end

    rect rgb(227, 242, 253)
        Note over Admin,DB: Assignment Phase
        Admin->>Server: POST /agents/{agent_id}/policy/{policy_id}
        Server->>DB: Update agent.policy_id
        Server-->>Admin: {success: true}
    end
```

## Agent Data Model

```mermaid
classDiagram
    class AgentRecord {
        +agent_uuid: UUID
        +name: string
        +policy_id: int | null
        +data: AgentData
        +created_at: datetime
    }

    class AgentData {
        +agent_metadata: dict
        +tools: list~AgentVersionedTool~
        +agent_schema: dict | null
    }

    class AgentVersionedTool {
        +version: int
        +tool: AgentTool
    }

    class AgentTool {
        +tool_name: string
        +arguments: dict
        +output_schema: dict
    }

    AgentRecord *-- AgentData : "data (JSONB)"
    AgentData *-- AgentVersionedTool
    AgentVersionedTool *-- AgentTool

    note for AgentRecord "Database table: agents"
    note for AgentData "Stored as JSONB in data column"
```

## Tool Versioning

When tools are updated, the system tracks changes:

```mermaid
flowchart LR
    subgraph v0["Version 0"]
        t0["search_kb<br/>━━━━━━━<br/>args: {query}"]
    end

    subgraph v1["Version 1 (Updated)"]
        t1["search_kb<br/>━━━━━━━<br/>args: {query, limit}"]
    end

    v0 -->|"Tool schema changed"| v1

    style v0 fill:#e0e0e0,stroke:#757575
    style v1 fill:#c8e6c9,stroke:#2e7d32
```

## Agent States

| State | policy_id | Controls | Evaluation Behavior |
|-------|-----------|----------|---------------------|
| **Unregistered** | N/A | None | Cannot evaluate (404) |
| **Registered** | `null` | None | Always returns `is_safe: true` |
| **Protected** | `<id>` | Active | Applies all policy controls |

## Complete Setup Example

```mermaid
flowchart TD
    subgraph step1["1. Create Controls"]
        c1["Create 'ssn-detector'"]
        c2["Configure regex pattern"]
    end

    subgraph step2["2. Create Control Set"]
        cs1["Create 'pii-protection'"]
        cs2["Add ssn-detector to set"]
    end

    subgraph step3["3. Create Policy"]
        p1["Create 'production-policy'"]
        p2["Add pii-protection to policy"]
    end

    subgraph step4["4. Register Agent"]
        a1["Register 'my-agent'"]
        a2["Provide tool schemas"]
    end

    subgraph step5["5. Assign Policy"]
        assign["Assign production-policy<br/>to my-agent"]
    end

    subgraph step6["6. Protected!"]
        eval["Evaluation requests now<br/>apply ssn-detector control"]
    end

    step1 --> step2
    step2 --> step3
    step3 --> step4
    step4 --> step5
    step5 --> step6

    style step6 fill:#c8e6c9,stroke:#2e7d32
```
