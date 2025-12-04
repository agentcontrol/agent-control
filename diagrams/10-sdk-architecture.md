# SDK Architecture

Structure of the Python SDK (`agent-control` package) and how its modules are organized.

## Module Overview

```mermaid
flowchart TB
    subgraph sdk["agent_control package"]
        init["__init__.py<br/>━━━━━━━━━━━━━<br/>Public API<br/>Convenience functions"]
        
        client["client.py<br/>━━━━━━━━━━━━━<br/>HTTP client<br/>Connection management"]
        
        subgraph operations["Operation Modules"]
            agents["agents.py"]
            policies["policies.py"]
            control_sets["control_sets.py"]
            controls["controls.py"]
            evaluation["evaluation.py"]
        end
        
        decorator["tool_decorator.py<br/>━━━━━━━━━━━━━<br/>@protect decorator"]
        
        subgraph plugins_pkg["plugins/"]
            plugins_init["__init__.py"]
            base["base.py"]
            registry["registry.py"]
            optional["optional/"]
        end
    end

    init --> client
    init --> operations
    init --> decorator
    decorator --> evaluation
```

## Module Responsibilities

```mermaid
flowchart LR
    subgraph modules["SDK Modules"]
        direction TB
        
        m1["client.py<br/>━━━━━━━━━<br/>AgentProtectClient<br/>HTTP session<br/>Health check"]
        
        m2["agents.py<br/>━━━━━━━━━<br/>register_agent<br/>get_agent"]
        
        m3["policies.py<br/>━━━━━━━━━<br/>create_policy<br/>add_control_set<br/>remove_control_set<br/>list_control_sets"]
        
        m4["control_sets.py<br/>━━━━━━━━━<br/>create_control_set<br/>add_control<br/>remove_control<br/>list_controls"]
        
        m5["controls.py<br/>━━━━━━━━━<br/>create_control<br/>get_control_data<br/>set_control_data"]
        
        m6["evaluation.py<br/>━━━━━━━━━<br/>evaluate"]
    end

    subgraph endpoints["Server Endpoints"]
        e1["/agents/*"]
        e2["/policies/*"]
        e3["/control-sets/*"]
        e4["/controls/*"]
        e5["/evaluation"]
    end

    m2 --> e1
    m3 --> e2
    m4 --> e3
    m5 --> e4
    m6 --> e5
```

## Client Usage Pattern

```mermaid
sequenceDiagram
    participant App as Application
    participant SDK as agent_control
    participant Client as AgentProtectClient
    participant Server as Server

    App->>SDK: import agent_control
    
    App->>Client: async with AgentProtectClient() as client:
    Client->>Client: Create HTTP session

    App->>SDK: agent_control.agents.register_agent(client, ...)
    SDK->>Client: POST /agents/initAgent
    Client->>Server: HTTP Request
    Server-->>Client: Response
    Client-->>SDK: Parsed result
    SDK-->>App: Return data

    App->>Client: Exit context manager
    Client->>Client: Close HTTP session
```

## Public API Exports

```mermaid
flowchart TD
    subgraph exports["agent_control exports"]
        subgraph functions["Functions"]
            f1["init()"]
            f2["current_agent()"]
            f3["get_agent()"]
            f4["protect()"]
        end
        
        subgraph classes["Classes"]
            c1["AgentProtectClient"]
        end
        
        subgraph modules_exp["Modules"]
            m1["agents"]
            m2["policies"]
            m3["control_sets"]
            m4["controls"]
            m5["evaluation"]
        end
        
        subgraph models_exp["Models (re-exported)"]
            mo1["Agent"]
            mo2["LlmCall"]
            mo3["ToolCall"]
            mo4["EvaluationRequest"]
            mo5["EvaluationResponse"]
        end
    end
```

## Two Usage Patterns

### Pattern 1: Module-First (Recommended)

```mermaid
flowchart LR
    subgraph code["Code"]
        import["import agent_control"]
        use["agent_control.policies.create_policy(client, name)"]
    end
```

### Pattern 2: Direct Import

```mermaid
flowchart LR
    subgraph code["Code"]
        import["from agent_control import policies"]
        use["policies.create_policy(client, name)"]
    end
```

## Plugin Module Structure

```mermaid
flowchart TB
    subgraph plugins["agent_control.plugins"]
        init["__init__.py<br/>━━━━━━━━━━━━━<br/>get_plugin()<br/>list_plugins()<br/>register_plugin()"]
        
        base["base.py<br/>━━━━━━━━━━━━━<br/>PluginMetadata<br/>PluginEvaluator"]
        
        registry["registry.py<br/>━━━━━━━━━━━━━<br/>Plugin storage<br/>Discovery logic"]
        
        subgraph optional_pkg["optional/"]
            luna["luna2.py"]
            guardrails["guardrails.py"]
        end
    end

    init --> registry
    registry --> base
    optional_pkg -.->|lazy load| registry
```

## Dependency Graph

```mermaid
flowchart BT
    models["agent-control-models"]
    engine["agent-control-engine"]
    sdk["agent-control (SDK)"]
    server["agent-control-server"]

    sdk --> models
    engine --> models
    server --> models
    server --> engine
    
    sdk -.->|HTTP| server
```

## Initialization Flow

```mermaid
flowchart TD
    start["Application Start"]
    
    import_sdk["import agent_control"]
    
    init["agent_control.init(<br/>  agent_name='my-agent',<br/>  agent_id=uuid,<br/>  tools=[...],<br/>  server_url='http://...'<br/>)"]
    
    register["Register agent with server"]
    
    store["Store current agent reference"]
    
    ready["Ready to use @protect"]

    start --> import_sdk
    import_sdk --> init
    init --> register
    register --> store
    store --> ready
```

## Error Handling

```mermaid
flowchart TD
    call["SDK API Call"]
    
    http["HTTP Request"]
    
    check{"Response<br/>Status?"}
    
    success["Return parsed data"]
    
    client_error["400-499:<br/>Raise HTTPError"]
    server_error["500-599:<br/>Raise HTTPError"]
    network_error["Connection Error:<br/>Raise Exception"]

    call --> http
    http --> check
    check -->|2xx| success
    check -->|4xx| client_error
    check -->|5xx| server_error
    http -.->|Network| network_error
```
