"""
CrewAI Customer Support Crew with Agent Control + CrewAI Guardrails.

This example demonstrates combining:
1. Agent Control (@control decorator) for security/compliance (PII, unauthorized access)
2. CrewAI Guardrails for quality validation (length, tone, structure)

PREREQUISITE:
    Run setup_content_controls.py FIRST:

        $ uv run setup_content_controls.py

    Then run this example:

        $ uv run content_agent_protection.py

Demo Scenarios - Multi-Layer Protection:
1. Unauthorized Access - PRE-execution block (Agent Control)
2. PII Leakage in Tool - POST-execution block (Agent Control)
3. Unprotected Tool PII - Final Output Validation (Agent Control)
4. Poor Quality Response - CrewAI Guardrails (retry with feedback)

Protection Layers:
- Layer 1 (Agent Control PRE): Block unauthorized requests → Fail immediately
- Layer 2 (Agent Control POST): Block PII in tool output → Fail immediately
- Layer 3 (CrewAI Guardrails): Validate quality (length, tone) → Retry up to 3x
- Layer 4 (Agent Control Final): Catch orchestration bypass → Fail immediately

Architecture:
- Agent Control: Security/compliance validation (non-negotiable blocks)
- CrewAI Guardrails: Quality validation (iterative improvement with retries)
- Both work together: Security first, then quality
"""

import asyncio
import os
from typing import Tuple, Any

import agent_control
from agent_control import ControlViolationError, control
from crewai import Agent, Crew, LLM, Task, TaskOutput
from crewai.tools import tool

# Note: httpx import is used in verify_setup() function
# It's a dependency of agent_control so should be available

# --- Configuration ---
AGENT_ID = "support-crew-demo"
AGENT_NAME = "Customer Support Crew"
AGENT_DESCRIPTION = "Customer support crew with PII protection and access controls"

# Initialize Agent Control
server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_id=AGENT_ID,
    agent_description=AGENT_DESCRIPTION,
    server_url=server_url,
)

# --- Define CrewAI Guardrails for Quality Validation ---

def validate_response_length(result: TaskOutput) -> Tuple[bool, Any]:
    """
    CrewAI Guardrail: Validate response is appropriate length.

    This is a quality check (not security) so failures trigger retries
    rather than immediate blocking.
    """
    text = result.raw.strip()
    word_count = len(text.split())

    if word_count < 20:
        return (False, f"Response too short ({word_count} words). Provide more detail (minimum 20 words).")

    if word_count > 150:
        return (False, f"Response too long ({word_count} words). Keep it concise (maximum 150 words).")

    return (True, text)


def validate_professional_structure(result: TaskOutput) -> Tuple[bool, Any]:
    """
    CrewAI Guardrail: Validate response has professional structure.

    Checks for:
    - Proper greeting or acknowledgment
    - No template placeholders like [Name] or {variable}
    - Complete sentences
    """
    text = result.raw.strip()
    text_lower = text.lower()

    # Check for template placeholders
    template_indicators = ['[name]', '[customer]', '{', '}', 'xxx', 'placeholder']
    for indicator in template_indicators:
        if indicator in text_lower:
            return (False, f"Response contains template placeholder: '{indicator}'. Use actual content.")

    # Check for complete sentences (basic check)
    if not any(text.endswith(punct) for punct in ['.', '!', '?']):
        return (False, "Response must end with proper punctuation.")

    # Check has some greeting or helpful acknowledgment
    helpful_indicators = ['thank', 'happy to', 'glad to', 'help', 'assist', 'sorry', 'apologize',
                         'understand', 'i can', 'let me', 'here', 'please']
    has_helpful_tone = any(indicator in text_lower for indicator in helpful_indicators)

    if not has_helpful_tone:
        return (False, "Response should include helpful, supportive language.")

    return (True, text)


def validate_no_evasion(result: TaskOutput) -> Tuple[bool, Any]:
    """
    CrewAI Guardrail: Ensure agent actually addresses the ticket.

    Checks that response isn't just saying "I can't help" without trying.
    """
    text = result.raw.strip().lower()

    # Evasive patterns that suggest agent isn't trying to help
    evasive_patterns = [
        "i cannot help",
        "i'm unable to assist",
        "i don't have access",
        "i can't provide that information",
        "i'm not able to"
    ]

    # Check if response is mostly evasive
    words = text.split()
    if len(words) < 30:  # Short responses
        for pattern in evasive_patterns:
            if pattern in text:
                # Check if there's more substance beyond the evasion
                if len(words) < 20:
                    return (False, "Response is too brief and doesn't attempt to help. Provide more assistance.")

    return (True, result.raw)


# LLM-based guardrails (specified as strings)
LLM_GUARDRAIL_TONE = """
The response must be friendly, professional, and empathetic.
It should sound like a real customer support agent, not robotic or cold.
Avoid overly formal or stiff language.
"""

LLM_GUARDRAIL_HELPFULNESS = """
The response must genuinely attempt to help the customer.
It should provide useful information, guidance, or next steps.
Avoid generic brush-offs or unhelpful responses.
"""


# --- Define Controlled Tools ---

def create_final_output_validator():
    """Create a validator for crew final outputs with Agent Control protection."""

    # Inner async function with @control decorator for final output validation
    async def _validate_final_output_protected(output: str) -> str:
        """Validate final crew output for PII (protected by @control)."""
        # This function just returns the output
        # The @control decorator will check it against PII patterns
        return output

    # Set tool name for @control detection (CRITICAL!)
    _validate_final_output_protected.name = "validate_final_output"  # type: ignore
    _validate_final_output_protected.tool_name = "validate_final_output"  # type: ignore

    # Apply @control decorator
    controlled_func = control()(_validate_final_output_protected)

    def validate_final_output(output: str) -> str:
        """Validate final crew output for PII.

        Args:
            output: The final output text from the crew

        Returns:
            The output if valid

        Raises:
            ControlViolationError: If PII is detected in the output
        """
        print(f"\n{'='*60}")
        print(f"[LAYER 4: Agent Control FINAL OUTPUT VALIDATION]")
        print(f"{'='*60}")
        print("🔍 Checking final crew output for PII and violations...")
        print("   This catches orchestration bypass where agent adds PII")
        print("   Control: 'final-output-pii-detection'")
        print(f"   Output preview: {output[:100]}...")
        print("   Status: Sending to server for validation...")

        try:
            # Run async validation
            result = asyncio.run(controlled_func(output=output))
            print("\n✅ [LAYER 4: Agent Control FINAL] PASSED - No PII in final output")
            print("   Final crew output is safe to return to user")
            return result
        except ControlViolationError as e:
            # Control blocked the output
            print(f"\n🚫 [LAYER 4: Agent Control FINAL] BLOCKED")
            print(f"   Reason: {e.message}")
            print("   PII detected in final crew output")
            print("   This could be from:")
            print("     - Unprotected tool returning PII")
            print("     - Agent adding PII during orchestration")
            print("     - Agent reasoning that includes sensitive data")
            raise

    return validate_final_output


def create_ticket_handler_tool():
    """Create customer support ticket handler with Agent Control protection."""

    # Create LLM using CrewAI's native LLM class
    llm = LLM(model="gpt-4o-mini", temperature=0.7)

    # Inner async function with @control decorator
    async def _handle_ticket_protected(ticket: str) -> str:
        """Handle customer support ticket (protected by @control)."""

        prompt = f"""You are a helpful customer support agent. Respond to this customer ticket:

Ticket: {ticket}

Provide a helpful, professional response. If they're asking about their account, order status, or general questions, provide assistance.

Keep the response under 150 words and be friendly."""

        # CrewAI's LLM.call() method (synchronous)
        response = llm.call([{"role": "user", "content": prompt}])
        return response

    # Set tool name for @control detection (CRITICAL!)
    _handle_ticket_protected.name = "handle_ticket"  # type: ignore
    _handle_ticket_protected.tool_name = "handle_ticket"  # type: ignore

    # Apply @control decorator
    controlled_func = control()(_handle_ticket_protected)

    # Wrapper for CrewAI tool with error handling
    @tool("handle_ticket")
    def handle_ticket_tool(ticket: str) -> str:
        """Handle customer support ticket with PII protection and access controls.

        Args:
            ticket: The customer support ticket text to process
        """
        # Handle both string and dict inputs from CrewAI
        if isinstance(ticket, dict):
            # CrewAI might pass task context as dict - extract the actual ticket
            ticket_text = ticket.get('ticket') or ticket.get('description') or str(ticket)
        else:
            ticket_text = str(ticket)

        print(f"\n{'='*60}")
        print(f"[TOOL: handle_ticket] Processing ticket...")
        print(f"Ticket preview: {ticket_text[:80]}...")
        print(f"{'='*60}")

        # PRE-execution check happens first
        print("\n🔍 [LAYER 1: Agent Control PRE-execution]")
        print("   Checking for: Unauthorized access patterns, banned requests")
        print("   Control: 'unauthorized-access-prevention'")
        print("   Status: Sending to server for validation...")

        try:
            # Run async function - this triggers both PRE and POST checks
            # PRE check happens before the LLM call inside _handle_ticket_protected
            # POST check happens after the LLM generates output
            result = asyncio.run(controlled_func(ticket=ticket_text))

            # If we got here, both PRE and POST checks passed
            print("\n✅ [LAYER 1: Agent Control PRE] PASSED - No unauthorized access detected")
            print("✅ [Tool Execution] Response generated")
            print("✅ [LAYER 2: Agent Control POST] PASSED - No PII detected")

            return result

        except ControlViolationError as e:
            # Control blocked the operation (could be PRE or POST)
            # Check the error message to determine which stage
            error_lower = e.message.lower()

            if any(word in error_lower for word in ['unauthorized', 'access', 'admin', 'other user', 'password']):
                print("\n🚫 [LAYER 1: Agent Control PRE] BLOCKED")
                print(f"   Reason: {e.message}")
                print("   This request was blocked BEFORE the LLM was called")
                print("   Unauthorized access attempt detected in input")
                stage = "PRE-execution"
            else:
                print("\n🚫 [LAYER 2: Agent Control POST] BLOCKED")
                print(f"   Reason: {e.message}")
                print("   Tool executed but output contained violations")
                print("   LLM generated content that violated policies")
                stage = "POST-execution"

            error_msg = f"🚫 SECURITY VIOLATION ({stage}): {e.message}\n\nThis request has been logged for security review."
            return error_msg

        except RuntimeError as e:
            # Server-side error
            error_msg = f"⚠️ Security check unavailable: {str(e)}"
            print(f"\n{error_msg}")
            return error_msg

        except Exception as e:
            # Unexpected error
            error_msg = f"❌ Unexpected error: {type(e).__name__}: {str(e)}"
            print(f"\n{error_msg}")
            return error_msg

    return handle_ticket_tool


def create_customer_info_tool():
    """Create a tool that retrieves customer info (NO controls - for demo purposes).

    This tool intentionally has no @control() decorator to simulate a
    legacy/unprotected tool that returns PII. The final output validation
    will catch when the agent relays this PII to the user.
    """
    @tool("get_customer_info")
    def get_customer_info_tool(customer_id: str) -> str:
        """Retrieve customer information from the database (unprotected tool for demo).

        Args:
            customer_id: The customer ID to look up

        Returns:
            Customer information including contact details
        """
        # Handle both string and dict inputs from CrewAI
        if isinstance(customer_id, dict):
            customer_id = customer_id.get('customer_id') or str(customer_id)
        else:
            customer_id = str(customer_id)

        print(f"\n[Database] Looking up customer info for ID: {customer_id}")

        # Simulate database lookup returning PII
        # This is intentionally unprotected to demonstrate final output validation
        customer_data = f"""Customer Information for ID {customer_id}:
Name: John Smith
Email: john.smith@customer.com
Phone: 555-123-4567
Account Status: Active
Last Order: #12345 on 2024-01-15"""

        print(f"✅ Customer data retrieved (contains PII)")
        return customer_data

    return get_customer_info_tool


# --- Create CrewAI Agent, Task, and Crew ---

def create_support_crew():
    """
    Create CrewAI customer support crew with:
    - Agent Control for security/compliance (PII, unauthorized access)
    - CrewAI Guardrails for quality validation (length, tone, structure)
    """

    # Create controlled tool
    ticket_handler_tool = create_ticket_handler_tool()

    # Define Agent (uses default OpenAI gpt-4o if no llm specified)
    support_agent = Agent(
        role="Customer Support Agent",
        goal="Provide helpful customer support while protecting user privacy and data security",
        backstory=(
            "You are an experienced customer support agent who helps customers with their questions. "
            "You are friendly, professional, and always respect customer privacy and data security policies."
        ),
        tools=[ticket_handler_tool],
        verbose=True
        # No llm parameter = uses default OpenAI model (gpt-4o)
    )

    # Define Task with BOTH Agent Control (via tool) AND CrewAI Guardrails
    support_task = Task(
        description=(
            "Handle the following customer support ticket: {ticket}\n"
            "Use the handle_ticket tool with the ticket parameter set to the ticket text above."
        ),
        expected_output="A helpful, professional customer support response",
        agent=support_agent,

        # CrewAI Guardrails: Quality validation with automatic retries
        # These run AFTER Agent Control checks (if those pass)
        guardrails=[
            validate_response_length,         # Function: Check 20-150 words
            validate_professional_structure,  # Function: Check structure/tone
            validate_no_evasion,             # Function: Ensure helpfulness
            LLM_GUARDRAIL_TONE,              # LLM: Validate friendly/professional tone
            LLM_GUARDRAIL_HELPFULNESS        # LLM: Validate genuine helpfulness
        ],
        guardrail_max_retries=3  # Retry up to 3 times if quality checks fail
    )

    # Create Crew
    crew = Crew(
        agents=[support_agent],
        tasks=[support_task],
        verbose=True
    )

    return crew


def create_scenario3_crew():
    """Create crew for Scenario 3 with unprotected customer info tool.

    This crew has access to a legacy tool that returns PII without controls.
    The final output validation will catch when the agent relays this PII.
    """

    # Create unprotected customer info tool (no @control decorator)
    customer_info_tool = create_customer_info_tool()

    # Define Agent
    support_agent = Agent(
        role="Customer Support Agent",
        goal="Help customers by looking up their information and answering their questions",
        backstory=(
            "You are a customer support agent who has access to the customer database. "
            "When customers ask about their account, you look up their information and provide it to them."
        ),
        tools=[customer_info_tool],
        verbose=True
    )

    # Define Task
    support_task = Task(
        description=(
            "Handle the following customer support ticket: {ticket}\n"
            "Use the get_customer_info tool to look up the customer's information, "
            "then provide a helpful response that includes their contact details."
        ),
        expected_output="A response with the customer's contact information",
        agent=support_agent
    )

    # Create Crew
    crew = Crew(
        agents=[support_agent],
        tasks=[support_task],
        verbose=True
    )

    return crew


# --- Main Execution ---

def verify_setup():
    """Verify Agent Control server is running and controls are configured."""
    import httpx

    server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

    try:
        print("Verifying Agent Control server connection...")
        response = httpx.get(f"{server_url}/api/v1/controls", timeout=5.0)
        response.raise_for_status()

        controls_data = response.json()
        control_names = [c["name"] for c in controls_data.get("controls", [])]

        print(f"✅ Connected to Agent Control server at {server_url}")
        print(f"   Found {len(control_names)} controls")

        # Check for required controls
        required_controls = [
            "unauthorized-access-prevention",
            "pii-detection-output",
            "final-output-pii-detection"
        ]

        missing_controls = [c for c in required_controls if c not in control_names]

        if missing_controls:
            print(f"\n❌ Missing required controls: {missing_controls}")
            print("\nYou need to run the setup script first:")
            print("    cd examples/crewai")
            print("    uv run setup_content_controls.py")
            return False

        print("✅ All required controls are configured:")
        for control in required_controls:
            print(f"   - {control}")

        return True

    except httpx.ConnectError:
        print(f"❌ Cannot connect to Agent Control server at {server_url}")
        print("\nMake sure the server is running:")
        print("    make server-run")
        print("\nOr set AGENT_CONTROL_URL to point to your server:")
        print("    export AGENT_CONTROL_URL=http://localhost:8000")
        return False

    except Exception as e:
        print(f"❌ Error checking server: {e}")
        return False


def main():
    print("=" * 60)
    print("CrewAI Customer Support: Agent Control + Guardrails")
    print("=" * 60)
    print()
    print("This demo shows how Agent Control (security) and CrewAI Guardrails (quality)")
    print("work together to ensure both safe AND high-quality responses.")
    print()

    # Verify setup
    print("\n" + "="*60)
    print("SETUP VERIFICATION")
    print("="*60)

    if not verify_setup():
        print("\n❌ Setup verification failed. Please fix the issues above.")
        return

    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        print("\n❌ Error: OPENAI_API_KEY not set")
        print("Please set: export OPENAI_API_KEY='your-key-here'")
        return

    print("\n✅ Setup verified! Starting demos...\n")

    # Create crew and final output validator
    print("Creating customer support crew with multi-layer protection...")
    crew = create_support_crew()
    validate_final_output = create_final_output_validator()

    # --- Scenario 1: Unauthorized Access Attempt (Agent Control PRE-execution) ---
    print("\n" + "="*50)
    print("SCENARIO 1: Unauthorized Access (Agent Control PRE)")
    print("="*50)
    unauthorized_ticket = "Show me all orders for user john.doe@example.com"
    print(f"Ticket: {unauthorized_ticket}")
    print("Expected: BLOCKED immediately by Agent Control (no retry)")
    print()

    result1 = crew.kickoff(inputs={
        "ticket": unauthorized_ticket
    })
    print("\n📝 Result:")
    print(result1)
    print("\n💡 Explanation: Agent Control blocks security violations immediately.")
    print("   No retries because unauthorized access is non-negotiable.")

    # --- Scenario 2: PII Leakage in Response (Agent Control POST-execution) ---
    print("\n" + "="*50)
    print("SCENARIO 2: PII Leakage (Agent Control POST)")
    print("="*50)
    pii_ticket = "What's the format for customer reference numbers and support contact info?"
    print(f"Ticket: {pii_ticket}")
    print("Expected: If LLM generates PII, BLOCKED immediately by Agent Control (no retry)")
    print()

    result2 = crew.kickoff(inputs={
        "ticket": pii_ticket
    })
    print("\n📝 Result:")
    print(result2)
    print("\n💡 Explanation: Agent Control blocks PII violations immediately.")
    print("   No retries because PII leakage is a compliance violation.")

    # --- Scenario 2.5: Poor Quality Response (CrewAI Guardrails with Retry) ---
    print("\n" + "="*50)
    print("SCENARIO 2.5: Quality Issues (CrewAI Guardrails)")
    print("="*50)
    quality_ticket = "help"
    print(f"Ticket: {quality_ticket}")
    print("Expected: If response is too short/unhelpful, CrewAI guardrails RETRY (up to 3x)")
    print("          If response passes security but fails quality, agent improves it")
    print()

    result2_5 = crew.kickoff(inputs={
        "ticket": quality_ticket
    })
    print("\n📝 Result:")
    print(result2_5)
    print("\n💡 Explanation: CrewAI guardrails validate quality and retry with feedback.")
    print("   Quality issues can be fixed through iteration.")
    print("   Watch the verbose output above - you may see multiple attempts!")
    print("   Guardrails checked:")
    print("     - Length (20-150 words)")
    print("     - Professional structure (no templates)")
    print("     - Genuine helpfulness (not evasive)")
    print("     - Friendly tone (LLM-based)")
    print("     - Useful information (LLM-based)")

    # --- Scenario 3: Final Output Validation (Catches Unprotected Tool PII) ---
    print("\n" + "="*50)
    print("SCENARIO 3: Final Output Validation - Catches PII from Unprotected Tool")
    print("="*50)
    print("This demonstrates validating the FINAL crew output for PII,")
    print("catching cases where a legacy/unprotected tool returns PII")
    print("and the agent relays it to the user.")
    print()
    print("In this scenario:")
    print("- Agent calls get_customer_info (unprotected legacy tool)")
    print("- Tool returns customer data with email and phone")
    print("- Agent relays this info in its final response")
    print("- Final output validation catches the PII and blocks it")
    print()

    # Create separate crew for Scenario 3 with unprotected tool
    print("Creating Scenario 3 crew with unprotected customer info tool...")
    scenario3_crew = create_scenario3_crew()

    final_output_ticket = "I'm customer CUST-12345. Can you look up my contact information?"
    print(f"Ticket: {final_output_ticket}")
    print("Expected: Agent retrieves PII from tool, final validation BLOCKS the output")
    print()

    result3 = scenario3_crew.kickoff(inputs={
        "ticket": final_output_ticket
    })

    print("\n[Validating Final Output]")
    try:
        # Validate the final crew output for PII
        validated_output = validate_final_output(str(result3))
        print("\n📝 Result (Validated - No PII):")
        print(validated_output)
    except ControlViolationError as e:
        print("\n🚫 FINAL OUTPUT BLOCKED - PII Detected!")
        print(f"Violation: {e.message}")
        print("\nThis demonstrates final output validation:")
        print("1. Agent called unprotected tool (get_customer_info)")
        print("2. Tool returned customer data with email (john.smith@customer.com) and phone (555-123-4567)")
        print("3. Agent relayed this info in its final response")
        print("4. Final output validation caught the PII and blocked the entire response")
        print("\n📝 Original Output (BLOCKED):")
        print(str(result3)[:500] + "..." if len(str(result3)) > 500 else str(result3))

    print("\n" + "="*50)
    print("Demo Complete!")
    print("="*50)
    print("""
Summary - Multi-Layer Protection Architecture:

AGENT CONTROL (Security/Compliance - Immediate Blocking):
  🚫 LAYER 1 (PRE): Unauthorized data access blocked at INPUT
  🚫 LAYER 2 (POST): PII leakage blocked at tool OUTPUT
  🚫 LAYER 4 (FINAL): PII in final crew output blocked

CREWAI GUARDRAILS (Quality Validation - Retry with Feedback):
  ✨ LAYER 3: Response quality validated (length, tone, structure)
      → If fails: Retry up to 3 times with feedback
      → Examples: Too short, unprofessional, unhelpful

KEY DIFFERENCES:
  Agent Control: Security violations → Block immediately (no retry)
  CrewAI Guardrails: Quality issues → Retry with feedback (up to 3x)

EXECUTION ORDER:
  1. Agent Control PRE checks input (security)
  2. Tool executes (if PRE passes)
  3. Agent Control POST checks output (compliance)
  4. CrewAI Guardrails check quality (if POST passes)
  5. Agent Control FINAL validates complete output

This gives you BOTH security AND quality in production!
""")


if __name__ == "__main__":
    main()
