# Agent Control Evaluator - detect-secrets

External evaluator that scans selector-selected payloads for likely secrets using
[`detect-secrets-async`](https://pypi.org/project/detect-secrets-async/), which wraps Yelp
`detect-secrets` in a bounded subprocess runtime.

- Entry point name: `yelp.detect_secrets`
- Transport/runtime: `detect-secrets-async`

## Installation

Install the evaluator package:

```bash
pip install agent-control-evaluator-detect-secrets
```

For local development from this repo:

```bash
uv pip install -e evaluators/contrib/detect_secrets
```

## Configuration

Evaluator config fields:

- `timeout_ms: int = 10000`
- `on_error: "allow" | "deny" = "allow"`
- `max_bytes: int = 1048576`
- `enabled_plugins: list[str] | None = None`
- `exclude_lines_regex: list[str] = []`

Notes:

- `enabled_plugins` takes upstream `detect-secrets` plugin class names such as
  `GitHubTokenDetector`.
- If `enabled_plugins` is omitted, the evaluator uses the pinned upstream default plugin set from
  `detect-secrets-async`.
- `exclude_lines_regex` uses RE2 syntax and blanks matching lines before scan submission so line
  numbering stays stable for plain string payloads.

## Behavior

- selector-selected `str` payloads are scanned directly
- selector-selected `dict` / `list` payloads are normalized to deterministic pretty JSON before
  scanning
- scalar numbers / booleans are normalized to JSON scalar text
- `None` produces `matched=False`

Safe metadata:

- `findings_count`
- `findings[]` with `type`, plus:
  - `line_number` for plain selected strings
  - `json_pointer` for normalized `dict` / `list` payloads when a finding maps back to a structural
    location
- `normalized_payload_type`
- `detect_secrets_version`
- `failure_mode` on evaluator failures
- `fallback_action` on fail-closed paths

Plaintext secrets, snippets, matching lines, and upstream `hashed_secret` are never surfaced.

## Usage

Once installed, the evaluator is auto-discovered:

```python
from agent_control_evaluators import discover_evaluators, get_evaluator

discover_evaluators()
DetectSecretsEvaluator = get_evaluator("yelp.detect_secrets")
```

Example control fragment:

```json
{
  "selector": { "path": "output" },
  "evaluator": {
    "name": "yelp.detect_secrets",
    "config": {
      "timeout_ms": 10000,
      "on_error": "allow",
      "enabled_plugins": ["GitHubTokenDetector"]
    }
  }
}
```
