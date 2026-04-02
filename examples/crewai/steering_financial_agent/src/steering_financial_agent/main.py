"""
CrewAI Financial Agent with Steering, Deny, and Observe actions.

Demonstrates the three key Agent Control action types in a realistic
wire-transfer scenario using a CrewAI crew:

  DENY  - Sanctioned country or fraud score blocks the transfer immediately.
  STEER - Large transfers pause execution and guide the agent through
          2FA verification or manager approval before retrying.
  OBSERVE - New recipients and PII in output are recorded for audit
            without blocking the transfer.

PREREQUISITE:
    Run setup_controls.py first:

        $ uv run --active python setup_controls.py

    Then run this example:

        $ uv run --active steering_financial_agent

Scenarios:
    1. Small legitimate transfer     -> OBSERVE (new recipient)
    2. Sanctioned country            -> DENY  (hard block)
    3. Large transfer ($15k)         -> STEER (2FA required, then allowed)
    4. Very large transfer ($75k)    -> STEER (manager approval, then allowed)
    5. High fraud score              -> DENY  (hard block)
"""

import json
import os

import agent_control

# ── Configuration ───────────────────────────────────────────────────────
AGENT_NAME = "crewai-financial-agent"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_description="CrewAI financial agent with steering controls",
    server_url=SERVER_URL,
)


# ── Crew factory ────────────────────────────────────────────────────────

def create_financial_crew():
    from steering_financial_agent.crew import SteeringFinancialCrew

    return SteeringFinancialCrew().crew()


# ── Server check ────────────────────────────────────────────────────────

def verify_server():
    """Check that Agent Control server is reachable and controls exist."""
    import httpx

    try:
        r = httpx.get(f"{SERVER_URL}/api/v1/controls?limit=100", timeout=5.0)
        r.raise_for_status()
        data = r.json()
        names = [c["name"] for c in data.get("controls", [])]
        required = [
            "deny-sanctioned-countries",
            "deny-high-fraud-score",
            "steer-require-2fa",
            "steer-require-manager-approval",
            "observe-new-recipient",
        ]
        missing = [n for n in required if n not in names]
        if missing:
            print(f"Missing controls: {missing}")
            print("Run:  uv run --active python setup_controls.py")
            return False
        print(f"Server OK - {len(names)} controls active")
        return True
    except Exception as e:
        print(f"Cannot reach server at {SERVER_URL}: {e}")
        print("Start the server:  make server-run  (from repo root)")
        return False


# ── Scenario runner ─────────────────────────────────────────────────────

def run_scenario(crew, number, title, request, expected):
    """Run a single scenario and print results."""
    print(f"\n{'#' * 60}")
    print(f"  SCENARIO {number}: {title}")
    print(f"{'#' * 60}")
    print(f"  Request:  {json.dumps(request)}")
    print(f"  Expected: {expected}")

    result = crew.kickoff(inputs={"transfer_request": json.dumps(request)})

    print(f"\n  Result: {str(result)[:300]}")
    print(f"{'#' * 60}\n")
    return result


# ── Main ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  CrewAI Financial Agent")
    print("  Steering, Deny & Observe with Agent Control")
    print("=" * 60)
    print()

    if not verify_server():
        return

    if not os.getenv("OPENAI_API_KEY"):
        print("\nSet OPENAI_API_KEY to run this example.")
        return

    crew = create_financial_crew()

    # ── Scenario 1: Small Legitimate Transfer ───────────────────────
    # Amount < $10k, known country, low fraud → OBSERVE only
    # Unknown recipient → OBSERVE (recorded, not blocked)
    run_scenario(
        crew,
        1,
        "Small Legitimate Transfer (OBSERVE)",
        {
            "amount": 2500,
            "recipient": "New Vendor XYZ",
            "destination_country": "Germany",
            "fraud_score": 0.1,
        },
        "Allowed with an observe event (new recipient recorded for audit)",
    )

    # ── Scenario 2: Sanctioned Country ──────────────────────────────
    # Destination is North Korea → DENY immediately
    run_scenario(
        crew,
        2,
        "Sanctioned Country (DENY)",
        {
            "amount": 500,
            "recipient": "Trade Partner",
            "destination_country": "North Korea",
            "fraud_score": 0.0,
        },
        "DENIED - OFAC sanctioned country",
    )

    # ── Scenario 3: Large Transfer Requiring 2FA ────────────────────
    # Amount $15k → STEER (2FA required), agent verifies, retries successfully
    run_scenario(
        crew,
        3,
        "Large Transfer - 2FA Steering (STEER then success)",
        {
            "amount": 15000,
            "recipient": "Acme Corp",
            "destination_country": "United Kingdom",
            "fraud_score": 0.2,
        },
        "STEERED (2FA), then succeeded after verification",
    )

    # ── Scenario 4: Very Large Transfer Requiring Manager Approval ──
    # Amount $75k → STEER (2FA + manager approval), agent handles both successfully
    run_scenario(
        crew,
        4,
        "Very Large Transfer - Manager Approval (STEER then success)",
        {
            "amount": 75000,
            "recipient": "Global Suppliers Inc",
            "destination_country": "Japan",
            "fraud_score": 0.15,
        },
        "STEERED (2FA + manager), then ALLOWED after approvals",
    )

    # ── Scenario 5: Fraud Detected ──────────────────────────────────
    # Fraud score 0.95 → DENY immediately
    run_scenario(
        crew,
        5,
        "High Fraud Score (DENY)",
        {
            "amount": 3000,
            "recipient": "Suspicious Entity",
            "destination_country": "Cayman Islands",
            "fraud_score": 0.95,
        },
        "DENIED - fraud score exceeds threshold",
    )

    # ── Summary ─────────────────────────────────────────────────────
    print("=" * 60)
    print("  Demo Complete!")
    print("=" * 60)
    print("""
  Action Types Demonstrated:

    DENY   Sanctioned country (Scenario 2) - hard block, no recovery
           High fraud score (Scenario 5)   - hard block, no recovery

    STEER  2FA verification (Scenario 3)   - pause, verify, retry
           Manager approval (Scenario 4)   - pause, collect + approve, retry

    OBSERVE New recipient (Scenario 1)      - recorded for audit, not blocked
            PII in output (if triggered)    - recorded for compliance, not blocked

  Key Differences:
    DENY  = ControlViolationError (agent cannot recover)
    STEER = ControlSteerError     (agent corrects and retries)
    OBSERVE = Recorded silently   (agent continues uninterrupted)
""")


def run():
    """Entry point for [project.scripts]."""
    try:
        main()
    finally:
        agent_control.shutdown()


if __name__ == "__main__":
    try:
        main()
    finally:
        agent_control.shutdown()
