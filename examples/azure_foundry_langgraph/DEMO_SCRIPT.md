# Demo Script

Open the Foundry Agent Playground and Agent Control UI side by side. All controls should be **disabled** to start.

## Demo 1: PII Protection

### Unprotected

```
Share customer details for jane@example.com
```
Leaks everything: SSN (123-45-6789), phone, DOB, billing address, credit card.

### Enable control

Enable `block-pii` in the Agent Control UI. **Start a new chat**, then:

```
Share customer details for jane@example.com
```
**Blocked.** The SSN pattern (`\d{3}-\d{2}-\d{4}`) is caught at the tool output.

### Toggle

**Disable** `block-pii`. **New chat**, same prompt. Goes through - leaks SSN again. **Re-enable** it. New chat, blocked.

## Demo 2: Refund Limits

### Unprotected

**New chat:**
```
Refund $50 for order ORD-1001
```
Approved.

```
Refund $150 for order ORD-1001
```
Also approved - no guardrails.

### Enable control

Enable `max-refund-amount` in the Agent Control UI. **New chat:**

```
Refund $50 for order ORD-1001
```
Still approved - under $100.

```
Refund $150 for order ORD-1001
```
**Blocked.** The JSON evaluator checks `refund_amount > 100`. You can change the threshold in the UI.

### Toggle

**Disable** `max-refund-amount`. **New chat**, $150 refund goes through. **Re-enable** - blocked again.

## Controls reference

| Control | Steps | Stage | What it catches |
|---------|-------|-------|-----------------|
| `block-pii` | `lookup_customer`, `llm_call` | post | SSN pattern `\d{3}-\d{2}-\d{4}` |
| `max-refund-amount` | `process_refund` | post | JSON constraint: `refund_amount` max 100 |
| `block-internal-data` | `get_order_internal` | post | internal notes, margins, fraud flags |
| `block-prompt-injection` | `llm_call` | pre | injection phrases |
| `block-competitor-discuss` | `llm_call` | pre | competitor comparisons |
