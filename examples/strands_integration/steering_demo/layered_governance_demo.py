#!/usr/bin/env python3
"""
Layered Governance Demo - AgentControl + Strands Steering

Shows two governance layers working together:
- Safety Layer (AgentControl): Hard blocks for PII and tool validation
- Quality Layer (Steering): Contextual guidance for response quality

Usage:
    streamlit run layered_governance_demo.py
"""

import asyncio
import os
import sys
from pathlib import Path
from uuid import UUID

import streamlit as st
from dotenv import load_dotenv

from strands import Agent, tool
from strands.models.openai import OpenAIModel
from strands.hooks import BeforeInvocationEvent, BeforeModelCallEvent, AfterModelCallEvent, BeforeToolCallEvent
from strands.experimental.steering import SteeringHandler, Guide, Proceed

import agent_control
from agent_control import ControlViolationError

# Add common module to path
sys.path.insert(0, str(Path(__file__).parent.parent / "common"))
from agent_control_hook import AgentControlHook

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env", override=False)


# ============================================================================
# Customer Support Tools
# ============================================================================

@tool
@agent_control.control()
async def check_order_status(order_id: str) -> dict:
    """
    Check the status of a customer's order.

    Args:
        order_id: Order ID (e.g., "ORD-12345" or "12345")
    """
    # Normalize order ID - add ORD- prefix if missing
    if not order_id.startswith("ORD-"):
        order_id = f"ORD-{order_id}"

    # Simulate order lookup
    orders = {
        "ORD-12345": {"status": "delivered", "delivery_date": "2024-01-15", "eligible_for_refund": True},
        "ORD-67890": {"status": "processing", "eta": "3-5 days"},
    }

    if order_id in orders:
        return orders[order_id]
    return {"status": "not_found", "message": "Order not found"}


@tool
@agent_control.control()
async def process_refund(order_id: str, amount: float, reason: str) -> dict:
    """
    Process a refund for a customer order.

    Args:
        order_id: Order ID to refund
        amount: Refund amount in dollars
        reason: Reason for refund
    """
    # Simulate refund processing
    return {
        "success": True,
        "refund_id": f"REF-{order_id}",
        "amount": amount,
        "message": f"Refund of ${amount:.2f} processed for order {order_id}"
    }


# ============================================================================
# Quality Steering Handler
# ============================================================================

class QualitySteeringHandler(SteeringHandler):
    """Provides quality guidance for customer support agents."""

    def __init__(self):
        super().__init__()
        self.guidances_given = 0

    async def steer_after_model(self, *, agent, message, stop_reason, **kwargs):
        """Check agent responses for quality issues."""
        print("\n" + "="*70)
        print("✨ STEERING: steer_after_model() CALLED")
        print("="*70)

        # Extract response text
        response_text = self._extract_text(message)
        print(f"📝 Extracted response: {response_text[:200]}...")

        if not response_text:
            print("⚠️  No response text extracted, returning Proceed()")
            return Proceed()

        response_lower = response_text.lower()

        # Check for vague/technical error messages without specifics
        print(f"\n🔍 Checking for vague technical errors...")
        has_violation_phrase = any(phrase in response_lower for phrase in ["safety check", "safety violation", "violation", "resulted in"])
        print(f"   Has violation phrase: {has_violation_phrase}")

        if has_violation_phrase:
            has_policy_limit = "$10,000" in response_text or "10,000" in response_text or "10000" in response_text
            print(f"   Has $10,000 policy limit: {has_policy_limit}")

            if not has_policy_limit:
                self.guidances_given += 1
                print(f"🎯 STEERING TRIGGERED! Guidance #{self.guidances_given}")
                print(f"   Reason: Vague technical error without policy limit")
                guidance = Guide(
                    "⚠️ Don't give vague technical errors! Be specific about what went wrong and the actual policy. "
                    "Say: 'I understand you'd like a $15,000 refund. Our policy allows refunds up to $10,000. "
                    "For amounts over this limit, I can connect you with our manager approval team who can help with your request.'"
                )
                print(f"   Returning Guide()")
                print("="*70 + "\n")
                return guidance

        # Check for poor error handling (just saying "can't" or "unable")
        print(f"\n🔍 Checking for poor error handling...")
        has_refusal = any(phrase in response_lower for phrase in ["i can't", "i cannot", "unable to", "not allowed"])
        print(f"   Has refusal phrase: {has_refusal}")

        if has_refusal:
            has_helpful = any(helpful in response_lower for helpful in ["however", "alternatively", "instead", "let me", "i can help", "contact support", "manager"])
            print(f"   Has helpful alternatives: {has_helpful}")

            if not has_helpful:
                self.guidances_given += 1
                print(f"🎯 STEERING TRIGGERED! Guidance #{self.guidances_given}")
                print(f"   Reason: Refusal without helpful alternatives")
                print(f"   Returning Guide()")
                print("="*70 + "\n")
                return Guide(
                    "⚠️ Don't just refuse - be helpful! When you can't do something, explain why briefly and offer alternatives. "
                    "For example: 'I understand your frustration. While I can't process amounts over $10,000 directly, "
                    "I can help you contact our manager approval team who can assist with larger refunds.'"
                )

        # Check for unauthorized refund promises
        print(f"\n🔍 Checking for unauthorized promises...")
        has_promise = any(phrase in response_lower for phrase in ["i'll refund", "i'll process", "processing your refund"])
        print(f"   Has promise phrase: {has_promise}")

        if has_promise:
            has_check = "let me check" in response_lower or "according to" in response_lower
            print(f"   Has order check: {has_check}")

            if not has_check:
                self.guidances_given += 1
                print(f"🎯 STEERING TRIGGERED! Guidance #{self.guidances_given}")
                print(f"   Reason: Unauthorized promise without order check")
                print(f"   Returning Guide()")
                print("="*70 + "\n")
                return Guide(
                    "⚠️ Don't promise refunds without checking the order first. Say: "
                    "'Let me check your order status and see what options are available.'"
                )

        # All checks passed
        print(f"\n✅ All steering checks passed - Returning Proceed()")
        print("="*70 + "\n")
        return Proceed()

    def _extract_text(self, message) -> str:
        """Extract text from message content."""
        if isinstance(message, dict):
            content = message.get('content', [])
        elif hasattr(message, 'content'):
            content = message.content
        else:
            return ""

        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and 'text' in block:
                    text_parts.append(block['text'])
                elif hasattr(block, 'text'):
                    text_parts.append(block.text)
            return ' '.join(text_parts)
        return ""


# ============================================================================
# Agent Creation
# ============================================================================

def create_support_agent(agent_uuid: UUID, server_url: str) -> tuple[Agent, QualitySteeringHandler]:
    """Create customer support agent with both governance layers."""
    model = OpenAIModel(model_id="gpt-4o-mini")

    # Safety layer (AgentControl)
    safety_hook = AgentControlHook(
        agent_uuid=agent_uuid,
        agent_name="steering-demo",
        server_url=server_url,
        event_control_list=[BeforeInvocationEvent, BeforeModelCallEvent, AfterModelCallEvent, BeforeToolCallEvent]
    )

    # Quality layer (Steering)
    quality_handler = QualitySteeringHandler()

    agent = Agent(
        name="support_agent",
        model=model,
        system_prompt="""You are a friendly customer support agent helping with order refunds.

Your role:
1. Help customers with refund requests
2. Use the available tools:
   - check_order_status: Check order status and eligibility
   - process_refund: Process refunds for customers
3. Be warm, empathetic, and professional

CRITICAL WORKFLOW:
- Step 1: Check order status
- Step 2: If eligible_for_refund is true, ALWAYS call process_refund with the requested amount
- Step 3: Provide the result to the customer

When a customer requests a refund and the order is eligible, you MUST attempt to process it using the process_refund tool, even for large amounts. The system will handle policy enforcement.

Be helpful and offer alternatives when operations fail.""",
        tools=[check_order_status, process_refund],
        hooks=[safety_hook, quality_handler]
    )

    return agent, quality_handler


# ============================================================================
# UI Functions
# ============================================================================

def render_header():
    """Render the app header."""
    st.title("🎯 Layered Governance Demo")
    st.subheader("Safety (AgentControl) + Quality (Steering)")

    st.markdown("""
    **Two Governance Layers Working Together:**

    🛡️ **Safety Layer (AgentControl)** - Hard blocks for compliance
    - Blocks excessive refund amounts ($15K > $10K limit)
    - Prevents security risks and policy violations
    - *Action: BLOCK and cancel invalid operations*

    ✨ **Quality Layer (Steering)** - Contextual guidance for graceful handling
    - Detects poor error handling (just saying "can't")
    - Guides agent to be helpful and offer alternatives
    - *Action: GUIDE agent to provide professional responses*

    **The Challenge:** When AgentControl blocks a request, how does the agent respond?
    **The Solution:** Steering guides graceful error handling with helpful alternatives.
    """)


def render_sidebar(safety_blocks: int, quality_guidances: int, total_requests: int):
    """Render the governance dashboard."""
    st.sidebar.title("📊 Governance Dashboard")

    # Layer Status
    st.sidebar.subheader("🛡️ Safety Layer (AgentControl)")
    if st.session_state.get("agentcontrol_initialized"):
        st.sidebar.success("✅ Active - PII Detection + Tool Validation")
    else:
        st.sidebar.error("❌ Inactive")

    st.sidebar.subheader("✨ Quality Layer (Steering)")
    st.sidebar.success("✅ Active - Quality Guidance")

    # Stats
    st.sidebar.subheader("📈 Statistics")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric("🛡️ Safety Blocks", safety_blocks)
    with col2:
        st.metric("✨ Quality Guides", quality_guidances,
                  delta=f"+{quality_guidances}" if quality_guidances > 0 else None,
                  delta_color="normal")
    st.sidebar.metric("Total Requests", total_requests)

    # Show layer activity
    if safety_blocks > 0 or quality_guidances > 0:
        st.sidebar.success("🎯 Both Layers Active!")

    # Legend
    st.sidebar.markdown("---")
    st.sidebar.caption("""
    **How it works:**
    - 🛡️ Safety blocks unsafe operations
    - ✨ Quality guides better responses
    - Together they ensure safe + helpful interactions
    """)


def render_test_prompts():
    """Render test examples."""
    st.subheader("🎯 Try This Example")

    test_prompt = "I want a full refund of $15,000 for my order ORD-12345. Process it now!"

    if st.button("🔄 Layered Governance Demo", use_container_width=True):
        st.session_state.test_prompt = test_prompt
        st.rerun()

    st.caption("""
    **Watch both layers work together:**
    1. Agent attempts to process $15K refund
    2. 🛡️ **AgentControl** blocks the tool call (exceeds $10K limit)
    3. ✨ **Steering** guides agent to handle the block gracefully
    4. Agent responds professionally with helpful alternatives
    """)


def render_chat(agent: Agent, quality_handler: QualitySteeringHandler):
    """Render the chat interface."""
    st.subheader("💬 Customer Support Chat")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "safety_blocks" not in st.session_state:
        st.session_state.safety_blocks = 0
    if "quality_guidances" not in st.session_state:
        st.session_state.quality_guidances = 0

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Handle test prompt injection
    user_input = None
    if "test_prompt" in st.session_state:
        user_input = st.session_state.test_prompt
        del st.session_state.test_prompt

    # Chat input
    if prompt := (user_input or st.chat_input("Type your message...")):
        # Track initial guidance count
        initial_guidances = quality_handler.guidances_given

        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get bot response
        with st.chat_message("assistant"):
            with st.spinner("🤔 Thinking..."):
                try:
                    result = asyncio.run(agent.invoke_async(prompt))

                    # Extract response
                    response = "No response generated"
                    if result and hasattr(result, 'message'):
                        agent_message = result.message
                        content = None

                        if isinstance(agent_message, dict):
                            content = agent_message.get('content')
                        elif hasattr(agent_message, 'content'):
                            content = agent_message.content

                        if content is not None:
                            if isinstance(content, list):
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict) and 'text' in block:
                                        text_parts.append(block['text'])
                                    elif hasattr(block, 'text'):
                                        text_parts.append(block.text)
                                response = '\n'.join(text_parts) if text_parts else str(content)
                            else:
                                response = str(content)

                    st.markdown(response)

                    # Update stats
                    new_guidances = quality_handler.guidances_given - initial_guidances

                    if new_guidances > 0:
                        st.session_state.quality_guidances += new_guidances
                        # Show steering notification
                        st.success(f"✨ **Quality Layer Activated!** Steering provided {new_guidances} guidance(s) to improve the response.")

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response
                    })

                except ControlViolationError as e:
                    # Safety control blocked the request
                    st.session_state.safety_blocks += 1
                    st.warning(f"🛡️ **Safety Control Activated**\n\n{str(e)}")
                    st.info("Your request was blocked by our safety system. Please rephrase without sensitive information.")
                except Exception as e:
                    st.error(f"❌ Error: {e}")

        st.rerun()


# ============================================================================
# Main App
# ============================================================================

def main():
    """Run the layered governance demo."""
    st.set_page_config(
        page_title="Layered Governance Demo",
        page_icon="🎯",
        layout="wide"
    )

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "safety_blocks" not in st.session_state:
        st.session_state.safety_blocks = 0
    if "quality_guidances" not in st.session_state:
        st.session_state.quality_guidances = 0

    # Initialize AgentControl
    if "agentcontrol_initialized" not in st.session_state:
        try:
            agent_control.init(
                agent_name="steering-demo",
                agent_id="550e8400-e29b-41d4-a716-446655440010"
            )
            st.session_state.agentcontrol_initialized = True
        except Exception as e:
            st.session_state.agentcontrol_initialized = False
            st.error(f"Failed to initialize AgentControl: {e}")
            st.stop()

    # Create agent
    agent_uuid = UUID("550e8400-e29b-41d4-a716-446655440010")
    server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

    if "agent" not in st.session_state:
        agent, quality_handler = create_support_agent(agent_uuid, server_url)
        st.session_state.agent = agent
        st.session_state.quality_handler = quality_handler

    # Render UI
    render_header()
    render_sidebar(
        st.session_state.safety_blocks,
        st.session_state.quality_guidances,
        len(st.session_state.messages) // 2  # Divide by 2 for user-bot pairs
    )
    render_test_prompts()

    st.markdown("---")

    render_chat(st.session_state.agent, st.session_state.quality_handler)

    # Footer
    st.markdown("---")
    st.caption("Built with AgentControl + AWS Strands Steering + Streamlit")


if __name__ == "__main__":
    main()
