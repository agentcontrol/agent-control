# ATR Threat Rules Evaluator for Agent Control

Regex-based AI agent threat detection using [ATR (Agent Threat Rules)](https://agentthreatrule.org) community rules.

## Features

- 20 bundled rules covering OWASP Agentic Top 10 categories
- Pure regex detection -- no API keys, no external calls
- Sub-5ms evaluation time
- Configurable severity threshold and category filtering
- Auto-discovered via Python entry points

## Categories

| Category | Rules | Description |
|----------|-------|-------------|
| prompt-injection | 5 | Direct, indirect, jailbreak, system override, multi-turn |
| agent-manipulation | 2 | Cross-agent attacks, goal hijacking |
| context-exfiltration | 2 | Data exfil via tools, context window leaks |
| privilege-escalation | 2 | Unauthorized escalation, role assumption |
| tool-poisoning | 5 | Tool definition poisoning, hidden instructions, credentials, reverse shell |
| skill-compromise | 1 | Malicious skill installation |
| excessive-autonomy | 2 | Unauthorized actions, safety bypass |
| data-poisoning | 1 | Training data poisoning |

## Configuration

```python
from agent_control_evaluator_atr.threat_rules import ATRConfig

config = ATRConfig(
    min_severity="medium",    # "low", "medium", "high", "critical"
    block_on_match=True,      # matched=True when threat detected
    categories=[],            # empty = all categories
    on_error="allow",         # "allow" (fail-open) or "deny" (fail-closed)
)
```

## Installation

```bash
uv pip install -e evaluators/contrib/atr
```

## License

Apache-2.0. ATR rules are MIT-licensed.
