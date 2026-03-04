# Agent Control

**Runtime guardrails for AI agents — configurable, extensible, and production-ready.**

Agent Control provides a control-based runtime layer that sits between your AI agents and the outside world. It evaluates inputs and outputs against configurable rules, blocking harmful content, prompt injections, PII leakage, and other risks — all without changing your agent's code.

---

## Why Agent Control?

AI agents are powerful but unpredictable. They can:
- Generate toxic or harmful content
- Be manipulated via prompt injection attacks
- Leak sensitive information (PII, secrets)
- Hallucinate incorrect facts
- Execute unintended actions

**Agent Control gives you runtime control over what your agents can do.**

---

## Key Concepts

Understanding these core concepts will help you get the most out of Agent Control:

### 🎛️ Controls

A **Control** is a single rule that defines what to check and what to do when a condition is met.

```
Control = Scope + Selector + Evaluator + Action
```

Example: *"If the output contains an SSN pattern, block the response."*

```json
{
  "name": "block-ssn-in-output",
  "execution": "server",
  "scope": { "step_types": ["llm"], "stages": ["post"] },
  "selector": { "path": "output" },
  "evaluator": {
    "name": "regex",
    "config": { "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b" }
  },
  "action": { "decision": "deny" }
}
```

### 📋 Control Sets

A **Control Set** is a named group of related controls. Use them to organize controls by purpose.

| Control Set | Controls |
|-------------|----------|
| `safety-controls` | block-toxicity, block-harassment, block-violence |
| `compliance-controls` | block-pii, block-phi, audit-logging |
| `quality-controls` | check-hallucination, verify-sources |

### 🔗 Control Associations

Controls can be linked directly to agents and reused across multiple agents. This keeps rollout and tuning fast without redeploying application code.

```
Controls → Agents
```

### 🎯 Selectors

A **Selector** defines *what data* to extract from the payload for evaluation.

| Path | Description | Example Use |
|------|-------------|-------------|
| `input` | Step input (tool args or LLM input) | Check for prompt injection |
| `output` | Step output | Check for PII leakage |
| `input.query` | Tool input field | Block SQL injection |
| `name` | Step name (tool name or model/chain id, required) | Restrict step usage |
| `context.user_id` | Context field | User-based rules |
| `*` | Entire step | Full payload analysis |

**Step scoping:** Controls can also scope by step type/name/stage:
```json
{
  "scope": {
    "step_types": ["tool"],
    "step_names": ["search_database", "execute_sql"],
    "step_name_regex": "^db_.*",
    "stages": ["pre"]
  }
}
```

### 🔍 Evaluators

An **Evaluator** defines *how* to analyze the selected data. Agent Control provides built-in evaluators and supports custom evaluators.

### ⚡ Actions

An **Action** defines *what to do* when a control matches:

| Action | Behavior |
|--------|----------|
| `deny` | Block the request/response |
| `steer` | Raise error with steering context for correction and retry |
| `allow` | Explicitly permit (override other controls) |
| `warn` | Log a warning but allow |
| `log` | Silent logging for monitoring |

### 🔄 Check Stages

Controls run at different stages (configured via `scope.stages`):

| Stage | When | Use Case |
|-------|------|----------|
| `pre` | Before execution | Block bad inputs, prevent tool misuse |
| `post` | After execution | Filter bad outputs, redact PII |

---

## Built-in Evaluators

Agent Control includes powerful evaluators out of the box:

### 1. Regex Evaluator (`regex`)

Pattern matching using Google RE2 (safe from ReDoS attacks).

**Configuration:**
| Option | Type | Description |
|--------|------|-------------|
| `pattern` | string | Regular expression pattern (RE2 syntax) |
| `flags` | list | Optional: `["IGNORECASE"]` |

**Examples:**

```json
// Block Social Security Numbers
{
  "name": "regex",
  "config": {
    "pattern": "\\b\\d{3}-\\d{2}-\\d{4}\\b"
  }
}

// Block credit card numbers (case-insensitive "card" + digits)
{
  "name": "regex",
  "config": {
    "pattern": "card.*\\d{4}[- ]?\\d{4}[- ]?\\d{4}[- ]?\\d{4}",
    "flags": ["IGNORECASE"]
  }
}

// Block AWS access keys
{
  "name": "regex",
  "config": {
    "pattern": "AKIA[0-9A-Z]{16}"
  }
}
```

**Use Cases:**
- PII detection (SSN, credit cards, phone numbers)
- Secret detection (API keys, passwords)
- Pattern-based blocklists
- Data format validation

---

### 2. List Evaluator (`list`)

Flexible value matching with multiple modes and logic options.

**Configuration:**
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `values` | list | required | Values to match against |
| `logic` | string | `"any"` | `"any"` = match any value, `"all"` = match all |
| `match_on` | string | `"match"` | `"match"` = trigger when found, `"no_match"` = trigger when NOT found |
| `match_mode` | string | `"exact"` | `"exact"` = full string, `"contains"` = substring/keyword |
| `case_sensitive` | bool | `false` | Case sensitivity |

**Examples:**

```json
// Block admin/root keywords (any match, contains, case-insensitive)
{
  "name": "list",
  "config": {
    "values": ["admin", "root", "sudo", "superuser"],
    "logic": "any",
    "match_mode": "contains",
    "case_sensitive": false
  }
}

// Require approval keyword (trigger if NOT found)
{
  "name": "list",
  "config": {
    "values": ["APPROVED", "VERIFIED"],
    "match_on": "no_match",
    "logic": "any"
  }
}

// Block competitor mentions
{
  "name": "list",
  "config": {
    "values": ["CompetitorA", "CompetitorB", "CompetitorC"],
    "match_mode": "contains",
    "case_sensitive": false
  }
}

// Allowlist: only permit specific tools
{
  "name": "list",
  "config": {
    "values": ["search", "calculate", "lookup"],
    "match_on": "no_match"
  }
}
```

**Use Cases:**
- Keyword blocklists/allowlists
- Required terms validation
- Competitor mention detection
- Tool restriction lists
- Profanity filtering

---

### 3. Luna-2 Evaluator (`galileo.luna2`)

AI-powered detection using Galileo's Luna-2 small language models. Provides real-time, low-latency evaluation for complex patterns that can't be caught with regex or lists.

**Configuration:**
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `metric` | string | required | Metric to evaluate (see below) |
| `operator` | string | required | `"gt"`, `"lt"`, `"gte"`, `"lte"`, `"eq"` |
| `target_value` | number | required | Threshold value (0.0-1.0) |
| `stage_type` | string | `"local"` | `"local"` or `"central"` |
| `galileo_project` | string | optional | Project name for logging |
| `on_error` | string | `"allow"` | `"allow"` (fail open) or `"deny"` (fail closed) |

**Available Metrics:**
| Metric | Description |
|--------|-------------|
| `input_toxicity` | Toxic/harmful content in user input |
| `output_toxicity` | Toxic/harmful content in agent response |
| `input_sexism` | Sexist content in user input |
| `output_sexism` | Sexist content in agent response |
| `prompt_injection` | Prompt manipulation attempts |
| `pii_detection` | Personally identifiable information |
| `hallucination` | Potentially false or fabricated statements |
| `tone` | Communication tone analysis |

**Examples:**

```json
// Block toxic inputs (score > 0.5)
{
  "name": "galileo.luna2",
  "config": {
    "metric": "input_toxicity",
    "operator": "gt",
    "target_value": 0.5,
    "galileo_project": "my-project"
  }
}

// Block prompt injection attempts
{
  "name": "galileo.luna2",
  "config": {
    "metric": "prompt_injection",
    "operator": "gt",
    "target_value": 0.7,
    "on_error": "deny"
  }
}

// Flag potential hallucinations (warn but allow)
{
  "name": "galileo.luna2",
  "config": {
    "metric": "hallucination",
    "operator": "gt",
    "target_value": 0.6
  }
}

// Using a central stage (pre-defined server-side rules)
{
  "name": "galileo.luna2",
  "config": {
    "stage_type": "central",
    "stage_name": "production-safety",
    "galileo_project": "my-project"
  }
}
```

**Use Cases:**
- Toxicity and harassment detection
- Prompt injection protection
- PII leakage prevention
- Hallucination flagging
- Tone and sentiment analysis

---

## Key Advantages

### 🛡️ Safety Without Code Changes
Add guardrails to any agent with a simple decorator. No need to modify your agent's core logic.

```python
from agent_control import control

@control()
async def chat(message: str) -> str:
    return await llm.generate(message)
```

### ⚡ Runtime Configuration
Update controls without redeploying your application. Critical for:
- Responding to emerging threats
- Tuning thresholds based on real-world data
- A/B testing different safety controls

### 🎯 Centralized Control Management
Define controls once, apply them to multiple agents. Security teams can manage controls independently from development teams.

```
┌─────────────────────────────────────────────────────┐
│             Control Collection                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ Control Set │  │ Control Set │  │ Control Set │ │
│  │  (Safety)   │  │ (Compliance)│  │  (Quality)  │ │
│  └─────────────┘  └─────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐      ┌─────────┐      ┌─────────┐
   │ Agent A │      │ Agent B │      │ Agent C │
   └─────────┘      └─────────┘      └─────────┘
```

### 📊 Full Observability
Every evaluation is logged with:
- Trace IDs for debugging
- Execution timestamps
- Match confidence scores
- Detailed metadata

Answer questions like: *"Why was this blocked?"* or *"What threats did we stop this week?"*

### 🔌 Pluggable Architecture
Use built-in evaluators or bring your own. The evaluator system supports:
- Simple pattern matching (regex, word lists)
- AI-powered detection (toxicity, prompt injection, hallucination)
- Custom business logic

### ⚖️ Configurable Risk Tolerance
Choose how to handle failures:
- `on_error: "deny"` — Fail closed (block on error)
- `on_error: "allow"` — Fail open (permit on error)

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         Your Application                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                     @control() decorator                    │  │
│  │                            │                                │  │
│  │                            ▼                                │  │
│  │  ┌──────────┐    ┌─────────────────┐    ┌──────────────┐   │  │
│  │  │  Input   │───▶│  Agent Control  │───▶│    Output    │   │  │
│  │  │          │    │     Engine      │    │              │   │  │
│  │  └──────────┘    └─────────────────┘    └──────────────┘   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Agent Control Server                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │  Controls  │  │Control Link│  │ Evaluators │  │   Agents   │  │
│  │    API     │  │    API     │  │  Registry  │  │    API     │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                         Evaluator Ecosystem                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │   Regex    │  │    List    │  │   Luna-2   │  │   Custom   │  │
│  │ Evaluator  │  │ Evaluator  │  │ Evaluator  │  │ Evaluators │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Description |
|-----------|-------------|
| **SDK** | Python client library with `@control()` decorator |
| **Server** | FastAPI service that stores and evaluates controls |
| **Engine** | Core evaluation logic (can run locally or server-side) |
| **Evaluators** | Extensible evaluators for different detection methods |
| **Models** | Shared Pydantic models for type-safe communication |

---

## Creating Custom Evaluators

Partners and developers can create custom evaluators to extend Agent Control with their own detection capabilities.

### Evaluator Interface

Every evaluator implements the `Evaluator` base class:

```python
from typing import Any

from agent_control_models import EvaluatorResult
from agent_control_evaluators import (
    Evaluator,
    EvaluatorConfig,
    EvaluatorMetadata,
    register_evaluator,
)


class MyEvaluatorConfig(EvaluatorConfig):
    """Configuration schema for your evaluator."""
    threshold: float = 0.5
    custom_option: str = "default"


@register_evaluator
class MyEvaluator(Evaluator[MyEvaluatorConfig]):
    """Your custom evaluator."""

    metadata = EvaluatorMetadata(
        name="my-evaluator",
        version="1.0.0",
        description="Detects custom patterns using proprietary logic",
        requires_api_key=True,  # Set to True if you need credentials
        timeout_ms=5000,
    )
    config_model = MyEvaluatorConfig

    def __init__(self, config: MyEvaluatorConfig) -> None:
        """Initialize with validated configuration."""
        super().__init__(config)
        # Set up any clients, load models, etc.

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """
        Evaluate the input data.
        
        Args:
            data: The content to evaluate (string, dict, etc.)
            
        Returns:
            EvaluatorResult with:
              - matched: bool — Did this trigger the control?
              - confidence: float — How confident (0.0-1.0)?
              - message: str — Human-readable explanation
              - metadata: dict — Additional context for logging
        """
        # Your detection logic here
        score = await self._analyze(data)
        
        return EvaluatorResult(
            matched=score > self.config.threshold,
            confidence=score,
            message=f"Custom analysis score: {score:.2f}",
            metadata={
                "score": score,
                "threshold": self.config.threshold,
            }
        )
    
    async def _analyze(self, data: Any) -> float:
        """Your proprietary analysis logic."""
        # Call your API, run your model, etc.
        return 0.0
```

### Evaluator Registration

Evaluators are discovered automatically via Python entry points. To make your evaluator available:

1. **Create a Python package** with your evaluator class decorated with `@register_evaluator`
2. **Register as an entry point** in your `pyproject.toml`:
   ```toml
   [project.entry-points."agent_control.evaluators"]
   my-evaluator = "my_package.evaluator:MyEvaluator"
   ```
3. **Install it** in the Agent Control environment

```bash
# Install your evaluator
pip install my-custom-evaluator

# It's now available
```

### Optional Dependencies

If your evaluator has optional dependencies, override `is_available()`:

```python
try:
    import optional_dep
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

@register_evaluator
class MyEvaluator(Evaluator[MyEvaluatorConfig]):
    @classmethod
    def is_available(cls) -> bool:
        return AVAILABLE
```

When `is_available()` returns `False`, the evaluator is silently skipped during registration.

### Evaluator Best Practices

| Practice | Why |
|----------|-----|
| **Use Pydantic for config** | Automatic validation and documentation |
| **Implement timeouts** | Prevent slow evaluators from blocking agents |
| **Return confidence scores** | Enable threshold-based filtering |
| **Include metadata** | Helps with debugging and observability |
| **Handle errors gracefully** | Respect the `on_error` configuration |
| **Make API calls async** | Don't block the event loop |

### Example: Third-Party Integration

Here's how a partner might integrate their content moderation API:

```python
@register_evaluator
class ContentModerationEvaluator(Evaluator[ContentModerationEvaluatorConfig]):
    """Integration with Acme Content Moderation API."""
    
    metadata = EvaluatorMetadata(
        name="acme-content-mod",
        version="1.0.0",
        description="Acme Inc. content moderation",
        requires_api_key=True,
        timeout_ms=3000,
    )
    config_model = ContentModerationEvaluatorConfig

    def __init__(self, config: ContentModerationEvaluatorConfig) -> None:
        super().__init__(config)
        self.client = AcmeClient(api_key=os.getenv("ACME_API_KEY"))

    async def evaluate(self, data: Any) -> EvaluatorResult:
        result = await self.client.moderate(str(data))
        
        return EvaluatorResult(
            matched=result.flagged,
            confidence=result.confidence,
            message=result.reason,
            metadata={"categories": result.categories}
        )
```

---

## Getting Started

### Installation

```bash
# Core SDK
pip install agent-control

# Server
pip install agent-control-server

# With Galileo Luna-2 evaluator support
pip install agent-control-evaluator-galileo
# Or via convenience extra:
pip install agent-control-server[galileo]
```

### Quick Start

```python
import agent_control
from agent_control import control

# Initialize
agent_control.init(
    agent_name="my-agent",
    server_url="http://localhost:8000"
)

# Protect your agent
@control()
async def process_message(message: str) -> str:
    # Your agent logic here
    return await llm.generate(message)
```

### Running the Server

```bash
# Start the server
make server-run

# Or with Docker
docker-compose up
```

---

## Use Cases

| Use Case | Controls Used |
|----------|---------------|
| **Customer Support Bot** | Toxicity, PII detection, tone |
| **Code Assistant** | Prompt injection, secret detection |
| **Research Agent** | Hallucination detection, source verification |
| **Sales Copilot** | Compliance rules, competitor mentions |
| **Healthcare Agent** | PHI detection, medical advice disclaimers |

---

## Roadmap

- [ ] Web UI for control management
- [ ] More built-in evaluators (OpenAI Moderation, Perspective API, etc.)
- [ ] Metrics and analytics dashboard
- [ ] Multi-language SDK support (TypeScript, Go)
- [ ] Webhook notifications for violations

---

## Contributing

We welcome contributions! See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines.

### Adding an Evaluator

1. Fork the repository
2. Create your evaluator in `evaluators/builtin/src/agent_control_evaluators/` (for builtins) or in `evaluators/extra/` (for external packages)
3. Add tests in `evaluators/tests/`
4. Submit a pull request

---

## License

Apache 2.0 — See [LICENSE](../LICENSE) for details.
