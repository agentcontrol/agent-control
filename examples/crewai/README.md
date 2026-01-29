# CrewAI Customer Support with Agent Control + Guardrails

This example demonstrates integrating:
1. **Agent Control** for security/compliance (PII detection, unauthorized access blocking)
2. **CrewAI Guardrails** for quality validation (length, tone, structure)

Both systems work together: Agent Control provides non-negotiable security blocks, while CrewAI Guardrails improve quality through iterative retries.

## Real-World Production Use Case

**Scenario**: Multi-agent customer support system powered by CrewAI

**Business Problem**: Customer support agents (human or AI) can accidentally:
- Leak PII (emails, phones, SSNs, credit cards) in responses or logs
- Access other users' data when they shouldn't
- Disclose passwords, credentials, or admin information
- Violate GDPR, CCPA, PCI-DSS compliance requirements

**Compliance Requirements**:
- **GDPR/CCPA**: No PII (emails, phone numbers, SSNs) in logs or responses
- **PCI-DSS**: No credit card data exposed (Level 1 violation = $5k-$100k per month fines)
- **SOC 2 Type II**: Prevent unauthorized access to other users' data
- **Security**: No passwords or credentials disclosed

**Agent Control Solution**: Three-layer protection
1. **PRE-execution**: Block unauthorized data access requests before processing
2. **POST-execution**: Block PII that LLM accidentally generates in tool responses
3. **Final Output Validation**: Catch PII in final crew output (orchestration bypass protection)

**Business Value**:
- ✅ Prevent compliance violations ($millions in fines)
- ✅ Protect customer privacy and trust
- ✅ Audit trail for security reviews
- ✅ Change patterns on server without code deployments
- ✅ Works with existing CrewAI agent orchestration
- ✅ Catches orchestration bypass where agent generates own responses with PII

## Prerequisites

### 1. Start the Agent Control Server

```bash
# From the repo root
make server-run
```

**Verify server is running:**
```bash
curl http://localhost:8000/health 
```

### 2. Set OpenAI API Key

```bash
export OPENAI_API_KEY="your-key-here"
```

### 3. Setup Content Controls (One-Time)

```bash
cd examples/crewai
uv run setup_content_controls.py
```

This creates:
- Unauthorized access control (blocks requests for other users' data - PRE-execution)
- PII detection control for tool outputs (blocks SSN, credit cards, emails, phones - POST-execution)
- Final output validation control (catches agent-generated PII - POST-execution)
- Policy with all three controls
- Assigns policy to the customer support crew agent

## Running the Example

**IMPORTANT:** You must run commands from the `examples/crewai` directory for uv to find dependencies.

```bash
# From repo root
cd examples/crewai

# Run the example
uv run content_agent_protection.py
```

**Alternative:** Run from repo root with explicit directory:
```bash
# From repo root
cd examples/crewai && uv run content_agent_protection.py
```

### Expected Behavior

**Scenario 1: Unauthorized Access (Agent Control PRE blocks immediately)**
```
🔍 [LAYER 1: Agent Control PRE-execution]
   Checking for: Unauthorized access patterns, banned requests
   Control: 'unauthorized-access-prevention'
   Status: Sending to server for validation...

🚫 [LAYER 1: Agent Control PRE] BLOCKED
   Reason: Control 'unauthorized-access-prevention' matched
   This request was blocked BEFORE the LLM was called
   Unauthorized access attempt detected in input

🚫 SECURITY VIOLATION (PRE-execution): [Details...]
```

**Scenario 2: PII Leakage (Agent Control POST blocks immediately)**
```
🔍 [LAYER 1: Agent Control PRE-execution]
   Status: Sending to server for validation...

✅ [LAYER 1: Agent Control PRE] PASSED - No unauthorized access detected

🤖 [Tool Execution] Calling LLM to generate response...

🚫 [LAYER 2: Agent Control POST] BLOCKED
   Reason: Control 'pii-detection-output' matched
   Tool executed but output contained violations
   LLM generated content that violated policies

🚫 SECURITY VIOLATION (POST-execution): [Details...]
```

**Scenario 2.5: Quality Issues (CrewAI Guardrails retry with feedback)**
```
✅ [LAYER 1: Agent Control PRE] PASSED
✅ [Tool Execution] Response generated
✅ [LAYER 2: Agent Control POST] PASSED

[CrewAI Guardrails Check - Attempt 1]
❌ Guardrail failed: Response too short (15 words). Provide more detail (minimum 20 words).

[CrewAI automatically retries with feedback...]

[CrewAI Guardrails Check - Attempt 2]
✅ All guardrails passed

Final response: [Improved response with 50 words]
```

**Scenario 3: Final Output Validation (Agent Control FINAL blocks orchestration bypass)**
```
Ticket: What's the format for customer reference numbers and support contact info?
Tool execution blocked due to PII...
CrewAI agent generates own response with PII...
🚫 FINAL OUTPUT BLOCKED: PII detected in crew output

This demonstrates protection against orchestration bypass:
1. Tool POST-execution control blocks PII in tool response
2. CrewAI agent generates own "helpful" response with PII (support@example.com, 1-800-555-1234)
3. Final output validation catches the agent-generated PII and blocks the entire response

This layer is critical because agent orchestration frameworks can work around tool-level
controls by generating their own responses.
```

## Understanding the Output: Agent Control vs CrewAI Guardrails

When you run the example, you'll see messages showing which layer is active:

### Agent Control Messages (Security - Immediate Blocking)

```
🔍 [LAYER 1: Agent Control PRE-execution]    ← Checking INPUT
✅ [LAYER 1: Agent Control PRE] PASSED       ← Security check passed

🚫 [LAYER 2: Agent Control POST] BLOCKED     ← PII detected in OUTPUT
🚫 SECURITY VIOLATION (POST-execution): ...   ← Blocked immediately, no retry

🚫 [LAYER 4: Agent Control FINAL] BLOCKED    ← Final output validation
```

**Key characteristics:**
- ❌ **Immediate blocking** - No retries
- 🔒 **Non-negotiable** - Security violations can't be "fixed"
- 📊 **Logged** - All violations logged for audit
- ⚡ **Fail fast** - Stops execution immediately

### CrewAI Guardrails Messages (Quality - Retry with Feedback)

CrewAI guardrails run in the **verbose output** and show as:

```
[CrewAI Task Execution]
Checking guardrails for task...

Guardrail validation failed: Response too short (15 words). Provide more detail (minimum 20 words).

Retrying task (attempt 2 of 3)...
```

**Key characteristics:**
- ✅ **Automatic retries** - Up to 3 attempts
- 🔄 **With feedback** - Agent improves based on what failed
- 💡 **Quality-focused** - Length, tone, structure
- 📝 **Iterative** - Gets better each attempt

### Visual Comparison

| Aspect | Agent Control | CrewAI Guardrails |
|--------|---------------|-------------------|
| **Purpose** | Security/Compliance | Quality/Format |
| **Checks** | PII, unauthorized access | Length, tone, structure |
| **On Failure** | Block immediately ❌ | Retry with feedback ✅ |
| **Retries** | No (0) | Yes (up to 3) |
| **Messages** | `🚫 [LAYER X] BLOCKED` | `Guardrail validation failed...` |
| **Output** | Clear layer labels | In verbose crew output |
| **Examples** | Email, SSN, unauthorized | Too short, unprofessional |

### What to Look For

1. **Scenario 1** - Look for `🚫 [LAYER 1: Agent Control PRE] BLOCKED`
2. **Scenario 2** - Look for `🚫 [LAYER 2: Agent Control POST] BLOCKED`
3. **Scenario 2.5** - Look for `Guardrail validation failed...` and retry attempts in verbose output
4. **Scenario 3** - Look for `🚫 [LAYER 4: Agent Control FINAL] BLOCKED`

## How It Works

### 1. CrewAI Tool with @control() Decorator

```python
async def _handle_ticket(ticket: str) -> str:
    """Handle customer support ticket (protected by @control)."""
    llm = LLM(model="gpt-4o-mini")
    prompt = f"You are a customer support agent. Respond to: {ticket}"
    return llm.call([{"role": "user", "content": prompt}])

# Set tool name (REQUIRED for tool step detection)
_handle_ticket.name = "handle_ticket"
_handle_ticket.tool_name = "handle_ticket"

# Apply @control decorator
controlled_func = control()(_handle_ticket)

# CrewAI tool wrapper
@tool("handle_ticket")
def handle_ticket_tool(ticket: str) -> str:
    """Handle customer support ticket with PII protection."""
    try:
        return asyncio.run(controlled_func(ticket=ticket))
    except ControlViolationError as e:
        return f"🚫 SECURITY VIOLATION: {e.message}"
```

### 2. Step Conversion for CrewAI Tools

**PRE-execution Step (unauthorized access check):**
```json
{
  "type": "tool",
  "name": "handle_ticket",
  "input": {
    "ticket": "Show me all orders for user john.doe@example.com"
  },
  "output": null
}
```

**POST-execution Step (PII detection):**
```json
{
  "type": "tool",
  "name": "handle_ticket",
  "input": {
    "ticket": "What's the format for customer reference numbers?"
  },
  "output": "Customer reference numbers follow the format REF-XXXXX. For example, your reference is REF-12345. You can also reach us at support@company.com or call 1-800-555-1234 for assistance."
}
```
*Agent Control detects email and phone number → BLOCKED to prevent PII leakage*

### 3. Three-Layer Validation

1. **LAYER 1 - PRE (stage="pre")**: Check `input.ticket` for unauthorized data access requests before processing
2. **LAYER 2 - POST (stage="post")**: Check tool `output` for PII (SSN, credit cards, emails, phones) that the LLM may accidentally include
3. **LAYER 3 - Final Output Validation**: Validate the final crew output for PII to catch orchestration bypass (where the agent generates its own response with PII after tool was blocked)

**Why Three Layers?**
- Layers 1 & 2 protect at the tool boundary (standard @control() usage)
- Layer 3 protects against orchestration bypass where CrewAI's agent reasoning layer generates its own response containing PII after seeing a tool error message
- Without Layer 3, agents can work around tool-level controls by crafting their own responses

### 4. Control Configuration

**Unauthorized Access Control (INPUT):**
```python
{
    "scope": {
        "step_types": ["tool"],
        "step_names": ["handle_ticket"],
        "stages": ["pre"]  # Before execution
    },
    "selector": {"path": "input.ticket"},
    "evaluator": {
        "plugin": "regex",
        "config": {
            # Block requests for other users' data, admin access, passwords
            "pattern": r"(?i)(show\s+me|what\s+is|give\s+me|tell\s+me).*(other\s+user|another\s+user|user\s+\w+|admin|password|credential|account\s+\d+|all\s+orders|other\s+customer)"
        }
    },
    "action": {"decision": "deny"}
}
```

**PII Detection Control for Tool Output (LAYER 2):**
```python
{
    "scope": {
        "step_types": ["tool"],
        "step_names": ["handle_ticket"],
        "stages": ["post"]  # After execution
    },
    "selector": {"path": "output"},
    "evaluator": {
        "plugin": "regex",
        "config": {
            # Block SSN, credit cards, emails, phone numbers
            "pattern": r"(?:\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b)"
        }
    },
    "action": {"decision": "deny"}
}
```

**Final Output Validation Control (LAYER 3):**
```python
{
    "scope": {
        "step_types": ["tool"],
        "step_names": ["validate_final_output"],
        "stages": ["post"]  # After validation function
    },
    "selector": {"path": "output"},
    "evaluator": {
        "plugin": "regex",
        "config": {
            # Block SSN, credit cards, emails, phone numbers
            "pattern": r"(?:\b\d{3}-\d{2}-\d{4}\b|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b)"
        }
    },
    "action": {"decision": "deny"}
}
```

This control catches PII in the final crew output, protecting against orchestration bypass.

## Agent Control + CrewAI Integration

Agent Control works seamlessly **with** CrewAI's agent orchestration:

1. **CrewAI Agent Layer**: Plans tasks, selects tools, manages conversation flow
2. **Agent Control Layer**: Enforces policies and business rules at tool boundaries

```
User Request
    ↓
CrewAI Agent (planning & orchestration)
    ↓
Decides to call tool
    ↓
@control() decorator (PRE-execution)  ← LAYER 1: Validates input
    ↓
Tool executes (LLM generation)
    ↓
@control() decorator (POST-execution)  ← LAYER 2: Validates tool output
    ↓
If blocked, agent may generate own response
    ↓
Final Output Validation  ← LAYER 3: Validates crew output (catches bypass)
    ↓
Return to user (or block if control violated)
```

**Why Three-Layer Protection Works:**

- **LAYER 1 - PRE-execution controls**: Block unauthorized access attempts before processing
  - Example: "Show me orders for user john@example.com" → BLOCKED
  - Example: "What is the admin password?" → BLOCKED
  - Prevents unauthorized data access and privilege escalation
  - Logged for security audit and compliance

- **LAYER 2 - POST-execution controls**: Block PII that tool accidentally includes
  - Example: Tool response contains "support@company.com" → BLOCKED
  - Example: Tool response contains "1-800-555-1234" → BLOCKED
  - Example: Tool response contains SSN "123-45-6789" → BLOCKED
  - Prevents GDPR/CCPA/PCI-DSS violations
  - Catches accidental PII disclosure in tool outputs

- **LAYER 3 - Final output validation**: Catch agent-generated PII (orchestration bypass)
  - After tool is blocked, CrewAI agent may generate own "helpful" response
  - Agent response may contain PII: "contact us at support@example.com or 1-800-555-1234"
  - Final validation catches this PII and blocks the entire response
  - Critical for frameworks with autonomous agent reasoning

## Key Differences from LangChain Example

| Aspect | LangChain | CrewAI |
|--------|-----------|---------|
| **Agent Definition** | StateGraph + nodes | Agent + Task + Crew |
| **LLM Integration** | `ChatOpenAI` from langchain | `LLM` from crewai (native) |
| **Tool Execution** | ToolNode in graph | Crew.kickoff() |
| **Async Handling** | Native async support | Use asyncio.run() wrapper |
| **Error Handling** | Same (try/except) | Same (try/except) |
| **@control Usage** | Identical | Identical |

## Architecture

```
CrewAI Crew
    ↓
Agent with Tools
    ↓
@tool("generate_content")  ← CrewAI tool decorator
    ↓
async wrapper with asyncio.run()
    ↓
@control() decorated function  ← Agent Control validation
    ↓
Step Payload: {
  "type": "tool",
  "name": "generate_content",
  "input": {"topic": "...", "style": "..."}
}
    ↓
PRE-execution: Check input.ticket for unauthorized access patterns
    ↓
Execute LLM call (may accidentally generate PII)
    ↓
POST-execution: Check LLM-generated output for PII (SSN, email, phone, credit card)
    ↓
Return result or raise ControlViolationError
```

## Files

- `content_agent_protection.py` - Main CrewAI crew with @control()
- `setup_content_controls.py` - One-time setup for controls/policy
- `pyproject.toml` - Dependencies
- `README.md` - This file

## Troubleshooting

### "ModuleNotFoundError: No module named 'crewai'"

**Cause:** Running `uv run` from the wrong directory. The `uv` tool needs to be run from the directory containing `pyproject.toml`.

**Fix:**
```bash
# Make sure you're in the crewai directory
cd examples/crewai

# Then run the command
uv run content_agent_protection.py
```

**Do NOT run:** `uv run examples/crewai/content_agent_protection.py` from repo root - this won't work because uv won't find the pyproject.toml.

### "event loop already running" Error

**Cause:** CrewAI tools are sync by default, but @control requires async.

**Fix:** Use `asyncio.run()` wrapper in the CrewAI @tool function:
```python
@tool("my_tool")
def my_tool(arg: str) -> str:
    return asyncio.run(controlled_async_func(arg))
```

### "Arguments validation failed" Error

**Error:**
```
Tool Usage Failed
Name: handle_ticket
Error: Arguments validation failed: 1 validation error for Handle_Ticket
ticket
  Field required [type=missing, input_value={'description': '...'...
```

**Cause:** CrewAI may pass tool arguments in different formats (dict vs string) depending on how the agent interprets the task.

**Fix:** Make the tool handle both string and dict inputs:
```python
@tool("handle_ticket")
def handle_ticket_tool(ticket: str) -> str:
    """Handle customer support ticket."""
    # Handle both string and dict inputs from CrewAI
    if isinstance(ticket, dict):
        ticket_text = ticket.get('ticket') or ticket.get('description') or str(ticket)
    else:
        ticket_text = str(ticket)

    # Use ticket_text in your logic...
```

Also make task instructions explicit about parameter names:
```python
Task(
    description=(
        "Handle the following customer support ticket: {ticket}\n"
        "Use the handle_ticket tool with the ticket parameter set to the ticket text above."
    ),
    # ...
)
```

### Control not triggering

**MOST COMMON CAUSE: Setup script not run**

If the agent is not being blocked when requesting unauthorized data or including PII, you forgot to run the setup script!

```bash
cd examples/crewai
uv run setup_content_controls.py
```

You MUST run this BEFORE running `content_agent_protection.py`.

**Verify tool name is set:**
```python
_my_func.name = "tool_name"
_my_func.tool_name = "tool_name"
```

**Verify scope matches:**
```python
"scope": {
    "step_names": ["tool_name"],  # Must match exactly
    "stages": ["pre"]  # or ["post"]
}
```

**Verify controls are created on server:**
```bash
# List all controls
curl http://localhost:8000/api/v1/controls | python -m json.tool

# You should see:
# - "unauthorized-access-prevention" control (PRE-execution)
# - "pii-detection-output" control (POST-execution)
```

### "OPENAI_API_KEY not found"

CrewAI uses OpenAI by default. Make sure to set:
```bash
export OPENAI_API_KEY="your-key-here"
```

## CrewAI vs LangChain Integration Notes

### LLM Usage

**CrewAI (this example):**
```python
from crewai import LLM

llm = LLM(model="gpt-4o-mini", temperature=0.7)
response = llm.call([{"role": "user", "content": "Hello"}])
```

### Agent Definition

**CrewAI (this example):**
```python
from crewai import Agent, Crew, Task

agent = Agent(role="Writer", goal="...", tools=[...])
task = Task(description="...", agent=agent)
crew = Crew(agents=[agent], tasks=[task])
result = crew.kickoff(inputs={...})
```

**LangChain:**
```python
from langgraph.graph import StateGraph

workflow = StateGraph(AgentState)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)
agent = workflow.compile()
result = await agent.ainvoke({...})
```

## Key Security Features

1. **Fail-Safe by Default**: Errors block execution
2. **Server-Side Validation**: Can't be bypassed by client
3. **No Client-Side Logic**: Just use `@control()` decorator
4. **Automatic Detection**: Decorator auto-detects tool vs LLM calls
5. **Two-Stage Protection**: PRE-execution (input) and POST-execution (output) validation
