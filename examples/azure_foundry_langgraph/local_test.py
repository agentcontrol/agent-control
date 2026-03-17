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
from tools import get_order_status, lookup_customer, get_order_internal, process_refund


async def run_tests():
    print("=" * 60)
    print("Local Agent Control Integration Test")
    print("=" * 60)

    print("\n1. Bootstrapping Agent Control...")
    bootstrap_agent_control()
    print("   OK - connected to server")

    print("\n2. get_order_status (safe data)...")
    try:
        result = await get_order_status.ainvoke({"order_id": "ORD-1001"})
        print(f"   PASS: {result['status']}, {result['carrier']}, ETA {result['estimated_delivery']}")
    except ControlViolationError as e:
        print(f"   BLOCKED: {e}")

    print("\n3. lookup_customer (has SSN - block-pii controls this)...")
    try:
        result = await lookup_customer.ainvoke({"email": "jane@example.com"})
        print(f"   PASS (control disabled): {result['name']}, SSN={result['ssn']}, phone={result['phone']}")
    except ControlViolationError as e:
        print(f"   BLOCKED (control enabled): {e}")

    print("\n4. get_order_internal (has margins - block-internal-data controls this)...")
    try:
        result = await get_order_internal.ainvoke({"order_id": "ORD-1001"})
        print(f"   PASS (control disabled): margin={result['profit_margin']}, notes={result['internal_notes'][:50]}...")
    except ControlViolationError as e:
        print(f"   BLOCKED (control enabled): {e}")

    print("\n5. process_refund $50 (under limit)...")
    try:
        result = await process_refund.ainvoke({"order_id": "ORD-1001", "amount": 50.0})
        import json
        parsed = json.loads(result) if isinstance(result, str) else result
        print(f"   PASS: {parsed['message']}")
    except ControlViolationError as e:
        print(f"   BLOCKED: {e}")

    print("\n6. process_refund $150 (over limit - max-refund-amount controls this)...")
    try:
        result = await process_refund.ainvoke({"order_id": "ORD-1001", "amount": 150.0})
        parsed = json.loads(result) if isinstance(result, str) else result
        print(f"   PASS (control disabled): {parsed['message']}")
    except ControlViolationError as e:
        print(f"   BLOCKED (control enabled): {e}")

    print("\n" + "=" * 60)
    print("Done. Toggle controls in the Agent Control UI and re-run to")
    print("see different behavior with the same code.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
