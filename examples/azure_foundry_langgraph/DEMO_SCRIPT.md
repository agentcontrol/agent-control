# Demo Script

Open the Foundry Agent Playground and Agent Control UI side by side. All controls should be **disabled** to start. **Start a new chat for each step.**

## Demo 1: PII Protection

### Unprotected

```
Share customer details for jane@example.com
```
Leaks everything: SSN (123-45-6789), phone, DOB, billing address, credit card.

### Enable control

Enable `block-pii` in the Agent Control UI. **New chat:**

```
Share customer details for jane@example.com
```
**Blocked.** The SSN pattern is caught at the tool output.

### Toggle

**Disable** `block-pii`. **New chat**, same prompt - leaks SSN again. **Re-enable**, new chat - blocked.

## Demo 2: Refund Limits

### Unprotected

**New chat:**
```
Process a refund of $50 for order ORD-1001
```
Approved.

**New chat:**
```
Process a refund of $150 for order ORD-1001
```
Also approved - no guardrails.

### Enable control

Enable `max-refund-amount` in the Agent Control UI. **New chat:**

```
Process a refund of $50 for order ORD-1003
```
Approved - under $100.

**New chat:**
```
Process a refund of $150 for order ORD-1001
```
**Blocked.** The JSON evaluator checks `refund_amount > 100`. You can change the max threshold in the UI.

### Toggle

**Disable** `max-refund-amount`. **New chat**, $150 refund goes through. **Re-enable**, new chat - blocked again.

## Controls reference

| Control | Steps | Stage | Evaluator | What it catches |
|---------|-------|-------|-----------|-----------------|
| `block-pii` | `lookup_customer`, `llm_call` | post | regex | SSN pattern `\d{3}-\d{2}-\d{4}` |
| `max-refund-amount` | `process_refund` | post | json | `refund_amount` max 100 |
| `block-internal-data` | `get_order_internal` | post | regex | internal notes, margins, fraud flags |
| `block-prompt-injection` | `llm_call` | pre | regex | injection phrases |
| `block-competitor-discuss` | `llm_call` | pre | regex | competitor comparisons |
