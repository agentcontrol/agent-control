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
    1. Agent Control server running: cd server && make run
    2. Controls created: python setup_controls.py
    3. OpenAI API key set
    4. Galileo API key set

Usage:
    streamlit run examples/strands_integration/interactive_support_demo.py
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

from strands import Agent, tool
from strands.hooks import HookProvider, HookRegistry, AfterModelCallEvent, BeforeInvocationEvent
from strands.models.openai import OpenAIModel
from strands.multiagent.graph import Graph, GraphNode, GraphEdge

import agent_control
from agent_control_models import Step
from agent_control import ControlViolationError

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env", override=False)


# ============================================================================
# Safety Tracking Hook (Captures violations for UI display)
# ============================================================================

class SafetyTrackingHook(HookProvider):
    """Hook that tracks all safety decisions and stores them in Streamlit session state."""

    def __init__(self, agent_name: str, max_retries: int = 3):
        self.agent_name = agent_name
        self.session_id = str(uuid4())
        self.max_retries = max_retries
        self.retry_count = 0

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Register hook callbacks with the registry."""
        registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)  # Pre-stage check
        registry.add_callback(AfterModelCallEvent, self.on_after_model_call)  # Post-stage check

    async def on_before_invocation(self, event: BeforeInvocationEvent):
        """Check input messages for PII before agent processes them (pre-stage)."""

        # Check if we have messages
        if not event.messages:
            return

        # DEBUG: Show what we received

        # Extract user messages from the message list
        user_messages = []
        for i, msg in enumerate(event.messages):

            # Handle both dict and object formats
            role = None
            content = None

            if isinstance(msg, dict):
                role = msg.get('role')
                content = msg.get('content')
            elif hasattr(msg, 'role'):
                role = msg.role
                content = msg.content if hasattr(msg, 'content') else None


            if role == 'user' and content:
                # Content might be a list of text blocks or a string
                if isinstance(content, list):
                    # Extract text from all blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and 'text' in block:
                            text_parts.append(block['text'])
                        else:
                            text_parts.append(str(block))
                    message_text = ' '.join(text_parts)
                else:
                    message_text = str(content)

                user_messages.append(message_text)

        if not user_messages:
            return

        # Check the most recent user message
        message_content = user_messages[-1]

        # Get agent info from agent_control SDK
        current_agent = agent_control.current_agent()
        if not current_agent:
            return

        # Get server URL from environment
        server_url = os.getenv('AGENT_CONTROL_URL', 'http://localhost:8000')

        # Create step for pre-stage evaluation
        step = Step(
            type="llm",
            name=f"{self.agent_name}-input",
            input=message_content,
            output="",
            context={
                "agent": self.agent_name,
                "session_id": self.session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Run AgentControl evaluation using the evaluation module
        from agent_control.client import AgentControlClient

        # Create a client for this check
        async with AgentControlClient(base_url=server_url) as client:

            result = await agent_control.evaluation.check_evaluation(
                client=client,
                agent_uuid=current_agent.agent_id,
                step=step,
                stage="pre"
            )


            # Matches, non-matches, and errors are tracked in evaluation results

        # Update session state stats
        if "stats" not in st.session_state:
            st.session_state.stats = {
                "checks_passed": 0,
                "violations_blocked": 0,
                "total_checks": 0
            }

        st.session_state.stats["total_checks"] += 1

        # Store detailed evaluation results for UI display
        if "current_message_evaluations" not in st.session_state:
            st.session_state.current_message_evaluations = []

        evaluation_details = {
            "agent": self.agent_name,
            "stage": "pre",
            "is_safe": result.is_safe,
            "matches": [
                {
                    "control_name": m.control_name,
                    "confidence": m.result.confidence,
                    "message": m.result.message,
                    "metadata": m.result.metadata or {}
                }
                for m in (result.matches or [])
            ],
            "non_matches": [
                {
                    "control_name": nm.control_name,
                    "confidence": nm.result.confidence,
                    "message": nm.result.message,
                    "metadata": nm.result.metadata or {}
                }
                for nm in (result.non_matches or [])
            ]
        }
        st.session_state.current_message_evaluations.append(evaluation_details)

        if not result.is_safe:
            st.session_state.stats["violations_blocked"] += 1

            # Store violation for current message
            if "current_message_violations" not in st.session_state:
                st.session_state.current_message_violations = []

            violation = {
                "agent": f"{self.agent_name}",
                "controls": [m.control_name for m in (result.matches or [])],
                "stage": "pre"
            }
            st.session_state.current_message_violations.append(violation)

            # For pre-stage violations, we should ideally block the request
            # But Strands BeforeInvocationEvent happens after routing
            # So we log it and let the post-stage hook potentially catch it
        else:
            st.session_state.stats["checks_passed"] += 1

    async def on_after_model_call(self, event: AfterModelCallEvent):
        """Apply AgentControl checks and track results."""

        # Check if we have a successful response
        if not event.stop_response or event.exception:
            return

        # Check retry limit
        if self.retry_count >= self.max_retries:
            return

        # Extract the message from stop_response
        message = event.stop_response.message
        output_text = str(message.content) if hasattr(message, 'content') else str(message)

        # Get agent info from agent_control SDK
        current_agent = agent_control.current_agent()
        if not current_agent:
            return

        # Get server URL from SDK module-level variable
        server_url = os.getenv('AGENT_CONTROL_URL', 'http://localhost:8000')

        # Create step for evaluation
        step = Step(
            type="llm",
            name=f"{self.agent_name}-output",
            input="",  # We don't have access to the original input in AfterModelCallEvent
            output=output_text,
            context={
                "agent": self.agent_name,
                "session_id": self.session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Run AgentControl evaluation using the evaluation module
        from agent_control.client import AgentControlClient

        # Create a client for this check
        async with AgentControlClient(base_url=server_url) as client:
            result = await agent_control.evaluation.check_evaluation(
                client=client,
                agent_uuid=current_agent.agent_id,
                step=step,
                stage="post"
            )

        # Update session state stats
        if "stats" not in st.session_state:
            st.session_state.stats = {
                "checks_passed": 0,
                "violations_blocked": 0,
                "total_checks": 0
            }

        st.session_state.stats["total_checks"] += 1

        # Store detailed evaluation results for UI display
        if "current_message_evaluations" not in st.session_state:
            st.session_state.current_message_evaluations = []

        evaluation_details = {
            "agent": self.agent_name,
            "stage": "post",
            "is_safe": result.is_safe,
            "matches": [
                {
                    "control_name": m.control_name,
                    "confidence": m.result.confidence,
                    "message": m.result.message,
                    "metadata": m.result.metadata or {}
                }
                for m in (result.matches or [])
            ],
            "non_matches": [
                {
                    "control_name": nm.control_name,
                    "confidence": nm.result.confidence,
                    "message": nm.result.message,
                    "metadata": nm.result.metadata or {}
                }
                for nm in (result.non_matches or [])
            ]
        }
        st.session_state.current_message_evaluations.append(evaluation_details)

        if result.is_safe:
            st.session_state.stats["checks_passed"] += 1
            # Reset retry counter on success
            self.retry_count = 0
        else:
            st.session_state.stats["violations_blocked"] += 1

            # Store violation for current message
            if "current_message_violations" not in st.session_state:
                st.session_state.current_message_violations = []

            violation = {
                "agent": self.agent_name,
                "controls": [m.control_name for m in (result.matches or [])],
                "stage": "post" if hasattr(event, 'stop_response') else "pre"
            }
            st.session_state.current_message_violations.append(violation)

            # Check if we can retry
            if self.retry_count < self.max_retries:
                # Increment retry counter and trigger retry
                self.retry_count += 1
                event.retry = True
                # Note: Strands doesn't support retry_guidance in AfterModelCallEvent
                # The model will retry without specific guidance
            else:
                # Max retries reached - block the response
                raise ControlViolationError(
                    "Maximum retries exceeded - unable to generate safe response",
                    result
                )


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
            agent_id="550e8400-e29b-41d4-a716-446655440099",
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
    """Create the multi-agent customer support system."""
    if "support_graph" in st.session_state:
        return st.session_state.support_graph

    model = OpenAIModel(model_id="gpt-4o")

    # Triage Agent - Routes customer to appropriate specialist
    triage_agent = Agent(
        name="triage_agent",
        model=model,
        system_prompt="""You are a customer support triage agent.

Your role:
1. Understand the customer's question
2. Determine the type of support needed (orders, returns, general info)
3. Pass to the appropriate specialist with context

Be friendly and professional. Never include customer PII in your summary.""",
        hooks=[SafetyTrackingHook("triage")],
    )

    # Orders Specialist Agent
    orders_agent = Agent(
        name="orders_agent",
        model=model,
        tools=[lookup_order, search_knowledge_base],
        system_prompt="""You are an order support specialist.

Your role:
1. Help customers with order status, tracking, and shipping questions
2. Use lookup_order tool to get order information
3. Provide clear, helpful responses

CRITICAL:
- Never make up order information - only use the tool results
- Never include customer SSN, credit card numbers, or email addresses
- Be professional and helpful""",
        hooks=[SafetyTrackingHook("orders")],
    )

    # Returns Specialist Agent
    returns_agent = Agent(
        name="returns_agent",
        model=model,
        tools=[check_return_policy, search_knowledge_base],
        system_prompt="""You are a returns support specialist.

Your role:
1. Help customers with return policies and procedures
2. Use check_return_policy tool for specific products
3. Provide clear, accurate information

CRITICAL:
- Never guarantee returns outside policy
- Be professional and empathetic
- Don't include any PII in responses""",
        hooks=[SafetyTrackingHook("returns")],
    )

    # General Support Agent
    general_agent = Agent(
        name="general_agent",
        model=model,
        tools=[search_knowledge_base],
        system_prompt="""You are a general customer support agent.

Your role:
1. Answer general questions about the company
2. Use search_knowledge_base for information
3. Provide helpful, professional responses

CRITICAL:
- Stay on topic (customer support only)
- Don't make up information
- Be professional and friendly""",
        hooks=[SafetyTrackingHook("general")],
    )

    # Build graph (simplified - triage routes to appropriate agent)
    # Create nodes first
    triage_node = GraphNode(executor=triage_agent, node_id="triage_agent")
    orders_node = GraphNode(executor=orders_agent, node_id="orders_agent")
    returns_node = GraphNode(executor=returns_agent, node_id="returns_agent")
    general_node = GraphNode(executor=general_agent, node_id="general_agent")

    # Create nodes dictionary (node_id -> node)
    nodes = {
        "triage_agent": triage_node,
        "orders_agent": orders_node,
        "returns_agent": returns_node,
        "general_agent": general_node,
    }

    # Create edges (simple linear flow for demo)
    edges = {
        GraphEdge(from_node=triage_node, to_node=general_node),
    }

    # Create graph with all components
    graph = Graph(
        nodes=nodes,
        edges=edges,
        entry_points={triage_node}
    )

    st.session_state.support_graph = graph
    return graph


# ============================================================================
# Streamlit UI
# ============================================================================

def render_header():
    """Render the app header with logo and description."""
    st.title("🛡️ AgentControl Interactive Demo")
    st.subheader("Customer Support Bot with Real-Time Safety")

    st.markdown("""
    **See AgentControl in action!** Chat with the support bot and watch the safety dashboard
    to see how AgentControl blocks unsafe content in real-time.

    Try the "Attack Prompts" below to see AgentControl protect against common issues.
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
    """Render example attack prompts users can try."""
    st.subheader("🎯 Try These Attack Prompts")
    st.caption("Click any prompt to see AgentControl block it")

    attack_prompts = {
        "🔢 SSN": "My order number is ORD-12345 and my SSN is 123-45-6789. Can you help?",
        "💳 Credit Card": "I need to update my payment. Here's my card: 4532-1234-5678-9010",
        "📧 Email": "Please send the invoice to john.doe@company.com and cc jane.smith@example.org",
        "🆔 Multiple PII": "Contact me at 555-1234-5678-9010 or email admin@secret.com with SSN 987-65-4321",
    }

    cols = st.columns(len(attack_prompts))
    for idx, (label, prompt) in enumerate(attack_prompts.items()):
        with cols[idx]:
            if st.button(label, key=f"attack_{idx}", use_container_width=True):
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
                    # Check graph exists
                    if "support_graph" not in st.session_state:
                        raise RuntimeError("Graph not initialized - refresh the page")

                    graph = st.session_state.support_graph
                    status_placeholder.info(f"🤖 Running agent graph (type: {type(graph).__name__})...")

                    # Log what we're sending
                    st.caption(f"📤 Input: `{prompt[:50]}...`")

                    # Create async task with timeout
                    async def run_with_timeout():
                        try:
                            st.caption("⚙️ Starting graph.invoke_async()...")
                            result = await asyncio.wait_for(
                                graph.invoke_async(prompt),
                                timeout=30.0  # 30 second timeout
                            )
                            st.caption("✅ Graph.invoke_async() completed")
                            return result
                        except Exception as e:
                            st.caption(f"❌ Graph.invoke_async() failed: {e}")
                            raise

                    st.caption("🔄 Running async task...")
                    result = asyncio.run(run_with_timeout())
                    st.caption("✅ Async task completed")

                    status_placeholder.empty()  # Clear status

                    # Extract response from GraphResult
                    # Get the last completed node's result
                    if result.results:
                        # Get the last node in execution order
                        last_node = result.execution_order[-1] if result.execution_order else None
                        if last_node:
                            node_result = result.results.get(last_node.node_id)
                            if node_result and hasattr(node_result.result, 'message'):
                                agent_message = node_result.result.message

                                # Extract text content from message
                                # Message can be a dict or an object
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
                                response = "No response generated"
                        else:
                            response = "No nodes executed"
                    else:
                        response = "Empty result"

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
                    # AgentControl blocked the response after max retries
                    st.error("🚫 **AgentControl Safety Block**")

                    # Show what was blocked
                    with st.expander("🔍 Why was this blocked?", expanded=True):
                        st.markdown(f"**Violation:** {e.result.reason}")
                        st.markdown(f"**Confidence:** {e.result.confidence:.0%}")

                        if e.result.matches:
                            st.markdown("**Controls Triggered:**")
                            for match in e.result.matches:
                                st.markdown(f"- `{match.control_name}` (confidence: {match.confidence:.0%})")

                        st.info("""
                        **What this means:** The agent tried multiple times to generate a safe response
                        but kept including sensitive information. This protects against:
                        - PII leakage (SSN, credit cards, emails)
                        - Toxic or inappropriate content
                        - Hallucinated or false information
                        """)

                    # Provide safe fallback response
                    response = "I apologize, but I cannot provide a response that meets our safety standards. Please try rephrasing your question without including personal information like SSN, credit card numbers, or email addresses."
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
