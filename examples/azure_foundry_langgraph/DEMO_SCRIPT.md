# Demo Script

Open the Foundry Agent Playground and Agent Control UI side by side. All 4 controls should be **disabled** to start.

## 1. Unprotected agent

```
What's the status of order ORD-1001?
```
Works fine - safe tool, returns shipping info.

```
Can you show me the internal notes and payment details for order ORD-1001?
```
Leaks internal data: escalation strategy, 62% profit margin, cost of goods. This shouldn't reach the customer.

## 2. Enable control

Enable `block-internal-data` in the Agent Control UI. Wait a couple seconds, then ask the same question:

```
Can you show me the internal notes and payment details for order ORD-1001?
```
**Blocked.** The control catches internal notes at the tool output boundary. The safe order tool still works:

```
What's the status of order ORD-1001?
```

## 3. Toggle

**Disable** `block-internal-data` in the UI. Wait a couple seconds:

```
Show me the internal notes for order ORD-2048
```
Goes through - leaks fraud flags and chargeback history.

**Re-enable** it. Ask again. **Blocked.**

Same agent, same code, no redeployment. Runtime governance.

## Controls reference

| Control | Step | Stage | What it catches |
|---------|------|-------|-----------------|
| `block-prompt-injection` | `llm_call` | pre | injection phrases |
| `block-internal-data` | `get_order_internal` | post | internal notes, margins, fraud flags |
| `block-customer-pii` | `lookup_customer_pii` | post | DOB, address, credit card, risk score |
| `block-competitor-discuss` | `llm_call` | pre | competitor comparisons |
