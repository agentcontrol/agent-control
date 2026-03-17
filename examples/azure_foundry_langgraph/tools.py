"""Customer support tools with Agent Control runtime guardrails.

Uses the checked-wrapper pattern so @control() sees the tool name at
registration time and correctly classifies steps as type="tool".

Pattern: raw function -> setattr(.name) -> control() -> @tool wrapper.
"""

from __future__ import annotations

from agent_control import control
from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Mock data - single customer, single order
# ---------------------------------------------------------------------------

MOCK_ORDERS = {
    f"ORD-{1000 + i}": {
        "order_id": f"ORD-{1000 + i}",
        "status": ["shipped", "processing", "delivered", "shipped", "processing",
                    "shipped", "delivered", "processing", "shipped", "delivered"][i - 1],
        "customer_name": "Jane Doe",
        "items": [
            {"name": ["Wireless Headphones", "USB-C Cable", "Standing Desk", "Monitor Arm",
                       "Keyboard", "Mouse", "Webcam", "Laptop Stand", "Power Strip", "Desk Mat"][i - 1],
             "qty": 1, "price": [89.99, 12.99, 549.00, 39.99, 79.99,
                                  29.99, 59.99, 44.99, 24.99, 34.99][i - 1]},
        ],
        "estimated_delivery": f"2026-03-{19 + i}",
        "tracking_number": f"1Z999AA1012345678{i}",
        "carrier": ["UPS", "FedEx", "USPS", "UPS", "FedEx",
                     "USPS", "UPS", "FedEx", "USPS", "UPS"][i - 1],
    }
    for i in range(1, 11)
}

MOCK_ORDER_INTERNALS = {
    f"ORD-{1000 + i}": {
        "order_id": f"ORD-{1000 + i}",
        "payment_method": ["Visa ending in 4242", "Amex ending in 1008", "Visa ending in 4242",
                           "MC ending in 3456", "Visa ending in 4242", "Amex ending in 1008",
                           "Visa ending in 4242", "MC ending in 3456", "Visa ending in 4242",
                           "Amex ending in 1008"][i - 1],
        "cost_of_goods": [34.19, 5.50, 312.50, 18.00, 35.00,
                          12.00, 28.00, 20.00, 10.00, 15.00][i - 1],
        "profit_margin": ["62%", "58%", "43%", "55%", "56%",
                          "60%", "53%", "56%", "60%", "57%"][i - 1],
        "internal_notes": [
            "Customer called twice about this order. Escalation risk - offer 15% discount if they complain again.",
            "Standard order, no issues.",
            "VIP account. Previously filed chargeback (suspected friendly fraud). Do NOT issue refund without manager approval.",
            "Bundled with ORD-1003.",
            "Customer requested gift wrapping.",
            "Replacement for defective unit from ORD-1002.",
            "Corporate purchase, net-30 terms.",
            "Express shipping upgraded by support.",
            "Backordered, expected restock 2026-03-22.",
            "Customer loyalty program bonus item.",
        ][i - 1],
        "fraud_review": ["None", "None", "Flagged - suspected friendly fraud", "None", "None",
                         "None", "None", "None", "None", "None"][i - 1],
    }
    for i in range(1, 11)
}

MOCK_CUSTOMERS = {
    "jane@example.com": {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "ssn": "123-45-6789",
        "phone": "415-555-0101",
        "date_of_birth": "1988-03-14",
        "billing_address": "742 Evergreen Terrace, Springfield, IL 62704",
        "credit_card_on_file": "Visa ending in 4242",
        "membership": "gold",
        "account_since": "2021-06-15",
        "recent_orders": ["ORD-1001"],
    },
}

# ---------------------------------------------------------------------------
# Tools - checked-wrapper pattern for correct @control() registration
# ---------------------------------------------------------------------------


async def _get_order_status(order_id: str) -> dict:
    """Look up order status by ID."""
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
    """Look up customer details by email."""
    customer = MOCK_CUSTOMERS.get(email)
    if not customer:
        return {"error": f"No customer found for {email}"}
    return customer


setattr(_lookup_customer, "name", "lookup_customer")
_lookup_customer_checked = control()(_lookup_customer)


@tool("lookup_customer")
async def lookup_customer(email: str) -> dict:
    """Look up customer details by email. Returns full profile including name, SSN, phone, date of birth, billing address, credit card, membership tier, and recent orders."""
    return await _lookup_customer_checked(email=email)


async def _get_order_internal(order_id: str) -> dict:
    """Fetch internal order details."""
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


async def _process_refund(order_id: str, amount: float) -> dict:
    """Process a refund for an order."""
    order = MOCK_ORDERS.get(order_id)
    if not order:
        return {"error": f"Order {order_id} not found"}
    return {
        "order_id": order_id,
        "refund_amount": amount,
        "status": "approved",
        "message": f"Refund of ${amount:.2f} approved for order {order_id}",
    }


setattr(_process_refund, "name", "process_refund")
_process_refund_checked = control()(_process_refund)


@tool("process_refund")
async def process_refund(order_id: str, amount: float) -> dict:
    """Process a refund for an order. Takes order ID and refund amount in dollars."""
    return await _process_refund_checked(order_id=order_id, amount=amount)


ALL_TOOLS = [get_order_status, lookup_customer, get_order_internal, process_refund]
