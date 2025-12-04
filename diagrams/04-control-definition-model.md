# Control Definition Model

Detailed structure of a Control's configuration stored in the `data` JSONB field.

## ControlDefinition Structure

```mermaid
classDiagram
    class ControlDefinition {
        +description: string | null
        +enabled: bool
        +applies_to: "llm_call" | "tool_call"
        +check_stage: "pre" | "post"
        +selector: ControlSelector
        +evaluator: ControlEvaluator
        +action: ControlAction
        +tags: list~string~
    }

    class ControlSelector {
        +path: string
    }

    class ControlAction {
        +decision: "allow" | "deny" | "warn" | "log"
    }

    ControlDefinition *-- ControlSelector
    ControlDefinition *-- ControlAction
    ControlDefinition *-- ControlEvaluator

    note for ControlDefinition "Stored in controls.data as JSONB"
```

## Evaluator Types

```mermaid
classDiagram
    class ControlEvaluator {
        <<union>>
    }

    class RegexControlEvaluator {
        +type: "regex"
        +config: RegexConfig
    }

    class ListControlEvaluator {
        +type: "list"
        +config: ListConfig
    }

    class PluginControlEvaluator {
        +type: "plugin"
        +config: PluginConfig
    }

    class CustomControlEvaluator {
        +type: "custom"
        +config: CustomConfig
    }

    ControlEvaluator <|-- RegexControlEvaluator
    ControlEvaluator <|-- ListControlEvaluator
    ControlEvaluator <|-- PluginControlEvaluator
    ControlEvaluator <|-- CustomControlEvaluator
```

## Evaluator Configurations

```mermaid
classDiagram
    class RegexConfig {
        +pattern: string
        +flags: list~string~
    }

    class ListConfig {
        +values: list~string~
        +logic: "any" | "all"
        +match_on: "match" | "no_match"
        +case_sensitive: bool
    }

    class PluginConfig {
        +plugin_name: string
        +plugin_config: dict
    }

    class CustomConfig {
        +code: string
        +language: string
    }

    note for RegexConfig "Uses Google RE2 engine"
    note for ListConfig "Supports allowlists and blocklists"
    note for PluginConfig "Delegates to external systems"
```

## Control Flow Decision Tree

```mermaid
flowchart TD
    start["Incoming Request"]
    
    check_enabled{"enabled?"}
    check_stage{"check_stage<br/>matches request?"}
    check_type{"applies_to<br/>matches payload?"}
    
    select["Select data via<br/>selector.path"]
    evaluate["Run evaluator"]
    
    check_match{"Matched?"}
    
    action_allow["Action: allow"]
    action_deny["Action: deny<br/>(is_safe = false)"]
    action_warn["Action: warn"]
    action_log["Action: log"]
    
    skip["Skip control"]
    
    start --> check_enabled
    check_enabled -->|No| skip
    check_enabled -->|Yes| check_stage
    check_stage -->|No| skip
    check_stage -->|Yes| check_type
    check_type -->|No| skip
    check_type -->|Yes| select
    select --> evaluate
    evaluate --> check_match
    check_match -->|No| skip
    check_match -->|Yes| action_allow
    check_match -->|Yes| action_deny
    check_match -->|Yes| action_warn
    check_match -->|Yes| action_log
```

## Example Control Definition

```json
{
  "description": "Block outputs containing SSN",
  "enabled": true,
  "applies_to": "llm_call",
  "check_stage": "post",
  "selector": {
    "path": "output"
  },
  "evaluator": {
    "type": "regex",
    "config": {
      "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b",
      "flags": []
    }
  },
  "action": {
    "decision": "deny"
  },
  "tags": ["pii", "compliance"]
}
```

## Check Stage Semantics

| Stage | When | Use Case |
|-------|------|----------|
| `pre` | Before LLM/tool execution | Validate inputs, block dangerous requests |
| `post` | After LLM/tool execution | Filter outputs, redact PII |

## Applies To Semantics

| Type | Payload | Use Case |
|------|---------|----------|
| `llm_call` | LlmCall (input/output text) | Content moderation, PII detection |
| `tool_call` | ToolCall (tool_name, arguments) | Permission enforcement, input validation |
