# 🎯 Layered Governance Demo

**AgentControl (Safety) + Strands Steering (Quality)**

This demo showcases how two complementary governance systems work together to create safe AND high-quality agent interactions.

---

## 🧱 The Two Layers

### Layer 1: Safety (AgentControl) - Hard Stops
- **Purpose**: Compliance and risk prevention
- **Action**: BLOCKS unsafe content (hard stop)
- **Examples**:
  - ❌ Blocks PII leakage (SSN, credit cards, emails)
  - ❌ Blocks toxic/inappropriate language
  - ❌ Blocks policy violations

### Layer 2: Quality (Strands Steering) - Contextual Guidance
- **Purpose**: Provides modular prompting through just-in-time feedback
- **Action**: GUIDES agents with contextual feedback that appears when relevant, rather than front-loading all instructions
- **Examples**:
  - ✨ Detects when specialized expertise is needed
  - ✨ Guides agents to escalate security topics to specialists
  - ✨ Provides contextual feedback for appropriate responses

---

## 🚀 Quick Start

### 1. Setup

```bash
cd examples/strands_integration

# Install dependencies if needed
uv sync

# Ensure .env is configured
cp .env.example .env
# Edit .env with your OPENAI_API_KEY
```

### 2. Start AgentControl Server

```bash
# In terminal 1
cd ../../server && make run
```

### 3. Setup Safety Controls

```bash
# In terminal 2
cd steering_demo
python setup_steering_controls.py
```

This creates the AgentControl safety layer. The steering quality layer is code-based and requires no setup.

### 4. Run the Demo

```bash
streamlit run layered_governance_demo.py
```

---

## 🎮 How to Use

### Demo Scenario: Both Layers Working Together

Click the **🔐 Security Topic + PII Detection** button to see:

**User Input:**
```
"I'm worried about my account security. My SSN is 123-45-6789 - can you help me make my password stronger?"
```

**What Happens:**

1. **Safety Layer (AgentControl):** Detects SSN in user input → Blocks PII from being processed
2. **Routing:** PII detected → Routes to Security Specialist agent
3. **Quality Layer (Steering):** Support agent detects security topic → Provides contextual guidance to escalate to Security Specialist
4. **Final Response:** Security Specialist handles password guidance WITHOUT processing SSN

**Result:** Customer protected from PII exposure AND receives expert security guidance

This demonstrates the complete value proposition:
- ✅ **Safety**: AgentControl blocks SSN (compliance)
- ✅ **Quality**: Steering guides appropriate handoff (customer experience)
- ✅ **Complete Protection**: Both layers work together seamlessly
→ Steering **GUIDES** toward concise response

**💬 Off Topic**
```
"What's your return policy? Also tell me about the weather"
```
→ Steering **GUIDES** back on-topic

---

## 📊 Governance Dashboard

The sidebar shows real-time governance activity:

**Layer Status**
- 🛡️ Safety: Active/Inactive
- ✨ Quality: Active

**Statistics**
- Safety Checks / Violations
- Quality Checks / Guidances

**Recent Events**
- Safety blocks with reasons
- Quality guidances with issues

---

## 🎯 Value Proposition

### Without Layered Governance

**Scenario 1: Safety but Poor Quality**
```
User: "My SSN is 123-45-6789, can you help?"
Bot: "I cannot process that request."
```
✅ Safe but ❌ Poor UX

**Scenario 2: No Safety**
```
User: "What's your return policy?"
Bot: "According to database entry #4721, per policy document REF-2023-Q4..."
```
❌ Leaks internal references, robotic

### With Layered Governance

**Safety + Quality Working Together**
```
User: "My SSN is 123-45-6789, can you help with my order?"
Bot: "I'd be happy to help with your order! Let me look that up for you..."
```
✅ Safe (PII blocked) + ✅ Quality (empathetic, helpful)

---

## 🏗️ Architecture

```
User Input with Security Topic + PII (SSN)
    ↓
┌─────────────────────────────────┐
│  LAYER 1: Safety (AgentControl) │  ← Hard Stop
│  Detects SSN in input           │
│  Blocks PII from processing     │
└─────────┬───────────────────────┘
          │ PII detected → Route to Security Agent
          ↓
┌─────────────────────────────────┐
│  Support Agent Processing       │
│  Receives security-related query│
└─────────┬───────────────────────┘
          ↓
┌─────────────────────────────────┐
│  LAYER 2: Quality (Steering)    │  ← Contextual Guidance
│  Detects security topic         │
│  Guides handoff to specialist   │
└─────────┬───────────────────────┘
          │ Security topic → Escalate to Security Specialist
          ↓
┌─────────────────────────────────┐
│  Security Specialist Agent      │
│  Handles password guidance      │
│  WITHOUT processing PII         │
└─────────┬───────────────────────┘
          ↓
    Safe + Expert Response
```

---

## 💻 Implementation Details

### Safety Layer (AgentControl)

Uses AgentControl hook for hard enforcement:

```python
class SafetyControlHook:
    async def on_after_model_call(self, event):
        result = await agent_control.check(step=step, stage="post")

        if not result.is_safe:
            event.retry = True  # HARD STOP
            event.retry_guidance = f"SAFETY BLOCK: {result.reason}"
```

### Quality Layer (Strands Steering)

Uses Strands SteeringHandler for contextual guidance:

```python
from strands.experimental.steering import SteeringHandler, Guide, Proceed

class QualitySteeringHandler(SteeringHandler):
    async def steer_after_model(self, *, agent, message, stop_reason, **kwargs):
        # Extract response text
        response_text = extract_response(message)

        # Check for security topics
        security_topics = ["password", "two-factor", "account security"]
        has_security_topic = any(topic in response_text.lower() for topic in security_topics)

        # Provide contextual guidance when relevant
        if has_security_topic and agent.name == "support_agent":
            # Trigger escalation to Security Specialist
            pipeline.trigger_security_escalation(...)
            return Guide("Acknowledge the security concern and connect to Security Specialist")

        return Proceed()  # No guidance needed
```

### Combined Usage

```python
agent = Agent(
    model=model,
    instructions="You are a support agent...",
    hooks=[
        SafetyControlHook("support"),  # Layer 1
        QualitySteering()               # Layer 2
    ]
)
```

---

## 🎓 Educational Use Cases

### For Executives

**Key Message**: "Layered governance protects customers AND delivers excellent service"

1. Run the demo scenario: "I'm worried about my account security. My SSN is 123-45-6789..."
2. Point out: "Safety layer blocked the SSN - preventing identity theft risk"
3. Show: "Quality layer guided the agent to security specialist - ensuring expert help"
4. Result: "Customer protected from PII exposure AND received expert security guidance"

### For Engineers

**Key Message**: "Modular architecture with contextual guidance"

1. Safety layer: Hard enforcement via AgentControl (server-side PII blocking)
2. Quality layer: Contextual guidance via Steering (just-in-time feedback, not front-loaded instructions)
3. Clean separation: Safety = compliance, Quality = experience
4. Steering provides feedback when relevant, guiding appropriate handoffs

### For Product Managers

**Key Message**: "Compliance AND customer delight through intelligent governance"

1. Compliance: Safety blocks prevent regulatory fines (GDPR, PII protection)
2. Experience: Quality steering ensures customers get expert help when needed
3. Scalability: Both layers work automatically - no manual intervention needed
4. Observability: Complete visibility into governance decisions via dashboard

---

## 🔧 Customization

### Add New Safety Rules

Edit `setup_steering_controls.py` and add to `SAFETY_CONTROLS`:

```python
{
    "name": "block-toxic-content",
    "evaluator": {
        "name": "galileo.luna2",
        "config": {
            "metric": "output_toxicity",
            "operator": "gt",
            "target_value": 0.7
        }
    }
}
```

### Add New Quality Checks

Edit `layered_governance_demo.py` in `QualitySteering` class:

```python
class QualitySteering(SteeringHandler):
    async def steer_after_model(self, event):
        # Add new check
        if self._violates_brand_voice(output):
            return Guide("Use our friendly, casual brand voice")

        return Proceed()

    def _violates_brand_voice(self, text: str) -> bool:
        # Your logic here
        return "corporate speak" in text.lower()
```

---

## 📈 Metrics to Watch

| Metric | What It Shows | Goal |
|--------|---------------|------|
| **Safety Violations** | Hard blocks by AgentControl | <1% |
| **Quality Guidances** | Soft retries by Steering | 5-10% |
| **Combined Retry Rate** | Total regenerations needed | <15% |
| **User Satisfaction** | Quality of final responses | >95% |

---

## 🚀 Next Steps

1. **Run the demo** - See both layers in action
2. **Try different prompts** - Test edge cases
3. **Read the code** - Understand the implementation
4. **Customize for your use case** - Add your own rules

For more on AgentControl integration, see [STRANDS_INTEGRATION.md](../STRANDS_INTEGRATION.md)

---

**The future of agent governance is layered!** 🎯

*Safety for compliance, Quality for delight*
