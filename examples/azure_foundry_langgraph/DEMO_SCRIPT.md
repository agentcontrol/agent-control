# Demo Script

Open the Foundry Agent Playground and Agent Control UI side by side. All controls should be **disabled** to start.

## 1. Unprotected agent

```
Share customer details for jane@example.com
```
Leaks everything: SSN (123-45-6789), phone, DOB, billing address, credit card, risk score.

## 2. Enable control

Enable `block-pii` in the Agent Control UI. Start a **new chat**, then:

```
Share customer details for jane@example.com
```
**Blocked.** The SSN pattern (`\d{3}-\d{2}-\d{4}`) is caught at the tool output. This control covers both the tool and the LLM response - defense in depth.

## 3. Toggle

**Disable** `block-pii` in the UI. Wait a couple seconds, new chat:

```
Share customer details for john@example.com
```
Goes through - leaks SSN, risk score, failed ID verification notes.

**Re-enable** it. New chat, ask again. **Blocked.**

Same agent, same code, no redeployment. Runtime governance.

## Controls reference

| Control | Steps | Stage | What it catches |
|---------|-------|-------|-----------------|
| `block-pii` | `lookup_customer_pii`, `llm_call` | post | SSN pattern `\d{3}-\d{2}-\d{4}` |
| `block-internal-data` | `get_order_internal` | post | internal notes, margins, fraud flags |
| `block-prompt-injection` | `llm_call` | pre | injection phrases |
| `block-competitor-discuss` | `llm_call` | pre | competitor comparisons |
