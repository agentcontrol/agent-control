# Banking Transaction Agent - AgentControl Steer Action Demo

**A realistic AI banking agent that processes wire transfers with compliance controls, fraud detection, and approval workflows.**

## What This Demonstrates

This example shows all three AgentControl action types in a real-world banking scenario:

- **ALLOW**: Auto-approve simple, low-risk transfers
- **DENY**: Hard-block compliance violations (OFAC sanctions, high fraud)
- **WARN**: Log suspicious activity without blocking (new recipients)
- **STEER**: Guide agent through approval workflows (2FA, manager approval)

## Understanding Steer Actions

**Steer is a non-fatal control signal** - unlike DENY which blocks execution, STEER provides corrective guidance to help agents satisfy control requirements:

- **Philosophy**: Agents are expected to correct the issue and retry
- **Behavior**: Raises `ControlSteerError` with structured guidance
- **Outcome**: After correction, retry succeeds through the allow path

**Key difference from DENY:**
- DENY = "You cannot do this" (permanent block)
- STEER = "You need to do X first" (correctable)

## Demo Flow

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Request  │ --> │  STEER   │ --> │ Correct  │ --> │  Retry   │ --> │  ALLOW   │
│ Transfer │     │ Triggered│     │  Issue   │     │ Transfer │     │ Success  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘
                      ↓                ↓
                 "Need 2FA"       Get code
                 "Need approval"  Get approval
```

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

- When to use **deny** vs **warn** vs **steer** actions
- How to integrate human feedback (2FA, approvals) into agent workflows
- How structured steering context enables deterministic agent workflows
- Real-world compliance patterns (OFAC, AML, fraud prevention)
- The steer → correct → retry → allow lifecycle

## How It Works

The agent uses AgentControl to gate wire transfers through 5 controls:

| Control | Type | Triggers When |
|---------|------|---------------|
| OFAC Sanctions | DENY | Destination is sanctioned country |
| High Fraud | DENY | Fraud score > 0.8 |
| New Recipient | WARN | Recipient not in known list |
| 2FA Required | STEER | Amount ≥ $10,000 without 2FA |
| Manager Approval | STEER | Amount ≥ $10,000 without approval |

### Structured Steering Context

STEER controls provide **structured JSON guidance** for deterministic agent workflows:

```json
{
  "required_actions": ["request_2fa", "verify_2fa"],
  "retry_flags": {
    "verified_2fa": true
  },
  "reason": "Large transfer requires identity verification via 2FA"
}
```

**For multi-step workflows:**
```json
{
  "required_actions": ["justification", "approval"],
  "steps": [
    {
      "step": 1,
      "action": "justification",
      "description": "Request business justification from user"
    },
    {
      "step": 2,
      "action": "approval",
      "description": "Submit to manager for approval"
    }
  ],
  "retry_flags": {
    "manager_approved": true,
    "justification": "<collected_from_user>"
  },
  "reason": "Transfer exceeds daily limit - requires approval"
}
```

**Key fields:**
- `required_actions`: List of actions the agent must complete
- `retry_flags`: Flags to set when retrying after correction
- `reason`: Human-readable explanation
- `steps`: (Optional) Sequential workflow steps with descriptions

This structured format enables **deterministic agent behavior** without LLM interpretation.

## Files

- `setup_controls.py` - Creates the 5 banking controls (deny, warn, steer)
- `autonomous_agent_demo.py` - Interactive agent with deterministic steer handling
- `README.md` - This file

---

**The key insight**: Steer actions transform rigid rules into intelligent steering context, letting agents handle complex workflows while maintaining compliance.
