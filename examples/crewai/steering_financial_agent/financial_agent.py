"""
CrewAI Financial Agent with Steering, Deny, and Warn actions.

Demonstrates the three key Agent Control action types in a realistic
wire-transfer scenario using a CrewAI crew:

  DENY  - Sanctioned country or fraud score blocks the transfer immediately.
  STEER - Large transfers pause execution and guide the agent through
          2FA verification or manager approval before retrying.
  WARN  - New recipients and PII in output are logged for audit
          without blocking the transfer.

PREREQUISITE:
    Run setup_controls.py first:

        $ uv run python setup_controls.py

    Then run this example:

        $ uv run python financial_agent.py

Scenarios:
    1. Small legitimate transfer     -> ALLOW (warn on new recipient)
    2. Sanctioned country            -> DENY  (hard block)
    3. Large transfer ($15k)         -> STEER (2FA required, then allowed)
    4. Very large transfer ($75k)    -> STEER (manager approval, then allowed)
    5. High fraud score              -> DENY  (hard block)
"""

import asyncio
import json
import os

import agent_control
from agent_control import ControlSteerError, ControlViolationError, control
from crewai import Agent, Crew, LLM, Task
from crewai.tools import tool

# ── Configuration ───────────────────────────────────────────────────────
AGENT_NAME = "crewai-financial-agent"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_description="CrewAI financial agent with steering controls",
    server_url=SERVER_URL,
)

# Simulated state — in production this comes from your auth system
SIMULATED_2FA_CODE = "482901"
SIMULATED_MANAGER = "Sarah Chen (VP Operations)"


# ── Protected Transfer Function ─────────────────────────────────────────

def create_transfer_tool():
    """Build the CrewAI tool with @control protection and steering logic."""

    llm = LLM(model="gpt-4o-mini", temperature=0.3)

    async def _process_transfer(
        amount: float,
        recipient: str,
        destination_country: str,
        fraud_score: float = 0.0,
        verified_2fa: bool = False,
        manager_approved: bool = False,
    ) -> str:
        """Process a wire transfer (protected by Agent Control)."""
        prompt = f"""You are a banking operations system. Process this wire transfer
and return a short confirmation message (2-3 sentences).

Transfer details:
- Amount: ${amount:,.2f}
- Recipient: {recipient}
- Destination: {destination_country}
- 2FA verified: {verified_2fa}
- Manager approved: {manager_approved}

Return a professional confirmation with a reference number."""

        return llm.call([{"role": "user", "content": prompt}])

    # Set function metadata for @control() step detection
    _process_transfer.name = "process_transfer"  # type: ignore[attr-defined]
    _process_transfer.tool_name = "process_transfer"  # type: ignore[attr-defined]

    # Wrap with Agent Control
    controlled_fn = control()(_process_transfer)

    @tool("process_transfer")
    def process_transfer_tool(transfer_request: str) -> str:
        """Process a wire transfer with compliance, fraud, and approval controls.

        Args:
            transfer_request: JSON string with transfer details (amount, recipient,
                destination_country). May also include fraud_score, verified_2fa,
                manager_approved.
        """
        # Parse the request — CrewAI may pass str or dict
        if isinstance(transfer_request, dict):
            params = transfer_request
        else:
            try:
                params = json.loads(transfer_request)
            except (json.JSONDecodeError, TypeError):
                return f"Invalid transfer request format. Expected JSON, got: {transfer_request!r}"

        amount = float(params.get("amount", 0))
        recipient = params.get("recipient", "Unknown")
        destination_country = params.get("destination_country", "Unknown")
        fraud_score = float(params.get("fraud_score", 0.0))
        verified_2fa = params.get("verified_2fa", False)
        manager_approved = params.get("manager_approved", False)

        header = (
            f"\n{'=' * 60}\n"
            f"  TRANSFER REQUEST: ${amount:,.2f} to {recipient} ({destination_country})\n"
            f"{'=' * 60}"
        )
        print(header)

        # ── Attempt loop: handles steering with retries ─────────────
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"\n  Attempt {attempt}/{max_attempts}")
                print(f"    2FA verified: {verified_2fa} | Manager approved: {manager_approved}")
                print(f"    Sending to Agent Control for evaluation...")

                result = asyncio.run(
                    controlled_fn(
                        amount=amount,
                        recipient=recipient,
                        destination_country=destination_country,
                        fraud_score=fraud_score,
                        verified_2fa=verified_2fa,
                        manager_approved=manager_approved,
                    )
                )

                # If we reach here, all controls passed
                print(f"\n  ALLOWED - Transfer processed successfully")
                return result

            except ControlViolationError as e:
                # ── DENY: Permanent block, no retry ─────────────────
                print(f"\n  DENIED by control: {e.control_name}")
                print(f"    Reason: {e.message}")
                return (
                    f"TRANSFER BLOCKED: {e.message}\n"
                    f"This violation has been logged for compliance review."
                )

            except ControlSteerError as e:
                # ── STEER: Agent must correct and retry ─────────────
                print(f"\n  STEERED by control: {e.control_name}")

                # Parse the steering guidance
                try:
                    guidance = json.loads(e.steering_context)
                except (json.JSONDecodeError, TypeError):
                    guidance = {"reason": str(e.steering_context)}

                reason = guidance.get("reason", "Additional verification required")
                actions = guidance.get("required_actions", [])
                retry_with = guidance.get("retry_with", {})

                print(f"    Reason: {reason}")
                print(f"    Required actions: {actions}")

                # ── Handle each required action ─────────────────────
                if "verify_2fa" in actions:
                    print(f"\n    [2FA VERIFICATION]")
                    print(f"    Sending 2FA code to customer's registered device...")
                    print(f"    Customer entered code: {SIMULATED_2FA_CODE}")
                    print(f"    Code verified successfully")
                    verified_2fa = True

                if "collect_justification" in actions:
                    print(f"\n    [BUSINESS JUSTIFICATION]")
                    print(f"    Collecting justification from requestor...")
                    print(f'    Justification: "Quarterly vendor payment per contract #QV-2024-889"')

                if "get_manager_approval" in actions:
                    print(f"\n    [MANAGER APPROVAL]")
                    print(f"    Routing to {SIMULATED_MANAGER} for approval...")
                    print(f"    Manager reviewed transfer details and justification")
                    print(f"    Approval granted by {SIMULATED_MANAGER}")
                    manager_approved = True

                # Apply any retry flags from steering context
                if retry_with.get("verified_2fa"):
                    verified_2fa = True
                if retry_with.get("manager_approved"):
                    manager_approved = True

                print(f"\n    Retrying with corrected parameters...")
                continue

        return "TRANSFER FAILED: Maximum steering attempts exceeded."

    return process_transfer_tool


# ── CrewAI Crew Setup ───────────────────────────────────────────────────

def create_financial_crew():
    transfer_tool = create_transfer_tool()

    banker = Agent(
        role="Financial Operations Agent",
        goal=(
            "Process wire transfer requests accurately and comply with all "
            "security and compliance controls"
        ),
        backstory=(
            "You are a senior financial operations agent at a major bank. "
            "You process wire transfers using the process_transfer tool. "
            "You always pass the transfer details as a JSON string with the "
            "exact fields: amount, recipient, destination_country, and "
            "optionally fraud_score. You respect all security controls."
        ),
        tools=[transfer_tool],
        verbose=True,
    )

    task = Task(
        description=(
            "Process this wire transfer request: {transfer_request}\n\n"
            "Use the process_transfer tool with a JSON string containing "
            "the transfer details. Report the outcome."
        ),
        expected_output="Transfer confirmation or explanation of why it was blocked",
        agent=banker,
    )

    return Crew(agents=[banker], tasks=[task], verbose=True)


# ── Scenario Runner ─────────────────────────────────────────────────────

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
            "warn-new-recipient",
        ]
        missing = [n for n in required if n not in names]
        if missing:
            print(f"Missing controls: {missing}")
            print("Run:  uv run python setup_controls.py")
            return False
        print(f"Server OK - {len(names)} controls active")
        return True
    except Exception as e:
        print(f"Cannot reach server at {SERVER_URL}: {e}")
        print("Start the server:  make server-run  (from repo root)")
        return False


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


def main():
    print("=" * 60)
    print("  CrewAI Financial Agent")
    print("  Steering, Deny & Warn with Agent Control")
    print("=" * 60)
    print()

    if not verify_server():
        return

    if not os.getenv("OPENAI_API_KEY"):
        print("\nSet OPENAI_API_KEY to run this example.")
        return

    crew = create_financial_crew()

    # ── Scenario 1: Small Legitimate Transfer ───────────────────────
    # Amount < $10k, known country, low fraud → ALLOW
    # Unknown recipient → WARN (logged, not blocked)
    run_scenario(
        crew,
        1,
        "Small Legitimate Transfer (ALLOW + WARN)",
        {
            "amount": 2500,
            "recipient": "New Vendor XYZ",
            "destination_country": "Germany",
            "fraud_score": 0.1,
        },
        "ALLOWED with warning (new recipient logged for audit)",
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
    # Amount $15k → STEER (2FA required), agent verifies, retries → ALLOW
    run_scenario(
        crew,
        3,
        "Large Transfer - 2FA Steering (STEER then ALLOW)",
        {
            "amount": 15000,
            "recipient": "Acme Corp",
            "destination_country": "United Kingdom",
            "fraud_score": 0.2,
        },
        "STEERED (2FA), then ALLOWED after verification",
    )

    # ── Scenario 4: Very Large Transfer Requiring Manager Approval ──
    # Amount $75k → STEER (2FA + manager approval), agent handles both → ALLOW
    run_scenario(
        crew,
        4,
        "Very Large Transfer - Manager Approval (STEER then ALLOW)",
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

    WARN   New recipient (Scenario 1)      - logged for audit, not blocked
           PII in output (if triggered)     - logged for compliance, not blocked

  Key Differences:
    DENY  = ControlViolationError (agent cannot recover)
    STEER = ControlSteerError     (agent corrects and retries)
    WARN  = Logged silently       (agent continues uninterrupted)
""")


if __name__ == "__main__":
    main()
