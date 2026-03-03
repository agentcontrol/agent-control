"""
Banking Transaction Agent - AgentControl Steer Action Demo

An interactive banking assistant that demonstrates how AgentControl governs AI agents
in real-world scenarios with compliance, fraud detection, and approval workflows.

## What This Demo Shows

This agent processes wire transfers while AgentControl enforces:
- DENY actions for hard compliance violations (OFAC sanctions, high fraud)
- STEER actions for approval workflows (2FA verification, manager approval)
- ALLOW actions for simple, low-risk transfers

## The Experience

You have a natural conversation with a banking agent:
  "Send $500 to Jane Smith" → ✅ Auto-approved
  "Wire $5k to North Korea" → ❌ Blocked (OFAC violation)
  "Transfer $15k to UK contractor" → 🔄 Guided through 2FA + manager approval

## How It Works

1. User requests a wire transfer in natural language
2. Agent parses the request and checks fraud risk
3. AgentControl evaluates 4 controls (2 DENY, 2 STEER)
4. If steered, agent prompts for 2FA/approval and retries
5. Transfer completes after all requirements are met

## Key Features

- Natural language parsing with GPT-4
- Real-time control evaluation via AgentControl server
- LLM-based steering context interpretation (agent reads control steering context and determines action)
- Human-in-the-loop for 2FA codes and manager approvals
- Autonomous retry logic with corrected parameters
- LangGraph state management for complex workflows

## Controls

- deny-sanctioned-countries: Blocks OFAC sanctioned destinations
- deny-high-fraud-risk: Blocks transactions with fraud score > 0.8
- steer-large-transfer-verification: Requires 2FA for transfers ≥ $10k
- steer-manager-approval-required: Requires approval for over-limit transfers

Run setup_controls.py first to create these controls on the server.
"""

import asyncio
import os
import time
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

import agent_control
from agent_control import ControlSteerError, ControlViolationError, control

# Configuration
AGENT_ID = "f8e5d3c2-4b1a-4e7f-9c8d-2a3b4c5d6e7f"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"  # Set DEBUG=true to show technical error details


# =============================================================================
# UTILITIES
# =============================================================================

def agent_say(message: str, delay: float = 0.5):
    """Agent speaks with typing effect."""
    print(f"\n🤖 Agent: {message}")
    time.sleep(delay)


def agent_think(message: str):
    """Show agent thinking/processing."""
    print(f"   💭 {message}", end='', flush=True)
    time.sleep(0.8)
    print(" ✓")


def agent_reason(message: str):
    """Show agent internal reasoning in italic/dimmed style."""
    print(f"\033[3m\033[90m   🧠 Reasoning: {message}\033[0m")
    time.sleep(0.3)


def log_trace(category: str, message: str):
    """Log detailed trace information."""
    print(f"\033[2m   ⚙️  [{category.upper()}] {message}\033[0m")
    time.sleep(0.2)


def log_escalation(message: str):
    """Log when transferring to another person/system."""
    print(f"\n   🔄 \033[1m{message}\033[0m")
    time.sleep(0.5)


def user_input(prompt: str) -> str:
    """Get input from user."""
    return input(f"\n👤 You: {prompt}").strip()


def parse_steering_context(message: str) -> dict:
    """Parse structured steering context from JSON string.

    Returns a dict with:
    - required_actions: list of action strings
    - retry_flags: dict of flags to set for retry
    - reason: human-readable explanation
    - steps: optional list of step objects for multi-step workflows

    Falls back to empty structure if parsing fails.
    """
    try:
        import json
        parsed = json.loads(message)
        return parsed
    except (json.JSONDecodeError, ValueError):
        # Fallback for plain text steering context
        log_trace("parser", "Failed to parse steering context as JSON, using fallback")
        return {
            "required_actions": ["unknown"],
            "retry_flags": {},
            "reason": message
        }


def check_fraud_score(amount: float, destination: str) -> float:
    """Check fraud risk based on destination.

    Note: Amount thresholds are handled by steer controls, not here.
    Controls are the source of truth for transfer decisions.
    """
    agent_think("Running fraud detection...")
    if "north korea" in destination.lower() or "iran" in destination.lower():
        return 0.95
    else:
        return 0.1


# =============================================================================
# STATE
# =============================================================================

class AgentState(TypedDict):
    """Agent conversation state."""
    messages: Annotated[list, add_messages]
    transfer_request: dict | None
    fraud_score: float | None
    verified_2fa: bool
    manager_approved: bool
    justification: str | None
    final_result: dict | None
    status: str


# =============================================================================
# PROTECTED TOOL
# =============================================================================

@tool
def _process_wire_transfer(
    amount: float,
    destination_country: str,
    recipient_name: str,
    verified_2fa: bool = False,
    manager_approved: bool = False,
    justification: str | None = None,
    fraud_score: float | None = None
) -> dict:
    """Simulate wire transfer processing."""
    # This function is a placeholder and will be wrapped by AgentControl for enforcement.
    return {
        "status": "completed",
        "transaction_id": f"TXN-{hash(recipient_name) % 100000:05d}",
        "amount": amount,
        "destination": destination_country,
        "recipient": recipient_name
    } 

async def process_wire_transfer(
    amount: float,
    destination_country: str,
    recipient_name: str,
    verified_2fa: bool = False,
    manager_approved: bool = False,
    justification: str | None = None,
    fraud_score: float | None = None
) -> dict:
    """Execute wire transfer - gated by AgentControl."""
    agent_think("Executing wire transfer...")
    return _process_wire_transfer.invoke({
        "amount": amount,
        "destination_country": destination_country,
        "recipient_name": recipient_name,
        "verified_2fa": verified_2fa,
        "manager_approved": manager_approved,
        "justification": justification,
        "fraud_score": fraud_score
    })

# Mark wrapper as tool BEFORE applying @control so tool detection works
process_wire_transfer.name = "process_wire_transfer"  # type: ignore[attr-defined]
process_wire_transfer.tool_name = "process_wire_transfer"  # type: ignore[attr-defined]
process_wire_transfer = control(step_name="process_wire_transfer")(process_wire_transfer)

# =============================================================================
# AGENT LOGIC
# =============================================================================

async def parse_transfer_request(user_request: str) -> dict:
    """Parse natural language transfer request."""
    agent_think("Understanding your request...")

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    parse_prompt = f"""Parse this wire transfer request into structured data.

User request: "{user_request}"

Examples:
- "Send $500 to Jane Smith" -> {{"amount": 500, "destination_country": "United States", "recipient_name": "Jane Smith"}}
- "Wire $15000 to contractor in UK" -> {{"amount": 15000, "destination_country": "United Kingdom", "recipient_name": "contractor"}}
- "Transfer $5k to North Korea" -> {{"amount": 5000, "destination_country": "North Korea", "recipient_name": "Unknown"}}

Extract these fields:
- amount: numeric dollar amount (e.g., 500, 15000, 5000)
- destination_country: full country name (if not mentioned, use "United States")
- recipient_name: person or company name (if not mentioned, use "Unknown")

IMPORTANT: Return ONLY valid JSON, no markdown, no explanation:
{{"amount": 500, "destination_country": "United States", "recipient_name": "Jane Smith"}}"""

    response = await llm.ainvoke([HumanMessage(content=parse_prompt)])

    import json
    import re

    try:
        # Clean up response - remove markdown code blocks if present
        content = response.content.strip()
        content = re.sub(r'^```json?\s*', '', content)
        content = re.sub(r'\s*```$', '', content)

        parsed = json.loads(content)

        # Validate fields
        if not isinstance(parsed.get("amount"), (int, float)) or parsed["amount"] <= 0:
            raise ValueError("Invalid amount")

        return parsed

    except Exception as e:
        # Try regex fallback
        import re

        amount_match = re.search(r'\$?([\d,]+)k?', user_request, re.IGNORECASE)
        amount = 1000  # default

        if amount_match:
            amount_str = amount_match.group(1).replace(',', '')
            amount = float(amount_str)
            if 'k' in user_request.lower() and amount < 100:
                amount *= 1000

        # Extract recipient name (words after "to")
        recipient_match = re.search(r'to\s+([A-Za-z\s]+?)(?:\s+in|\s*$)', user_request, re.IGNORECASE)
        recipient = recipient_match.group(1).strip() if recipient_match else "Unknown"

        # Extract country
        country_match = re.search(r'in\s+([A-Za-z\s]+?)(?:\s+for|\s*$)', user_request, re.IGNORECASE)
        country = country_match.group(1).strip() if country_match else "United States"

        return {
            "amount": amount,
            "destination_country": country,
            "recipient_name": recipient
        }


async def process_transfer_node(state: AgentState) -> AgentState:
    """Main processing node."""
    request = state["transfer_request"]

    # Show what we're processing
    agent_say(f"Processing wire transfer:")
    print(f"   💵 Amount: ${request['amount']:,.2f}")
    print(f"   🌍 Destination: {request['destination_country']}")
    print(f"   👤 Recipient: {request['recipient_name']}")

    # Show if this is a retry with corrected flags
    if state.get("verified_2fa") or state.get("manager_approved"):
        print(f"\n   ♻️  \033[1mRETRY WITH CORRECTIONS:\033[0m")
        if state.get("verified_2fa"):
            print(f"      ✓ 2FA verified")
        if state.get("manager_approved"):
            print(f"      ✓ Manager approved")
        log_trace("retry", "Re-evaluating transfer with corrected authorization flags")

    # Check fraud if first time
    if state.get("fraud_score") is None:
        fraud_score = check_fraud_score(request["amount"], request["destination_country"])
        risk_level = "HIGH" if fraud_score > 0.7 else "MEDIUM" if fraud_score > 0.4 else "LOW"
        print(f"   🔍 Fraud Risk: {fraud_score:.2f} ({risk_level})")
        time.sleep(0.5)
    else:
        fraud_score = state["fraud_score"]

    agent_think("Checking compliance controls...")
    log_trace("agent-control", "Initiating pre-execution control evaluation")
    agent_reason("All transfers must pass control checks before execution")

    # DEBUG: Show what we're about to evaluate
    print(f"   🔍 DEBUG: Calling process_wire_transfer with:")
    print(f"      - step_name: 'process_wire_transfer'")
    print(f"      - amount: ${request['amount']:,.2f}")
    print(f"      - verified_2fa: {state.get('verified_2fa', False)}")
    print(f"      - manager_approved: {state.get('manager_approved', False)}")

    log_trace("agent-control", "Sending request to AgentControl server for evaluation")
    log_trace("agent-control", f"Evaluating against {4} active controls")

    try:
        # Attempt transfer - AgentControl gates this
        log_trace("execution", "Attempting wire transfer execution...")
        result = await process_wire_transfer(
            amount=request["amount"],
            destination_country=request["destination_country"],
            recipient_name=request["recipient_name"],
            verified_2fa=state.get("verified_2fa", False),
            manager_approved=state.get("manager_approved", False),
            justification=state.get("justification"),
            fraud_score=fraud_score
        )

        # Success!
        log_trace("agent-control", "All control checks passed ✓")
        log_trace("execution", "Wire transfer executed successfully")
        agent_reason("Transfer complies with all controls - proceeding with execution")

        # Show if this was a successful retry after steer correction
        if state.get("verified_2fa") or state.get("manager_approved"):
            print(f"\n   ✅ \033[1mALLOW PATH: Transfer succeeded after steer corrections!\033[0m")
            log_trace("lifecycle", "STEER → FIX → RETRY → SUCCESS lifecycle completed")

        agent_say(f"✅ Transfer completed successfully!")
        print(f"   📝 Transaction ID: {result['transaction_id']}")
        print(f"   ✓ ${result['amount']:,.2f} sent to {result['recipient']}")
        log_trace("audit", f"Transaction logged: ID={result['transaction_id']}, Amount=${result['amount']:,.2f}")

        # Note: Warn actions (if any) are logged but don't block execution
        # Check if this was a new recipient (which triggers warn control)
        if request["recipient_name"] not in ["John Smith", "Acme Corp", "Global Suppliers Inc"]:
            print(f"\n   ⚠️  \033[33mWARN: New recipient detected\033[0m")
            print(f"   Control: warn-new-recipient")
            print(f"   Note: Transfer to '{request['recipient_name']}' is not in known recipient list")
            print(f"   Action: Logged for review (non-blocking)")
            log_trace("warn", f"New recipient logged for review: {request['recipient_name']}")

        return {
            **state,
            "fraud_score": fraud_score,
            "final_result": result,
            "status": "success"
        }

    except ControlViolationError as e:
        # DENY - Hard block
        log_trace("agent-control", f"DENY control triggered: {e.control_name}")
        log_trace("compliance", "Transaction blocked by compliance control")
        agent_reason("This transaction violates a hard control rule - cannot proceed")
        agent_say(f"❌ I cannot process this transfer.")

        # Control Evaluation Summary
        print(f"\n   ┌─────────────────────────────────────────────────┐")
        print(f"   │ 🚫 CONTROL EVALUATION SUMMARY                   │")
        print(f"   ├─────────────────────────────────────────────────┤")
        print(f"   │ Action:           DENY (Hard Block)             │")
        print(f"   │ Control:          {e.control_name:<31}│")
        print(f"   │ Reason:           {e.message[:31]:<31}│")
        if len(e.message) > 31:
            print(f"   │                   {e.message[31:62]:<31}│")
        print(f"   └─────────────────────────────────────────────────┘")

        # Show metadata in debug mode
        if DEBUG and hasattr(e, 'metadata') and e.metadata:
            print(f"\n   🐛 \033[90mDEBUG - Metadata:\033[0m")
            print(f"   \033[90m{e.metadata}\033[0m")

        log_trace("audit", f"Blocked transaction: Control={e.control_name}, Amount=${request['amount']:,.2f}")
        agent_say("This transaction violates compliance controls and cannot be approved under any circumstances.")

        return {
            **state,
            "fraud_score": fraud_score,
            "status": "failed"
        }

    except ControlSteerError as e:
        # STEER - Need human input
        agent_say(f"⚠️  This transfer requires additional verification.")

        log_trace("control", f"Steer action triggered by control '{e.control_name}'")
        log_trace("decision", "Transfer cannot proceed without additional approvals")
        agent_reason("Control rules require verification before large transactions")

        # Parse structured steering context (deterministic, no LLM needed)
        agent_think("Parsing steering context...")
        log_trace("parser", "Extracting required actions from structured JSON")

        steering_data = parse_steering_context(e.steering_context)
        required_actions = steering_data.get("required_actions", [])
        reason = steering_data.get("reason", "Additional verification required")

        # Control Evaluation Summary
        print(f"\n   ┌─────────────────────────────────────────────────┐")
        print(f"   │ 🔄 CONTROL EVALUATION SUMMARY                   │")
        print(f"   ├─────────────────────────────────────────────────┤")
        print(f"   │ Action:           STEER (Corrective)            │")
        print(f"   │ Control:          {e.control_name:<31}│")
        print(f"   │ Reason:           {reason[:31]:<31}│")
        if len(reason) > 31:
            print(f"   │                   {reason[31:62]:<31}│")
        print(f"   │ Required Actions: {', '.join(required_actions)[:31]:<31}│")
        if len(', '.join(required_actions)) > 31:
            print(f"   │                   {', '.join(required_actions)[31:62]:<31}│")
        print(f"   └─────────────────────────────────────────────────┘")

        # Show technical error message in debug mode
        if DEBUG:
            print(f"\n   🐛 \033[90mDEBUG - Technical Error Message:\033[0m")
            print(f"   \033[90m{e.message}\033[0m")

        # Determine which action to take based on current state
        action = None
        if "request_2fa" in required_actions or "verify_2fa" in required_actions:
            if not state.get("verified_2fa"):
                action = "2fa"
        if "justification" in required_actions or "approval" in required_actions:
            if not state.get("manager_approved"):
                action = "approval" if action is None else action

        if action is None:
            action = "unknown"

        print(f"   → Next action: {action.upper()}")

        # Handle based on action
        if action == "2fa" and not state.get("verified_2fa"):
            log_escalation("ESCALATING TO: Identity Verification System")
            agent_reason(f"Control requires 2FA verification for this ${request['amount']:,.2f} transfer")
            log_trace("security", "Initiating 2-factor authentication workflow")
            log_trace("auth-system", "Preparing to send verification code to user")

            agent_say("I need to verify your identity with 2-factor authentication.")
            log_trace("auth-system", "Waiting for user to enter verification code")

            while True:
                code = user_input("Please enter your 6-digit 2FA code: ")

                if code.lower() == 'cancel':
                    log_trace("auth-system", "User cancelled verification")
                    agent_say("Transfer cancelled.")
                    return {**state, "fraud_score": fraud_score, "status": "cancelled"}

                if len(code) == 6 and code.isdigit():
                    agent_think("Verifying code...")
                    log_trace("auth-system", "Validating code against authentication server")
                    log_trace("auth-system", "Code verified successfully")
                    agent_reason("Identity confirmed via 2FA - proceeding with transfer")
                    agent_say("✅ Identity verified!")

                    print(f"\n   🔄 \033[1mSTEER CORRECTION COMPLETE - RETRYING TRANSFER\033[0m")
                    log_trace("workflow", "Returning to transfer processing with verified_2fa=True")
                    log_trace("retry", "Transfer will be re-evaluated with corrected flags")

                    return {
                        **state,
                        "verified_2fa": True,
                        "fraud_score": fraud_score,
                        "status": "processing"
                    }
                else:
                    log_trace("auth-system", "Invalid code format received")
                    agent_say("Invalid code format. Please enter exactly 6 digits.")

        elif action == "approval" and not state.get("manager_approved"):
            log_escalation("ESCALATING TO: Manager Approval System")
            agent_reason(f"Control requires manager approval for this ${request['amount']:,.2f} transfer")
            log_trace("compliance", "Manager approval required per control rules")

            # Get justification
            if not state.get("justification"):
                log_trace("workflow", "Business justification required for approval request")
                agent_say("I need a business justification for this large transfer.")

                justification = user_input("Why is this transfer needed? (or type 'auto' for AI): ")

                if justification.lower() == 'auto':
                    agent_think("Generating justification...")
                    log_trace("llm", "Using AI to generate business justification")

                    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
                    llm_prompt = f"""Generate a realistic 2-sentence business justification for:
Amount: ${request['amount']:,.2f}
Recipient: {request['recipient_name']}
Destination: {request['destination_country']}

Format: "Payment for [service] per Invoice #INV-2024-XXX. [Additional context about contract/agreement]."
Only output the justification, nothing else."""

                    response = await llm.ainvoke([HumanMessage(content=llm_prompt)])
                    justification = response.content.strip()

                    agent_say(f"Generated justification:")
                    print(f"   \"{justification}\"")
                    log_trace("llm", "AI-generated justification created")
                else:
                    log_trace("workflow", "User-provided justification received")
                    justification = justification
            else:
                justification = state["justification"]

            # Request manager approval
            log_escalation("TRANSFERRING TO: Finance Manager")
            agent_reason("Preparing approval request package with transaction details")
            log_trace("approval-system", "Creating approval request ticket")
            log_trace("approval-system", f"Ticket assigned to: Finance Manager")
            log_trace("notification", "Email notification sent to manager")

            agent_say("Requesting manager approval...")
            print(f"\n   📄 Transfer Details:")
            print(f"      Amount: ${request['amount']:,.2f}")
            print(f"      Justification: {justification}")

            log_trace("approval-system", "Waiting for manager decision...")
            approval = user_input("\n   [Acting as Manager] Approve transfer? (yes/no): ")

            if approval.lower() in ['yes', 'y']:
                log_trace("approval-system", "Manager approved the transfer")
                log_trace("audit", f"Approval logged: Manager ID: MGR-001, Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                agent_reason("Manager authorization received - transfer now complies with controls")
                agent_say("✅ Manager approved!")

                print(f"\n   🔄 \033[1mSTEER CORRECTION COMPLETE - RETRYING TRANSFER\033[0m")
                log_trace("workflow", "Returning to transfer processing with manager_approved=True")
                log_trace("retry", "Transfer will be re-evaluated with corrected flags")

                return {
                    **state,
                    "manager_approved": True,
                    "justification": justification,
                    "fraud_score": fraud_score,
                    "status": "processing"
                }
            else:
                log_trace("approval-system", "Manager rejected the transfer")
                log_trace("audit", f"Rejection logged: Manager ID: MGR-001, Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
                agent_reason("Manager denied authorization - transfer cannot proceed")
                agent_say("❌ Manager rejected. Transfer cancelled.")
                return {
                    **state,
                    "justification": justification,
                    "fraud_score": fraud_score,
                    "status": "failed"
                }

        else:
            agent_say("I'm not sure how to proceed with this steering context.")
            return {**state, "fraud_score": fraud_score, "status": "failed"}


def route_next(state: AgentState) -> str:
    """Route to next node."""
    status = state.get("status", "processing")
    return "process" if status == "processing" else "end"


def create_banking_graph() -> StateGraph:
    """Create agent workflow."""
    workflow = StateGraph(AgentState)
    workflow.add_node("process", process_transfer_node)
    workflow.set_entry_point("process")
    workflow.add_conditional_edges(
        "process",
        route_next,
        {"process": "process", "end": END}
    )
    return workflow.compile()


# =============================================================================
# MAIN
# =============================================================================

async def run_banking_agent():
    """Run the conversational banking agent."""

    # Initialize
    agent_control.init(
        agent_name="banking-transaction-agent",
        server_url=SERVER_URL
    )

    # DEBUG: Check if controls were loaded
    controls = agent_control.get_server_controls()
    print(f"\n🔍 DEBUG: Loaded {len(controls) if controls else 0} controls from server")
    if controls:
        for c in controls:
            control_def = c.get('control', {})
            scope = control_def.get('scope', {})
            print(f"   - {c.get('name', 'unknown')}")
            print(f"     execution: {control_def.get('execution', 'unknown')}")
            print(f"     step_types: {scope.get('step_types', [])}")
            print(f"     step_names: {scope.get('step_names', [])}")
    else:
        print("   ⚠️  WARNING: No controls loaded! Agent will allow all operations.")

    # DEBUG: Check registered steps
    registered_steps = agent_control.get_registered_steps()
    print(f"\n🔍 DEBUG: Registered steps: {len(registered_steps)}")
    for step in registered_steps:
        print(f"   - {step.get('type', 'unknown')}:{step.get('name', 'unknown')}")

    print("\n" + "="*80)
    print("🏦 WEALTHBANK WIRE TRANSFER ASSISTANT")
    print("="*80)
    agent_say("Hello! I'm your banking assistant. I can help you send wire transfers.")
    agent_say("I'm governed by AgentControl to ensure compliance and security.")

    app = create_banking_graph()

    while True:
        print("\n" + "-"*80)

        try:
            # Get user request
            request = user_input("Describe the wire transfer you'd like to make (or 'quit'): ")

            if request.lower() in ['quit', 'exit', 'q']:
                agent_say("Goodbye! Have a great day!")
                break

            if not request:
                continue

            # Parse request
            transfer_data = await parse_transfer_request(request)

            # Confirm understanding
            agent_say(f"I understand you want to send ${transfer_data['amount']:,.2f} to {transfer_data['recipient_name']} in {transfer_data['destination_country']}.")

            confirm = user_input("Is this correct? (yes/no): ")
            if confirm.lower() not in ['yes', 'y']:
                agent_say("Let's try again.")
                continue

            # Process transfer
            agent_say("Let me process this transfer for you...")

            initial_state: AgentState = {
                "messages": [],
                "transfer_request": transfer_data,
                "fraud_score": None,
                "verified_2fa": False,
                "manager_approved": False,
                "justification": None,
                "final_result": None,
                "status": "processing"
            }

            await app.ainvoke(initial_state)

            # Done
            print("\n" + "-"*80)

        except KeyboardInterrupt:
            print("\n")
            agent_say("Session interrupted. Goodbye!")
            break
        except Exception as e:
            agent_say(f"An error occurred: {e}")

    print("\n" + "="*80)
    print("Thank you for using WealthBank!")
    print("="*80)


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY environment variable not set")
        exit(1)

    asyncio.run(run_banking_agent())
