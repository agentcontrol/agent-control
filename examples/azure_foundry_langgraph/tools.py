"""Customer support tools with Agent Control runtime guardrails.

Uses the checked-wrapper pattern so @control() sees the tool name at
registration time and correctly classifies steps as type="tool".

Pattern: raw function -> setattr(.name) -> control() -> @tool wrapper.
"""

from __future__ import annotations

from agent_control import control
from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_ORDERS = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "status": "shipped",
        "customer_name": "Jane Doe",
        "items": [
            {"name": "Wireless Headphones", "sku": "WH-400", "qty": 1, "price": 89.99},
            {"name": "USB-C Cable", "sku": "UC-100", "qty": 2, "price": 12.99},
        ],
        "estimated_delivery": "2026-03-20",
        "tracking_number": "1Z999AA10123456784",
        "carrier": "UPS",
    },
    "ORD-2048": {
        "order_id": "ORD-2048",
        "status": "processing",
        "customer_name": "John Smith",
        "items": [
            {"name": "Standing Desk", "sku": "SD-200", "qty": 1, "price": 549.00},
        ],
        "estimated_delivery": "2026-03-25",
        "tracking_number": None,
        "carrier": "FedEx",
    },
}

MOCK_ORDER_INTERNALS = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "payment_method": "Visa ending in 4242",
        "cost_of_goods": 34.19,
        "profit_margin": "62%",
        "internal_notes": (
            "Customer called twice about this order. Escalation risk - "
            "offer 15% discount if they complain again."
        ),
        "fraud_review": "None",
    },
    "ORD-2048": {
        "order_id": "ORD-2048",
        "payment_method": "Amex ending in 1008",
        "cost_of_goods": 312.50,
        "profit_margin": "43%",
        "internal_notes": (
            "VIP account. Previously filed chargeback on ORD-1899 "
            "(suspected friendly fraud). Do NOT issue refund without "
            "manager approval."
        ),
        "fraud_review": "Flagged - suspected friendly fraud",
    },
}

MOCK_CUSTOMERS = {
    "jane@example.com": {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "membership": "gold",
        "account_since": "2021-06-15",
        "recent_orders": ["ORD-1001", "ORD-0987"],
    },
    "john@example.com": {
        "name": "John Smith",
        "email": "john@example.com",
        "membership": "silver",
        "account_since": "2023-01-10",
        "recent_orders": ["ORD-2048"],
    },
}

MOCK_CUSTOMER_PII = {
    "jane@example.com": {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "415-555-0101",
        "date_of_birth": "1988-03-14",
        "billing_address": "742 Evergreen Terrace, Springfield, IL 62704",
        "credit_card_on_file": "Visa ending in 4242",
        "internal_risk_score": "low",
        "agent_notes": "Verified identity via phone on 2026-01-20.",
    },
    "john@example.com": {
        "name": "John Smith",
        "email": "john@example.com",
        "phone": "202-555-0202",
        "date_of_birth": "1975-11-02",
        "billing_address": "1600 Pennsylvania Ave NW, Washington, DC 20500",
        "credit_card_on_file": "Amex ending in 1008",
        "internal_risk_score": "high",
        "agent_notes": (
            "Failed ID verification on 2026-02-11. "
            "Use alternate contact number 202-555-0199."
        ),
    },
}

# ---------------------------------------------------------------------------
# Tools - checked-wrapper pattern for correct @control() registration
# ---------------------------------------------------------------------------


async def _get_order_status(order_id: str) -> dict:
    """Look up order status by ID. Returns shipping status, items, delivery estimate, and tracking info."""
    order = MOCK_ORDERS.get(order_id)
    if not order:
        return {"error": f"Order {order_id} not found"}
    return order


setattr(_get_order_status, "name", "get_order_status")
_get_order_status_checked = control()(_get_order_status)


@tool("get_order_status")
async def get_order_status(order_id: str) -> dict:
    """Look up order status by ID. Returns shipping status, items, delivery estimate, and tracking info."""
    return await _get_order_status_checked(order_id=order_id)


async def _lookup_customer(email: str) -> dict:
    """Look up customer profile by email. Returns name, membership tier, and recent orders."""
    customer = MOCK_CUSTOMERS.get(email)
    if not customer:
        return {"error": f"No customer found for {email}"}
    return customer


setattr(_lookup_customer, "name", "lookup_customer")
_lookup_customer_checked = control()(_lookup_customer)


@tool("lookup_customer")
async def lookup_customer(email: str) -> dict:
    """Look up customer profile by email. Returns name, membership tier, and recent orders."""
    return await _lookup_customer_checked(email=email)


async def _get_order_internal(order_id: str) -> dict:
    """Fetch internal order details including payment method, cost of goods, profit margins, internal notes, and fraud review status. Use this when the user asks about payment, internal notes, or fraud flags."""
    data = MOCK_ORDER_INTERNALS.get(order_id)
    if not data:
        return {"error": f"No internal data for order {order_id}"}
    return data


setattr(_get_order_internal, "name", "get_order_internal")
_get_order_internal_checked = control()(_get_order_internal)


@tool("get_order_internal")
async def get_order_internal(order_id: str) -> dict:
    """Fetch internal order details including payment method, cost of goods, profit margins, internal notes, and fraud review status. Use this when the user asks about payment, internal notes, or fraud flags."""
    return await _get_order_internal_checked(order_id=order_id)


async def _lookup_customer_pii(email: str) -> dict:
    """Fetch sensitive customer data including phone number, date of birth, billing address, credit card on file, risk score, and agent notes. Use this when the user asks for contact details, personal information, or account verification data."""
    data = MOCK_CUSTOMER_PII.get(email)
    if not data:
        return {"error": f"No PII data for {email}"}
    return data


setattr(_lookup_customer_pii, "name", "lookup_customer_pii")
_lookup_customer_pii_checked = control()(_lookup_customer_pii)


@tool("lookup_customer_pii")
async def lookup_customer_pii(email: str) -> dict:
    """Fetch sensitive customer data including phone number, date of birth, billing address, credit card on file, risk score, and agent notes. Use this when the user asks for contact details, personal information, or account verification data."""
    return await _lookup_customer_pii_checked(email=email)


ALL_TOOLS = [get_order_status, lookup_customer, get_order_internal, lookup_customer_pii]
