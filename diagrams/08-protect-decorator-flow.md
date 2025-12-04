# @protect Decorator Flow

How the SDK's `@protect` decorator intercepts function calls and enforces controls.

## Decorator Overview

```mermaid
flowchart LR
    subgraph code["Your Code"]
        func["@protect('step-id', input='msg')<br/>async def process(msg):"]
    end

    subgraph decorator["Decorator Behavior"]
        extract["Extract mapped<br/>parameters"]
        pre["PRE check"]
        execute["Execute function"]
        post["POST check"]
    end

    call["Function Call"] --> decorator
    decorator --> result["Return Value"]

    style code fill:#e3f2fd,stroke:#1565c0
    style decorator fill:#f3e5f5,stroke:#7b1fa2
```

## Execution Sequence

```mermaid
sequenceDiagram
    participant App as Application
    participant Dec as @protect Decorator
    participant Func as Your Function
    participant Engine as Control Engine

    App->>Dec: Call decorated function
    
    Dec->>Dec: Bind arguments to parameters
    Dec->>Dec: Extract mapped data sources

    rect rgb(255, 243, 224)
        Note over Dec,Engine: PRE-execution check
        Dec->>Engine: Evaluate(data, stage="pre")
        Engine-->>Dec: EvaluationResponse
        
        alt is_safe = false
            Dec-->>App: Raise exception or return error
        end
    end

    Dec->>Func: Execute original function
    Func-->>Dec: Return value

    rect rgb(232, 245, 233)
        Note over Dec,Engine: POST-execution check
        Dec->>Dec: Add return value to data
        Dec->>Engine: Evaluate(data, stage="post")
        Engine-->>Dec: EvaluationResponse
        
        alt is_safe = false
            Dec-->>App: Raise exception or return error
        end
    end

    Dec-->>App: Return result
```

## Data Source Mapping

```mermaid
flowchart TD
    subgraph decorator["Decorator Definition"]
        dec["@protect('step-id',<br/>  input='user_msg',<br/>  context='ctx',<br/>  output='response')"]
    end

    subgraph function["Function Signature"]
        func["def process(<br/>  user_msg: str,<br/>  ctx: dict<br/>) -> str:"]
    end

    subgraph mapping["Extracted Data"]
        m1["input → user_msg parameter"]
        m2["context → ctx parameter"]
        m3["output → return value"]
    end

    decorator --> mapping
    function --> mapping

    style mapping fill:#e8f5e9,stroke:#388e3c
```

## Parameter Binding Process

```mermaid
flowchart LR
    subgraph call["Function Call"]
        args["process('Hello', {'user': 'A'})"]
    end

    subgraph bind["Signature Binding"]
        sig["signature(process)"]
        bound["bind(*args, **kwargs)"]
        defaults["apply_defaults()"]
    end

    subgraph result["Bound Arguments"]
        ba["user_msg: 'Hello'<br/>ctx: {'user': 'A'}"]
    end

    call --> bind
    bind --> result

    style result fill:#fff3e0,stroke:#ef6c00
```

## Data Available at Each Stage

```mermaid
flowchart TD
    subgraph pre["PRE Stage"]
        pre_data["Available Data:<br/>━━━━━━━━━━━━<br/>✓ All mapped parameters<br/>✗ Return value (not yet)"]
    end

    exec["Function Executes"]

    subgraph post["POST Stage"]
        post_data["Available Data:<br/>━━━━━━━━━━━━<br/>✓ All mapped parameters<br/>✓ Return value (if mapped)"]
    end

    pre --> exec
    exec --> post

    style pre fill:#fff3e0,stroke:#ef6c00
    style post fill:#e8f5e9,stroke:#388e3c
```

## What You CAN and CANNOT Access

```mermaid
flowchart LR
    subgraph can["✓ Accessible"]
        p1["Function parameters"]
        p2["Return value"]
        p3["Default values"]
        p4["Nested data in params"]
    end

    subgraph cannot["✗ Not Accessible"]
        n1["Local variables"]
        n2["Outer scope variables"]
        n3["Intermediate results"]
        n4["Unmapped parameters"]
    end

    style can fill:#c8e6c9,stroke:#2e7d32
    style cannot fill:#ffcdd2,stroke:#c62828
```

## Common Patterns

### Pattern 1: Input Validation

```mermaid
flowchart LR
    input["User Input"] --> pre["PRE Check"]
    pre -->|Safe| func["Process"]
    pre -->|Unsafe| block["Block"]
    func --> output["Output"]

    style block fill:#ffcdd2,stroke:#c62828
```

### Pattern 2: Output Filtering

```mermaid
flowchart LR
    input["Input"] --> func["Process"]
    func --> post["POST Check"]
    post -->|Safe| output["Return Output"]
    post -->|PII Detected| redact["Redact/Block"]

    style redact fill:#fff3e0,stroke:#ef6c00
```

### Pattern 3: Full Pipeline

```mermaid
flowchart LR
    input["Input"] 
    pre["PRE Check"]
    func["Process"]
    post["POST Check"]
    output["Output"]

    input --> pre
    pre -->|Pass| func
    func --> post
    post -->|Pass| output

    pre -->|Fail| blocked1["Blocked"]
    post -->|Fail| blocked2["Blocked"]

    style blocked1 fill:#ffcdd2,stroke:#c62828
    style blocked2 fill:#ffcdd2,stroke:#c62828
```

## LangGraph Integration Example

```mermaid
flowchart TD
    subgraph graph["LangGraph Workflow"]
        start["Start"]
        
        node1["@protect('input-check')<br/>Input Node"]
        node2["LLM Node"]
        node3["@protect('output-check')<br/>Output Node"]
        
        finish["End"]
    end

    start --> node1
    node1 --> node2
    node2 --> node3
    node3 --> finish

    style node1 fill:#e3f2fd,stroke:#1565c0
    style node3 fill:#e3f2fd,stroke:#1565c0
```

## Error Handling

```mermaid
flowchart TD
    check["Control Check"]
    
    result{"Result?"}
    
    safe["Continue execution"]
    
    deny["Action: deny"]
    warn["Action: warn"]
    log["Action: log"]
    
    exception["Raise RuleViolation"]
    log_warning["Log warning,<br/>continue"]
    log_info["Log match,<br/>continue"]

    check --> result
    result -->|is_safe| safe
    result -->|deny match| deny
    result -->|warn match| warn
    result -->|log match| log
    
    deny --> exception
    warn --> log_warning
    log --> log_info

    style exception fill:#ffcdd2,stroke:#c62828
    style log_warning fill:#fff3e0,stroke:#ef6c00
    style safe fill:#c8e6c9,stroke:#2e7d32
```
