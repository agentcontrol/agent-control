# Agent Control SDK Integration Tests

## Overview

These integration tests verify actual user workflows against a running Agent Control server. They ensure that the SDK functionality remains stable over time and that all operations work correctly end-to-end.

## Test Categories

### 1. Health & Connectivity (`test_integration_health.py`)
- Server health checks
- Client connection management
- Error handling for unreachable servers

### 2. Agent Operations (`test_integration_agents.py`)
- Agent registration workflow
- Agent retrieval workflow
- Agent updates via re-registration
- `init()` function integration
- `current_agent()` function
- Convenience functions

### 3. Policy Operations (`test_integration_policies.py`)
- Policy creation
- Control-to-policy associations
- Listing policy controls
- Idempotent operations
- Error handling (404, 409)

### 4. Control Operations (`test_integration_controls.py`)
- Control creation
- Rule-to-control associations
- Listing control rules
- Idempotent operations
- Error handling (404, 409)

## Prerequisites

### 1. Install Test Dependencies

```bash
cd sdks/python
uv pip install pytest pytest-asyncio httpx
```

Or add to `pyproject.toml`:

```toml
[dependency-groups]
test = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "httpx>=0.25.0"
]
```

### 2. Start the Agent Control Server

The server must be running before executing tests:

```bash
# From server directory
cd server
uv run uvicorn agent_control_server.main:app --reload
```

Or use the Makefile:

```bash
make server-dev
```

### 3. Configure Database (Optional)

For SQLite (local testing):

```bash
cd server
echo "DB_URL=sqlite+aiosqlite:///./test_agent_control.db" > .env
uv run alembic upgrade head
```

## Running Tests

### Run All Integration Tests

```bash
cd sdks/python
uv run pytest tests/ -v
```

### Run Specific Test Module

```bash
# Test agents only
uv run pytest tests/test_integration_agents.py -v

# Test policies only
uv run pytest tests/test_integration_policies.py -v

# Test controls only
uv run pytest tests/test_integration_controls.py -v

# Test health only
uv run pytest tests/test_integration_health.py -v
```

### Run Specific Test Function

```bash
uv run pytest tests/test_integration_agents.py::test_agent_registration_workflow -v
```

### Run with Coverage

```bash
uv pip install pytest-cov
uv run pytest tests/ --cov=agent_control --cov-report=html
```

### Run with Different Server URL

```bash
AGENT_CONTROL_TEST_URL=http://staging.example.com:8000 uv run pytest tests/ -v
```

## Test Output

Tests include detailed output showing what's being verified:

```
test_integration_agents.py::test_agent_registration_workflow 
✓ Agent registered: True
✓ Rules received: 0
PASSED

test_integration_policies.py::test_control_association_workflow 
✓ Control 5 added to policy 1
✓ Idempotent add verified
✓ Control appears in policy controls list
✓ Control removed from policy
✓ Idempotent remove verified
✓ Control no longer in policy controls list
PASSED
```

## Test Fixtures

### Session-Scoped Fixtures
- `server_url`: Server URL (from env or default)
- `verify_server_running`: Ensures server is accessible before tests

### Function-Scoped Fixtures
- `client`: Authenticated AgentProtectClient instance
- `unique_name`: Unique name generator for test resources
- `test_agent_id`: Unique agent ID for testing
- `test_agent`: Registered test agent
- `test_policy`: Created test policy
- `test_control`: Created test control
- `sample_steps`: Sample step definitions

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AGENT_CONTROL_TEST_URL` | Server URL for tests | `http://localhost:8000` |
| `AGENT_CONTROL_API_KEY` | API key for server authentication | (none) |

### Authentication

If the server has authentication enabled, you must provide an API key:

```bash
# Set the API key for tests
export AGENT_CONTROL_API_KEY="your-test-api-key"

# Run tests
uv run pytest tests/ -v
```

Or configure the server to disable authentication for local testing:

```bash
# In server/.env
AGENT_CONTROL_API_KEY_ENABLED=false
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: SDK Integration Tests

on: [push, pull_request]

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: agent_control_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd sdks/python
          uv pip install -e ".[test]"
      
      - name: Start server
        run: |
          cd server
          uv run uvicorn agent_control_server.main:app &
          sleep 5
        env:
          DB_URL: postgresql+psycopg://postgres:postgres@localhost/agent_control_test
          AGENT_CONTROL_API_KEYS: test-api-key-ci
          AGENT_CONTROL_ADMIN_API_KEYS: test-api-key-ci
      
      - name: Run tests
        run: |
          cd sdks/python
          uv run pytest tests/ -v --cov=agent_control
        env:
          AGENT_CONTROL_API_KEY: test-api-key-ci
```

## Test Data Cleanup

Some tests create data that persists in the database:
- **Agents**: Remain in database (no delete endpoint yet)
- **Policies**: Remain in database (no delete endpoint yet)
- **Controls**: Remain in database (no delete endpoint yet)

For clean testing:
1. Use a dedicated test database
2. Reset database between test runs
3. Use unique names (fixtures provide `unique_name`)

## Troubleshooting

### Tests are skipped

```
SKIPPED [1] tests/conftest.py:32: Agent Control server not available
```

**Solution**: Start the Agent Control server before running tests.

### Connection refused errors

```
httpx.ConnectError: [Errno 61] Connection refused
```

**Solution**: 
1. Check server is running: `lsof -ti:8000`
2. Verify server URL: `echo $AGENT_CONTROL_TEST_URL`
3. Check server logs for errors

### 404 Errors in rule association tests

```
⚠️  Rule 1 not found - skipping rule association test
```

**Solution**: This is expected if your test database has no rules. Tests gracefully handle this scenario.

### Database errors

```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table
```

**Solution**: Run database migrations:
```bash
cd server
uv run alembic upgrade head
```

## Writing New Tests

Follow this pattern for new integration tests:

```python
import pytest
import agent_control

@pytest.mark.asyncio
async def test_my_new_workflow(
    client: agent_control.AgentControlClient,
    test_agent: dict
):
    """
    Test my new workflow.
    
    Verifies:
    - Feature X works correctly
    - Feature Y returns expected data
    """
    # Arrange
    agent_id = test_agent["agent_id"]
    
    # Act
    result = await agent_control.my_module.my_operation(client, agent_id)
    
    # Assert
    assert result["success"] is True
    assert "data" in result
    
    print(f"✓ My new workflow works")
```

## Best Practices

1. **Use fixtures** for setup/teardown
2. **Generate unique names** for test resources
3. **Test idempotency** where applicable
4. **Verify error handling** (404, 409, etc.)
5. **Include helpful output** with print statements
6. **Document what you're testing** in docstrings
7. **Keep tests independent** - don't rely on test order

## Support

For issues or questions:
1. Check server logs: `cd server && uv run uvicorn ... --log-level debug`
2. Run tests with verbose output: `pytest -vv`
3. Check test fixtures in `conftest.py`
