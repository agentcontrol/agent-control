# Agent Control Models

Shared Pydantic models used by the server and SDKs. These models define the API contract for agents, controls, evaluation requests, and responses.

## What this package provides

- Strongly typed request/response schemas
- Consistent validation and serialization across server and SDKs
- A single source of truth for model changes

## Usage

```python
from agent_control_models import Agent, Step

agent = Agent(agent_name="support-bot", agent_description="Support agent")
step = Step(type="llm", name="chat", input="hello")
```

## Tests

```bash
cd models
uv run pytest
```

Full guide: https://docs.agentcontrol.dev/components/models
