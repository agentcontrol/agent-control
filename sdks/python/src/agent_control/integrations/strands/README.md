# Agent Control + Strands Integration

Seamless safety controls for [AWS Strands](https://github.com/awslabs/strands) agents using hooks and plugins - no code changes needed.

## Overview

This integration provides two complementary approaches for adding Agent Control safety guardrails to Strands agents:

1. **`AgentControlPlugin`** - Hook-based integration for tool-stage and model-stage deny checks
2. **`AgentControlSteeringHandler`** - Steering-based integration that converts Agent Control steer actions into Strands Guide() instructions

Both integrate natively with Strands' hook and plugin systems, providing automatic safety without modifying your agent code.

## Installation

```bash
pip install agent-control-sdk[strands-agents]
```

This installs Agent Control SDK with Strands support.

## Components

### AgentControlPlugin

Hook-based integration that enforces Agent Control policies at multiple stages of agent execution:

- **Before/After Model Calls** - Check LLM inputs and outputs
- **Before/After Tool Calls** - Validate tool arguments and results
- **Before/After Node Calls** - Control workflow transitions
- **Before Invocation** - Initial request validation

**Key Features:**
- Automatic registration with Strands' hook registry
- Configurable event control list (choose which stages to check)
- Hard blocks (deny actions) raise `ControlViolationError`
- Steer actions raise `ControlSteerError` with steering context
- Optional callback support for custom handling

**Usage:**

```python
from agent_control.integrations.strands import AgentControlPlugin
from strands import Agent
import agent_control

# Initialize Agent Control
agent_control.init(agent_name="my-agent")

# Create plugin with desired hook stages
plugin = AgentControlPlugin(
    agent_name="my-agent",
    event_control_list=[BeforeToolCallEvent, AfterToolCallEvent],
    enable_logging=True
)

# Add to agent
agent = Agent(
    name="my_agent",
    model=model,
    tools=[...],
    plugins=[plugin]
)
```

### AgentControlSteeringHandler

Steering-based integration that uses Strands' experimental steering API to guide agents based on Agent Control steer actions.

**Key Features:**
- Converts Agent Control steer matches into Strands `Guide()` actions
- Evaluates LLM outputs after model calls (post-generation)
- Deny matches raise `ControlViolationError` (hard block)
- Steer matches return `Guide()` with steering context (soft guidance)
- Tracks steering statistics (`steers_applied`, `last_steer_info`)

**Usage:**

```python
from agent_control.integrations.strands import AgentControlSteeringHandler
from strands import Agent
import agent_control

# Initialize Agent Control
agent_control.init(agent_name="banking-agent")

# Create steering handler
steering_handler = AgentControlSteeringHandler(
    agent_name="banking-agent",
    enable_logging=True
)

# Add to agent as plugin
agent = Agent(
    name="banking_agent",
    model=model,
    tools=[...],
    plugins=[steering_handler]
)
```

**Steering Flow:**
1. LLM generates output
2. Steering handler evaluates output against Agent Control policies
3. If steer match found:
   - Extracts steering context from control result
   - Returns `Guide(steering_context)` to Strands
   - Strands adds guidance to next LLM call
   - Agent retries with improved context
4. If deny match found:
   - Raises `ControlViolationError`
   - Execution stops

## Architecture

### How It Works

Both integrations use Agent Control's evaluation engine to check agent behavior against server-side policies:

1. **Agent Control Server** - Centralized policy engine that evaluates controls
2. **Strands Agent** - AWS Strands agent with hook/plugin integration
3. **Integration Layer** - `AgentControlPlugin` or `AgentControlSteeringHandler`
4. **Hook/Plugin System** - Strands' native extension points

```
┌─────────────────────────────────────────────────────────────┐
│                     Strands Agent                           │
│  ┌─────────────┐      ┌──────────────┐                     │
│  │   Model     │──┬──▶│  Tool Call   │                     │
│  │    Call     │  │   └──────────────┘                     │
│  └─────────────┘  │                                         │
│         │         │                                         │
│         ▼         │                                         │
│  ┌──────────────────────────────────────┐                  │
│  │  AgentControlPlugin (Hooks)          │                  │
│  │  - BeforeModelCallEvent              │                  │
│  │  - AfterModelCallEvent               │                  │
│  │  - BeforeToolCallEvent               │                  │
│  │  - AfterToolCallEvent                │                  │
│  └──────────────────────────────────────┘                  │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────┐                  │
│  │  AgentControlSteeringHandler         │                  │
│  │  - steer_after_model()               │                  │
│  │  - Returns Guide() or Proceed()      │                  │
│  └──────────────────────────────────────┘                  │
│         │                                                    │
└─────────┼────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│              Agent Control Server                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Evaluation Engine                                     │ │
│  │  - Scope matching (stages, paths)                     │ │
│  │  - Evaluator execution (regex, PII, custom)           │ │
│  │  - Action determination (deny, steer, warn, allow)    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Dual-Layer Governance

You can use both components together for comprehensive protection:

```python
from agent_control.integrations.strands import (
    AgentControlPlugin,
    AgentControlSteeringHandler
)

# Hook layer: Hard blocks at tool execution
plugin = AgentControlPlugin(
    agent_name="banking-agent",
    event_control_list=[BeforeToolCallEvent, AfterToolCallEvent]
)

# Steering layer: Guidance at LLM output
steering = AgentControlSteeringHandler(
    agent_name="banking-agent"
)

# Both as plugins
agent = Agent(
    name="banking_agent",
    model=model,
    tools=[send_email, lookup_account],
    plugins=[plugin, steering]
)
```

**Layer Responsibilities:**
- **Plugin (Hooks)**: Enforces hard blocks on tool calls, prevents dangerous operations
- **Steering**: Guides LLM to rephrase/redact before tool calls happen

## Error Handling

Both integrations raise standard Agent Control exceptions:

- **`ControlViolationError`** - Hard block (deny action)
  - Contains: `control_id`, `control_name`, `message`, `metadata`
  - Should be caught and handled by your application

- **`ControlSteerError`** - Steering suggestion (steer action, plugin only)
  - Contains: `steering_context`, `control_name`
  - Can be caught to extract steering guidance

**Example:**

```python
from agent_control import ControlViolationError

try:
    result = await agent.invoke_async("Send email with SSN 123-45-6789")
except ControlViolationError as e:
    print(f"Blocked by: {e.control_name}")
    print(f"Reason: {e.message}")
    # Handle gracefully (log, retry, notify user, etc.)
```

## Examples

See complete working examples in the repository:

**[examples/strands_agents/](../../../../../../examples/strands_agents/)**

- **[Interactive Demo](../../../../../../examples/strands_agents/interactive_demo/)** - Customer support agent with PII blocking and SQL injection prevention
- **[Steering Demo](../../../../../../examples/strands_agents/steering_demo/)** - Banking email agent with dual-layer governance (hook + steering)

## Configuration

Both components support:

- **`agent_name`** (required) - Agent identifier for control lookup
- **`enable_logging`** (optional) - Enable debug logging (default: `True`)

**Plugin-specific:**
- **`event_control_list`** - List of Strands events to hook (default: all)
- **`on_control_match`** - Custom callback for control matches
- **`use_runtime_error`** - Raise `RuntimeError` instead of `ControlViolationError`

**Steering-specific:**
- **`steers_applied`** - Counter for applied steering actions
- **`last_steer_info`** - Last steering match info (for debugging/UI)

## Best Practices

1. **Use Plugin for Tool Protection** - Block dangerous tool calls before execution
2. **Use Steering for Content Guidance** - Guide LLM to rephrase sensitive outputs
3. **Combine Both for Defense-in-Depth** - Hook denies dangerous actions, steering improves drafts
4. **Test Controls Incrementally** - Start with warn actions, promote to deny after validation
5. **Monitor Steering Stats** - Track `steers_applied` to understand agent behavior

## Requirements

- Python 3.12+
- `agent-control-sdk`
- `strands-agents` (AWS Strands framework)
- Running Agent Control server

## Links

- [Agent Control Documentation](https://docs.agentcontrol.dev)
- [AWS Strands GitHub](https://github.com/awslabs/strands)
- [Examples](../../../../../../examples/strands_agents/)
- [Agent Control Server](../../../../../../server/)
