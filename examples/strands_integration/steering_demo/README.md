# Banking Email Safety Demo

**AgentControl + Strands Steering for PII Redaction**

Demonstrates layered governance for banking agents that send automated account summaries containing financial PII.

## What It Does

Bank agent sends monthly account summaries. Backend data contains PII (account numbers, SSN, large amounts). Agent drafts emails including this data:

```
User: "Send monthly summary to john@example.com"
  ↓
Agent looks up account → 123456789012, balance $45,234.56
  ↓
Agent drafts: "Account 123456789012, balance $45,234.56..."
  ↓
🛡️ Steering detects PII in draft
  ↓
✨ Steering guides redaction: "Use 'account ending in 9012', '$45.2K'"
  ↓
Agent redrafts: "Account ending in 9012, balance $45.2K..."
  ↓
✅ Email sent (compliant!)
```

**Key Point**: User input is clean (no PII). PII comes from backend lookup. AgentControl catches it in agent's draft and guides redaction.

## Running the Demo

**Setup controls:**
```bash
cd examples/strands_integration/steering_demo
uv run setup_email_controls.py
```

**Launch app:**
```bash
streamlit run email_safety_demo.py
```

## Test It

Click sidebar buttons in the UI:

**📧 John's Summary**
- Backend: Account 123456789012, $45,234.56, deposit $15,000
- Detects: Account number + 2 large amounts
- Redacts: "ending in 9012", "$45.2K", "$15.0K"

**📧 Sarah's Summary**
- Backend: Account 987654321098 + SSN 987-65-4321, $128,456.78
- Detects: Account + SSN + very large amount
- Redacts: All PII to last 4 digits / rounded amounts

UI shows the redacted email + what was protected.

## Why This Matters

**Without governance:**
- Agent sends: "Your account 123456789012 has $128,456.78..."
- GDPR violation → €20M fine

**With AgentControl + Steering:**
- Agent sends: "Your account ending in 1098 has $128K..."
- Compliant, secure, professional ✅
