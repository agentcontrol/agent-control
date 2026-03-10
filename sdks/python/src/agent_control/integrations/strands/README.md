# Agent Control + Strands Integration

High-level integration guide for adding Agent Control safety guardrails to [AWS Strands](https://github.com/strands-agents/sdk-python) agents using plugins and steering. This keeps your agent code unchanged while enforcing centralized policies.

## Overview

Agent Control integrates with Strands using two native extension points:

- **`AgentControlPlugin`** for deny-style enforcement at model and tool stages
- **`AgentControlSteeringHandler`** for steer-style guidance using Strands `Guide()`

Use the plugin for hard blocks and the steering handler for soft guidance. You can run both together.

## Installation

```bash
pip install agent-control-sdk[strands-agents]
```

## Integration Patterns

### Plugin pattern (hard blocks)

Use the plugin to enforce controls before and after model calls, tool calls, node transitions, and invocation.

```python
from agent_control.integrations.strands import AgentControlPlugin
from strands import Agent
import agent_control

agent_control.init(agent_name="my-agent")

plugin = AgentControlPlugin(
    agent_name="my-agent",
    event_control_list=[BeforeToolCallEvent, AfterToolCallEvent],
    enable_logging=True,
)

agent = Agent(
    name="my_agent",
    model=model,
    tools=[...],
    plugins=[plugin],
)
```

### Steering pattern (soft guidance)

Use the steering handler to convert steer actions into `Guide()` instructions for the next LLM call.

```python
from agent_control.integrations.strands import AgentControlSteeringHandler
from strands import Agent
import agent_control

agent_control.init(agent_name="banking-agent")

steering_handler = AgentControlSteeringHandler(
    agent_name="banking-agent",
    enable_logging=True,
)

agent = Agent(
    name="banking_agent",
    model=model,
    tools=[...],
    plugins=[steering_handler],
)
```

## What this enables

- **Multi-stage protection** across model calls, tool calls, and node transitions
- **Centralized policy updates** without redeploying agents
- **Hard blocks and soft guidance** depending on control action
- **Zero code changes** to existing Strands tools and workflows

## Error handling

- `ControlViolationError` for hard blocks (deny)
- `ControlSteerError` for steer actions (plugin only)

```python
from agent_control import ControlViolationError

try:
    result = await agent.invoke_async("Send email with SSN 123-45-6789")
except ControlViolationError as exc:
    print(f"Blocked by: {exc.control_name}")
```

## Docs and Examples

Read more about this integration and follow through examples:

- **Docs:** https://docs.agentcontrol.dev/integrations/strands
- **Examples:** ../../../../../../examples/strands_agents/
