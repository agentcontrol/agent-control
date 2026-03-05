# Agent Control Evaluator - Cisco AI Defense (Chat Inspection)

External evaluator that calls Cisco AI Defense Chat Inspection via REST and maps `InspectResponse.is_safe` to Agent Control decisions.

- Entry point name: `ai_defense.chat_inspect`
- Transport: direct HTTP (httpx)

## Installation

Install from PyPI (if available):

```bash
pip install agent-control-evaluator-ai-defense
```

Or install from the workspace for local development:

```bash
uv pip install -e evaluators/contrib/ai_defense
```

Alternatively, install via the builtin evaluators package extra (one-liner):

```bash
pip install agent-control-evaluators[ai_defense]
```

- Build wheel from the repo root (contrib package only):

  ```bash
  make aidefense-build
  ```

To run the server with this evaluator enabled, see `examples/ai_defense/README.md` for setup and seeding instructions.

## Configuration

Set the `AI_DEFENSE_API_KEY` environment variable:

```bash
export AI_DEFENSE_API_KEY="<your_key>"
```

Evaluator config fields (all optional unless stated):

- `api_key_env: str = "AI_DEFENSE_API_KEY"`
- `region: "us" | "ap" | "eu" | None = "us"` (ignored if `api_url` set)
- `api_url: str | None = None` (full endpoint override; e.g., `https://us.../api/v1/inspect/chat`)
- `timeout_ms: int = 15000`
- `on_error: "allow" | "deny" = "allow"` (fail-open or fail-closed on transport/response errors)
- `payload_field: "input" | "output" | None = None`
  - When set, synthesizes a single message from that field; `input` → `role=user`, `output` → `role=assistant`.
- `messages_strategy: "single" | "history" = "history"`
  - `history` forwards an existing `messages` list in the selected data if present; falls back to single otherwise.
- `metadata: dict[str, Any] | None = None` (forwarded to API per OpenAPI spec)
- `inspect_config: dict[str, Any] | None = None` (forwarded to API per OpenAPI spec)

## Available Evaluators

| Name | Description |
|------|-------------|
| `ai_defense.chat_inspect` | Cisco AI Defense Chat Inspection |

Behavior mapping:

- `is_safe == false` → `EvaluatorResult.matched = true` (e.g., a `deny` action will block)
- `is_safe == true` → `matched = false`
- Errors or invalid responses → `matched = (on_error == "deny")`; error details in `metadata`; the `error` field is set only when `matched=False` per model invariant

## Minimal server control configuration

Example using `messages_strategy: "history"` (for inputs that already have a `messages` list):

```
{
  "description": "Apply Cisco AI Defense Security, Safety, and Privacy guardrails",
  "enabled": true,
  "execution": "server",
  "scope": { "step_types": ["llm"], "stages": ["pre", "post"] },
  "selector": { "path": "input" },
  "evaluator": {
    "name": "ai_defense.chat_inspect",
    "config": {
      "api_key_env": "AI_DEFENSE_API_KEY",
      "region": "us",
      "timeout_ms": 15000,
      "on_error": "allow",
      "messages_strategy": "history"
    }
  },
  "action": { "decision": "deny" },
  "tags": ["ai_defense", "safety"]
}
```

```
{
  "description": "Apply Cisco AI Defense Security, Safety, and Privacy guardrails",
  "enabled": true,
  "execution": "server",
  "scope": { "step_types": ["llm"], "stages": ["pre", "post"] },
  "selector": { "path": "input" },
  "evaluator": {
    "name": "ai_defense.chat_inspect",
    "config": {
      "api_key_env": "AI_DEFENSE_API_KEY",
      "region": "us",
      "timeout_ms": 15000,
      "on_error": "allow",
      "messages_strategy": "single",
      "payload_field": "input"
    }
  },
  "action": { "decision": "deny" },
  "tags": ["ai_defense", "safety"]
}
```

## Usage

Once installed, the evaluator is automatically discovered:

```python
from agent_control_evaluators import discover_evaluators, get_evaluator

discover_evaluators()
ChatInspectEvaluator = get_evaluator("ai_defense.chat_inspect")
```

Or import directly:

```python
import asyncio
from agent_control_evaluator_ai_defense.chat_inspect import ChatInspectEvaluator, ChatInspectEvaluatorConfig

cfg = ChatInspectEvaluatorConfig(
    region="us",
    timeout_ms=15000,
    on_error="allow",
    messages_strategy="history",
    payload_field="input",
)
ev = ChatInspectEvaluator(cfg)

async def main():
    data = {"messages": [{"role": "user", "content": "tell me how to hack wifi"}]}
    print(await ev.evaluate(data))

asyncio.run(main())
```

## Notes

- Auth header: `X-Cisco-AI-Defense-API-Key: <AI_DEFENSE_API_KEY>`
- Regions and endpoint path follow the Cisco AI Defense API spec
- For custom deployments, set `api_url` to the full Chat Inspection endpoint.

## Documentation

- Cisco AI Defense Inspection API reference: https://developer.cisco.com/docs/ai-defense-inspection/introduction/
- Cisco Security Console (get API Key): https://security.cisco.com
- Cisco AI Defense User Guide: https://securitydocs.cisco.com/docs/ai-def/user/97384.dita
- Regional API base URLs used by this evaluator:
  - US: `https://us.api.inspect.aidefense.security.cisco.com`
  - AP: `https://ap.api.inspect.aidefense.security.cisco.com`
  - EU: `https://eu.api.inspect.aidefense.security.cisco.com`
  - Chat Inspection path: `/api/v1/inspect/chat`
