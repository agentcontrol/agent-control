# Agent Control Models

Shared data models for Agent Control server and SDK. This package contains all the Pydantic models used for API requests, responses, and data validation.

## Why Shared Models?

Having a separate models package provides several benefits:

1. **Single Source of Truth**: Models are defined once and used everywhere
2. **Type Safety**: Ensures server and SDK use identical data structures
3. **Versioning**: Models can be versioned independently
4. **Easier Maintenance**: Changes propagate automatically to both server and SDK
5. **Clear Contract**: API contract is explicitly defined

## Common Patterns in Popular Python Packages

This design follows patterns used by popular packages:

### 1. Shared Models (Our Approach)
- **Google APIs** (`google-api-core`): Separate proto/model definitions
- **Stripe** (`stripe-python`): Models package shared across components
- **PySpark**: Shared types and schemas

### 2. JSON/Pydantic Hybrid
- **FastAPI**: Pydantic models with JSON serialization
- **Anthropic SDK**: Pydantic models with `.to_dict()` and `.from_dict()`
- **OpenAI SDK**: Typed models with JSON compatibility

## Installation

This package is typically installed as a dependency:

```bash
# Server depends on it
cd server
uv add agent-control-models

# SDK depends on it
cd sdk
uv add agent-control-models
```

## Usage

### Agent Models

```python
from agent_control_models import Agent, Step

# Create an agent
agent = Agent(
    agent_name="Customer Support Bot",
    agent_id="support-bot-v1",
    agent_description="Handles customer inquiries",
    agent_version="1.0.0"
)

# Create a step
step = Step(
    type="llm_inference",
    name="chat",
    input="Hello, how can I help?",
    output="I'm here to assist you!"
)
```

### Control Models

```python
from agent_control_models import ControlDefinition, ControlScope, ControlAction

# Define a control
control = ControlDefinition(
    name="block-toxic-input",
    description="Block toxic user messages",
    enabled=True,
    execution="server",
    scope=ControlScope(
        step_types=["llm_inference"],
        stages=["pre"]
    ),
    action=ControlAction(decision="deny")
)
```

### Evaluation Models

```python
from agent_control_models import EvaluationRequest, EvaluationResponse

# Create evaluation request
request = EvaluationRequest(
    agent_uuid="agent-uuid-here",
    step=Step(
        type="llm_inference",
        name="chat",
        input="User message"
    ),
    stage="pre"
)

# Evaluation response
response = EvaluationResponse(
    allowed=True,
    violated_controls=[]
)
```

## Models

### Core Models

#### BaseModel

Base class for all models with common utilities:

- `model_dump()`: Convert to Python dictionary (Pydantic v2)
- `model_dump_json()`: Convert to JSON string (Pydantic v2)
- `model_validate()`: Create from dictionary (Pydantic v2)

Configuration:
- Accepts both snake_case and camelCase fields
- Validates on assignment
- JSON-compatible serialization

#### Agent

Agent metadata and configuration.

**Fields:**
- `agent_name` (str): Human-readable agent name
- `agent_id` (str): Unique identifier
- `agent_description` (Optional[str]): Agent description
- `agent_version` (Optional[str]): Agent version
- `tools` (Optional[List[str]]): List of available tools
- `metadata` (Optional[Dict]): Additional metadata

#### Step

Represents a single step in agent execution.

**Fields:**
- `type` (str): Step type (e.g., "llm_inference", "tool")
- `name` (str): Step name
- `input` (Optional[Any]): Step input data
- `output` (Optional[Any]): Step output data
- `context` (Optional[Dict]): Additional context

#### ControlDefinition

Complete control specification.

**Fields:**
- `name` (str): Control name
- `description` (Optional[str]): Control description
- `enabled` (bool): Whether control is active
- `execution` (str): Execution mode ("server" or "local")
- `scope` (ControlScope): When to apply the control
- `selector` (ControlSelector): What data to evaluate
- `evaluator` (EvaluatorConfig): How to evaluate
- `action` (ControlAction): What to do on match

#### EvaluationRequest

Request for evaluating controls.

**Fields:**
- `agent_uuid` (str): Agent identifier
- `step` (Step): Step to evaluate
- `stage` (str): Evaluation stage ("pre" or "post")

#### EvaluationResponse

Response from control evaluation.

**Fields:**
- `allowed` (bool): Whether the step is allowed
- `violated_controls` (List[str]): Names of violated controls
- `evaluation_results` (Optional[List]): Detailed evaluation results

#### HealthResponse

Health check response.

**Fields:**
- `status` (str): Health status ("healthy")
- `version` (str): Server version

## Design Patterns

### 1. Pydantic v2

All models use Pydantic v2 for validation and serialization:

```python
from agent_control_models import Agent

# Create with validation
agent = Agent(
    agent_name="My Agent",
    agent_id="my-agent-v1"
)

# Serialize to dict
agent_dict = agent.model_dump()

# Serialize to JSON
agent_json = agent.model_dump_json()

# Deserialize from dict
agent_copy = Agent.model_validate(agent_dict)
```

### 2. Type Safety

Models provide strong typing throughout the stack:

```python
from agent_control_models import Step, EvaluationRequest

# Type-safe step creation
step = Step(
    type="llm_inference",
    name="chat",
    input="Hello"
)

# Type-safe evaluation request
request = EvaluationRequest(
    agent_uuid="uuid-here",
    step=step,
    stage="pre"
)
```

### 3. Extensibility

Models support additional metadata for extensibility:

```python
from agent_control_models import Agent

# Add custom metadata
agent = Agent(
    agent_name="Support Bot",
    agent_id="support-v1",
    metadata={
        "team": "customer-success",
        "environment": "production",
        "custom_field": "value"
    }
)
```

## Development

### Adding New Models

1. Create a new file in `src/agent_control_models/`
2. Define models extending `BaseModel`
3. Export in `__init__.py`
4. Update both server and SDK to use the new models

Example:

```python
# src/agent_control_models/auth.py
from .base import BaseModel

class AuthRequest(BaseModel):
    api_key: str
    
# src/agent_control_models/__init__.py
from .auth import AuthRequest

__all__ = [..., "AuthRequest"]
```

### Testing

```bash
cd models
uv run pytest
```

## Best Practices

1. **Always extend BaseModel**: Get free JSON/dict conversion
2. **Use Field for validation**: Add constraints and descriptions
3. **Keep models simple**: No business logic, just data
4. **Version carefully**: Model changes affect both server and SDK
5. **Document fields**: Use Field's `description` parameter
6. **Use Optional appropriately**: Mark optional fields clearly

