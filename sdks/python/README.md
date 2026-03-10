# Agent Control - Python SDK

Python SDK for adding safety controls and guardrails to AI agents. Protect tools and LLM calls with server-side or local policy enforcement.

## Installation

```bash
pip install agent-control-sdk
```

## Quick Start

```python
import agent_control
from agent_control import control

# Initialize
agent_control.init(agent_name="my-agent")

# Protect a tool with decorator
@control()
async def search_database(query: str) -> str:
    return db.execute(query)
```

Controls are defined centrally and enforced automatically at runtime. See [Python SDK Documentation](https://docs.agentcontrol.dev/sdk/python-sdk) for complete reference.
