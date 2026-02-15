# Layered Governance Demo

**AgentControl (Safety) + Strands Steering (Quality)**

Shows how two governance layers work together for safe AND high-quality agent interactions.

---

## Two Governance Layers

### 🛡️ Safety Layer (AgentControl) - Hard Blocks
- **Purpose**: Compliance and risk prevention
- **Action**: BLOCKS unsafe content (hard stop)
- **Example**: Blocks PII (SSN, credit cards, emails)

### ✨ Quality Layer (Strands Steering) - Contextual Guidance
- **Purpose**: Just-in-time feedback through modular prompting
- **Action**: GUIDES agents with contextual feedback
- **Examples**:
  - Prevents unauthorized promises
  - Detects hallucinations
  - Provides contextual guidance

---

## Quick Start

### 1. Install Dependencies
```bash
cd examples/strands_integration
uv sync  # or: pip install -e .
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env and add:
#   OPENAI_API_KEY=your_key_here
#   AGENT_CONTROL_URL=http://localhost:8000
```

### 3. Start AgentControl Server
```bash
# Terminal 1
cd server
make run
```

### 4. Setup Controls
```bash
# Terminal 2
cd examples/strands_integration/steering_demo
python setup_steering_controls.py
```

You should see:
```
✅ Layered Governance Demo Ready

Control created:
  • validate-refund-amount - Blocks refunds over $10,000 (AgentControl)

Quality layer:
  • QualitySteeringHandler - Guides graceful error handling (Steering)
```

### 5. Launch the Demo
```bash
# Terminal 3
cd examples/strands_integration/steering_demo
streamlit run layered_governance_demo.py
```

Open http://localhost:8501 in your browser.

### 6. Try It Out

Click the **"🔄 Layered Governance Demo"** button to see:
- User requests $15,000 refund (exceeds $10K policy limit)
- 🛡️ **AgentControl blocks** the refund tool call
- Agent responds with vague "safety violation" error
- ✨ **Steering guides** agent to be specific about the $10K policy
- Agent provides helpful response with manager escalation option

Watch the console and sidebar dashboard to see both layers in action!

---

## How It Works

```
User Input: "I want a full refund of $15,000 for my order ORD-12345. Process it now!"
    ↓
Agent checks order status
    ├─ Order: ORD-12345
    └─ Status: delivered, eligible_for_refund: true
    ↓
Agent attempts: process_refund(amount=15000)
    ↓
Safety Layer (AgentControl)
    ├─ Intercepts tool call via BeforeToolCallEvent
    ├─ Evaluates: validate-refund-amount control
    ├─ Match: 15000 > 10000 (5 digits)
    └─ 🛡️ BLOCKS: Sets event.cancel_tool = "Safety violation detected"
    ↓
Agent generates response: "safety violation detected... unable to process high refund amounts"
    ↓
Quality Layer (Steering)
    ├─ Detects: "violation" without "$10,000" policy details
    └─ ✨ GUIDES: "Be specific about the $10K policy and offer manager escalation"
    ↓
Agent retries → Better response with policy details and alternatives
    ↓
Safe + Quality Response ✅
```

### Integration

**Tools with @control decorator:**

```python
from strands import Agent, tool
import agent_control

@tool
@agent_control.control()
async def check_order_status(order_id: str) -> dict:
    """Check the status of a customer's order."""
    # Returns: {"status": "delivered", "eligible_for_refund": True}
    pass

@tool
@agent_control.control()
async def process_refund(order_id: str, amount: float, reason: str) -> dict:
    """
    Process a refund for a customer order.

    AgentControl validates amount via server-side control:
    - Blocks amounts over $10,000 (validate-refund-amount control)
    """
    pass
```

**Quality Steering Handler:**

```python
from strands.experimental.steering import SteeringHandler, Guide, Proceed

class QualitySteeringHandler(SteeringHandler):
    async def steer_after_model(self, *, agent, message, stop_reason, **kwargs):
        response = self._extract_text(message).lower()

        # Check for vague technical errors without policy details
        if "violation" in response or "safety" in response:
            if "$10,000" not in response and "10,000" not in response:
                return Guide(
                    "⚠️ Don't give vague technical errors! Be specific about the $10K policy "
                    "and offer manager escalation for amounts over the limit."
                )

        return Proceed()
```

**Agent with both layers:**

```python
from agent_control_hook import AgentControlHook
from strands.hooks import BeforeInvocationEvent, BeforeModelCallEvent, AfterModelCallEvent, BeforeToolCallEvent

# Safety layer (AgentControl)
safety_hook = AgentControlHook(
    agent_uuid=agent_uuid,
    agent_name="steering-demo",
    event_control_list=[
        BeforeInvocationEvent,    # Check user input
        BeforeModelCallEvent,     # Check model input
        AfterModelCallEvent,      # Check model output
        BeforeToolCallEvent       # Validate tool calls
    ]
)

# Quality layer (Steering)
quality_handler = QualitySteeringHandler()

# Attach both layers
agent = Agent(
    model=model,
    tools=[check_order_status, process_refund],
    hooks=[safety_hook, quality_handler]  # Both layers work together!
)
```

---

## Value Proposition

**Without Layered Governance:**
```
User: "I need a $15,000 refund for order ORD-12345!"
Bot: "There was a safety violation detected. Unable to process."
```
✅ Safe but ❌ Poor UX (vague, unhelpful)

**With Layered Governance:**
```
User: "I need a $15,000 refund for order ORD-12345!"

🛡️ AgentControl blocks excessive amount
✨ Steering guides helpful response

Bot: "I understand you'd like a $15,000 refund. Our policy allows
     refunds up to $10,000. For amounts over this limit, I can
     connect you with our manager approval team who can help."
```
✅ Safe + ✅ Quality (specific, empathetic, actionable)

---

## Dashboard

The sidebar shows real-time governance activity:

**Layer Status**
- 🛡️ Safety: Active/Inactive
- ✨ Quality: Active

**Statistics**
- Safety Blocks
- Quality Guidances
- Total Requests

---

## Learn More

- **[common/README.md](../common/README.md)** - AgentControlHook API and usage
- **[common/INTEGRATION_GUIDE.md](../common/INTEGRATION_GUIDE.md)** - Integration concepts and patterns
- **[Interactive Demo](../interactive_demo/)** - Basic safety controls example
