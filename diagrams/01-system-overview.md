# System Overview

High-level view of Agent Protect architecture showing the main components and how they interact.

## Component Architecture

```mermaid
flowchart TB
    subgraph client["Client Application"]
        agent["AI Agent<br/>(LangChain, LangGraph, etc.)"]
        sdk["Agent Control SDK"]
    end

    subgraph server["Agent Control Server"]
        api["REST API<br/>(FastAPI)"]
        engine["Control Engine"]
        db[(PostgreSQL)]
    end

    subgraph external["External Services"]
        luna["Luna-2"]
        guardrails["Guardrails AI"]
        custom["Custom Plugins"]
    end

    agent <--> sdk
    sdk <-->|HTTP/JSON| api
    api <--> engine
    api <--> db
    engine -.->|plugin calls| luna
    engine -.->|plugin calls| guardrails
    engine -.->|plugin calls| custom

    style client fill:#e1f5fe,stroke:#01579b
    style server fill:#f3e5f5,stroke:#4a148c
    style external fill:#fff3e0,stroke:#e65100
```

## Package Structure

```mermaid
flowchart LR
    subgraph packages["Python Packages"]
        models["agent-control-models<br/>━━━━━━━━━━━━━━━<br/>Shared Pydantic models<br/>for API contracts"]
        
        engine["agent-control-engine<br/>━━━━━━━━━━━━━━━<br/>Control evaluation logic<br/>Evaluators & Selectors"]
        
        sdk["agent-control<br/>━━━━━━━━━━━━━━━<br/>Python SDK client<br/>@protect decorator"]
        
        server["agent-control-server<br/>━━━━━━━━━━━━━━━<br/>FastAPI server<br/>Database layer"]
    end

    models --> engine
    models --> sdk
    models --> server
    engine --> server
    sdk -.->|HTTP| server

    style models fill:#c8e6c9,stroke:#2e7d32
    style engine fill:#bbdefb,stroke:#1565c0
    style sdk fill:#fff9c4,stroke:#f9a825
    style server fill:#f8bbd9,stroke:#c2185b
```

## Key Interactions

| From | To | Protocol | Purpose |
|------|-----|----------|---------|
| AI Agent | SDK | In-process | Wrap agent calls with protection |
| SDK | Server | HTTP/JSON | Register agents, evaluate requests |
| Server | Database | SQL | Persist agents, policies, controls |
| Engine | Plugins | In-process | Delegate to external evaluators |
