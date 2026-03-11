"""Transfer tool with @control() protection and steering retry logic."""

import asyncio
import json

from agent_control import ControlSteerError, ControlViolationError, control
from crewai import LLM
from crewai.tools import tool

# Simulated state — in production this comes from your auth system
SIMULATED_2FA_CODE = "482901"
SIMULATED_MANAGER = "Sarah Chen (VP Operations)"


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
