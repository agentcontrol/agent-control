#!/usr/bin/env python3
"""
Layered Governance Demo with Intelligent Routing

This demo shows how governance can intelligently route requests:
- When PII is detected → Route to Security Agent
- When customer is angry → Route to Escalation Agent
- Normal requests → Route to Support Agent

REAL-WORLD FLOW:
1. User submits request
2. Safety layer detects issue (e.g., PII)
3. Intelligent routing steers to specialist agent
4. Specialist agent handles the scenario properly
5. User gets helpful response instead of just "blocked"

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

    agent = Agent(
        name="support_agent",
        model=model,
        system_prompt="""You are a friendly customer support agent. Help customers with their
        questions about orders, returns, and shipping. Be warm, empathetic, and professional.
        Keep responses concise (under 3 sentences).""",
        hooks=[SafetyControlHook("support", pipeline)]
    )

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
        hooks=[SafetyControlHook("security", pipeline)]
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
        hooks=[SafetyControlHook("escalation", pipeline)]
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

    return routing_message, agent_name, response_text, pipeline


# ============================================================================
# UI Rendering Functions
# ============================================================================

def render_header():
    """Render the app header."""
    st.title("🎯 Intelligent Agent Routing Demo")
    st.subheader("Governance + Smart Routing = Better UX")

    st.markdown("""
    **How it works:**
    1. 🔍 **Detect the situation** (PII, angry customer, normal request)
    2. 🎯 **Route to specialist** (Security, Escalation, or Support agent)
    3. ✅ **Get expert help** instead of generic "blocked" message

    Try the scenarios below to see intelligent routing in action!
    """)


def render_sidebar():
    """Render the dashboard."""
    st.sidebar.title("📊 Routing Dashboard")

    # AgentControl status
    st.sidebar.subheader("🛡️ Safety Layer")
    if st.session_state.get("agentcontrol_initialized"):
        st.sidebar.success("Active")
    else:
        st.sidebar.error("Inactive")

    # Routing statistics
    st.sidebar.subheader("📈 Routing Stats")

    pipelines = st.session_state.get("pipelines", [])

    security_routes = sum(1 for p in pipelines if p.routed_to and p.routed_to["agent"] == "security")
    escalation_routes = sum(1 for p in pipelines if p.routed_to and p.routed_to["agent"] == "escalation")
    support_routes = sum(1 for p in pipelines if p.routed_to and p.routed_to["agent"] == "support")

    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric("🔒 Security", security_routes)
        st.metric("⚠️ Escalation", escalation_routes)
    with col2:
        st.metric("💬 Support", support_routes)
        st.metric("Total", len(pipelines))

    # Recent routings
    if pipelines:
        st.sidebar.subheader("📋 Recent Routes")
        for idx, pipeline in enumerate(reversed(pipelines[-5:])):
            if pipeline.routed_to:
                agent = pipeline.routed_to["agent"]
                reason = pipeline.routed_to["reason"]
                icon = {"security": "🔒", "escalation": "⚠️", "support": "💬"}.get(agent, "❓")

                with st.sidebar.expander(f"{icon} {agent.title()} #{len(pipelines) - idx}", expanded=False):
                    st.caption(f"**Reason:** {reason}")
                    for stage in pipeline.stages:
                        status = "✅" if stage["passed"] else "🔄"
                        st.caption(f"{status} {stage['layer']}: {stage['action']}")


def render_scenarios():
    """Render test scenarios."""
    st.subheader("🎬 Try These Examples")
    st.caption("Click any button to see intelligent routing in action")

    scenarios = {
        "🔒 PII Detected": {
            "prompt": "My order ORD-12345 hasn't arrived. My SSN is 123-45-6789, can you help?",
            "expected": "Detects PII → Routes to Security Agent → Explains security concerns warmly"
        },
        "😤 Angry Customer": {
            "prompt": "This is absolutely TERRIBLE! WORST service I've ever experienced! UNACCEPTABLE!",
            "expected": "Detects frustration → Routes to Escalation Agent → Shows extra empathy"
        },
        "💬 Normal Request": {
            "prompt": "What's your return policy?",
            "expected": "Standard request → Routes to Support Agent → Provides helpful response"
        }
    }

    cols = st.columns(3)
    for idx, (label, scenario) in enumerate(scenarios.items()):
        with cols[idx]:
            if st.button(label, key=f"scenario_{idx}", use_container_width=True):
                st.session_state.scenario_prompt = scenario["prompt"]
                st.rerun()

            with st.expander("What happens?", expanded=False):
                st.caption(scenario["expected"])


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
