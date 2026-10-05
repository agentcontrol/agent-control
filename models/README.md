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

## Control execution duration

Evaluation responses include an optional top-level `execution_duration_ms` on each
`ControlMatch` in `matches`, `non_matches`, and `errors`. It measures that control's
condition evaluation in wall-clock milliseconds, including the visited condition
leaves, evaluator work, and time waiting for an evaluator concurrency slot.
Control loading and request/response overhead are outside this measurement.

Completed evaluations include a nonnegative value, including evaluator failures.
Precheck failures have no duration, and canceled evaluations produce no result.
Older responses without the field remain valid. The Python SDK copies the value
to `ControlExecutionEvent.execution_duration_ms`; the TypeScript SDK exposes it as
`executionDurationMs`.

## Tests

```bash
cd models
uv run pytest
```

Full guide: https://docs.agentcontrol.dev/components/models
