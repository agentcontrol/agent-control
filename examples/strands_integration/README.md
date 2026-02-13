# 🛡️ AgentControl + AWS Strands Integration

**Interactive demos showing agent governance in multi-agent systems.**

This directory contains two complementary demos:

## 📁 Demos

### 1. 🛡️ [Interactive Demo](interactive_demo/) - Safety Protection
Real-time PII detection and blocking with visual feedback. Perfect for showing safety enforcement.

### 2. 🎯 [Steering Demo](steering_demo/) - Layered Governance
AgentControl (safety) + Strands Steering (quality) working together. Shows how to combine hard enforcement with soft guidance.

---

## 🚀 Quick Start

### 1. Installation

```bash
cd examples/strands_integration

# Install dependencies (includes Streamlit)
uv sync  # or: pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start the Server

```bash
# In terminal 1
cd ../../server && make run
```

### 3. Setup Controls

```bash
# In terminal 2
cd examples/strands_integration/interactive_demo
python setup_interactive_controls.py
```

This creates 2 controls optimized for visual demonstration:
- `block-pii-input` - Blocks SSN, credit cards, emails in user input (regex)
- `block-pii-output` - Blocks SSN, credit cards, emails in agent output (regex)

### 4. Launch the Demo

```bash
streamlit run interactive_support_demo.py
```

The app will open in your browser at `http://localhost:8501`

---

## 🎮 How to Use the Demo

### 1. **Normal Conversation**

Try these safe prompts:
- "What's your return policy?"
- "I need help with my order ORD-12345"
- "How long does shipping take?"

Watch the **Safety Dashboard** show checks passing ✅

### 2. **Try Attack Prompts**

Click any of the pre-loaded attack prompts:

**SSN Leakage:**
```
"My order number is ORD-12345 and my SSN is 123-45-6789. Can you help?"
```
👉 Watch AgentControl block the SSN in real-time!

**Credit Card:**
```
"I need to update my payment. Here's my card: 4532-1234-5678-9010"
```
👉 Watch PII detection block the card number!

**Email:**
```
"Please send the invoice to john.doe@company.com and cc jane.smith@example.org"
```
👉 See email addresses blocked before they leak!

**Multiple PII:**
```
"Contact me at 555-1234-5678-9010 or email admin@secret.com with SSN 987-65-4321"
```
👉 Watch AgentControl catch multiple PII patterns at once!

### 3. **Watch the Safety Dashboard**

The sidebar shows:

**AgentControl Status:**
- Connection status (✅ Connected or ❌ Not initialized)
- Server URL and control count
- Real-time server health

**Active Controls (Expandable):**
- Control name and ID
- Evaluator type (e.g., "regex")
- Configuration (patterns, thresholds)
- Action (deny/allow)
- Stage (pre/post)

**Violation Details:**
- Shown inline with chat messages in expandable sections
- Control name that triggered
- Type of PII detected (SSN, credit card, email)
- Confidence score

### 4. **Try Custom Prompts**

Make up your own attack prompts to test the system. Try to:
- Leak PII (SSN, emails, phone numbers, credit cards)
- Use different PII formats
- Combine multiple PII types
- Test edge cases

AgentControl will catch them all! 🛡️

---

## 🏗️ Architecture

### Multi-Agent Workflow

```
User Message
    ↓
┌───────────────┐
│ Triage Agent  │ ← AgentControl: PII checks (pre-stage)
└───────┬───────┘
        ↓ Routes to appropriate specialist
┌───────────────┐
│  Specialist   │ ← AgentControl: PII checks (post-stage)
│  Agent        │
└───────┬───────┘
        ↓
┌───────────────┐
│ Final Response│ ← AgentControl: Final safety check
└───────────────┘
    ↓
User sees safe response
```

### Safety Layers

Each agent has a **SafetyTrackingHook** that:
1. Intercepts every LLM call (pre and post stages)
2. Runs AgentControl checks via server
3. Updates the UI in real-time
4. Blocks unsafe content before user sees it
5. Triggers retry with safety guidance

---

## 📊 Value Proposition Demonstrated

### 1. **Real-Time Protection**

❌ **Without AgentControl:**
```
User: "My SSN is 123-45-6789, can you help?"
Bot: "Sure! I see your SSN 123-45-6789 in our system..."
```
🚨 **Result:** PII leaked to UI, regulatory violation

✅ **With AgentControl:**
```
User: "My SSN is 123-45-6789, can you help?"
[AgentControl blocks content containing SSN]
Bot: "I'd be happy to help! Let me look up your account..."
```
✅ **Result:** SSN blocked, safe response generated

### 2. **Complete Observability**

Every check is tracked:
- ✅ Passed checks (green in dashboard)
- 🚫 Blocked violations (red with details)
- 📊 Live statistics
- 📋 Complete audit trail

**Value for Compliance:**
- Regulators: "Show us your safety measures"
- You: *Points to dashboard* "Here's every check we performed"

### 3. **Defense in Depth**

Multiple protection layers:
1. **Pre-Stage (Input):** Block PII in user messages
2. **Post-Stage (Output):** Block PII in agent responses
3. **Multi-Agent:** Each agent independently protected

If one layer misses something, others catch it!

### 4. **Instant Policy Updates**

Change control configuration via API - no code deployment needed!

---

## 🔧 Customization Guide

### Adding New Controls

Edit `interactive_demo/setup_interactive_controls.py`:

```python
{
    "name": "my-custom-control",
    "description": "My custom safety check",
    "definition": {
        "enabled": True,
        "execution": "server",
        "scope": {
            "step_types": ["llm"],
            "stages": ["post"]
        },
        "selector": {"path": "output"},
        "evaluator": {
            "name": "regex",
            "config": {
                "pattern": r"your_pattern_here"
            }
        },
        "action": {"decision": "deny"}
    }
}
```

Run setup script → control is active!

### Adding New Attack Prompts

Edit `interactive_demo/interactive_support_demo.py`, find `attack_prompts`:

```python
attack_prompts = {
    "🔢 Your Label": "Your attack prompt text",
    "🆔 Another Attack": "Another prompt to test",
}
```

New buttons appear automatically!

### Changing Agent Behavior

Modify agent instructions in `create_support_agents()`:

```python
specialist_agent = Agent(
    model=model,
    instructions="""Your new instructions here""",
    tools=[your_tools],
    hooks=[SafetyTrackingHook("specialist")],
)
```

---

## 🐛 Troubleshooting

### "AgentControl not initialized"

**Problem:** Server not running or controls not set up

**Solution:**
```bash
# Terminal 1: Start server
cd ../../server && make run

# Terminal 2: Setup controls
cd interactive_demo
python setup_interactive_controls.py
```

### "Import Error: strands"

**Problem:** Dependencies not installed

**Solution:**
```bash
uv sync  # or: pip install -e .
```

### No violations showing

**Problem:** Controls might not be triggering

**Solution:**
- Try the pre-loaded attack prompts (they're designed to trigger)
- Check sidebar to confirm controls are active
- Check server logs for evaluation errors

### Server connection errors

**Problem:** Can't reach AgentControl server

**Solution:**
- Verify server is running: `curl http://localhost:8000/health`
- Check `.env` has correct `AGENT_CONTROL_URL`
- Restart server if needed

---

## 💡 Demo Tips

### For Maximum Impact

1. **Start with Success:** Show normal conversation first (builds trust)
2. **Build Suspense:** "Let's try to break it..."
3. **Point to Dashboard:** "Watch the sidebar" (creates focus)
4. **Show the Block:** "See that red notification? That's a regulatory fine prevented"
5. **Repeat:** Try multiple attacks (proves it's not luck)

### Key Talking Points

**For Executives:**
- "This prevents regulatory fines" (PII blocks)
- "This protects brand reputation" (content filtering)
- "This avoids customer complaints" (quality control)
- "All of this happens in real-time"

**For Engineers:**
- "See how the hook intercepts responses?"
- "Each agent has independent safety checks"
- "Controls are fetched from server, updated without deploy"
- "Complete audit trail for debugging"

**For Product Managers:**
- "Blocks unsafe content automatically"
- "Reduces manual review workload"
- "Enables faster shipping of AI features"
- "Provides compliance dashboard for audits"

---

## 🎓 Educational Use Cases

### For Product Demos

**Scenario:** Showing stakeholders why AgentControl matters

1. Start the demo
2. Show normal conversation (passes all checks)
3. Click "SSN" attack prompt
4. **Point to sidebar:** "See? AgentControl just blocked that SSN"
5. Show statistics: "We've blocked X violations in this demo"

**Impact:** Stakeholders see protection happening in real-time, not just in logs.

### For Sales Presentations

**"Try to break it" Challenge:**

1. Give prospect control of the chat
2. "Try to make it leak PII or say something inappropriate"
3. They try multiple attacks
4. AgentControl blocks them all
5. **Close:** "This is protecting your brand 24/7"

---

## 📚 Technical Documentation

### Integration Pattern

AgentControl integrates with AWS Strands using **hook-based architecture**:

```python
from strands.hooks import HookProvider
import agent_control

class SafetyTrackingHook(HookProvider):
    async def on_after_model_call(self, event):
        # Create AgentControl step
        step = Step(
            type="llm",
            name="assistant",
            input=event.input,
            output=event.output
        )

        # Run safety check
        result = await agent_control.check(step=step, stage="post")

        if not result.is_safe:
            # Trigger retry with guidance
            event.retry = True
            event.retry_guidance = f"Blocked: {result.reason}"
```

For detailed integration patterns, see [STRANDS_INTEGRATION.md](STRANDS_INTEGRATION.md)

---

## 🚀 Next Steps

After running the demo:

1. **Read the code** - See how hooks integrate with Strands
2. **Modify controls** - Try different patterns and thresholds
3. **Add new agents** - Extend the multi-agent system
4. **Deploy your own** - Use this as a template

For production deployment patterns, see [STRANDS_INTEGRATION.md](STRANDS_INTEGRATION.md)

---

## ❓ FAQ

**Q: Can I use this in production?**
A: This is a demo optimized for visual impact. For production, see [STRANDS_INTEGRATION.md](STRANDS_INTEGRATION.md) for production patterns.

**Q: How do I add my own controls?**
A: Edit `interactive_demo/setup_interactive_controls.py` and add your control definition. Run the setup script again.

**Q: Can I deploy this publicly?**
A: Yes, but add authentication! Streamlit has built-in auth options. Also consider rate limiting.

**Q: Why Streamlit?**
A: Fastest way to build interactive demos. Easy to modify, no frontend skills needed.

**Q: Can I use this with other frameworks (LangChain, CrewAI)?**
A: Yes! Replace the Strands agents with your framework's agents. The AgentControl integration patterns are the same.

---

**Try to break it - watch AgentControl defend in real-time!** 🛡️

*Built with AgentControl + AWS Strands + Streamlit*
