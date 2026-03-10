"""
Interactive Customer Support Demo with AgentControl

This Streamlit app demonstrates AgentControl's real-time safety features through
an interactive customer support chatbot. Users can chat with the bot and see
AgentControl block unsafe content in real-time.

VALUE DEMONSTRATION:
- Real-time PII protection (blocks SSN, credit cards, emails)
- Toxicity filtering (blocks rude/inappropriate language)
- Hallucination detection (prevents false information)
- Off-topic prevention (keeps conversations focused)
- Multi-agent safety (triage → specialist → response)

TRY TO BREAK IT:
The app includes "attack" prompts that demonstrate how AgentControl protects
against common safety issues. Watch the safety dashboard to see blocks in action!

Prerequisites:
    1. Agent Control server running:
       curl -fsSL https://raw.githubusercontent.com/agentcontrol/agent-control/docker-compose.yml | docker compose -f - up -d
    2. Controls created: python setup_interactive_controls.py
    3. OpenAI API key set
    4. Galileo API key set

Usage:
    streamlit run interactive_support_demo.py
"""

import asyncio
import os
from pathlib import Path
from typing import Any, Optional

import streamlit as st
from dotenv import load_dotenv

from strands import Agent, tool
from strands.hooks import (
    BeforeInvocationEvent,
    AfterModelCallEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
)
from strands.models.openai import OpenAIModel

import agent_control
from agent_control import ControlSteerError, ControlViolationError
from agent_control.integrations.strands import AgentControlPlugin
from agent_control_models import EvaluationResult

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env", override=False)


# ============================================================================
# Safety Tracking Plugin (using reusable AgentControlPlugin)
# ============================================================================

def _action_error(result: EvaluationResult) -> tuple[str, Exception] | None:
    """
    Return the first blocking action as an exception.

    Args:
        result: EvaluationResult from AgentControl

    Returns:
        ("deny", ControlViolationError) or ("steer", ControlSteerError) if a blocking
        action is present, otherwise None.
    """
    match = next(
        (m for m in (result.matches or []) if m.action in ("deny", "steer")),
        None,
    )
    if not match:
        return None

    msg = getattr(getattr(match, "result", None), "message", None) or result.reason
    msg = msg or f"Control '{match.control_name}' triggered"

    if match.action == "deny":
        err = ControlViolationError(message=f"Policy violation [{match.control_name}]: {msg}")
        return "deny", err

    ctx = getattr(match, "steering_context", None)
    ctx_msg = getattr(ctx, "message", None) if ctx else None
    err = ControlSteerError(
        control_name=match.control_name,
        message=f"Steering required [{match.control_name}]: {msg}",
        steering_context=ctx_msg or msg,
    )
    return "steer", err


class SafetyTrackingPlugin(AgentControlPlugin):
    """
    Streamlit-specific plugin that extends AgentControlPlugin.

    Tracks all safety decisions and stores them in Streamlit session state for UI display.
    """

    def __init__(self, agent_name: str):
        """
        Initialize SafetyTrackingPlugin with Streamlit tracking.

        Args:
            agent_name: Name of the agent for logging and control filtering
        """
        # Initialize base AgentControlPlugin with specific events and custom callback
        super().__init__(
            agent_name=agent_name,
            event_control_list=[
                BeforeInvocationEvent,  # Check user input (has messages attribute)
                AfterModelCallEvent,    # Check output from LLM
                BeforeToolCallEvent,    # Check tool calls (enables tool-specific controls)
                AfterToolCallEvent,     # Check tool results
            ],
            on_violation_callback=self._handle_streamlit_violation,
            enable_logging=True  # Enable console logging to see control checks
        )

    def _initialize_session_state(self):
        """Initialize Streamlit session state if not already present."""
        if "stats" not in st.session_state:
            st.session_state.stats = {
                "checks_passed": 0,
                "violations_blocked": 0,
                "total_checks": 0
            }

        if "current_message_evaluations" not in st.session_state:
            st.session_state.current_message_evaluations = []

        if "current_message_violations" not in st.session_state:
            st.session_state.current_message_violations = []

    def _handle_streamlit_violation(self, violation_info: dict, _evaluation_result: Any):
        """
        Custom callback for updating Streamlit session state when violation detected.

        This is called by AgentControlPlugin whenever a safety violation occurs.
        """
        self._initialize_session_state()

        # Store detailed violation for UI
        violation = {
            "agent": violation_info["agent"],
            "controls": [violation_info["control_name"]],
            "stage": violation_info["stage"]
        }
        st.session_state.current_message_violations.append(violation)

        # Update violation stats
        st.session_state.stats["violations_blocked"] += 1

    async def _evaluate_and_enforce(
        self,
        step_name: str,
        input: Any | None = None,
        output: Any | None = None,
        context: dict[str, Any] | None = None,
        step_type: str = "llm",
        stage: str = "pre",
        violation_type: str = "Step",
        use_runtime_error: bool = False,
    ) -> None:
        """
        Override to add Streamlit-specific tracking for all checks.

        Tracks every check (pass or fail) in session state and stores
        detailed evaluation results for UI display.
        """
        self._initialize_session_state()
        st.session_state.stats["total_checks"] += 1

        result = await agent_control.evaluate_controls(
            step_name=step_name,
            input=input,
            output=output,
            step_type=step_type,
            stage=stage,
            agent_name=self.agent_name,
        )

        if result.is_safe:
            st.session_state.stats["checks_passed"] += 1

        try:
            evaluation_details = {
                "agent": self.agent_name,
                "stage": stage,
                "is_safe": result.is_safe,
                "matches": [
                    {
                        "control_name": m.control_name,
                        "confidence": m.result.confidence,
                        "message": m.result.message,
                        "metadata": m.result.metadata or {},
                    }
                    for m in (result.matches or [])
                ],
                "non_matches": [
                    {
                        "control_name": nm.control_name,
                        "confidence": nm.result.confidence,
                        "message": nm.result.message,
                        "metadata": nm.result.metadata or {},
                    }
                    for nm in (result.non_matches or [])
                ],
            }
            st.session_state.current_message_evaluations.append(evaluation_details)
        except Exception:
            pass

        action = _action_error(result)
        if action:
            _, err = action
            control_name = getattr(err, "control_name", "unknown")
            self._handle_streamlit_violation(
                {
                    "agent": self.agent_name,
                    "control_name": control_name,
                    "stage": stage,
                },
                result,
            )
            self._raise_error(err, use_runtime_error)

        if not result.is_safe:
            control_name = "unknown"
            reason = result.reason

            if result.matches:
                first_match = result.matches[0]
                control_name = first_match.control_name
                if not reason:
                    match_result = getattr(first_match, "result", None)
                    msg = getattr(match_result, "message", None) if match_result else None
                    reason = msg or f"Control '{control_name}' triggered"

            self._handle_streamlit_violation(
                {
                    "agent": self.agent_name,
                    "control_name": control_name,
                    "stage": stage,
                },
                result,
            )
            error_msg = f"Policy violation [{control_name}]: {reason}"
            self._raise_error(ControlViolationError(message=error_msg), use_runtime_error)


# ============================================================================
# Simulated Customer Support Tools
# ============================================================================

@tool
async def lookup_order(order_id: str) -> dict:
    """
    Look up order information.

    Args:
        order_id: The order ID to look up

    Returns:
        Order details including status and items
    """
    await asyncio.sleep(0.2)

    # Simulate order lookup
    orders = {
        "ORD-12345": {
            "status": "Shipped",
            "items": ["Laptop", "Mouse"],
            "total": "$1,299.99",
            "tracking": "TRK-98765"
        },
        "ORD-67890": {
            "status": "Processing",
            "items": ["Headphones"],
            "total": "$199.99",
            "tracking": "Not yet available"
        }
    }

    return orders.get(order_id, {"status": "Not found"})


@tool
async def check_return_policy(product: str) -> str:
    """
    Check the return policy for a product.

    Args:
        product: The product name

    Returns:
        Return policy information
    """
    await asyncio.sleep(0.1)
    return "30-day return policy for most items. Electronics have a 14-day return window."


@tool
async def search_knowledge_base(query: str) -> str:
    """
    Search the company knowledge base.

    Args:
        query: The search query

    Returns:
        Relevant information from knowledge base
    """
    await asyncio.sleep(0.2)

    kb = {
        "shipping": "Standard shipping: 5-7 business days. Express: 2-3 business days.",
        "warranty": "All products come with a 1-year manufacturer warranty.",
        "contact": "Email: support@example.com, Phone: 1-800-SUPPORT"
    }

    for key, value in kb.items():
        if key in query.lower():
            return value

    return "I couldn't find specific information. Please contact support."


# ============================================================================
# Initialize AgentControl and Create Agents
# ============================================================================

def initialize_agentcontrol():
    """Initialize AgentControl with customer support controls."""
    if "agentcontrol_initialized" in st.session_state:
        return

    server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

    try:
        agent_control.init(
            agent_name="interactive-support-demo",
            server_url=server_url,
            agent_description="Interactive customer support demo with real-time safety"
        )
        st.session_state.agentcontrol_initialized = True
        st.session_state.controls_active = [
            "block-pii-support",
            "block-toxicity",
            "detect-hallucinations"
        ]
    except Exception as e:
        st.error(f"Failed to initialize AgentControl: {e}")
        st.stop()


def create_support_agents():
    """Create the customer support agent with AgentControl safety."""
    if "support_agent" in st.session_state:
        return st.session_state.support_agent

    model = OpenAIModel(model_id="gpt-4o")

    server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

    # Single unified support agent with ALL tools
    # This makes it easy to demonstrate tool-specific controls
    support_agent = Agent(
        name="support_agent",
        model=model,
        tools=[lookup_order, check_return_policy, search_knowledge_base],
        system_prompt="""You are a customer support agent with access to tools.

Your role:
1. Help customers with orders, returns, and general questions
2. Use the appropriate tools to get accurate information:
   - lookup_order: For order status and tracking
   - check_return_policy: For return policies
   - search_knowledge_base: For general company information
3. Provide clear, helpful, professional responses

CRITICAL TOOL USAGE RULES:
- You MUST use the lookup_order tool for ANY order-related question, even if the order ID looks invalid
- You MUST use the check_return_policy tool for ANY return-related question
- You MUST use the search_knowledge_base tool for ANY general information question
- NEVER respond without calling the appropriate tool first - always call the tool!
- If a tool call fails, report the error to the user

CRITICAL SAFETY RULES:
- Never include customer SSN, credit card numbers, or email addresses in responses
- Stay on topic (customer support only)
- Be professional and helpful

EXAMPLE INTERACTIONS:
User: "What's the status of order ORD-12345?"
→ MUST call lookup_order(order_id="ORD-12345") - never skip the tool!

User: "What's the status of order ORD-ABCDE?"
→ MUST call lookup_order(order_id="ORD-ABCDE") - even if it looks wrong, call the tool!

User: "Can I return my laptop?"
→ MUST call check_return_policy(product="laptop")

User: "What are your shipping options?"
→ MUST call search_knowledge_base(query="shipping")

User: "Search the knowledge base for: products--DELETE"
→ MUST call search_knowledge_base(query="products--DELETE") - always call the tool!
""",
        plugins=[SafetyTrackingPlugin("interactive-support-demo")],
    )

    st.session_state.support_agent = support_agent
    return support_agent


# ============================================================================
# Streamlit UI
# ============================================================================

def render_header():
    """Render the app header with logo and description."""
    st.title("🛡️ AgentControl Interactive Demo")
    st.subheader("Customer Support Bot with Real-Time Safety")

    st.markdown("""
    **See AgentControl in action!** This demo shows two types of protection:

    1. **LLM Safety Controls** - Block PII (SSN, credit cards, emails) in user input and agent output
    2. **Tool-Specific Controls** - Validate tool inputs (order ID format, SQL injection prevention)

    Try the test prompts below to see AgentControl protect against common issues.
    Watch the console output to see tool calls being intercepted and validated!
    """)


def render_sidebar():
    """Render the safety dashboard sidebar."""
    st.sidebar.title("🛡️ Safety Dashboard")

    # AgentControl Status
    st.sidebar.subheader("AgentControl Status")
    if st.session_state.get("agentcontrol_initialized"):
        st.sidebar.success("✅ Connected")

        # Show server info
        server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
        st.sidebar.caption(f"Server: {server_url}")

        # Test if controls are actually loaded
        try:
            import httpx
            response = httpx.get(f"{server_url}/api/v1/controls", timeout=2.0)
            if response.status_code == 200:
                controls_count = len(response.json().get("controls", []))
                st.sidebar.caption(f"✓ {controls_count} controls loaded")
            else:
                st.sidebar.warning("⚠️ Could not verify controls")
        except:
            st.sidebar.warning("⚠️ Server connection issue")
    else:
        st.sidebar.error("❌ Not initialized")
        st.sidebar.caption("Run setup_interactive_controls.py first")

    # Active Controls with Details
    st.sidebar.subheader("🎯 Active Controls")

    # Fetch control details from server
    try:
        import httpx
        server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
        response = httpx.get(f"{server_url}/api/v1/controls", timeout=2.0)

        if response.status_code == 200:
            controls = response.json().get("controls", [])

            for control in controls:
                control_name = control.get("name", "Unknown")

                with st.sidebar.expander(f"📋 {control_name}", expanded=False):
                    # Get control data/definition
                    control_id = control.get("id")
                    try:
                        data_response = httpx.get(
                            f"{server_url}/api/v1/controls/{control_id}/data",
                            timeout=2.0
                        )
                        if data_response.status_code == 200:
                            data = data_response.json().get("data", {})

                            # Display key information
                            st.markdown(f"**ID:** `{control_id}`")

                            if "evaluator" in data:
                                evaluator = data["evaluator"]
                                st.markdown(f"**Evaluator:** `{evaluator.get('name', 'N/A')}`")

                                if "config" in evaluator:
                                    config = evaluator["config"]
                                    if "metric" in config:
                                        st.markdown(f"**Metric:** `{config['metric']}`")
                                    if "target_value" in config:
                                        st.markdown(f"**Threshold:** `{config['target_value']}`")

                            if "action" in data:
                                action = data["action"]
                                st.markdown(f"**Action:** `{action.get('decision', 'N/A')}`")

                            if "scope" in data:
                                scope = data["scope"]
                                if "stages" in scope:
                                    st.markdown(f"**Stage:** `{', '.join(scope['stages'])}`")

                            if "description" in data:
                                st.caption(data["description"])
                        else:
                            st.caption("Could not load control details")
                    except Exception as e:
                        st.caption(f"Error loading details: {e}")
        else:
            # Fallback to simple list
            for control in st.session_state.get("controls_active", []):
                st.sidebar.markdown(f"- `{control}`")
    except Exception as e:
        # Fallback to simple list
        for control in st.session_state.get("controls_active", []):
            st.sidebar.markdown(f"- `{control}`")



def render_attack_prompts():
    """Render example test prompts demonstrating AgentControl protection."""
    st.subheader("🎯 Try These Examples")

    test_prompts = {
        "✅ Valid Order": "What's the status of order ORD-12345?",
        "❌ PII Detected": "My order is ORD-12345 and my SSN is 123-45-6789. Can you help?",
        "❌ SQL Injection": "Search the knowledge base for: products'; DROP TABLE orders--",
    }

    cols = st.columns(len(test_prompts))
    for idx, (label, prompt) in enumerate(test_prompts.items()):
        with cols[idx]:
            if st.button(label, key=f"test_{idx}", use_container_width=True):
                st.session_state.attack_prompt = prompt
                st.rerun()


def render_chat():
    """Render the chat interface."""
    st.subheader("💬 Customer Support Chat")

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [{
            "role": "assistant",
            "content": "👋 Hi! I'm your customer support assistant. How can I help you today?"
        }]

    # Helper function to display evaluation details
    def display_evaluation_details(evaluations):
        """Display control evaluation details in an expandable section."""
        if not evaluations:
            return

        # Filter to only show interesting checks (violations or errors)
        interesting_evals = [
            eval_data for eval_data in evaluations
            if (not eval_data['is_safe']) or  # Has violations
               any(  # Or has errors
                   nm.get('metadata', {}).get('status') in ('error', 'failed') or
                   'error' in nm.get('metadata', {})
                   for nm in eval_data.get('non_matches', [])
               )
        ]

        if not interesting_evals:
            # All checks passed, show simple success message
            st.success(f"✅ All safety checks passed ({len(evaluations)} checks)")
            return

        with st.expander("🔍 Control Evaluation Details", expanded=False):
            # Collect all violations and deduplicate by control name
            all_violations = []
            for eval_data in interesting_evals:
                if not eval_data['is_safe'] and eval_data.get('matches'):
                    all_violations.extend(eval_data['matches'])

            # Deduplicate violations by control name
            unique_violations = list({v['control_name']: v for v in all_violations}.values())

            if unique_violations:
                st.error(f"🚫 Security violation detected")

                for violation in unique_violations:
                    with st.container():
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"• **{violation['control_name']}**")
                            # Simplify the message - detect what type of PII
                            msg_lower = violation['message'].lower()
                            if 'credit' in msg_lower or 'card' in msg_lower or '4532' in violation['message']:
                                st.caption("_Credit card number detected_")
                            elif 'ssn' in msg_lower or 'social security' in msg_lower or '123-45' in violation['message']:
                                st.caption("_Social Security Number detected_")
                            elif 'email' in msg_lower or '@' in violation['message']:
                                st.caption("_Email address detected_")
                            else:
                                st.caption("_PII pattern detected_")
                        with col2:
                            st.metric("Confidence", f"{violation['confidence']:.0%}")

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            # Show evaluation details if available for this message
            if message.get("evaluations"):
                display_evaluation_details(message["evaluations"])

    # Handle attack prompt injection
    user_input = None
    if "attack_prompt" in st.session_state:
        user_input = st.session_state.attack_prompt
        del st.session_state.attack_prompt

    # Chat input
    if prompt := (user_input or st.chat_input("Type your message...")):
        # Initialize tracking for this message
        st.session_state.current_message_violations = []
        st.session_state.current_message_evaluations = []

        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get bot response
        with st.chat_message("assistant"):
            # Debug status
            status_placeholder = st.empty()
            status_placeholder.info("🔄 Processing your message...")

            with st.spinner("🤔 Thinking..."):
                try:
                    # Check agent exists
                    if "support_agent" not in st.session_state:
                        raise RuntimeError("Agent not initialized - refresh the page")

                    agent = st.session_state.support_agent
                    status_placeholder.info(f"🤖 Running support agent...")

                    # Log what we're sending
                    st.caption(f"📤 Input: `{prompt[:50]}...`")

                    # Create async task with timeout
                    async def run_with_timeout():
                        try:
                            st.caption("⚙️ Starting agent.invoke_async()...")
                            result = await asyncio.wait_for(
                                agent.invoke_async(prompt),
                                timeout=30.0  # 30 second timeout
                            )
                            st.caption("✅ Agent.invoke_async() completed")
                            return result
                        except Exception as e:
                            st.caption(f"❌ Agent.invoke_async() failed: {e}")
                            raise

                    st.caption("🔄 Running async task...")
                    result = asyncio.run(run_with_timeout())
                    st.caption("✅ Async task completed")

                    status_placeholder.empty()  # Clear status

                    # Extract response from AgentResult
                    # Agent.invoke_async() returns an AgentResult with a message
                    response = "No response generated"

                    if result:
                        # Try to extract message from result
                        agent_message = None

                        # Check if result has message attribute
                        if hasattr(result, 'message'):
                            agent_message = result.message
                        # Check if result IS the message (some Strands versions return message directly)
                        elif hasattr(result, 'content'):
                            agent_message = result

                        if agent_message:
                            # Extract text content from message
                            content = None
                            if isinstance(agent_message, dict):
                                content = agent_message.get('content')
                            elif hasattr(agent_message, 'content'):
                                content = agent_message.content

                            if content is not None:
                                # If content is a list, extract text from each block
                                if isinstance(content, list):
                                    text_parts = []
                                    for block in content:
                                        if isinstance(block, dict) and 'text' in block:
                                            text_parts.append(block['text'])
                                        elif hasattr(block, 'text'):
                                            text_parts.append(block.text)
                                        else:
                                            text_parts.append(str(block))
                                    response = '\n'.join(text_parts)
                                else:
                                    response = str(content)
                            else:
                                response = str(agent_message)
                        else:
                            # Fallback: stringify result
                            response = str(result)

                    st.markdown(response)

                    # Show which controls detected violations during this exchange
                    violations = st.session_state.get("current_message_violations", [])
                    if violations:
                        # Group by control name
                        control_counts = {}
                        for v in violations:
                            for control in v["controls"]:
                                control_counts[control] = control_counts.get(control, 0) + 1

                        if control_counts:
                            st.caption("🛡️ **AgentControl Protection Active**")
                            for control, count in control_counts.items():
                                st.caption(f"  • `{control}` detected and blocked violations ({count}x)")

                    # Show detailed control evaluation results using helper function
                    evaluations = st.session_state.get("current_message_evaluations", [])
                    display_evaluation_details(evaluations)

                    # Store message with evaluation details
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response,
                        "evaluations": st.session_state.get("current_message_evaluations", [])
                    })

                    # Clear tracking data for next message
                    st.session_state.current_message_violations = []
                    st.session_state.current_message_evaluations = []

                    # Rerun to update sidebar stats
                    st.rerun()

                except asyncio.TimeoutError:
                    st.error("⏱️ **Request Timeout**")
                    st.warning("The agent took too long to respond. This might be due to retry loops. Please try a simpler question.")
                    response = "I apologize, but I'm unable to respond right now. Please try again with a different question."
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    st.rerun()

                except ControlViolationError as e:
                    # AgentControl blocked the request due to safety violation
                    print(f"\n🚫 CONTROL VIOLATION (caught by Streamlit)")
                    print(f"   Error: {e}")
                    st.error("🚫 **AgentControl Safety Block**")

                    # Show what was blocked
                    with st.expander("🔍 Why was this blocked?", expanded=True):
                        st.markdown(f"**Reason:** {str(e)}")

                        st.info("""
                        **What this means:** AgentControl detected unsafe content in your request
                        and blocked it from being processed. This protects against:
                        - PII leakage (SSN, credit cards, emails)
                        - SQL injection attacks
                        - Malicious input patterns
                        - Data security violations

                        Please try again with a safe request.
                        """)

                    # Provide safe fallback response
                    response = "I apologize, but I cannot process this request due to safety concerns. Please try again with a different question."
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    st.rerun()

                except Exception as e:
                    st.error(f"❌ **Unexpected Error**")
                    st.error(f"**Type:** `{type(e).__name__}`")
                    st.error(f"**Message:** {str(e)}")
                    import traceback
                    with st.expander("🔍 Full Traceback", expanded=True):
                        st.code(traceback.format_exc())

                    # Provide fallback response
                    response = f"I apologize, but I encountered an error: {str(e)[:100]}"
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    st.rerun()

        # This shouldn't be reached if any rerun was triggered above
        st.rerun()


# ============================================================================
# Main App
# ============================================================================

def main():
    """Main Streamlit app."""
    st.set_page_config(
        page_title="AgentControl Interactive Demo",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Initialize
    initialize_agentcontrol()
    create_support_agents()

    # Render UI
    render_header()
    render_sidebar()
    render_attack_prompts()
    render_chat()

    # Footer
    st.markdown("---")
    st.caption("Built with AgentControl + AWS Strands + Streamlit")


if __name__ == "__main__":
    main()
