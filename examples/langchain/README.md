# LangChain SQL Agent with Agent Control

This example demonstrates integrating Agent Control with a LangChain SQL agent to block dangerous SQL operations.

## Prerequisites

### 1. Start the Agent Control Server (for remote execution)

**IMPORTANT: You must start/restart the server to load the SQL evaluator!**

```bash
cd path/to/agent-control

# Kill any old servers
pkill -f "uvicorn agent_control_server"

# Start the server
cd server
make run
# OR: uv run --package agent-control-server uvicorn agent_control_server.main:app --port 8000
```

**Verify evaluators are loaded:**
```bash
curl http://localhost:8000/api/v1/evaluators | python -m json.tool
# Should show: {"sql": {"name": "sql", "version": "1.0.0", ...}, ...}
```

### 2. Set OpenAI API Key

```bash
export OPENAI_API_KEY="your-key-here"
```

### 3. Setup SQL Controls (One-Time)

```bash
cd examples/langchain
uv run setup_sql_controls.py
```

This creates:
- SQL safety control (blocks DROP, DELETE, TRUNCATE, ALTER, GRANT)
- Direct association of the control with the SQL agent

> For local execution, create the control with `execution: "sdk"` in
> `setup_sql_controls.py` (see `sql_control_data_sdk`) and enable
> `AGENT_CONTROL_LOCAL_EVAL=true` when running the agent.

## Running the Example

```bash
cd examples/langchain
uv run sql_agent_protection.py
```

### Local vs Remote Control Execution

**Remote (server-side) controls**:
- Default mode
- Requires running the Agent Control server
- Uses `@control()` to call `/api/v1/evaluation` on the server

**Local (SDK-side) controls**:
- Set `AGENT_CONTROL_LOCAL_EVAL=true`
- Controls must be configured with `execution: "sdk"`
- Uses `agent_control.check_evaluation_with_local(...)` before executing the tool

Example:
```bash
export AGENT_CONTROL_LOCAL_EVAL=true
uv run sql_agent_protection.py
```

### Expected Behavior

**Safe Query (SELECT with LIMIT):**
```
✅ Safety check passed for: SELECT * FROM Track LIMIT 3
[Query executes successfully]
```

**Dangerous Query (DROP TABLE):**
```
✗ Execution blocked!
Error: Control evaluation failed...
[Query is blocked, table is NOT dropped]
```

## How It Works

### 1. The `@control()` Decorator

```python
async def _execute_query(query: str):
    return query_tool.invoke(query)

# Set tool name (required for tool step detection)
_execute_query.name = "sql_db_query"
_execute_query.tool_name = "sql_db_query"

# Apply decorators
safe_query_tool = tool(
    "sql_db_query",
    description="Execute SQL query with safety checks"
)(control()(_execute_query))
```

### 2. Automatic Tool Call Detection

The `@control()` decorator:
1. Detects this is a tool (via `name` attribute)
2. Creates a `Step` payload with `type="tool"`, `name`, and `input`
3. Sends to server for evaluation **before** execution
4. Blocks execution if control triggers deny action

### 3. SQL Control Execution

The SQL is evaluated using the `sql` evaluator:
- Parses the query
- Checks for blocked operations (DROP, DELETE, etc.)
- Validates LIMIT clauses
- Returns deny/allow decision

### 4. Fail-Safe Error Handling

If the control check fails with an error:
- ✅ Execution is BLOCKED (fail-safe)
- ✅ RuntimeError is raised
- ❌ Query never executes

## Troubleshooting

### "Evaluator 'sql' not found"

**Cause:** Server was started before evaluators were installed, or using old code.

**Fix:**
```bash
# Kill old server
pkill -f "uvicorn agent_control_server"

# Restart server
cd server && make run
```

### "Control already associated with agent"

**Cause:** Setup script was run multiple times and the direct association already exists.

**Fix:** This is expected/idempotent; you can ignore and continue.

### DROP TABLE still executes

**Causes:**
1. Server not running or evaluators not loaded (remote mode)
2. Control not associated directly with the agent
3. Control data missing/invalid (control not returned to agent)
4. Local mode enabled but control is still `execution: "server"`

**Fix:**
1. Restart server with `make run`
2. Re-run `setup_sql_controls.py`
3. Verify decorator code is up-to-date

## Architecture

```
LangChain Agent
    ↓
@tool("sql_db_query")  ← Marks as LangChain tool
@control()            ← Applies server-side validation
    ↓
Step Payload: {
  "type": "tool",
  "name": "sql_db_query",
  "input": {"query": "DROP TABLE..."}
}
    ↓
Agent Control Server
    ↓
SQL Evaluator Execution
    ↓
DENY (blocks DROP) or ALLOW (safe query)
    ↓
Back to Decorator
    ↓
Raise ControlViolationError (DENY) or Execute (ALLOW)
```

## Files

- `sql_agent_protection.py` - Main SQL agent with `@control()` decorator
- `setup_sql_controls.py` - One-time setup script for controls/direct associations
- `pyproject.toml` - Dependencies and configuration
- `README.md` - This file

## Key Security Features

1. **Fail-Safe by Default**: Errors block execution
2. **Server-Side Validation**: Remote controls enforced centrally
3. **SDK-Side Validation**: Local controls run before tool execution
4. **Automatic Detection**: Decorator auto-detects tool vs LLM calls
