"""Local test script - exercises Agent Control integration without Azure model.

Usage:
    python local_test.py

Requires the Agent Control server to be running and controls seeded.
Enable controls in the UI before running to see blocking in action.
"""

import asyncio

from dotenv import load_dotenv
load_dotenv()  # Must be before any agent_control imports

from agent_control import ControlViolationError

from agent_control_setup import bootstrap_agent_control
from tools import (
    get_order_status,
    get_order_internal,
    lookup_customer,
    lookup_customer_pii,
)


async def run_tests():
    print("=" * 60)
    print("Local Agent Control Integration Test")
    print("=" * 60)

    print("\n1. Bootstrapping Agent Control...")
    bootstrap_agent_control()
    print("   OK - connected to server")

    # --- Safe tools (should always pass) ---

    print("\n2. get_order_status (safe tool - no controls target this)...")
    try:
        result = await get_order_status.ainvoke({"order_id": "ORD-1001"})
        print(f"   PASS: {result['status']}, {result['carrier']}, ETA {result['estimated_delivery']}")
    except ControlViolationError as e:
        print(f"   BLOCKED: {e}")

    print("\n3. lookup_customer (safe tool - no controls target this)...")
    try:
        result = await lookup_customer.ainvoke({"email": "jane@example.com"})
        print(f"   PASS: {result['name']}, {result['membership']} member")
    except ControlViolationError as e:
        print(f"   BLOCKED: {e}")

    # --- Sensitive tools (controlled - behavior depends on whether controls are enabled) ---

    print("\n4. get_order_internal (sensitive - block-internal-data controls this)...")
    try:
        result = await get_order_internal.ainvoke({"order_id": "ORD-1001"})
        print(f"   PASS (control disabled): margin={result['profit_margin']}, notes={result['internal_notes'][:50]}...")
    except ControlViolationError as e:
        print(f"   BLOCKED (control enabled): {e}")

    print("\n5. lookup_customer_pii (sensitive - block-customer-pii controls this)...")
    try:
        result = await lookup_customer_pii.ainvoke({"email": "jane@example.com"})
        print(f"   PASS (control disabled): phone={result['phone']}, DOB={result['date_of_birth']}")
    except ControlViolationError as e:
        print(f"   BLOCKED (control enabled): {e}")

    print("\n" + "=" * 60)
    print("Done. Toggle controls in the Agent Control UI and re-run to")
    print("see different behavior with the same code.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
