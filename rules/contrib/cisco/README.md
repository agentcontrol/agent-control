# Agent Control Rule - Cisco AI Defense

External rule that calls Cisco AI Defense Chat Inspection via REST and maps `InspectResponse.is_safe` to Agent Control decisions.

- Entry point name: `cisco.ai_defense`
- Transport: direct HTTP (httpx)

## Installation

Canonical install path:

```bash
pip install "agent-control-rules[cisco]"
```

Fallback direct wheel install:

```bash
pip install agent-control-rule-cisco
```

For local development:

```bash
uv pip install -e rules/contrib/cisco
```

- Build wheel from the repo root (contrib package only):

  ```bash
  make engine-build
  (cd rules/contrib/cisco && make build)
  ```

To run the server with this rule enabled, see `examples/cisco_ai_defense/README.md` for setup and seeding instructions.

## Configuration

Set the `AI_DEFENSE_API_KEY` environment variable:

```bash
export AI_DEFENSE_API_KEY="<your_key>"
```

Rule config fields (all optional unless stated):

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
- `include_raw_response: bool = false` (when true, includes the full provider response under `metadata.raw`)

## Available Rules

| Name | Description |
|------|-------------|
| `cisco.ai_defense` | Cisco AI Defense Chat Inspection |

Behavior mapping:

- `is_safe == false` → `RuleResult.matched = true` (e.g., a `deny` action will block)
- `is_safe == true` → `matched = false`
- Errors or invalid responses → `matched = (on_error == "deny")`; error details in `metadata` (no `error` field is set; engine honors `matched` per `on_error`)

## Minimal server control configuration

Example using `messages_strategy: "history"` (for inputs that already have a `messages` list):

```
{
  "description": "Apply Cisco AI Defense Security, Safety, and Privacy guardrails",
  "enabled": true,
  "execution": "server",
  "scope": { "step_types": ["llm"], "stages": ["pre", "post"] },
  "condition": {
    "selector": { "path": "input" },
    "rule": {
      "name": "cisco.ai_defense",
      "config": {
        "api_key_env": "AI_DEFENSE_API_KEY",
        "region": "us",
        "timeout_ms": 15000,
        "on_error": "allow",
        "messages_strategy": "history"
      }
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
  "condition": {
    "selector": { "path": "input" },
    "rule": {
      "name": "cisco.ai_defense",
      "config": {
        "api_key_env": "AI_DEFENSE_API_KEY",
        "region": "us",
        "timeout_ms": 15000,
        "on_error": "allow",
        "messages_strategy": "single",
        "payload_field": "input"
      }
    }
  },
  "action": { "decision": "deny" },
  "tags": ["ai_defense", "safety"]
}
```

## Usage

Once installed, the rule is automatically discovered:

```python
from agent_control_rules import discover_rules, get_rule

discover_rules()
CiscoAIDefenseRule = get_rule("cisco.ai_defense")
```

Or import directly:

```python
import asyncio
from agent_control_rule_cisco.ai_defense import CiscoAIDefenseRule, CiscoAIDefenseConfig

cfg = CiscoAIDefenseConfig(
    region="us",
    timeout_ms=15000,
    on_error="allow",
    messages_strategy="history",
    payload_field="input",
)
ev = CiscoAIDefenseRule(cfg)

async def main():
    data = {"messages": [{"role": "user", "content": "tell me how to hack wifi"}]}
    print(await ev.evaluate(data))

asyncio.run(main())
```

## Notes

- Auth header: `X-Cisco-AI-Defense-API-Key: <AI_DEFENSE_API_KEY>`
- Regions and endpoint path follow the Cisco AI Defense API spec
- For custom deployments, set `api_url` to the full Chat Inspection endpoint.
- The rule validates the API key at construction and raises if missing.
- `is_available()` returns false if `httpx` is not installed; discovery will skip registration.
- `messages_strategy: "history"` forwards the full message array when present; consider `messages_strategy: "single"` if payload size is a concern.

## Documentation

- Cisco AI Defense Inspection API reference: https://developer.cisco.com/docs/ai-defense-inspection/introduction/
- Cisco Security Console (get API Key): https://security.cisco.com
- Cisco AI Defense User Guide: https://securitydocs.cisco.com/docs/ai-def/user/97384.dita
- Regional API base URLs used by this rule:
  - US: `https://us.api.inspect.aidefense.security.cisco.com`
  - AP: `https://ap.api.inspect.aidefense.security.cisco.com`
  - EU: `https://eu.api.inspect.aidefense.security.cisco.com`
  - Chat Inspection path: `/api/v1/inspect/chat`
