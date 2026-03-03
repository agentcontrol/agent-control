"""
Customer Support Agent - Example Integration with Agent Control SDK

This module demonstrates how to integrate the agent-control SDK into
an existing customer support application. It shows:

1. SDK initialization at startup
2. Using @control() decorator to protect functions
3. Handling ControlViolationError gracefully
4. Realistic enterprise patterns (mock services, multiple tools)

NOTE: Controls are defined on the server via the UI, not in code.
This keeps security controls centrally managed and separate from code.
"""

import asyncio
import random
from datetime import datetime
from typing import Any

import agent_control
from agent_control import ControlViolationError, control
from agent_control.tracing import with_trace

# =============================================================================
# SDK INITIALIZATION
# =============================================================================
# Call this once at the start of your application.
# The agent registers with the server and loads associated controls.

agent_control.init(
    agent_name="646d5dea-c2e6-4453-b446-7035482b38e4",
    agent_description="AI-powered customer support assistant that helps with inquiries, "
                      "searches knowledge bases, and creates support tickets.",
    agent_version="1.0.0",
    observability_enabled=True,
)


# =============================================================================
# MOCK SERVICES (Simulated - No External Dependencies)
# =============================================================================
# In a real application, these would connect to actual services.


class MockLLM:
    """Simulates an LLM for generating responses. No API key needed."""

    RESPONSES = {
        "greeting": "Hello! I'm your customer support assistant. How can I help you today?",
        "refund": "I understand you'd like a refund. Let me look into your order. "
                  "Our refund guidelines allow returns within 30 days of purchase.",
        "technical": "I can help with technical issues. Could you describe the problem "
                     "you're experiencing in more detail?",
        "status": "I'll check the status of your order right away. "
                  "Could you provide your order number?",
        "default": "Thank you for your message. Let me help you with that.",
    }

    @classmethod
    def generate(cls, message: str) -> str:
        """Generate a response based on message content."""
        message_lower = message.lower()

        if any(word in message_lower for word in ["hi", "hello", "hey"]):
            return cls.RESPONSES["greeting"]
        elif any(word in message_lower for word in ["refund", "return", "money back"]):
            return cls.RESPONSES["refund"]
        elif any(word in message_lower for word in ["error", "bug", "broken", "not working"]):
            return cls.RESPONSES["technical"]
        elif any(word in message_lower for word in ["status", "order", "tracking"]):
            return cls.RESPONSES["status"]
        else:
            return cls.RESPONSES["default"]


class CustomerDatabase:
    """Simulates a customer database lookup."""

    CUSTOMERS = {
        "C001": {
            "id": "C001",
            "name": "Alice Smith",
            "email": "alice@example.com",
            "tier": "premium",
            "orders": 15,
        },
        "C002": {
            "id": "C002",
            "name": "Bob Johnson",
            "email": "bob@example.com",
            "tier": "standard",
            "orders": 3,
        },
        "alice@example.com": {
            "id": "C001",
            "name": "Alice Smith",
            "email": "alice@example.com",
            "tier": "premium",
            "orders": 15,
        },
    }

    @classmethod
    def lookup(cls, query: str) -> dict[str, Any] | None:
        """Look up a customer by ID or email."""
        return cls.CUSTOMERS.get(query)


class KnowledgeBase:
    """Simulates a RAG-style knowledge base search."""

    ARTICLES = [
        {
            "id": "KB001",
            "title": "How to Request a Refund",
            "content": "To request a refund, go to Orders > Select Order > Request Refund. "
                       "Refunds are processed within 5-7 business days.",
            "category": "billing",
        },
        {
            "id": "KB002",
            "title": "Resetting Your Password",
            "content": "Click 'Forgot Password' on the login page. Enter your email and "
                       "follow the instructions in the reset email.",
            "category": "account",
        },
        {
            "id": "KB003",
            "title": "Shipping Times and Tracking",
            "content": "Standard shipping takes 5-7 business days. Express shipping takes "
                       "2-3 business days. Track your order in the Orders section.",
            "category": "shipping",
        },
    ]

    @classmethod
    def search(cls, query: str) -> list[dict[str, Any]]:
        """Search for relevant knowledge base articles."""
        query_lower = query.lower()
        results = []

        for article in cls.ARTICLES:
            if (query_lower in article["title"].lower() or
                query_lower in article["content"].lower() or
                query_lower in article["category"]):
                results.append(article)

        # If no exact match, return a random article
        if not results:
            results = [random.choice(cls.ARTICLES)]

        return results


class TicketSystem:
    """Simulates a ticket creation system."""

    _ticket_counter = 1000

    @classmethod
    def create(cls, subject: str, description: str, priority: str = "medium") -> dict[str, Any]:
        """Create a new support ticket."""
        cls._ticket_counter += 1
        return {
            "ticket_id": f"TKT-{cls._ticket_counter}",
            "subject": subject,
            "description": description,
            "priority": priority,
            "status": "open",
            "created_at": datetime.now().isoformat(),
        }


# =============================================================================
# PROTECTED AGENT FUNCTIONS
# =============================================================================
# These functions are protected by the @control() decorator.
# The server evaluates controls and blocks/allows based on agent associations.


@control()
async def respond_to_customer(message: str) -> str:
    """
    Main chat function - generates an LLM response to customer message.

    The @control() decorator:
    - Checks 'pre' controls before generating (input validation)
    - Checks 'post' controls after generating (output validation)

    If a control triggers with 'deny' action, ControlViolationError is raised.
    """
    # Generate response using mock LLM
    response = MockLLM.generate(message)
    return response


async def _lookup_customer(query: str) -> dict[str, Any]:
    """
    Look up customer information - protected tool call.

    The decorator protects this operation by validating:
    - The query doesn't contain injection attempts
    - The result doesn't leak unauthorized data
    """
    customer = CustomerDatabase.lookup(query)
    if customer:
        return {"found": True, "customer": customer}
    return {"found": False, "message": f"No customer found for: {query}"}


_lookup_customer.name = "lookup_customer"  # type: ignore[attr-defined]
_lookup_customer.tool_name = "lookup_customer"  # type: ignore[attr-defined]
lookup_customer = control()(_lookup_customer)


async def _search_knowledge_base(query: str) -> dict[str, Any]:
    """
    Search the knowledge base - protected tool call.

    Validates that:
    - Search queries don't contain harmful content
    - Results are appropriate to share
    """
    articles = KnowledgeBase.search(query)
    return {
        "query": query,
        "results_count": len(articles),
        "articles": articles,
    }


_search_knowledge_base.name = "search_knowledge_base"  # type: ignore[attr-defined]
_search_knowledge_base.tool_name = "search_knowledge_base"  # type: ignore[attr-defined]
search_knowledge_base = control()(_search_knowledge_base)


async def _create_ticket(
    subject: str, description: str, priority: str = "medium"
) -> dict[str, Any]:
    """
    Create a support ticket - protected tool call.

    Validates that:
    - Ticket content is appropriate
    - No sensitive data in public fields
    """
    ticket = TicketSystem.create(subject, description, priority)
    return {"success": True, "ticket": ticket}


_create_ticket.name = "create_ticket"  # type: ignore[attr-defined]
_create_ticket.tool_name = "create_ticket"  # type: ignore[attr-defined]
create_ticket = control()(_create_ticket)


# =============================================================================
# CUSTOMER SUPPORT AGENT CLASS
# =============================================================================


class CustomerSupportAgent:
    """
    High-level agent that orchestrates the protected functions.

    This demonstrates the pattern of catching ControlViolationError
    and providing graceful fallback responses.
    """

    def __init__(self):
        self.conversation_history: list[dict[str, str]] = []

    async def chat(self, user_message: str) -> str:
        """
        Process a user message and return a response.

        Handles ControlViolationError gracefully by returning
        a safe fallback message instead of exposing internal errors.
        """
        self.conversation_history.append({"role": "user", "content": user_message})

        try:
            # Main LLM response - protected by controls
            response = await respond_to_customer(user_message)

            self.conversation_history.append({"role": "assistant", "content": response})
            return response

        except ControlViolationError as e:
            # Control triggered - return safe fallback
            fallback = (
                "I'm sorry, but I can't help with that request. "
                "Is there something else I can assist you with?"
            )
            self.conversation_history.append({"role": "assistant", "content": fallback})
            print(f"  [Control triggered: {e.control_name}]")
            return fallback

    async def lookup(self, query: str) -> str:
        """Look up customer information with error handling."""
        try:
            result = await lookup_customer(query)
            if result["found"]:
                customer = result["customer"]
                name, email, tier = customer['name'], customer['email'], customer['tier']
                return f"Found customer: {name} ({email}) - {tier} tier"
            return result["message"]

        except ControlViolationError as e:
            print(f"  [Control triggered: {e.control_name}]")
            return "I'm unable to process that lookup request."

    async def search(self, query: str) -> str:
        """Search the knowledge base with error handling."""
        try:
            result = await search_knowledge_base(query)
            if result["articles"]:
                article = result["articles"][0]
                return f"Found: {article['title']}\n{article['content']}"
            return "No relevant articles found."

        except ControlViolationError as e:
            print(f"  [Control triggered: {e.control_name}]")
            return "I'm unable to search for that query."

    async def create_support_ticket(
        self, subject: str, description: str, priority: str = "medium"
    ) -> str:
        """Create a support ticket with error handling."""
        try:
            result = await create_ticket(subject, description, priority)
            if result["success"]:
                ticket = result["ticket"]
                return f"Ticket created: {ticket['ticket_id']} (Priority: {ticket['priority']})"
            return "Failed to create ticket."

        except ControlViolationError as e:
            print(f"  [Control triggered: {e.control_name}]")
            return "I'm unable to create a ticket with that content."

    async def handle_comprehensive_support(
        self, user_message: str, customer_id: str | None = None
    ) -> str:
        """
        Handle a comprehensive support request - demonstrates multiple spans in one trace.

        This method calls multiple @control() decorated functions in sequence,
        creating multiple spans within a single trace for observability testing:
        1. lookup_customer (if customer_id provided)
        2. search_knowledge_base
        3. respond_to_customer

        Each @control() decorated function creates its own span, all grouped
        under the same trace context using with_trace().
        """
        self.conversation_history.append({"role": "user", "content": user_message})

        # Use with_trace() to ensure all spans share the same trace ID
        # This creates a parent trace context that child spans inherit
        with with_trace():
            context_parts = []

            # Span 1: Customer lookup (if customer_id provided)
            if customer_id:
                try:
                    customer_result = await lookup_customer(customer_id)
                    if customer_result["found"]:
                        customer = customer_result["customer"]
                        tier = customer['tier']
                        orders = customer['orders']
                        context_parts.append(
                            f"Customer: {customer['name']} ({tier} tier, {orders} orders)"
                        )
                except ControlViolationError as e:
                    print(f"  [Control triggered on lookup: {e.control_name}]")

            # Span 2: Knowledge base search
            try:
                # Extract keywords from user message for search
                search_query = user_message.split()[0] if user_message else "help"
                kb_result = await search_knowledge_base(search_query)
                if kb_result["articles"]:
                    article = kb_result["articles"][0]
                    context_parts.append(f"Relevant KB: {article['title']}")
            except ControlViolationError as e:
                print(f"  [Control triggered on KB search: {e.control_name}]")

            # Span 3: Generate response
            try:
                # Build enhanced prompt with context
                enhanced_message = user_message
                if context_parts:
                    enhanced_message = f"{user_message}\n[Context: {'; '.join(context_parts)}]"

                response = await respond_to_customer(enhanced_message)
                self.conversation_history.append({"role": "assistant", "content": response})
                return response

            except ControlViolationError as e:
                fallback = (
                    "I'm sorry, but I can't help with that request. "
                    "Is there something else I can assist you with?"
                )
                self.conversation_history.append({"role": "assistant", "content": fallback})
                print(f"  [Control triggered on response: {e.control_name}]")
                return fallback


# =============================================================================
# DIRECT EXECUTION
# =============================================================================

if __name__ == "__main__":
    # Quick test
    async def main():
        agent = CustomerSupportAgent()

        print("\n--- Test: Normal chat (1 span) ---")
        response = await agent.chat("Hello, I need help with a refund")
        print(f"Agent: {response}")

        print("\n--- Test: Customer lookup (1 span) ---")
        response = await agent.lookup("C001")
        print(f"Agent: {response}")

        print("\n--- Test: Knowledge base search (1 span) ---")
        response = await agent.search("refund")
        print(f"Agent: {response}")

        print("\n--- Test: Create ticket (1 span) ---")
        response = await agent.create_support_ticket(
            subject="Refund request",
            description="I would like to return my order",
            priority="medium"
        )
        print(f"Agent: {response}")

        print("\n--- Test: Comprehensive support (2-3 spans in one trace) ---")
        response = await agent.handle_comprehensive_support(
            user_message="I need help with a refund for my recent order",
            customer_id="C001"
        )
        print(f"Agent: {response}")

        print("\n--- Test: Comprehensive support without customer (2 spans) ---")
        response = await agent.handle_comprehensive_support(
            user_message="How do I reset my password?"
        )
        print(f"Agent: {response}")

    asyncio.run(main())
