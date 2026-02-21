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
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import streamlit as st
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent.parent / ".env", override=False)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "sdks" / "python" / "src"))

# Import required modules
try:
    from strands import Agent, tool
    from strands.models.openai import OpenAIModel
    from strands.experimental.steering import Guide, Proceed, SteeringHandler
    import agent_control
    from agent_control import ControlViolationError
except ImportError as e:
    st.error(f"Missing dependency: {e}")
    st.stop()

# Add common directory to path for AgentControlHook
sys.path.insert(0, str(Path(__file__).parent.parent / "common"))
from agent_control_hook import AgentControlHook


# =============================================================================
# Configuration
# =============================================================================

AGENT_ID = "550e8400-e29b-41d4-a716-446655440030"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


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

    Args:
        customer_email: Customer's email address
        summary_text: The summary email body text
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
# Quality Steering Handler
# =============================================================================

class BankingPIIRedactionHandler(SteeringHandler):
    """Steering handler for banking PII redaction.

    Detects financial PII in agent responses and guides redaction:
    - Full account numbers → "account ending in XXXX"
    - SSN → "SSN ending in XXXX"
    - Large amounts → Rounded (e.g., "$45.2K")
    - Full transaction details → Generalized
    """

    def __init__(self):
        super().__init__()
        self.redactions_made = 0
        self.guidances_given = 0
        self.last_redaction_info = None  # Store info about latest redaction

    async def steer_after_model(self, *, agent, message, stop_reason, **kwargs):
        """Check LLM output for financial PII and guide redaction."""

        print("\n" + "="*70)
        print("✨ STEERING: steer_after_model() CALLED")
        print("="*70)

        # Extract response text AND tool parameters
        response_text = self._extract_text(message)
        tool_params_text = self._extract_tool_params(message)

        # Combine both for PII checking
        full_text = response_text + " " + tool_params_text

        print(f"📝 Response preview: {response_text[:150] if response_text else '(no text)'}...")
        if tool_params_text:
            print(f"🔧 Tool params preview: {tool_params_text[:150]}...")

        if not full_text.strip():
            print("⚠️  No content to check, returning Proceed()")
            print("="*70 + "\n")
            return Proceed()

        response_lower = full_text.lower()
        needs_redaction = False
        redaction_guidance = []

        # Detect full account numbers (9-12 digits)
        account_matches = re.findall(r'\b(\d{9,12})\b', full_text)
        if account_matches:
            needs_redaction = True
            for acc_num in account_matches:
                last_four = acc_num[-4:]
                redaction_guidance.append(
                    f"• Account number {acc_num} → 'account ending in {last_four}'"
                )
                print(f"🚨 PII DETECTED: Full account number {acc_num}")
                print(f"   ✅ Redaction: 'account ending in {last_four}'")

        # Detect SSN (XXX-XX-XXXX format)
        ssn_matches = re.findall(r'\b(\d{3}[-\s]?\d{2}[-\s]?\d{4})\b', full_text)
        if ssn_matches:
            needs_redaction = True
            for ssn in ssn_matches:
                last_four = ssn[-4:]
                redaction_guidance.append(
                    f"• SSN {ssn} → 'SSN ending in {last_four}' OR remove entirely"
                )
                print(f"🚨 PII DETECTED: SSN {ssn}")
                print(f"   ✅ Redaction: Remove or use 'SSN ending in {last_four}'")

        # Detect large dollar amounts (> $10,000)
        large_amounts = re.findall(r'\$([\d,]+\.?\d*)', full_text)
        for amount in large_amounts:
            # Parse amount
            amount_clean = amount.replace(',', '')
            try:
                amount_value = float(amount_clean)
                if amount_value > 10000:
                    needs_redaction = True
                    rounded = f"${amount_value/1000:.1f}K"
                    redaction_guidance.append(
                        f"• Large amount ${amount} → '{rounded}'"
                    )
                    print(f"🚨 SENSITIVE: Large amount ${amount}")
                    print(f"   ✅ Redaction: '{rounded}'")
            except:
                pass

        # Detect specific transaction details (e.g., "Deposit of $15,000")
        # Only flag if transaction type is directly followed by amount
        transaction_patterns = [
            r'(deposit|withdrawal|transfer|payment)\s+(of|for|:)\s*\$[\d,]+',
            r'\$[\d,]+\s+(deposit|withdrawal|transfer|payment)'
        ]
        for pattern in transaction_patterns:
            if re.search(pattern, full_text, re.IGNORECASE):
                # Extract the match to show what was found
                match = re.search(pattern, full_text, re.IGNORECASE)
                if match:
                    needs_redaction = True
                    matched_text = match.group(0)
                    redaction_guidance.append(
                        f"• Transaction detail '{matched_text}' → Generalize (e.g., 'Recent deposit activity')"
                    )
                    print(f"🔍 DETECTED: Specific transaction detail: {matched_text}")
                    break  # Only need to flag once

        if needs_redaction:
            self.redactions_made += 1
            self.guidances_given += 1

            # Store redaction info for UI display
            self.last_redaction_info = {
                "redacted_items": redaction_guidance,
                "count": len(redaction_guidance)
            }

            print("\n" + "🚨"*35)
            print("⚠️  FINANCIAL PII DETECTED - GUIDING REDACTION")
            print("🚨"*35)
            print("\n📋 REDACTION INSTRUCTIONS:")
            for instruction in redaction_guidance:
                print(f"   {instruction}")
            print("\n✅ STEERING: Returning Guide() to agent with redaction instructions")
            print("   Agent will RETRY with redacted content")
            print("="*70 + "\n")

            guidance = (
                "⚠️ FINANCIAL PII DETECTED - Apply these redactions:\n\n" +
                "\n".join(redaction_guidance) +
                "\n\n✅ Best practices:\n"
                "- Use last 4 digits only for account/card numbers\n"
                "- Round large amounts to nearest thousand ($45.2K)\n"
                "- Generalize transaction types without exact amounts\n"
                "- Never include full SSN, routing numbers, or PINs"
            )

            return Guide(reason=guidance)

        # Clear redaction info when no PII detected
        self.last_redaction_info = None
        print(f"✅ STEERING: No PII detected, returning Proceed()")
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

    def _extract_tool_params(self, message) -> str:
        """Extract text from tool call parameters."""
        import json

        if isinstance(message, dict):
            content = message.get('content', [])
        elif hasattr(message, 'content'):
            content = message.content
        else:
            return ""

        if not isinstance(content, list):
            return ""

        tool_params_text = []
        for block in content:
            # Check for toolUse blocks
            if isinstance(block, dict):
                if 'toolUse' in block:
                    tool_use = block['toolUse']
                    if 'input' in tool_use:
                        # Convert tool params to string
                        params_str = json.dumps(tool_use['input'])
                        tool_params_text.append(params_str)
                elif block.get('type') == 'tool_use':
                    if 'input' in block:
                        params_str = json.dumps(block['input'])
                        tool_params_text.append(params_str)
            elif hasattr(block, 'type') and block.type == 'tool_use':
                if hasattr(block, 'input'):
                    params_str = json.dumps(block.input)
                    tool_params_text.append(params_str)

        return ' '.join(tool_params_text)


# =============================================================================
# Initialize Agent
# =============================================================================

def initialize_agent():
    """Initialize email agent with both safety and quality layers."""

    # Initialize AgentControl
    try:
        agent_control.init(
            agent_name="banking-email-agent",
            agent_id=AGENT_ID,
            server_url=SERVER_URL
        )
    except Exception as e:
        if "409" not in str(e):
            raise

    # Create PII redaction steering handler
    steering_handler = BankingPIIRedactionHandler()

    # Create AgentControl hook (safety layer)
    hook = AgentControlHook(
        agent_uuid=UUID(AGENT_ID),
        agent_name="banking-email-agent",
        server_url=SERVER_URL,
        enable_logging=True
    )

    # Create agent
    model = OpenAIModel(model_id="gpt-4o-mini")
    agent = Agent(
        name="banking_email_agent",
        model=model,
        system_prompt="""You are a banking customer service assistant that sends automated monthly account summaries.

WORKFLOW:
1. When asked to send a summary, first use lookup_customer_account() to retrieve account data
2. Draft a professional email including the account details from the lookup
3. Use send_monthly_account_summary() to send the email
4. AFTER sending, show the user the final email content that was sent

IMPORTANT:
- Always look up account data first before drafting
- Include specific details: account number, balance, recent transactions
- Be professional, clear, and reassuring
- If you receive guidance to redact information, follow it precisely
- NEVER mention technical errors, policy violations, or safety systems to customers
- After sending, display the email content to show what was sent

Response format after sending:
"✅ Monthly summary sent to [email]

📧 **Email Sent:**
[Show the actual email content that was sent]"
""",
        tools=[lookup_customer_account, send_monthly_account_summary],
        hooks=[hook, steering_handler]  # Both layers
    )

    return agent, steering_handler


# =============================================================================
# Streamlit UI
# =============================================================================

def render_header():
    """Render app header."""
    st.title("🏦 Banking Email Safety Demo")
    st.markdown("""
    **Critical Scenario: Automated Monthly Account Summaries with Financial PII Redaction**

    Two governance layers working together:
    - 🛡️ **AgentControl (Safety)**: Detects financial PII in agent responses
    - ✨ **Steering (Redaction)**: Guides smart redaction instead of removal
    """)
    st.divider()


def render_sidebar(steering_handler):
    """Render sidebar with stats."""
    with st.sidebar:
        st.header("📊 Governance Stats")

        st.metric("🛡️ AgentControl Warnings", st.session_state.get('safety_blocks', 0))
        st.metric("✨ PII Redactions Made", steering_handler.redactions_made)
        st.metric("📝 Steering Guidances", steering_handler.guidances_given)

        st.divider()

        st.header("🧪 Test Scenarios")
        st.caption("Click to test - see redaction in action!")

        if st.button("📧 John's Summary", use_container_width=True):
            st.session_state['test_prompt'] = "Send monthly summary to john@example.com"
        st.caption("**Will detect:** Account# 123456789012, Balance $45K, Deposit $15K")

        if st.button("📧 Sarah's Summary", use_container_width=True):
            st.session_state['test_prompt'] = "Send monthly summary to sarah@example.com"
        st.caption("**Will detect:** Account# + SSN 987-65-4321, Balance $128K, Transfer $50K")

        st.divider()

        st.caption("""
        **Flow:**
        1. 🔍 Lookup account (PII in backend)
        2. 📝 Draft email with full details
        3. 🚨 Steering detects PII
        4. ✨ Guide redaction
        5. 📧 Send with redacted info
        6. ✅ Show final email in UI
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
            # Show redaction info if present
            if msg.get('redaction_info'):
                st.info("🛡️ **PII Detected and Redacted**")
                st.caption("The following sensitive information was redacted for security:")
                for item in msg['redaction_info']['redacted_items']:
                    st.caption(f"  {item}")
                st.caption(f"✅ Email sent with {msg['redaction_info']['count']} redaction(s) applied")

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

                    # Check if redaction occurred and show info
                    message_data = {'role': 'assistant', 'content': response_text}
                    if steering_handler.last_redaction_info:
                        message_data['redaction_info'] = steering_handler.last_redaction_info
                        st.info("🛡️ **PII Detected and Redacted**")
                        st.caption("The following sensitive information was redacted for security:")
                        for item in steering_handler.last_redaction_info['redacted_items']:
                            st.caption(f"  {item}")
                        st.caption(f"✅ Email sent with {steering_handler.last_redaction_info['count']} redaction(s) applied")

                    st.session_state['messages'].append(message_data)

                except Exception as e:
                    error_msg = f"Error: {str(e)}"
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
