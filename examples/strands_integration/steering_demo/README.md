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

### Layer 2: Quality (Strands Steering) - Soft Guidance
- **Purpose**: Behavior optimization and quality improvement
- **Action**: GUIDES toward better responses (soft retry)
- **Examples**:
  - ✨ Guides toward more empathetic language
  - ✨ Guides back on-topic when agent wanders
  - ✨ Guides toward concise responses

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

### Test Safety Layer (AgentControl)

Click the **🛡️ Safety Tests** buttons:

**🔢 PII Leak**
```
"My order is ORD-123 and my SSN is 123-45-6789"
```
→ AgentControl **BLOCKS** (hard stop)

**💳 Credit Card**
```
"My card number is 4532-1234-5678-9010"
```
→ AgentControl **BLOCKS** (hard stop)

### Test Quality Layer (Steering)

Click the **✨ Quality Tests** buttons:

**🤖 Too Robotic**
```
"Tell me about your return policy in technical terms"
```
→ Steering **GUIDES** toward warm, conversational tone

**📝 Too Verbose**
```
"Explain everything about shipping in extreme detail"
```
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
User Input
    ↓
┌─────────────────────────────────┐
│  Agent Processing              │
└─────────┬───────────────────────┘
          ↓
    ┌─────────────────────┐
    │ LAYER 1: Safety     │  ← AgentControl (Hard Stop)
    │ Check for PII       │
    │ Check for violations│
    └──────┬──────────────┘
           │ If unsafe → BLOCK
           ↓
    ┌─────────────────────┐
    │ LAYER 2: Quality    │  ← Strands Steering (Soft Guidance)
    │ Check empathy       │
    │ Check topic         │
    │ Check brevity       │
    └──────┬──────────────┘
           │ If poor quality → GUIDE (retry)
           ↓
    Safe + Quality Response
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

Uses Strands SteeringHandler for soft guidance:

```python
from strands.experimental.steering import SteeringHandler, ModelSteeringAction, Guide, Proceed

class QualitySteering(SteeringHandler):
    async def steer_after_model(self, event) -> ModelSteeringAction:
        if self._is_too_robotic(output):
            return Guide("Be more warm and empathetic")  # SOFT GUIDANCE

        if self._is_off_topic(output):
            return Guide("Stay focused on support issue")

        return Proceed()  # All quality checks passed
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

**Key Message**: "Safety isn't enough - you need quality too"

1. Show safety block → "We prevent violations"
2. Show quality guidance → "We also ensure great customer experience"
3. Show combined result → "Safe + Delightful = Competitive advantage"

### For Engineers

**Key Message**: "Layered architecture for different concerns"

1. Safety layer: Hard enforcement via AgentControl
2. Quality layer: Soft guidance via Steering
3. Clean separation of concerns
4. Each layer independently testable

### For Product Managers

**Key Message**: "Compliance AND customer satisfaction"

1. Compliance team happy → Safety blocks prevent fines
2. Customer team happy → Quality guidance improves CSAT
3. Engineering team happy → Clean, maintainable architecture

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
