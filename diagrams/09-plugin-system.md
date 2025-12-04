# Plugin System Architecture

How external evaluators integrate with Agent Control through the plugin system.

## Plugin Overview

```mermaid
flowchart TB
    subgraph engine["Control Engine"]
        eval_factory["Evaluator Factory"]
        
        subgraph builtin["Built-in Evaluators"]
            regex["Regex"]
            list["List"]
        end
        
        plugin_wrapper["Plugin Wrapper"]
    end

    subgraph plugins["Plugin Registry"]
        registry["Plugin Registry"]
        
        subgraph registered["Registered Plugins"]
            luna["galileo-luna2"]
            guardrails["guardrails-ai"]
            custom["custom-plugin"]
        end
    end

    subgraph external["External Services"]
        luna_api["Luna-2 API"]
        gr_api["Guardrails API"]
    end

    eval_factory --> builtin
    eval_factory --> plugin_wrapper
    plugin_wrapper --> registry
    registry --> registered
    luna -.-> luna_api
    guardrails -.-> gr_api
```

## Plugin Class Hierarchy

```mermaid
classDiagram
    class PluginMetadata {
        +name: string
        +version: string
        +description: string
        +requires_api_key: bool
        +timeout_ms: int
        +config_schema: dict | null
    }

    class PluginEvaluator {
        <<abstract>>
        +metadata: PluginMetadata
        +evaluate(data, config)*: EvaluatorResult
        +get_timeout_seconds(config): float
    }

    class Luna2Plugin {
        +metadata: PluginMetadata
        +evaluate(data, config): EvaluatorResult
    }

    class GuardrailsPlugin {
        +metadata: PluginMetadata
        +evaluate(data, config): EvaluatorResult
    }

    class CustomPlugin {
        +metadata: PluginMetadata
        +evaluate(data, config): EvaluatorResult
    }

    PluginEvaluator <|-- Luna2Plugin
    PluginEvaluator <|-- GuardrailsPlugin
    PluginEvaluator <|-- CustomPlugin
    PluginEvaluator *-- PluginMetadata
```

## Plugin Registration Flow

```mermaid
sequenceDiagram
    participant Plugin as Plugin Module
    participant Registry as Plugin Registry
    participant Engine as Control Engine

    Note over Plugin,Registry: Registration (at import time)
        Plugin->>Registry: @register_plugin decorator
        Registry->>Registry: Store plugin class by name

    Note over Engine,Registry: Usage (at evaluation time)
        Engine->>Registry: get_plugin("plugin-name")
        Registry-->>Engine: PluginClass
        Engine->>Engine: Instantiate plugin
        Engine->>Plugin: evaluate(data, config)
        Plugin-->>Engine: EvaluatorResult
```

## Plugin Configuration in ControlDefinition

```mermaid
flowchart LR
    subgraph control["ControlDefinition"]
        evaluator["evaluator:<br/>━━━━━━━━<br/>type: 'plugin'<br/>config: PluginConfig"]
    end

    subgraph config["PluginConfig"]
        pc["plugin_name: 'galileo-luna2'<br/>plugin_config:<br/>  model: 'luna-2-large'<br/>  threshold: 0.8<br/>  timeout_ms: 5000"]
    end

    control --> config
```

## Plugin Evaluation Flow

```mermaid
flowchart TD
    request["Evaluation Request"]
    
    select["Select Data<br/>from Payload"]
    
    wrapper["Plugin Wrapper"]
    
    subgraph plugin_exec["Plugin Execution"]
        load["Load Plugin<br/>from Registry"]
        instantiate["Create Plugin<br/>Instance"]
        call["Call evaluate()"]
    end

    subgraph external["External Call"]
        api["External API<br/>(Luna-2, etc.)"]
    end

    result["EvaluatorResult"]
    
    error["Error Result<br/>(if plugin fails)"]

    request --> select
    select --> wrapper
    wrapper --> plugin_exec
    plugin_exec --> external
    external --> result
    plugin_exec -.->|exception| error
```

## Creating a Custom Plugin

```mermaid
flowchart TD
    subgraph steps["Plugin Development Steps"]
        s1["1. Extend PluginEvaluator"]
        s2["2. Define metadata"]
        s3["3. Implement evaluate()"]
        s4["4. Register with decorator"]
    end

    subgraph structure["Plugin Structure"]
        meta["PluginMetadata<br/>━━━━━━━━━━━━<br/>name<br/>version<br/>description<br/>timeout_ms"]
        
        eval["evaluate(data, config)<br/>━━━━━━━━━━━━<br/>→ EvaluatorResult"]
    end

    steps --> structure
```

## Plugin Error Handling

```mermaid
flowchart TD
    call["Plugin.evaluate()"]
    
    result{"Success?"}
    
    success["Return EvaluatorResult"]
    
    error["Exception caught"]
    
    error_result["EvaluatorResult<br/>━━━━━━━━━━━━<br/>matched: false<br/>confidence: 0.0<br/>message: error details<br/>metadata: {error: ...}"]

    call --> result
    result -->|Yes| success
    result -->|Exception| error
    error --> error_result
```

## Available Plugins

| Plugin | Description | Requires API Key |
|--------|-------------|------------------|
| `galileo-luna2` | Galileo's Luna-2 safety model | Yes |
| `guardrails-ai` | Guardrails AI validators | Depends |
| Custom | User-defined plugins | Varies |

## Plugin Config Schema

Plugins can define a JSON Schema for their configuration:

```mermaid
flowchart LR
    subgraph plugin["Plugin Definition"]
        meta["metadata.config_schema:<br/>{<br/>  'model': {type: 'string'},<br/>  'threshold': {type: 'number'}<br/>}"]
    end

    subgraph usage["Control Config"]
        config["plugin_config:<br/>{<br/>  'model': 'luna-2-large',<br/>  'threshold': 0.8<br/>}"]
    end

    plugin -.->|validates| usage
```

## Timeout Handling

```mermaid
flowchart LR
    config["plugin_config"]
    meta["metadata.timeout_ms"]
    
    check{"timeout_ms<br/>in config?"}
    
    use_config["Use config timeout"]
    use_default["Use metadata default"]
    
    seconds["Convert to seconds<br/>for API calls"]

    config --> check
    meta --> check
    check -->|Yes| use_config
    check -->|No| use_default
    use_config --> seconds
    use_default --> seconds
```
