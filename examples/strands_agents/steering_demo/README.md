# Banking Email Safety Demo

## Overview

This demo shows how **AgentControl steering** integrates with **Strands** to make AI agents safer for sensitive tasks. A banking agent sends automated account summaries that include PII (account numbers, balances, SSNs) from backend systems. Instead of blocking the agent entirely, AgentControl **guides it to redact** sensitive information before sending—allowing useful work while maintaining compliance. At the tool stage, hard deny rules block credentials or internal system info. This demonstrates **safe autonomy**: steer when possible, block when necessary.

## How It Works

**Simple 4-Step Flow:**

1. **Agent drafts email** (LLM generates text with PII from backend data)
   - Example: "Account 123456789012 has balance $45,234.56..."

2. **AgentControl steer detects PII** in draft output
   - Matches: account numbers, SSN, large amounts
   - Provides redaction guidance: "Mask to last 4 digits, round amounts"

3. **Strands Guide forces rewrite** with steering instructions
   - Agent automatically retries with redacted content
   - Example: "Account ****9012 has balance approximately $45K..."

4. **Tool sends safe email** after deny checks pass
   - AgentControl verifies no credentials or internal data leaked
   - Email sent successfully ✅

## Running the Demo

**1. Start Agent Control server:**
```bash
curl -fsSL https://raw.githubusercontent.com/agentcontrol/agent-control/docker-compose.yml | docker compose -f - up -d
```

**2. Setup controls (creates policies on AgentControl server):**
```bash
cd examples/strands_integration/steering_demo
uv run setup_email_controls.py
```

**3. Launch the Streamlit app:**
```bash
streamlit run email_safety_demo.py
```

**4. Test it:**
- Click **"📧 John's Summary"** in sidebar
- Watch agent draft → detect PII → steer → redact → send
- Console shows full flow with before/after content

## Test Scenarios

**📧 John's Account:**
- Backend: `123456789012`, `$45,234.56`, deposit `$15,000`
- Detects: Account number + large amounts
- Redacts: `****9012`, `$45K`, "recent deposit activity"

**📧 Sarah's Account:**
- Backend: `987654321098` + SSN `987-65-4321`, `$128,456.78`
- Detects: Account + SSN + very large amount
- Redacts: All to last 4 digits + rounded amounts

**🚫 Credential Test (should block):**
- Try sending: "password: secret123"
- AgentControl DENY blocks at tool stage 🛡️

## Why This Matters

**Safe Autonomy = Block When Needed, Steer When Possible**

❌ **Without governance:**
- Agent sends raw PII → GDPR violation → €20M fine
- Only option: disable agent entirely

✅ **With AgentControl + Strands steering:**
- Agent learns to redact PII → compliant emails sent
- Hard blocks catch credentials/secrets
- Useful work continues safely

**Key benefit:** Agents can handle sensitive data with guardrails that guide rather than just block, enabling real-world deployment in regulated industries like banking, healthcare, and finance.
