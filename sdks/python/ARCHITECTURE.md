# Agent Control SDK Architecture

## Overview

The Agent Control SDK follows a modular architecture that mirrors the server's endpoint structure. This makes the codebase more maintainable, easier to navigate, and follows the single responsibility principle.

## Directory Structure

```
sdks/python/src/agent_control/
├── __init__.py               # Main entry point, init() function, and exports
├── client.py                 # Base HTTP client class
├── agents.py                 # Agent management operations
├── policies.py               # Policy management operations
├── controls.py               # Control management operations
├── control_decorators.py     # @control() decorator implementation
├── evaluation.py             # Evaluation and evaluator operations
├── observability.py          # Observability and telemetry
├── settings.py               # SDK configuration and settings
├── tracing.py                # Distributed tracing support
├── py.typed                  # PEP 561 type marker
└── evaluators/               # Evaluator base classes and discovery system
    ├── __init__.py           # Evaluator discovery, registration, and Luna-2 integration
    └── base.py               # Base Evaluator and EvaluatorMetadata classes
```

## Module Responsibilities

### `client.py` - Base HTTP Client

**Purpose**: Provides the core HTTP client for server communication.

**Key Components**:
- `AgentControlClient` class with async context manager support
- HTTP connection management
- Health check endpoint
- Base URL and timeout configuration

**Usage**:
```python
async with AgentControlClient(base_url="http://localhost:8000") as client:
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
import agent_control

async with agent_control.AgentControlClient() as client:
    # Register agent
    response = await agent_control.agents.register_agent(
        client, agent, tools=[...]
    )
    
    # Get agent
    agent_data = await agent_control.agents.get_agent(client, "agent-id")
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
import agent_control

async with agent_control.AgentControlClient() as client:
    # Create policy
    result = await agent_control.policies.create_policy(client, "prod-policy")
    policy_id = result["policy_id"]
    
    # Add control set to policy
    await agent_control.policies.add_control_set_to_policy(
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
import agent_control

async with agent_control.AgentControlClient() as client:
    # Create control
    result = await agent_control.controls.create_control(client, "pii-protection")
    control_id = result["control_id"]
    
    # Add rule to control
    await agent_control.controls.add_rule_to_control(
        client, control_id=5, rule_id=10
    )
```

### `control_decorators.py` - Control Decorator

**Purpose**: Implements the `@control()` decorator for server-side policy evaluation.

**Key Components**:
- `@control()` decorator for protecting functions
- Automatic pre/post execution checks
- Integration with server-side controls

**Usage**:
```python
from agent_control import control

@control()
async def chat(message: str) -> str:
    """This function is protected by server-defined controls"""
    return await llm.generate(message)
```

### `evaluation.py` - Evaluation Operations

**Purpose**: Client-side and server-side evaluation management.

**Key Components**:
- Evaluator registration and management
- Evaluation execution
- Integration with control evaluation pipeline

### `observability.py` - Observability & Telemetry

**Purpose**: Provides observability features for agent execution.

**Key Components**:
- Telemetry collection
- Metrics tracking
- Execution logging

### `settings.py` - SDK Configuration

**Purpose**: Centralized configuration management for the SDK.

**Key Components**:
- Environment variable handling
- Configuration defaults
- Settings validation

### `tracing.py` - Distributed Tracing

**Purpose**: Distributed tracing support for agent operations.

**Key Components**:
- OpenTelemetry integration
- Span creation and management
- Context propagation

### `evaluators/` - Evaluator System

**Purpose**: Evaluator base classes, discovery, and registration system.

**Key Components**:
- Base evaluator classes (`Evaluator`, `EvaluatorMetadata`)
- Evaluator discovery via entry points
- Third-party evaluator integration (e.g., Luna-2, Guardrails AI)
- Registration functions for custom evaluators

**Structure**:
- `__init__.py` - Evaluator discovery (`discover_evaluators()`, `list_evaluators()`), registration (`register_evaluator()`), and optional Luna-2 integration
- `base.py` - Base `Evaluator` and `EvaluatorMetadata` classes (re-exported from `agent_control_models`)

**Usage**:
```python
from agent_control.evaluators import Evaluator, EvaluatorMetadata, discover_evaluators

# Discover all available evaluators (built-in and third-party)
discover_evaluators()

# Create custom evaluator by extending base class
class MyCustomEvaluator(Evaluator):
    pass
```

### `__init__.py` - Main Entry Point

**Purpose**: Public API, convenience functions, and initialization.

**Key Functions**:
- `init(agent_name, agent_id, ...)` - Initialize Agent Control
- `get_agent(agent_id, server_url)` - Convenience function for fetching agents
- `list_agents()` - List all registered agents
- `current_agent()` - Get the currently initialized agent
- `control()` - Decorator for server-side policy enforcement
- `create_control()`, `get_control()`, `list_controls()` - Control management
- `get_logger()` - SDK logging

**Exports**:
- Core functions: `init`, `current_agent`, `get_agent`, `control`
- Client class: `AgentControlClient`
- Operation modules: `agents`, `policies`, `controls`, `evaluation`
- Decorators: `control`, `ControlViolationError`
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
await agent_control.policies.create_policy(client, "my-policy")
await agent_control.controls.add_rule_to_control(client, 5, 10)
```

This pattern:
- Makes it clear which endpoint category you're working with
- Allows for easy mocking in tests
- Provides a clean, functional API

### 3. Convenience Functions
High-level convenience functions are provided in `__init__.py` for common operations:

```python
# Convenience: No need to manage client manually
agent_data = await agent_control.get_agent("agent-id")

# Equivalent module-first approach:
async with AgentControlClient() as client:
    agent_data = await agent_control.agents.get_agent(client, "agent-id")
```

### 4. API Stability
The SDK maintains a stable public API:
- `init()` function for agent initialization
- `control()` decorator for policy enforcement
- Core exports remain stable across versions
- Examples demonstrate best practices

## Migration Guide

### Before (Monolithic __init__.py)

```python
async with AgentControlClient() as client:
    result = await client.create_policy("my-policy")
    await client.add_control_to_policy(1, 5)
```

### After (Modular Structure)

```python
import agent_control

async with agent_control.AgentControlClient() as client:
    result = await agent_control.policies.create_policy(client, "my-policy")
    await agent_control.policies.add_control_set_to_policy(client, 1, 5)
```

**Benefits of New Structure**:
- ✅ Clear organization by endpoint category
- ✅ Easy to find operations: `agent_control.policies.*`, `agent_control.controls.*`
- ✅ Matches server structure for consistency
- ✅ Smaller, more maintainable files
- ✅ Better IDE autocomplete and navigation

## Testing Strategy

Each module can be tested independently:

```python
# Test policies module
from agent_control import policies
from agent_control.client import AgentControlClient

async def test_create_policy():
    async with AgentControlClient() as client:
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

## Module Sizes

Current module organization:

- `__init__.py`: ~1000 lines (main entry point with convenience functions)
- `client.py`: ~100 lines (HTTP client)
- `agents.py`: ~180 lines (agent operations)
- `policies.py`: ~160 lines (policy operations)
- `controls.py`: ~430 lines (control operations)
- `control_decorators.py`: ~580 lines (@control decorator implementation)
- `evaluation.py`: ~400 lines (evaluation operations)
- `observability.py`: ~700 lines (telemetry and observability)
- `settings.py`: ~160 lines (configuration)
- `tracing.py`: ~240 lines (distributed tracing)

Total organized into focused, maintainable modules with clear responsibilities.

## Summary

The Agent Control SDK architecture provides:
- ✅ **Clear organization** matching server endpoints and responsibilities
- ✅ **Maintainability** through separation of concerns
- ✅ **Discoverability** via logical module names
- ✅ **Testability** with independent modules
- ✅ **Scalability** for future endpoint and feature additions
- ✅ **Type safety** with full type annotations
- ✅ **Extensibility** through evaluator system
- ✅ **Observability** with built-in tracing and telemetry
