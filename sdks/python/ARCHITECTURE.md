# Agent Control SDK Architecture

## Overview

The Agent Control SDK has been refactored to follow a modular architecture that mirrors the server's endpoint structure. This makes the codebase more maintainable, easier to navigate, and follows the single responsibility principle.

## Directory Structure

```
sdks/python/src/agent_protect/
├── __init__.py          # Main entry point, init() function, and exports
├── client.py            # Base HTTP client class
├── agents.py            # Agent management operations
├── policies.py          # Policy management operations
├── controls.py          # Control management operations
└── protection.py        # Protection check operations
```

## Module Responsibilities

### `client.py` - Base HTTP Client

**Purpose**: Provides the core HTTP client for server communication.

**Key Components**:
- `AgentProtectClient` class with async context manager support
- HTTP connection management
- Health check endpoint
- Base URL and timeout configuration

**Usage**:
```python
async with AgentProtectClient(base_url="http://localhost:8000") as client:
    # Use client with operation modules
    pass
```

### `agents.py` - Agent Operations

**Purpose**: Agent registration and retrieval operations.

**Endpoints Covered**:
- `POST /api/v1/agents/initAgent` - Register or update an agent
- `GET /api/v1/agents/{agent_id}` - Get agent details

**Functions**:
- `async def register_agent(client, agent, tools)` - Register an agent with tools
- `async def get_agent(client, agent_id)` - Fetch agent details by ID

**Usage**:
```python
import agent_protect

async with agent_protect.AgentProtectClient() as client:
    # Register agent
    response = await agent_protect.agents.register_agent(
        client, agent, tools=[...]
    )
    
    # Get agent
    agent_data = await agent_protect.agents.get_agent(client, "agent-id")
```

### `policies.py` - Policy Operations

**Purpose**: Policy creation and control association management.

**Endpoints Covered**:
- `PUT /api/v1/policies` - Create a new policy
- `POST /api/v1/policies/{policy_id}/control_sets/{control_set_id}` - Add control set to policy
- `DELETE /api/v1/policies/{policy_id}/control_sets/{control_set_id}` - Remove control set from policy
- `GET /api/v1/policies/{policy_id}/control_sets` - List policy control sets

**Functions**:
- `async def create_policy(client, name)` - Create a new policy
- `async def add_control_set_to_policy(client, policy_id, control_set_id)` - Associate control set
- `async def remove_control_set_from_policy(client, policy_id, control_set_id)` - Dissociate control set
- `async def list_policy_control_sets(client, policy_id)` - List all control sets in policy

**Usage**:
```python
import agent_protect

async with agent_protect.AgentProtectClient() as client:
    # Create policy
    result = await agent_protect.policies.create_policy(client, "prod-policy")
    policy_id = result["policy_id"]
    
    # Add control set to policy
    await agent_protect.policies.add_control_set_to_policy(
        client, policy_id=1, control_set_id=5
    )
```

### `controls.py` - Control Operations

**Purpose**: Control creation and rule association management.

**Endpoints Covered**:
- `PUT /api/v1/controls` - Create a new control
- `POST /api/v1/controls/{control_id}/rules/{rule_id}` - Add rule to control
- `DELETE /api/v1/controls/{control_id}/rules/{rule_id}` - Remove rule from control
- `GET /api/v1/controls/{control_id}/rules` - List control rules

**Functions**:
- `async def create_control(client, name)` - Create a new control
- `async def add_rule_to_control(client, control_id, rule_id)` - Associate rule
- `async def remove_rule_from_control(client, control_id, rule_id)` - Dissociate rule
- `async def list_control_rules(client, control_id)` - List all rules in control

**Usage**:
```python
import agent_protect

async with agent_protect.AgentProtectClient() as client:
    # Create control
    result = await agent_protect.controls.create_control(client, "pii-protection")
    control_id = result["control_id"]
    
    # Add rule to control
    await agent_protect.controls.add_rule_to_control(
        client, control_id=5, rule_id=10
    )
```

### `protection.py` - Protection Operations

**Purpose**: Runtime protection checks for agent operations.

**Endpoints Covered**:
- `POST /api/v1/protect` - Check if an operation is safe

**Functions**:
- `async def check_protection(client, agent_uuid, step, stage)` - Validate operation

**Usage**:
```python
import agent_protect
from agent_control_models import Step

async with agent_protect.AgentProtectClient() as client:
    result = await agent_protect.protection.check_protection(
        client=client,
        agent_uuid=agent.agent_id,
        step=Step(type="llm_inference", name="chat", input="User question", output=None),
        stage="pre"
    )
    print(f"Safe: {result.is_safe}")
```

### `__init__.py` - Main Entry Point

**Purpose**: Public API, convenience functions, and initialization.

**Key Functions**:
- `init(agent_name, agent_id, ...)` - Initialize Agent Control
- `get_agent(agent_id, server_url)` - Convenience function for fetching agents
- `current_agent()` - Get the currently initialized agent
- `protect(step_name, **data_sources)` - Decorator for rule enforcement

**Exports**:
- Core functions: `init`, `current_agent`, `get_agent`, `protect`
- Client class: `AgentProtectClient`
- Operation modules: `agents`, `policies`, `controls`, `protection`
- Models (if available): `Agent`, `Step`, `StepSchema`, etc.

## Design Principles

### 1. Separation of Concerns
Each module handles operations for a specific server endpoint category. This makes it easy to:
- Find relevant code quickly
- Understand what each module does
- Maintain and extend functionality

### 2. Module-First API
All operations are accessed via module functions that take a client as the first parameter:

```python
# Pattern: module.operation(client, ...args)
await agent_protect.policies.create_policy(client, "my-policy")
await agent_protect.controls.add_rule_to_control(client, 5, 10)
```

This pattern:
- Makes it clear which endpoint category you're working with
- Allows for easy mocking in tests
- Provides a clean, functional API

### 3. Convenience Functions
High-level convenience functions are provided in `__init__.py` for common operations:

```python
# Convenience: No need to manage client manually
agent_data = await agent_protect.get_agent("agent-id")

# Equivalent module-first approach:
async with AgentProtectClient() as client:
    agent_data = await agent_protect.agents.get_agent(client, "agent-id")
```

### 4. Backwards Compatibility
The refactoring maintains API compatibility:
- `init()` function works the same way
- `protect()` decorator unchanged
- Core exports remain the same
- Examples updated to show new patterns

## Migration Guide

### Before (Monolithic __init__.py)

```python
async with AgentProtectClient() as client:
    result = await client.create_policy("my-policy")
    await client.add_control_to_policy(1, 5)
```

### After (Modular Structure)

```python
import agent_protect

async with agent_protect.AgentProtectClient() as client:
    result = await agent_protect.policies.create_policy(client, "my-policy")
    await agent_protect.policies.add_control_set_to_policy(client, 1, 5)
```

**Benefits of New Structure**:
- ✅ Clear organization by endpoint category
- ✅ Easy to find operations: `agent_protect.policies.*`, `agent_protect.controls.*`
- ✅ Matches server structure for consistency
- ✅ Smaller, more maintainable files
- ✅ Better IDE autocomplete and navigation

## Testing Strategy

Each module can be tested independently:

```python
# Test policies module
from agent_protect import policies
from agent_protect.client import AgentProtectClient

async def test_create_policy():
    async with AgentProtectClient() as client:
        result = await policies.create_policy(client, "test-policy")
        assert "policy_id" in result
```

## Future Additions

When adding new endpoints:

1. **Create new module** if it's a new endpoint category (e.g., `rules.py`)
2. **Add operation functions** following the pattern: `async def operation(client, ...)`
3. **Update `__init__.py`** to export the new module
4. **Add convenience functions** if needed for common operations
5. **Update documentation** and examples

## File Sizes

The refactoring reduced file sizes significantly:

- **Before**: `__init__.py` ~900 lines
- **After**:
  - `__init__.py`: ~340 lines
  - `client.py`: ~75 lines
  - `agents.py`: ~90 lines
  - `policies.py`: ~145 lines
  - `controls.py`: ~145 lines
  - `protection.py`: ~120 lines

Total lines remain similar, but organized into focused, maintainable modules.

## Summary

The refactored SDK architecture provides:
- ✅ **Clear organization** matching server endpoints
- ✅ **Maintainability** through separation of concerns
- ✅ **Discoverability** via logical module names
- ✅ **Testability** with independent modules
- ✅ **Scalability** for future endpoint additions
- ✅ **Type safety** preserved throughout
- ✅ **Backwards compatibility** maintained
