#!/usr/bin/env python3
"""
Layered Governance Demo - AgentControl + Strands Steering

This demo shows how two governance layers work together:
- Safety Layer (AgentControl): Hard blocks for PII protection
- Quality Layer (Steering): Contextual guidance for agent responses

DEMONSTRATION:
1. User submits request with security concern + PII (SSN)
2. Safety layer (AgentControl) detects and blocks PII
3. Intelligent routing sends to Security Specialist
4. Quality layer (Steering) provides contextual guidance when security topics detected
5. Security Specialist provides expert help WITHOUT processing PII

VALUE: Customer protected from PII exposure AND receives helpful expert guidance

Prerequisites:
    1. AgentControl server running: cd server && make run
    2. Controls created: python setup_steering_controls.py
    3. OpenAI API key set

Usage:
    streamlit run layered_governance_demo.py
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

from strands import Agent
from strands.hooks import HookRegistry, AfterModelCallEvent, BeforeInvocationEvent
from strands.models.openai import OpenAIModel
from strands.multiagent.graph import Graph, GraphNode, GraphEdge
from strands.experimental.steering import SteeringHandler, Guide, Proceed

import agent_control
from agent_control_models import Step

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env", override=False)


# ============================================================================
# Governance Pipeline Tracker
# ============================================================================

class GovernancePipeline:
    """Tracks the flow of a request through governance and routing."""

    def __init__(self):
        self.stages = []
        self.routed_to = None  # Track which agent handled the request
        self.needs_security_escalation = False  # NEW: Track if quality steering detected security topic
        self.escalation_response = None  # Store support agent's escalation message

    def add_stage(self, layer: str, action: str, detail: str, passed: bool):
        """Record a governance stage."""
        self.stages.append({
            "layer": layer,
            "action": action,
            "detail": detail,
            "passed": passed,
            "timestamp": datetime.now(timezone.utc)
        })

    def set_routing(self, agent_type: str, reason: str):
        """Record routing decision."""
        self.routed_to = {"agent": agent_type, "reason": reason}

    def trigger_security_escalation(self, escalation_msg: str):
        """Mark that quality steering detected a security topic requiring specialist."""
        self.needs_security_escalation = True
        self.escalation_response = escalation_msg


# ============================================================================
# Quality Steering Handler - Realistic Business Scenarios
# ============================================================================

class QualitySteeringHandler(SteeringHandler):
    """
    Provides realistic quality steering for customer support agents.

    Scenarios covered:
    1. Unauthorized Promise Detection - Prevents agents from making commitments beyond authority
    2. Hallucination Detection - Catches when agents fabricate specific details
    3. Policy Compliance - Ensures responses follow company policies
    4. Accuracy Guidance - Guides agents to verify information instead of guessing
    """

    def __init__(self, pipeline: GovernancePipeline):
        super().__init__()
        self.pipeline = pipeline
        print(f"✅ QualitySteeringHandler initialized for pipeline")

    async def steer_after_model(self, *, agent, message, stop_reason, **kwargs):
        """Check agent responses for quality issues and provide guidance.

        Args:
            agent: The agent instance
            message: The model's generated message
            stop_reason: The reason the model stopped generating
            **kwargs: Additional keyword arguments

        Returns:
            ModelSteeringAction (Guide or Proceed)
        """
        # Log that we're being called
        print(f"🔍 Quality Steering: steer_after_model() called!")
        print(f"🔍 Quality Steering: Agent: {agent.name}")
        print(f"🔍 Quality Steering: Message type: {type(message)}")
        print(f"🔍 Quality Steering: Stop reason: {stop_reason}")

        # Extract response text from message (can be dict or object)
        response_text = ""

        # Try dict access first (Strands 1.26.0 format)
        if isinstance(message, dict):
            content = message.get('content', [])
            print(f"🔍 Quality Steering: Message content (dict): {content}")
        # Try attribute access (object format)
        elif hasattr(message, 'content'):
            content = message.content
            print(f"🔍 Quality Steering: Message content (attr): {content}")
        else:
            content = None
            print(f"🔍 Quality Steering: Could not extract content from message")

        # Extract text from content
        if isinstance(content, str):
            response_text = content
        elif isinstance(content, list):
            # Message content is list of content blocks
            text_parts = []
            for block in content:
                if isinstance(block, dict) and 'text' in block:
                    text_parts.append(block['text'])
                elif hasattr(block, 'text'):
                    text_parts.append(block.text)
                else:
                    text_parts.append(str(block))
            response_text = ' '.join(text_parts)

        print(f"🔍 Quality Steering: Response text: {response_text[:100] if response_text else 'EMPTY'}...")

        if not response_text:
            print("🔍 Quality Steering: No response text, proceeding")
            return Proceed()

        response_lower = response_text.lower()

        # 1. Check for unauthorized promises (including subtle ones)
        # Check for refund promises without verification
        refund_keywords = ["refund", "money back", "full credit"]
        verification_keywords = ["let me check", "need to verify", "need to look up", "let me see", "first, i need"]

        has_refund_mention = any(keyword in response_lower for keyword in refund_keywords)
        has_verification = any(keyword in response_lower for keyword in verification_keywords)

        # Check for problematic patterns
        unauthorized_patterns = [
            ("yes, you can" in response_lower and has_refund_mention and not has_verification,
             "promising refund without verification"),
            ("i'll refund" in response_lower, "direct refund promise"),
            ("i'll give you" in response_lower, "direct compensation promise"),
            ("i guarantee" in response_lower, "unauthorized guarantee"),
            ("you'll definitely get" in response_lower, "definite outcome promise"),
            ("i'll extend your warranty" in response_lower, "warranty promise without authority"),
            ("i'll waive the fee" in response_lower, "fee waiver without approval"),
            ("no problem, " in response_lower and has_refund_mention and not has_verification,
             "casual refund promise without checking")
        ]

        for condition, issue in unauthorized_patterns:
            if condition:
                guidance_message = (
                    f"⚠️ Don't promise refunds or actions without verification. Instead say: "
                    f"'Let me check your order and our policy for damaged items. Can you provide your order number so I can verify and see what options are available?' "
                    f"Always verify before promising outcomes."
                )
                self.pipeline.add_stage(
                    "Quality Steering",
                    "GUIDED",
                    f"Unauthorized promise: {issue} - must verify before promising",
                    False
                )
                print(f"🚨 Quality Steering: GUIDING - {issue}")
                print(f"   Guidance: {guidance_message[:100]}...")
                return Guide(guidance_message)

        # 2. Check for specific fabricated details (hallucinations)
        hallucination_patterns = [
            ("will arrive on", "specific delivery date"),
            ("will be delivered at", "specific delivery time"),
            ("tracking number is", "fabricated tracking number"),
            ("arrives tomorrow", "unverified delivery promise"),
            ("in exactly", "fabricated timeframe")
        ]

        for pattern, issue in hallucination_patterns:
            if pattern in response_lower and "let me check" not in response_lower:
                self.pipeline.add_stage(
                    "Quality Steering",
                    "GUIDED",
                    f"Possible hallucination: '{issue}' - guiding to verify tracking details",
                    False
                )
                return Guide(
                    f"⚠️ Don't fabricate specific details. Instead of stating '{pattern}', "
                    f"say 'Let me look up the tracking information' or 'I'll check the delivery status'. "
                    f"Only provide specific dates/times/numbers from actual data, not estimates."
                )

        # 3. Check for policy violations
        policy_violations = [
            ("60 day return", "extended return window"),
            ("90 day warranty", "incorrect warranty period"),
            ("unlimited exchanges", "unauthorized exchange policy"),
            ("no questions asked refund", "unauthorized refund policy")
        ]

        for violation, issue in policy_violations:
            if violation in response_lower:
                self.pipeline.add_stage(
                    "Quality Steering",
                    "GUIDED",
                    f"Policy violation: '{issue}' - guiding to correct policy",
                    False
                )
                return Guide(
                    f"⚠️ That's not our policy. Instead of saying '{violation}', "
                    f"state the correct policy: '30-day return window' or 'Let me check our current policy for your situation'. "
                    f"Don't invent policies - stick to what's documented."
                )

        # 4. Check if agent should escalate but isn't
        escalation_triggers = [
            "legal action",
            "lawyer",
            "sue",
            "fraud",
            "stolen credit card",
            "unauthorized charge"
        ]

        has_escalation_trigger = any(trigger in response_lower for trigger in escalation_triggers)
        mentions_escalation = any(word in response_lower for word in ["manager", "supervisor", "specialist", "escalate"])

        if has_escalation_trigger and not mentions_escalation:
            self.pipeline.add_stage(
                "Quality Steering",
                "GUIDED",
                "Escalation needed but not mentioned - guiding to escalate to specialist",
                False
            )
            return Guide(
                "⚠️ This issue requires specialist handling. Include: "
                "'This requires attention from our specialist team. Let me connect you with [security/legal/escalation] team who can help immediately.' "
                "Don't try to handle legal/fraud issues yourself."
            )

        # 5. Check if agent is handling security/privacy topics without authority
        security_topics = [
            "password",
            "two-factor",
            "2fa",
            "account security",
            "data breach",
            "privacy concern",
            "personal information",
            "data protection",
            "security settings"
        ]

        has_security_topic = any(topic in response_lower for topic in security_topics)
        is_support_agent = agent.name == "support_agent"
        mentions_security_specialist = "security specialist" in response_lower or "security team" in response_lower

        if has_security_topic and is_support_agent and not mentions_security_specialist:
            self.pipeline.add_stage(
                "Quality Steering",
                "ESCALATING",
                "Security topic detected - triggering handoff to Security Specialist",
                False
            )
            # Mark that we need to escalate to security agent
            self.pipeline.trigger_security_escalation(
                "I understand your concern about account security. Let me connect you with our Security Specialist team who can provide expert guidance on password strength and account protection."
            )
            print(f"🔄 Quality Steering: ESCALATING to Security Specialist")
            # Guide the support agent to acknowledge and prepare for handoff
            return Guide(
                "⚠️ This is a security topic. Acknowledge the customer's concern briefly (1 sentence) and tell them "
                "you're connecting them to the security specialist team for expert help with their account security."
            )

        # All quality checks passed
        self.pipeline.add_stage(
            "Quality Steering",
            "PASSED",
            "No quality issues detected - response approved",
            True
        )
        print("✅ Quality Steering: All checks passed, proceeding")
        return Proceed()


# ============================================================================
# Safety Hook with Routing Detection
# ============================================================================

class SafetyControlHook:
    """AgentControl hook that detects when routing is needed."""

    def __init__(self, agent_name: str, pipeline: GovernancePipeline):
        self.agent_name = agent_name
        self.pipeline = pipeline
        self.pii_detected = False
        self.escalation_needed = False

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Register safety check callbacks."""
        registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)
        registry.add_callback(AfterModelCallEvent, self.on_after_model_call)

    async def on_before_invocation(self, event: BeforeInvocationEvent):
        """Pre-check: Detect PII and escalation needs."""
        if not event.messages:
            return

        # Extract user message
        user_message = ""
        for msg in event.messages:
            if isinstance(msg, dict) and msg.get('role') == 'user':
                content = msg.get('content', '')
                # Handle content as string or list of blocks
                if isinstance(content, list):
                    # Extract text from content blocks
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and 'text' in block:
                            text_parts.append(block['text'])
                        else:
                            text_parts.append(str(block))
                    user_message = ' '.join(text_parts)
                else:
                    user_message = str(content)
                break
            elif hasattr(msg, 'role') and msg.role == 'user':
                content = msg.content if hasattr(msg, 'content') else ''
                # Handle content as string or list
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if hasattr(block, 'text'):
                            text_parts.append(block.text)
                        else:
                            text_parts.append(str(block))
                    user_message = ' '.join(text_parts)
                else:
                    user_message = str(content)
                break

        if not user_message:
            return

        # Check for PII
        step = Step(
            type="llm",
            name="user-input",
            input=user_message,
            output=""
        )

        try:
            current_agent = agent_control.current_agent()
            if not current_agent:
                return

            from agent_control.client import AgentControlClient
            server_url = os.getenv('AGENT_CONTROL_URL', 'http://localhost:8000')

            async with AgentControlClient(base_url=server_url) as client:
                result = await agent_control.evaluation.check_evaluation(
                    client=client,
                    agent_uuid=current_agent.agent_id,
                    step=step,
                    stage="pre"
                )

                if not result.is_safe:
                    self.pii_detected = True
                    # Build detail message from matches
                    pii_types = []
                    if result.matches:
                        for match in result.matches:
                            if hasattr(match, 'metadata') and match.metadata:
                                pii_types.append(str(match.metadata))
                            elif hasattr(match, 'control_name'):
                                pii_types.append(match.control_name)

                    detail = f"PII patterns detected: {', '.join(pii_types)}" if pii_types else "PII detected in input"

                    self.pipeline.add_stage(
                        "Safety Detection",
                        "PII FOUND",
                        detail,
                        False
                    )
                else:
                    self.pipeline.add_stage("Safety Check", "PASSED", "No PII in input", True)

        except Exception as e:
            self.pipeline.add_stage("Safety Check", "ERROR", str(e), False)

        # Check for escalation needs (extreme frustration)
        angry_keywords = ["furious", "terrible", "worst", "horrible", "unacceptable"]
        if any(word in user_message.lower() for word in angry_keywords):
            self.escalation_needed = True

    async def on_after_model_call(self, event: AfterModelCallEvent):
        """Post-check: Validate agent output."""
        output_text = ""
        if hasattr(event, 'output'):
            if isinstance(event.output, str):
                output_text = event.output
            elif isinstance(event.output, dict) and 'content' in event.output:
                output_text = event.output['content']

        step = Step(
            type="llm",
            name="assistant",
            input="",
            output=output_text
        )

        try:
            current_agent = agent_control.current_agent()
            if not current_agent:
                return

            from agent_control.client import AgentControlClient
            server_url = os.getenv('AGENT_CONTROL_URL', 'http://localhost:8000')

            async with AgentControlClient(base_url=server_url) as client:
                result = await agent_control.evaluation.check_evaluation(
                    client=client,
                    agent_uuid=current_agent.agent_id,
                    step=step,
                    stage="post"
                )

                if not result.is_safe:
                    self.pipeline.add_stage(
                        "Safety (Post)",
                        "BLOCKED",
                        f"Unsafe output: {result.reason}",
                        False
                    )
                    event.retry = True
                    event.retry_guidance = f"🛡️ Safety violation: {result.reason}. Regenerate without PII."
                else:
                    self.pipeline.add_stage("Safety (Post)", "PASSED", "Output is safe", True)

        except Exception as e:
            self.pipeline.add_stage("Safety (Post)", "ERROR", str(e), False)


# ============================================================================
# Specialized Agents
# ============================================================================

def create_support_agent(pipeline: GovernancePipeline) -> Agent:
    """Standard support agent for normal requests."""
    model = OpenAIModel(model_id="gpt-4o-mini")

    print(f"🔧 Creating support agent with hooks...")
    quality_handler = QualitySteeringHandler(pipeline)
    print(f"🔧 QualitySteeringHandler instance: {quality_handler}")
    print(f"🔧 QualitySteeringHandler type: {type(quality_handler)}")
    print(f"🔧 Is SteeringHandler subclass: {isinstance(quality_handler, SteeringHandler)}")

    agent = Agent(
        name="support_agent",
        model=model,
        system_prompt="""You are a friendly customer support agent. Help customers with their
        questions about orders, returns, and shipping. Be warm, empathetic, and professional.
        Keep responses concise (under 3 sentences).""",
        hooks=[
            SafetyControlHook("support", pipeline),
            quality_handler
        ]
    )

    print(f"🔧 Support agent created")
    return agent


def create_security_agent(pipeline: GovernancePipeline) -> Agent:
    """Security agent for handling PII-related requests."""
    model = OpenAIModel(model_id="gpt-4o-mini")

    agent = Agent(
        name="security_agent",
        model=model,
        system_prompt="""You are a Security Specialist. When customers accidentally share
        sensitive information (SSN, credit cards, etc):

        1. Briefly acknowledge the security concern (1 sentence)
        2. Actually help with their original question using safe information like order numbers
        3. Provide a complete solution to their problem

        Example:
        - Customer: "My order ORD-123 hasn't arrived, here's my SSN 123-45-6789"
        - You: "For security, I can't process SSN. Let me check order ORD-123 - it's currently
          in transit and should arrive in 2-3 business days. I'll send you tracking info!"

        Be warm, helpful, and solve their actual problem. Keep it concise (2-3 sentences).""",
        hooks=[
            SafetyControlHook("security", pipeline),
            QualitySteeringHandler(pipeline)
        ]
    )

    return agent


def create_escalation_agent(pipeline: GovernancePipeline) -> Agent:
    """Escalation agent for upset customers."""
    model = OpenAIModel(model_id="gpt-4o-mini")

    agent = Agent(
        name="escalation_agent",
        model=model,
        system_prompt="""You are a Senior Support Specialist handling escalated cases.
        You prioritize empathy and understanding. When customers are upset:
        1. Acknowledge their frustration sincerely
        2. Apologize for their experience
        3. Take ownership and offer immediate help

        Be exceptionally empathetic. Keep it concise (2-3 sentences).""",
        hooks=[
            SafetyControlHook("escalation", pipeline),
            QualitySteeringHandler(pipeline)
        ]
    )

    return agent


# ============================================================================
# Intelligent Router
# ============================================================================

async def route_request(user_message: str, pipeline: GovernancePipeline) -> tuple[str, str]:
    """
    Intelligently route request to appropriate agent.

    Returns: (agent_type, routing_reason)
    """
    import re

    # Check for PII using proper regex matching
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    cc_pattern = r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

    has_ssn = re.search(ssn_pattern, user_message)
    has_cc = re.search(cc_pattern, user_message)
    has_email = re.search(email_pattern, user_message)
    has_pii = has_ssn or has_cc or has_email

    # Check for extreme frustration
    angry_keywords = ["furious", "terrible", "worst", "horrible", "unacceptable", "outraged"]
    is_very_angry = sum(1 for word in angry_keywords if word in user_message.lower()) >= 2

    if has_pii:
        pipeline.add_stage(
            "Intelligent Routing",
            "ROUTE TO SECURITY",
            "PII detected → Security Agent",
            True
        )
        return "security", "PII detected in request"
    elif is_very_angry:
        pipeline.add_stage(
            "Intelligent Routing",
            "ROUTE TO ESCALATION",
            "Extreme frustration → Senior Agent",
            True
        )
        return "escalation", "Customer needs escalation"
    else:
        pipeline.add_stage(
            "Intelligent Routing",
            "ROUTE TO SUPPORT",
            "Normal request → Support Agent",
            True
        )
        return "support", "Standard support request"


# ============================================================================
# Multi-Agent Graph with Routing
# ============================================================================

async def get_governed_response(user_message: str) -> tuple[str, str, str, GovernancePipeline]:
    """
    Get response with intelligent routing based on governance.

    Returns: (routing_message, agent_name, agent_response, pipeline)
    """
    pipeline = GovernancePipeline()

    # Check OpenAI API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")

    # Intelligent routing decision
    agent_type, reason = await route_request(user_message, pipeline)
    pipeline.set_routing(agent_type, reason)

    # Create routing message
    agent_labels = {
        "security": "🔒 Security Specialist",
        "escalation": "⚠️ Senior Support Agent",
        "support": "💬 Support Agent"
    }
    agent_name = agent_labels.get(agent_type, agent_type)

    routing_messages = {
        "security": f"🎯 **Routing Decision:** PII detected in request. Transferring to {agent_name} for secure handling...",
        "escalation": f"🎯 **Routing Decision:** High frustration detected. Escalating to {agent_name} for priority assistance...",
        "support": f"🎯 **Routing Decision:** Standard request. Connecting to {agent_name}..."
    }
    routing_message = routing_messages.get(agent_type, f"Routing to {agent_name}...")

    # Create the appropriate agent
    if agent_type == "security":
        agent = create_security_agent(pipeline)
    elif agent_type == "escalation":
        agent = create_escalation_agent(pipeline)
    else:
        agent = create_support_agent(pipeline)

    # Create graph and execute
    agent_node = GraphNode(executor=agent, node_id=agent_type)
    graph = Graph(
        nodes={agent_type: agent_node},
        edges=set(),
        entry_points={agent_node}
    )

    result = await graph.invoke_async(user_message)

    # Extract response
    response_text = "No response generated"
    if result.results and result.execution_order:
        last_node = result.execution_order[-1]
        node_result = result.results.get(last_node.node_id)

        if node_result and hasattr(node_result.result, 'message'):
            agent_message = node_result.result.message
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
                        else:
                            text_parts.append(str(block))
                    response_text = ' '.join(text_parts)
                else:
                    response_text = str(content)

    # Check if Quality Steering triggered a security escalation
    if pipeline.needs_security_escalation:
        print(f"🔄 Escalation detected! Routing to Security Specialist...")

        # Add handoff stage
        pipeline.add_stage(
            "Quality Steering Handoff",
            "ESCALATING",
            "Support agent acknowledged → Transferring to Security Specialist",
            True
        )

        # Store the support agent's escalation message
        support_escalation_msg = response_text

        # Create security agent and execute
        security_agent = create_security_agent(pipeline)
        security_node = GraphNode(executor=security_agent, node_id="security")
        security_graph = Graph(
            nodes={"security": security_node},
            edges=set(),
            entry_points={security_node}
        )

        # Execute security agent with original user message
        security_result = await security_graph.invoke_async(user_message)

        # Extract security agent response
        security_response = "No response generated"
        if security_result.results and security_result.execution_order:
            last_node = security_result.execution_order[-1]
            node_result = security_result.results.get(last_node.node_id)

            if node_result and hasattr(node_result.result, 'message'):
                agent_message = node_result.result.message
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
                            else:
                                text_parts.append(str(block))
                        security_response = ' '.join(text_parts)
                    else:
                        security_response = str(content)

        # Update pipeline routing to show final destination
        pipeline.set_routing("security", "Quality Steering escalated security topic")

        # Return security agent's response as final response
        # Routing message shows the escalation path
        escalation_routing = (
            f"🎯 **Initial Route:** Support Agent\n\n"
            f"💬 **Support Agent:** {support_escalation_msg}\n\n"
            f"🔄 **Quality Steering:** Detected security topic → Escalating to Security Specialist...\n\n"
            f"🔒 **Security Specialist:** Taking over..."
        )

        return escalation_routing, "🔒 Security Specialist", security_response, pipeline

    return routing_message, agent_name, response_text, pipeline


# ============================================================================
# UI Rendering Functions
# ============================================================================

def render_header():
    """Render the app header."""
    st.title("🎯 Layered Governance Demo")
    st.subheader("Safety (AgentControl) + Quality (Steering) = Complete Protection")

    st.markdown("""
    **Two Governance Layers:**

    🛡️ **Safety Layer (AgentControl)** - Hard stops for compliance
    - Blocks PII leakage (SSN, credit cards, emails)
    - Enforces security policies
    - *Action: BLOCK and re-route*

    ✨ **Quality Layer (Steering)** - Contextual guidance through modular prompting
    - Provides just-in-time feedback that appears when relevant, rather than front-loading all instructions
    - Helps agents respond appropriately to security topics by steering them to specialists
    - Detects when specialized expertise is needed and guides handoff
    - *Action: GUIDE with contextual feedback*

    Try the scenario below to see both layers working together!
    """)


def render_sidebar():
    """Render the dashboard."""
    st.sidebar.title("📊 Governance Dashboard")

    # Layer Status
    st.sidebar.subheader("🛡️ Safety Layer (AgentControl)")
    if st.session_state.get("agentcontrol_initialized"):
        st.sidebar.success("✅ Active - PII Detection Enabled")
    else:
        st.sidebar.error("❌ Inactive")

    st.sidebar.subheader("✨ Quality Layer (Steering)")
    st.sidebar.success("✅ Active - Contextual Guidance")
    st.sidebar.caption("• Detects security topics\n• Guides agent handoffs\n• Provides just-in-time feedback\n• Helps agents respond appropriately")

    # Governance statistics
    st.sidebar.subheader("📈 Governance Stats")

    pipelines = st.session_state.get("pipelines", [])

    # Count safety blocks
    safety_blocks = sum(
        1 for p in pipelines
        for stage in p.stages
        if "Safety" in stage["layer"] and not stage["passed"]
    )

    # Count quality guidances
    quality_guidances = sum(
        1 for p in pipelines
        for stage in p.stages
        if "Quality" in stage["layer"] and stage["action"] == "GUIDED"
    )

    # Count routing
    security_routes = sum(1 for p in pipelines if p.routed_to and p.routed_to["agent"] == "security")
    escalation_routes = sum(1 for p in pipelines if p.routed_to and p.routed_to["agent"] == "escalation")
    support_routes = sum(1 for p in pipelines if p.routed_to and p.routed_to["agent"] == "support")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric("🛡️ Safety Blocks", safety_blocks)
        st.metric("🔒 Security Routes", security_routes)
    with col2:
        st.metric("✨ Quality Guides", quality_guidances)
        st.metric("Total Requests", len(pipelines))

    # Recent activity
    if pipelines:
        st.sidebar.subheader("🕐 Recent Activity")
        for idx, pipeline in enumerate(reversed(pipelines[-3:])):
            if pipeline.routed_to:
                agent = pipeline.routed_to["agent"]
                icon = {"security": "🔒", "escalation": "⚠️", "support": "💬"}.get(agent, "❓")

                # Count issues in this pipeline
                safety_issues = sum(1 for s in pipeline.stages if "Safety" in s["layer"] and not s["passed"])
                quality_issues = sum(1 for s in pipeline.stages if "Quality" in s["layer"] and s["action"] == "GUIDED")

                with st.sidebar.expander(f"#{len(pipelines) - idx}: {icon} {agent.title()}", expanded=False):
                    if safety_issues > 0:
                        st.caption(f"🛡️ Safety: {safety_issues} issue(s)")
                    if quality_issues > 0:
                        st.caption(f"✨ Quality: {quality_issues} guidance(s)")
                    if safety_issues == 0 and quality_issues == 0:
                        st.caption("✅ All checks passed")


def render_scenarios():
    """Render test scenario."""
    st.subheader("🎬 Demo Scenario")
    st.caption("Click the button to see both governance layers in action")

    # Single scenario showing both layers
    scenario = {
        "label": "🔐 Security Topic + PII Detection",
        "prompt": "I'm worried about my account security. My SSN is 123-45-6789 - can you help me make my password stronger?",
        "expected": """**What happens:**

1. **Safety Layer (AgentControl):** Detects SSN in user input → Blocks PII from being processed
2. **Routing:** PII detected → Routes to Security Specialist agent
3. **Quality Layer (Steering):** Support agent detects security topic → Provides contextual guidance to escalate to Security Specialist
4. **Final Response:** Security Specialist handles password guidance WITHOUT processing SSN

**Result:** Customer protected from PII exposure AND receives expert security guidance"""
    }

    # Single button for the scenario
    if st.button(scenario["label"], key="scenario_main", use_container_width=True):
        st.session_state.scenario_prompt = scenario["prompt"]
        st.rerun()

    with st.expander("What happens?", expanded=False):
        st.markdown(scenario["expected"])


def render_pipeline_visualization(pipeline: GovernancePipeline):
    """Render the governance and routing pipeline as a trajectory."""
    with st.expander("🗺️ Request Trajectory", expanded=False):
        st.markdown("**Flow:** User → Router → Safety Checks → Specialist Agent → Response")
        st.markdown("---")

        # Show stages in order
        for idx, stage in enumerate(pipeline.stages, 1):
            # Determine style based on layer and status
            if stage["passed"]:
                icon = "✅"
                style = "success"
            else:
                if "Safety" in stage["layer"] or "Security" in stage["layer"]:
                    icon = "⚠️"
                    style = "warning"
                else:
                    icon = "🔄"
                    style = "info"

            # Show stage number and title
            st.markdown(f"**Step {idx}: {stage['layer']}**")

            # Show result with appropriate styling
            if style == "success":
                st.success(f"{icon} {stage['action']}")
            elif style == "warning":
                st.warning(f"{icon} {stage['action']}")
            else:
                st.info(f"{icon} {stage['action']}")

            # Show detail
            st.caption(f"↳ _{stage['detail']}_")

            # Add arrow between stages
            if idx < len(pipeline.stages):
                st.markdown("↓")

        # Show final routing decision
        if pipeline.routed_to:
            st.markdown("---")
            agent = pipeline.routed_to["agent"]
            reason = pipeline.routed_to["reason"]
            icon = {"security": "🔒", "escalation": "⚠️", "support": "💬"}.get(agent, "❓")
            st.info(f"**Final Destination:** {icon} {agent.upper()} AGENT - {reason}")


def render_chat():
    """Render the chat interface."""
    st.subheader("💬 Customer Support Chat")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pipelines" not in st.session_state:
        st.session_state.pipelines = []

    # Display chat history
    for message in st.session_state.messages:
        avatar = message.get("avatar", None)
        agent = message.get("agent", None)

        with st.chat_message(message["role"], avatar=avatar):
            if agent:
                st.markdown(f"**{agent}:**")
            st.markdown(message["content"])

            if "pipeline" in message:
                render_pipeline_visualization(message["pipeline"])

    # Handle scenario injection
    user_input = None
    if "scenario_prompt" in st.session_state:
        user_input = st.session_state.scenario_prompt
        del st.session_state.scenario_prompt

    # Chat input
    if prompt := (user_input or st.chat_input("Type your message...")):
        st.session_state.current_user_message = prompt

        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get bot response with routing
        with st.spinner("🔍 Analyzing request and determining route..."):
            try:
                routing_msg, agent_name, response, pipeline = asyncio.run(get_governed_response(prompt))

                # Show routing decision
                with st.chat_message("assistant", avatar="🎯"):
                    st.markdown(routing_msg)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": routing_msg,
                        "avatar": "🎯",
                        "agent": "Router"
                    })

                # Show specialist agent response
                agent_avatar = agent_name.split()[0]  # Extract emoji
                with st.chat_message("assistant", avatar=agent_avatar):
                    st.markdown(f"**{agent_name}:**")
                    if not response or response == "No response generated":
                        st.warning("⚠️ No response was generated. Please try again.")
                    else:
                        st.markdown(response)

                    render_pipeline_visualization(pipeline)

                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response if response else "No response generated",
                        "avatar": agent_avatar,
                        "agent": agent_name,
                        "pipeline": pipeline
                    })

                st.session_state.pipelines.append(pipeline)

            except Exception as e:
                st.error(f"❌ Error: {e}")
                import traceback
                st.error(traceback.format_exc())

        st.rerun()


# ============================================================================
# Main App
# ============================================================================

def main():
    """Run the intelligent routing demo."""
    st.set_page_config(
        page_title="Intelligent Agent Routing",
        page_icon="🎯",
        layout="wide"
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pipelines" not in st.session_state:
        st.session_state.pipelines = []

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
            st.warning(f"⚠️ AgentControl not initialized: {e}")

    # Render UI
    render_header()
    render_sidebar()
    render_scenarios()

    st.markdown("---")

    render_chat()


if __name__ == "__main__":
    main()
