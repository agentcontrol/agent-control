#!/usr/bin/env python3
"""
Email Safety Demo - AgentControl + Steering

CRITICAL SCENARIO: Prevent PII leakage in automated customer emails

Shows two governance layers:
1. AgentControl (Safety): BLOCKS emails with PII, credentials, sensitive data
2. Steering (Quality): GUIDES agent to rephrase when PII detected

Flow:
  Customer: "Send password reset for account 123-45-6789"
  ↓
  LLM drafts: "We'll reset password for SSN 123-45-6789"
  ↓
  AgentControl: BLOCKS (contains PII)
  ↓
  Steering: GUIDES "Rephrase without PII"
  ↓
  LLM tries again: "We'll reset password for your account"
  ↓
  Email sent ✅

Usage:
    streamlit run email_safety_demo.py
"""

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env", override=False)

# Import required modules
try:
    from strands import Agent, tool
    from strands.models.openai import OpenAIModel
    from strands.hooks import BeforeToolCallEvent, AfterToolCallEvent
    import agent_control
    from agent_control.integrations.strands import AgentControlPlugin, AgentControlSteeringHandler
    from agent_control.control_decorators import ControlViolationError
except ImportError as e:
    st.error(f"Missing dependency: {e}")
    st.stop()


# =============================================================================
# Mock Banking Tools
# =============================================================================

# Mock database of account information (contains PII!)
MOCK_ACCOUNTS = {
    "john@example.com": {
        "account_number": "123456789012",
        "name": "John Smith",
        "balance": 45234.56,
        "transactions": [
            {"date": "2/15", "type": "Deposit", "amount": 15000.00},
            {"date": "2/18", "type": "ATM Withdrawal", "amount": 200.00},
        ]
    },
    "sarah@example.com": {
        "account_number": "987654321098",
        "name": "Sarah Johnson",
        "ssn": "987-65-4321",
        "balance": 128456.78,
        "transactions": [
            {"date": "2/10", "type": "Wire Transfer", "amount": 50000.00},
            {"date": "2/20", "type": "Bill Payment", "amount": 1500.00},
        ]
    },
    "mike@example.com": {
        "account_number": "555123456789",
        "name": "Mike Davis",
        "ssn": "111-22-3333",
        "balance": 95432.10,
        "transactions": [
            {"date": "2/12", "type": "Direct Deposit", "amount": 25000.00},
            {"date": "2/17", "type": "ATM Withdrawal", "amount": 500.00},
        ]
    }
}

@tool
async def lookup_customer_account(customer_email: str) -> dict:
    """Look up customer account information from banking system.

    Args:
        customer_email: Customer's email address

    Returns:
        Account information including account number, balance, transactions, etc.
    """
    account_data = MOCK_ACCOUNTS.get(customer_email, {
        "account_number": "000000000000",
        "name": "Unknown Customer",
        "balance": 0.0,
        "transactions": []
    })

    print(f"\n📊 ACCOUNT LOOKUP: Retrieved data for {customer_email}")
    print(f"   Account: {account_data.get('account_number', 'N/A')}")
    print(f"   Balance: ${account_data.get('balance', 0):,.2f}")
    if account_data.get('ssn'):
        print(f"   ⚠️  SSN: {account_data['ssn']} (PII in database!)")
    print()

    return account_data

@tool
async def send_monthly_account_summary(
    customer_email: str,
    summary_text: str
) -> dict:
    """Send monthly account summary email to customer.

    IMPORTANT: Only call this tool AFTER the final email draft is approved and compliant.
    Do not call this during the drafting phase.

    Args:
        customer_email: Customer's email address
        summary_text: The summary email body text (final, redacted version)
    """
    print(f"\n📧 SENDING EMAIL to {customer_email}")
    print(f"   Preview: {summary_text[:100]}...")
    print()

    return {
        "success": True,
        "email_id": f"SUMMARY-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "sent_to": customer_email,
        "message": "Monthly account summary email sent successfully"
    }


# =============================================================================
# Initialize Agent
# =============================================================================

def initialize_agent():
    """Initialize email agent with dual-plugin AgentControl integration."""

    # Initialize AgentControl
    try:
        agent_control.init(
            agent_name="banking-email-agent",
            server_url=os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
        )
    except Exception as e:
        if "409" not in str(e):
            raise

    # Plugin 1: AgentControlPlugin for tool-stage deny checks
    # Enforces hard blocks (credentials, internal info) at tool execution
    tool_plugin = AgentControlPlugin(
        agent_name="banking-email-agent",
        event_control_list=[BeforeToolCallEvent, AfterToolCallEvent],
        enable_logging=True
    )

    # Plugin 2: AgentControlSteeringHandler for LLM post-output steer
    # Guides PII redaction via Strands Guide() before tools are called
    steering_handler = AgentControlSteeringHandler(
        agent_name="banking-email-agent",
        enable_logging=True
    )

    # Create agent with both plugins
    model = OpenAIModel(model_id="gpt-4o-mini")
    agent = Agent(
        name="banking_email_agent",
        model=model,
        system_prompt="""You are a banking customer service assistant that sends automated monthly account summaries.

WORKFLOW (STRICT - TWO PHASES):
1. Look up account: Use lookup_customer_account() to retrieve account data
2. Draft email: Compose the email as plain text. Include account details (number, balance, transactions).
   - Do NOT call send_monthly_account_summary() yet
   - Just draft the email content
3. Send email: Call send_monthly_account_summary() with the final email text
4. Report success to the user

IMPORTANT:
- Phase 1: Draft the email BEFORE calling send tool
- Phase 2: Send the email AFTER draft is finalized
- If you receive guidance to redact information, revise the draft before sending
- Include specific account details in the email (these will be checked for PII)
- Be professional, clear, and reassuring
- NEVER mention technical errors, policy violations, or safety systems to customers

After sending, respond with:
"✅ Monthly summary sent to [email]

📧 **Email Content:**
[The email text that was sent]"
""",
        tools=[lookup_customer_account, send_monthly_account_summary],
        plugins=[tool_plugin, steering_handler]  # Both as plugins
    )

    return agent, steering_handler


# =============================================================================
# Streamlit UI
# =============================================================================

def render_header():
    """Render app header."""
    st.title("🏦 Banking Email Safety Demo")
    st.markdown("""
    **AgentControl Steer + Strands Steering Integration**

    Seamless integration of two governance systems:
    - 🎯 **AgentControl Steer**: Server-side PII detection with steering context
    - ✨ **Strands Guide**: Converts steer to Guide() for agent retry
    - 🔄 **Automatic Retry**: Agent receives guidance and retries with redacted content

    **How it works:** AgentControl detects PII via server-side controls, raises `ControlSteerError`
    with steering context, which is automatically converted to a Strands `Guide()` action.
    """)
    st.divider()


def render_sidebar(steering_handler):
    """Render sidebar with stats."""
    with st.sidebar:
        st.header("📊 Governance Stats")

        st.metric("🛡️ AgentControl Denies", st.session_state.get('safety_blocks', 0))
        st.metric("🎯 AgentControl Steers", steering_handler.steers_applied)

        st.divider()

        st.header("🧪 Test Scenarios")
        st.caption("Click to test - AgentControl steer in action!")

        if st.button("📧 John's Summary", use_container_width=True):
            st.session_state['test_prompt'] = "Send monthly summary to john@example.com"
        st.caption("**AgentControl will detect:** Account# 123456789012, Balance $45K")

        if st.button("📧 Sarah's Summary", use_container_width=True):
            st.session_state['test_prompt'] = "Send monthly summary to sarah@example.com"
        st.caption("**AgentControl will detect:** Account# + SSN 987-65-4321, Balance $128K")

        st.divider()

        st.caption("""
        **Flow:**
        1. 🔍 Lookup account (PII in backend)
        2. 📝 Draft email with full details
        3. 🚨 AgentControl steer detects PII
        4. ✨ Strands Guide with steering context
        5. 🔄 Agent retries with guidance
        6. ✅ Email sent with redacted info
        """)


def render_chat(agent, steering_handler):
    """Render chat interface."""
    st.header("💬 Banking Email Automation System")

    # Initialize chat history
    if 'messages' not in st.session_state:
        st.session_state['messages'] = [
            {
                'role': 'assistant',
                'content': 'I can help you send monthly account summaries. What would you like me to do?'
            }
        ]

    # Display chat messages
    for msg in st.session_state['messages']:
        with st.chat_message(msg['role']):
            st.markdown(msg['content'])
            # Show AgentControl steer info if present
            if msg.get('steer_info'):
                st.info("🎯 **AgentControl Steer Applied**")
                st.caption(f"Control: {msg['steer_info']['control_name']}")
                st.caption("Steering Context:")
                st.caption(f"  {msg['steer_info']['steering_context'][:200]}...")
                st.caption("✅ Agent retried with AgentControl guidance")

    # Handle test prompt injection
    user_input = None
    if 'test_prompt' in st.session_state:
        user_input = st.session_state['test_prompt']
        del st.session_state['test_prompt']

    # Chat input
    if prompt := (user_input or st.chat_input("Type your request...")):
        # Add user message
        st.session_state['messages'].append({'role': 'user', 'content': prompt})

        with st.chat_message('user'):
            st.markdown(prompt)

        # Get agent response
        with st.chat_message('assistant'):
            with st.spinner('Processing...'):
                try:
                    result = asyncio.run(agent.invoke_async(prompt))

                    # Extract response text
                    response_text = "No response generated"
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
                                response_text = '\n'.join(text_parts) if text_parts else str(content)
                            else:
                                response_text = str(content)

                    st.markdown(response_text)

                    # Check if AgentControl steer occurred and show info
                    message_data = {'role': 'assistant', 'content': response_text}
                    if steering_handler.last_steer_info:
                        message_data['steer_info'] = steering_handler.last_steer_info
                        print("\n🎯 AGENTCONTROL STEER APPLIED")
                        print(f"   Control: {steering_handler.last_steer_info['control_name']}")
                        print("   Steering Context:")
                        print(f"   {steering_handler.last_steer_info['steering_context']}")
                        st.info("🎯 **AgentControl Steer Applied**")
                        st.caption(f"Control: {steering_handler.last_steer_info['control_name']}")
                        st.caption("Steering Context:")
                        st.caption(f"  {steering_handler.last_steer_info['steering_context'][:200]}...")
                        st.caption("✅ Agent retried with AgentControl guidance")

                    st.session_state['messages'].append(message_data)

                except ControlViolationError as e:
                    error_msg = f"Blocked by control: {e}"
                    print(f"\n🚫 CONTROL VIOLATION - {e}")
                    st.error(error_msg)
                    st.session_state['messages'].append({'role': 'assistant', 'content': error_msg})
                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    print(f"\n⚠️  ERROR - {e}")
                    st.error(error_msg)
                    st.session_state['messages'].append({'role': 'assistant', 'content': error_msg})


def main():
    """Main app entry point."""
    st.set_page_config(
        page_title="Email Safety Demo",
        page_icon="🛡️",
        layout="wide"
    )

    # Initialize session state
    if 'messages' not in st.session_state:
        st.session_state['messages'] = []
    if 'safety_blocks' not in st.session_state:
        st.session_state['safety_blocks'] = 0

    # Initialize agent
    try:
        agent, steering_handler = initialize_agent()
    except Exception as e:
        st.error(f"Failed to initialize agent: {e}")
        st.info("Make sure the AgentControl server is running")
        st.stop()

    # Render UI
    render_header()
    render_sidebar(steering_handler)
    render_chat(agent, steering_handler)

    st.markdown("---")
    st.caption("Built with AgentControl + Strands Steering")


if __name__ == "__main__":
    main()
