# Control Evaluation Flow

How the Control Engine processes evaluation requests and applies controls.

## High-Level Flow

```mermaid
flowchart TD
    request["EvaluationRequest<br/>━━━━━━━━━━━━━━━<br/>agent_uuid<br/>check_stage<br/>payload"]

    subgraph engine["Control Engine"]
        filter["Filter Applicable<br/>Controls"]
        loop["For Each Control"]
        
        subgraph process["Process Control"]
            select["1. Select Data"]
            evaluate["2. Evaluate"]
            act["3. Record Match"]
        end
    end

    response["EvaluationResponse<br/>━━━━━━━━━━━━━━━<br/>is_safe<br/>confidence<br/>matches"]

    request --> filter
    filter --> loop
    loop --> process
    process --> response

    style request fill:#e3f2fd,stroke:#1565c0
    style engine fill:#f5f5f5,stroke:#616161
    style response fill:#e8f5e9,stroke:#388e3c
```

## Control Filtering Logic

```mermaid
flowchart TD
    controls["All Agent Controls"]
    
    c1{"enabled = true?"}
    c2{"check_stage<br/>matches request?"}
    c3{"applies_to<br/>matches payload?"}
    
    applicable["Applicable Controls"]
    skipped["Skipped"]

    controls --> c1
    c1 -->|No| skipped
    c1 -->|Yes| c2
    c2 -->|No| skipped
    c2 -->|Yes| c3
    c3 -->|No| skipped
    c3 -->|Yes| applicable

    style applicable fill:#c8e6c9,stroke:#2e7d32
    style skipped fill:#ffcdd2,stroke:#c62828
```

## Data Selection

The Selector extracts data from the payload using a path expression:

```mermaid
flowchart LR
    subgraph payload["LlmCall Payload"]
        input["input: 'Hello world'"]
        output["output: 'Response text'"]
    end

    selector["Selector<br/>path: 'output'"]
    
    data["Selected Data:<br/>'Response text'"]

    payload --> selector
    selector --> data

    style payload fill:#e3f2fd,stroke:#1565c0
    style data fill:#e8f5e9,stroke:#388e3c
```

## Evaluator Processing

```mermaid
flowchart TD
    data["Selected Data"]
    
    type{"Evaluator Type?"}
    
    subgraph regex["Regex Evaluator"]
        re_compile["Compile Pattern<br/>(RE2 Engine)"]
        re_match["Search for Match"]
    end

    subgraph list["List Evaluator"]
        list_norm["Normalize Input"]
        list_match["Match Against Values"]
        list_logic["Apply Logic<br/>(any/all)"]
    end

    subgraph plugin["Plugin Evaluator"]
        plugin_load["Load Plugin"]
        plugin_call["Call Plugin.evaluate()"]
    end

    result["EvaluatorResult<br/>━━━━━━━━━━━━━<br/>matched: bool<br/>confidence: float<br/>message: string<br/>metadata: dict"]

    data --> type
    type -->|"regex"| regex
    type -->|"list"| list
    type -->|"plugin"| plugin
    regex --> result
    list --> result
    plugin --> result

    style data fill:#e3f2fd,stroke:#1565c0
    style result fill:#fff3e0,stroke:#ef6c00
```

## Result Aggregation

```mermaid
flowchart TD
    matches["All Control Matches"]
    
    check{"Any match with<br/>action = 'deny'?"}
    
    safe["is_safe = true"]
    unsafe["is_safe = false"]

    response["EvaluationResponse"]

    matches --> check
    check -->|No| safe
    check -->|Yes| unsafe
    safe --> response
    unsafe --> response

    style safe fill:#c8e6c9,stroke:#2e7d32
    style unsafe fill:#ffcdd2,stroke:#c62828
```

## Complete Sequence

```mermaid
sequenceDiagram
    participant Client as SDK Client
    participant API as Server API
    participant DB as Database
    participant Engine as Control Engine
    participant Eval as Evaluator

    Client->>API: POST /evaluation
    API->>DB: Get Agent by UUID
    API->>DB: Get Controls via Policy→ControlSets
    DB-->>API: List of Controls
    
    API->>Engine: Process(request, controls)
    
    loop For each applicable control
        Engine->>Engine: Select data from payload
        Engine->>Eval: Evaluate(data)
        Eval-->>Engine: EvaluatorResult
        
        alt If matched
            Engine->>Engine: Record ControlMatch
            alt If action = deny
                Engine->>Engine: Set is_safe = false
            end
        end
    end
    
    Engine-->>API: EvaluationResponse
    API-->>Client: JSON Response
```

## List Evaluator Logic Detail

```mermaid
flowchart TD
    input["Input Values"]
    config["Config Values"]
    
    match_check["Match each input<br/>against config values"]
    
    matches["Matched Values"]
    
    logic{"logic setting?"}
    
    any_check{"Any matched?"}
    all_check{"All matched?"}
    
    condition_met["condition_met = true"]
    condition_not["condition_met = false"]
    
    match_on{"match_on setting?"}
    
    result_match["matched = condition_met"]
    result_nomatch["matched = !condition_met"]

    input --> match_check
    config --> match_check
    match_check --> matches
    matches --> logic
    
    logic -->|"any"| any_check
    logic -->|"all"| all_check
    
    any_check -->|Yes| condition_met
    any_check -->|No| condition_not
    all_check -->|Yes| condition_met
    all_check -->|No| condition_not
    
    condition_met --> match_on
    condition_not --> match_on
    
    match_on -->|"match"| result_match
    match_on -->|"no_match"| result_nomatch

    style condition_met fill:#c8e6c9,stroke:#2e7d32
    style condition_not fill:#ffcdd2,stroke:#c62828
```
