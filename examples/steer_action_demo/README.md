# Banking Transaction Agent - AgentControl Steer Action Demo

**A realistic AI banking agent that processes wire transfers with compliance controls, fraud detection, and approval workflows.**

## What This Demonstrates

This example shows all three AgentControl action types in a real-world banking scenario:

- **ALLOW**: Auto-approve simple, low-risk transfers
- **DENY**: Hard-block compliance violations (OFAC sanctions, high fraud)
- **STEER**: Guide agent through approval workflows (2FA, manager approval)

## Quick Start

### Prerequisites

1. Start the AgentControl server
2. Set your OpenAI API key: `export OPENAI_API_KEY="your-key"`

### Run the Demo

```bash
cd examples/steer_action_demo

# 1. Create the controls (one-time setup)
uv run setup_controls.py

# 2. Run the interactive banking agent
uv run autonomous_agent_demo.py
```

## Try These Scenarios

The demo is an interactive conversation with a banking agent. Try these requests:

### 1. Simple Transfer (Auto-Approved)
```
"Send $500 to Jane Smith"
```
**Expected**: ✅ Automatically approved - no controls triggered

### 2. Sanctioned Country (Blocked)
```
"Wire $5,000 to North Korea"
```
**Expected**: ❌ Hard blocked - OFAC compliance violation

### 3. Large Transfer (Requires Approval)
```
"Transfer $15,000 to contractor in UK"
```
**Expected**:
1. 🔄 Agent requests 2FA code from you
2. 🔄 Agent asks for business justification
3. 🔄 Agent requests manager approval
4. ✅ Transfer completes after approvals

## What You'll Learn

- When to use **deny** vs **steer** actions
- How to integrate human feedback (2FA, approvals) into agent workflows
- How AgentControl guides agents with natural language instructions
- Real-world compliance patterns (OFAC, AML, fraud prevention)

## How It Works

The agent uses AgentControl to gate wire transfers through 4 controls:

| Control | Type | Triggers When |
|---------|------|---------------|
| OFAC Sanctions | DENY | Destination is sanctioned country |
| High Fraud | DENY | Fraud score > 0.8 |
| 2FA Required | STEER | Amount ≥ $10,000 |
| Manager Approval | STEER | Amount ≥ $10,000 |

When a STEER control triggers, it provides guidance like:
> "This large transfer requires user verification. Request 2FA code from user, verify it, then retry the transaction with verified_2fa=True."

The agent interprets this guidance and takes the corrective action automatically.

## Files

- `setup_controls.py` - Creates the 4 banking controls
- `autonomous_agent_demo.py` - Interactive agent with natural language interface
- `README.md` - This file

---

**The key insight**: Steer actions transform rigid rules into intelligent guidance, letting agents handle complex workflows while maintaining compliance.
