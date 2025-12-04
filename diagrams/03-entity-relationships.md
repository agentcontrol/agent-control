# Entity Relationships

Database schema showing the hierarchical relationship between Agents, Policies, Control Sets, and Controls.

## Entity Hierarchy

```mermaid
flowchart TD
    agent["🤖 Agent"]
    policy["📋 Policy"]
    controlset["📦 Control Set"]
    control["⚙️ Control"]

    agent -->|"has one (optional)"| policy
    policy -->|"has many"| controlset
    controlset -->|"has many"| control

    style agent fill:#e3f2fd,stroke:#1565c0
    style policy fill:#f3e5f5,stroke:#7b1fa2
    style controlset fill:#e8f5e9,stroke:#388e3c
    style control fill:#fff3e0,stroke:#ef6c00
```

## Database Schema (ERD)

```mermaid
erDiagram
    agents {
        UUID agent_uuid PK "Primary key"
        VARCHAR name UK "Unique agent name"
        JSONB data "Agent metadata & tools"
        INT policy_id FK "Optional policy reference"
        TIMESTAMP created_at "Creation timestamp"
    }

    policies {
        INT id PK "Auto-increment"
        VARCHAR name UK "Unique policy name"
    }

    control_sets {
        INT id PK "Auto-increment"
        VARCHAR name UK "Unique control set name"
    }

    controls {
        INT id PK "Auto-increment"
        VARCHAR name UK "Unique control name"
        JSONB data "ControlDefinition JSON"
    }

    policy_control_sets {
        INT policy_id PK,FK
        INT control_set_id PK,FK
    }

    control_set_controls {
        INT control_set_id PK,FK
        INT control_id PK,FK
    }

    agents ||--o| policies : "belongs to"
    policies ||--o{ policy_control_sets : "has"
    policy_control_sets }o--|| control_sets : "contains"
    control_sets ||--o{ control_set_controls : "has"
    control_set_controls }o--|| controls : "contains"
```

## Relationship Details

### Agent → Policy (Many-to-One)
- An Agent can optionally have one Policy assigned
- A Policy can be shared across multiple Agents
- When an Agent has no Policy, it has no active controls

### Policy ↔ Control Set (Many-to-Many)
- A Policy groups multiple Control Sets together
- A Control Set can be reused across multiple Policies
- Association managed via `policy_control_sets` junction table

### Control Set ↔ Control (Many-to-Many)  
- A Control Set groups multiple atomic Controls
- A Control can be reused across multiple Control Sets
- Association managed via `control_set_controls` junction table

## Example Configuration

```mermaid
flowchart LR
    subgraph agents["Agents"]
        a1["customer-service-bot"]
        a2["sales-assistant"]
    end

    subgraph policies["Policies"]
        p1["production-policy"]
    end

    subgraph controlsets["Control Sets"]
        cs1["pii-protection"]
        cs2["content-safety"]
    end

    subgraph controls["Controls"]
        c1["ssn-detector"]
        c2["email-detector"]
        c3["profanity-filter"]
        c4["toxicity-check"]
    end

    a1 --> p1
    a2 --> p1
    p1 --> cs1
    p1 --> cs2
    cs1 --> c1
    cs1 --> c2
    cs2 --> c3
    cs2 --> c4

    style agents fill:#e3f2fd,stroke:#1565c0
    style policies fill:#f3e5f5,stroke:#7b1fa2
    style controlsets fill:#e8f5e9,stroke:#388e3c
    style controls fill:#fff3e0,stroke:#ef6c00
```

## Data Traversal

To get all Controls for an Agent:
```
Agent → Policy → ControlSets (via junction) → Controls (via junction)
```

This multi-hop traversal is performed server-side when processing evaluation requests.
