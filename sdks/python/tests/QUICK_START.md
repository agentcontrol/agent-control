# Quick Start: Running Integration Tests

## TL;DR

```bash
# 1. Start the server
cd server
uv run uvicorn agent_control_server.main:app --reload

# 2. In another terminal, run tests
cd sdks/python
uv run pytest tests/ -v
```

## What Gets Tested

✅ **Agent Operations**
- Registration with tools
- Retrieval by ID
- Updates via re-registration
- `init()` and convenience functions

✅ **Policy Operations**
- Creation with unique names
- Control associations (add/remove)
- Listing controls
- Idempotency and error handling

✅ **Control Operations**
- Creation with unique names
- Rule associations (add/remove)
- Listing rules
- Idempotency and error handling

✅ **Health & Connectivity**
- Server health checks
- Client management
- Error handling

## Quick Commands

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific module
uv run pytest tests/test_integration_agents.py -v

# Run specific test
uv run pytest tests/test_integration_agents.py::test_agent_registration_workflow -v

# Run with coverage
uv run pytest tests/ --cov=agent_control --cov-report=html

# Show detailed output
uv run pytest tests/ -vv -s
```

## Expected Output

```
tests/test_integration_health.py::test_health_check_workflow PASSED
✓ Server health: healthy

tests/test_integration_agents.py::test_agent_registration_workflow PASSED
✓ Agent registered: True
✓ Rules received: 0

tests/test_integration_policies.py::test_policy_creation_workflow PASSED
✓ Policy created: ID 1
✓ Duplicate policy name correctly rejected

======================= 15 passed in 2.34s ========================
```

## Troubleshooting

**Problem**: Tests are skipped
```
SKIPPED [1] tests/conftest.py:32: Agent Control server not available
```

**Solution**: Start the server first!
```bash
cd server
uv run uvicorn agent_control_server.main:app
```

---

**Problem**: Connection refused
```
httpx.ConnectError: Connection refused
```

**Solution**: Check if port 8000 is in use
```bash
lsof -ti:8000  # Should show a process ID
```

---

**Problem**: Database errors
```
sqlalchemy.exc.OperationalError: no such table
```

**Solution**: Run migrations
```bash
cd server
uv run alembic upgrade head
```

## Environment Configuration

```bash
# Use custom server URL
export AGENT_CONTROL_TEST_URL=http://staging:8000

# Run tests
uv run pytest tests/ -v
```

## Next Steps

For detailed documentation, see [README.md](./README.md)

