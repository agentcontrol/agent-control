## Concepts
Understanding these core concepts will help you get the most out of Agent Control.

![Agent Control Policy Architecture](./docs/images/Policy.png)

## Policy

A Policy is a named collection of controls assigned to an agent. Policies enable you to:

- Bundle multiple controls together as a cohesive protection strategy
- Audit your safety rules
- Enables reusable security/compliance configurations across agents
- Apply different policies to different environments (dev/staging/prod)

```python
# Policy for PROD deployment
{
  "id": 42,
  "name": "production-safety",
  "controls": [ # collection of rules.
    {....}
  ]
}
```

## Controls

![Control Components](./docs/images/Control.png)

A Control is a protection rule that evaluates agent interactions (inputs/outputs) and takes action based on configured criteria. It defines when to check, what to check, how to evaluate it, and what to do with the results.

**Control = Scope (When) + Selector (What) + Evaluator (How) + Action (Decision)**

### 1. Scope (When to Check)

The **Scope** defines which steps trigger the control—acting as a filter to select specific sections of your agent workflow to monitor.

**Fields:**
- `step_types`: List of step types (`['tool', 'llm_inference']`). If null, applies to all types.
- `step_names`: List of exact step names to target (e.g., `['search_db', 'send_email']`)
- `step_name_regex`: Regex pattern for step name matching (e.g., `"^db.*"` matches all "db_" prefixed steps)
- `stages`: When to evaluate - `['pre', 'post']`
  - `'pre'`: Check before execution (block bad inputs, prevent prompt injection)
  - `'post'`: Check after execution (filter bad outputs, redact PII)

**Example 1: Apply to all tool steps before execution**
```json
{
  "scope": {
    "step_types": ["tool"],
    "stages": ["pre"]
  }
}
```

**Example 2: Target specific database operations**
```json
{
  "scope": {
    "step_names": ["query_database", "execute_sql", "db_lookup"],
    "stages": ["pre"]
  }
}
```

**Example 3: Use regex to match multiple steps**
```json
{
  "scope": {
    "step_name_regex": "^db_.*",  // Matches all steps starting with "db_"
    "stages": ["pre", "post"]
  }
}
```

**Example 4: Full scope configuration**
```json
{
  "scope": {
    "step_types": ["tool", "llm_inference"],
    "step_names": ["search_db", "query_api"],
    "step_name_regex": "^db_.*",
    "stages": ["pre", "post"]
  }
}
```

---

### 2. Selector (What to Check)

The **Selector** specifies which portion of the step's data to extract and pass to the evaluator for analysis. It uses a path specification to navigate the step object.

**Field:**
- `path`: Dot-notation path to the data you want to evaluate

**Common Paths:**
- `"input"` - Entire input to the step
- `"output"` - Step's output/result
- `"input.query"` - Specific parameter within input
- `"input.user_message"` - User message field
- `"name"` - The step/tool name itself
- `"context.user_id"` - Context metadata
- `"*"` - All available payload data

**Example 1: Check tool output for PII**
```json
{
  "selector": {
    "path": "output"
  }
}
```

**Example 2: Validate specific input parameter**
```json
{
  "selector": {
    "path": "input.sql_query"
  }
}
```

**Example 3: Check user message in LLM input**
```json
{
  "selector": {
    "path": "input.user_message"
  }
}
```

**Example 4: Access context metadata**
```json
{
  "selector": {
    "path": "context.user_id"
  }
}
```

---

### 3. Evaluator (How to Check)

The **Evaluator** receives the data extracted by the selector and evaluates it against configured rules, returning whether the data matches specified criteria.

**Components:**
- `name`: Evaluator identifier (e.g., `"regex"`, `"list"`, `"galileo-luna2"`)
- `config`: Evaluator-specific configuration, validated against the evaluator's schema
- `metadata`: Optional evaluator identification (name, version, description)

**Example 1: Regex evaluator to detect PII**
```json
{
  "evaluator": {
    "name": "regex",
    "config": {
      "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b"  // Social Security Number pattern
    }
  }
}
```

**Example 2: List evaluator for banned terms**
```json
{
  "evaluator": {
    "name": "list",
    "config": {
      "values": ["DROP TABLE", "DELETE FROM", "TRUNCATE"],
      "case_sensitive": false
    }
  }
}
```

**Example 3: AI-powered toxicity detection with Luna-2**
```json
{
  "evaluator": {
    "name": "galileo-luna2",
    "config": {
      "metric": "input_toxicity",
      "operator": "gt",
      "target_value": 0.5
    }
  }
}
```

**Example 4: Complex regex for multiple PII types**
```json
{
  "evaluator": {
    "name": "regex",
    "config": {
      "pattern": "(?:\\b\\d{3}-\\d{2}-\\d{4}\\b|\\b\\d{4}[\\s-]?\\d{4}[\\s-]?\\d{4}[\\s-]?\\d{4}\\b|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})"
    }
  }
}
```

---

### 4. Action (What to Do)

The **Action** defines what happens when the evaluator matches/detects an issue.

**Fields:**
- `decision`: The enforcement action to take
  - `"allow"` - Continue execution (useful for allowlist controls)
  - `"deny"` - Hard stop execution (blocks the request)
  - `"warn"` - Log a warning but continue execution
  - `"log"` - Log the match for observability only
- `metadata`: Optional additional context (JSON object)

**Important: "Deny Wins" Semantics**

Agent Control uses "deny wins" logic: if **any** enabled control with a `deny` action matches, the request is blocked regardless of other control results. This ensures fail-safe behavior.

**Example 1: Block on match**
```json
{
  "action": {
    "decision": "deny"
  }
}
```

**Example 2: Warn without blocking**
```json
{
  "action": {
    "decision": "warn"
  }
}
```

**Example 3: Action with metadata**
```json
{
  "action": {
    "decision": "deny",
    "metadata": {
      "reason": "PII detected in output",
      "severity": "high",
      "compliance": "GDPR"
    }
  }
}
```

---

### Complete Control Example

Putting it all together - a control that blocks Social Security Numbers in tool outputs:

```json
{
  "name": "block-ssn-output",
  "description": "Prevent SSN leakage in tool responses",
  "enabled": true,
  "scope": {
    "step_types": ["tool"],
    "stages": ["post"]
  },
  "selector": {
    "path": "output"
  },
  "evaluator": {
    "name": "regex",
    "config": {
      "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b"
    }
  },
  "action": {
    "decision": "deny",
    "metadata": {
      "reason": "SSN detected",
      "compliance": "PII protection"
    }
  }
}
```

