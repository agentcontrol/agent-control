#!/usr/bin/env python3
"""
Question Answering Agent with DeepEval Quality Controls

This example demonstrates:
1. Using agent-control SDK with @control() decorator
2. DeepEval GEval evaluators for quality enforcement
3. Handling ControlViolationError gracefully

The agent is protected by DeepEval-based controls that check:
- Response coherence (logical consistency)
- Answer relevance (stays on topic)
- Factual correctness (when expected outputs available)

Usage:
    # Setup first (creates controls on server)
    python setup_controls.py

    # Then run the agent
    python qa_agent.py

Requirements:
    - agent-control server running
    - OPENAI_API_KEY set (for DeepEval)
    - Controls configured via setup_controls.py
"""

import asyncio
import os
import sys

import agent_control
from agent_control import ControlViolationError, control

# =============================================================================
# SDK INITIALIZATION
# =============================================================================

agent_control.init(
    agent_name="Q&A Agent with DeepEval",
    agent_id="qa-agent-deepeval",
    agent_description="Question answering agent with DeepEval quality controls",
    agent_version="1.0.0",
)


# =============================================================================
# MOCK LLM (Simulates various quality scenarios)
# =============================================================================


class MockQASystem:
    """
    Simulates a Q&A system with various response quality scenarios.

    This mock helps demonstrate how DeepEval controls catch quality issues:
    - Coherent responses pass
    - Incoherent responses are blocked
    - Irrelevant responses are blocked
    """

    GOOD_RESPONSES = {
        "python": (
            "Python is a high-level, interpreted programming language known for its "
            "simplicity and readability. It was created by Guido van Rossum and first "
            "released in 1991. Python supports multiple programming paradigms including "
            "procedural, object-oriented, and functional programming."
        ),
        "capital": (
            "Paris is the capital and largest city of France. It is located in the "
            "north-central part of the country along the River Seine. Paris has been "
            "a major center of culture, art, and politics for centuries."
        ),
        "photosynthesis": (
            "Photosynthesis is the process by which plants convert light energy into "
            "chemical energy. Using chlorophyll, plants absorb sunlight and combine "
            "carbon dioxide from the air with water from the soil to produce glucose "
            "and oxygen. This process is essential for life on Earth."
        ),
        "gravity": (
            "Gravity is a fundamental force of nature that attracts objects with mass "
            "toward each other. On Earth, gravity gives objects weight and causes them "
            "to fall toward the ground. The force of gravity was described by Newton's "
            "laws and later refined by Einstein's theory of general relativity."
        ),
    }

    # Incoherent responses (logical inconsistencies, contradictions)
    INCOHERENT_RESPONSES = {
        "trigger_incoherent": (
            "Python is a snake. Also Python is not a snake. "
            "It's both simultaneously. Yesterday is tomorrow. "
            "The sky is made of cheese but also not cheese. "
            "Numbers are letters and letters are numbers."
        ),
    }

    # Irrelevant responses (don't answer the question)
    IRRELEVANT_RESPONSES = {
        "trigger_irrelevant": (
            "Bananas are yellow fruits that grow on trees. "
            "The weather today is sunny. I like pizza. "
            "Dogs are mammals. The year has 12 months."
        ),
    }

    @classmethod
    def answer_question(cls, question: str) -> str:
        """Generate an answer to the question."""
        question_lower = question.lower()

        # Check for test triggers
        if "trigger_incoherent" in question_lower or "incoherent" in question_lower:
            return cls.INCOHERENT_RESPONSES["trigger_incoherent"]

        if "trigger_irrelevant" in question_lower or "irrelevant" in question_lower:
            return cls.IRRELEVANT_RESPONSES["trigger_irrelevant"]

        # Match question to good responses
        if "python" in question_lower:
            return cls.GOOD_RESPONSES["python"]
        elif "capital" in question_lower and "france" in question_lower:
            return cls.GOOD_RESPONSES["capital"]
        elif "photosynthesis" in question_lower:
            return cls.GOOD_RESPONSES["photosynthesis"]
        elif "gravity" in question_lower:
            return cls.GOOD_RESPONSES["gravity"]
        else:
            # Default educational response
            return (
                f"That's an interesting question about '{question}'. "
                "Based on general knowledge, I can provide information on this topic. "
                "Would you like me to explain in more detail?"
            )


# =============================================================================
# PROTECTED AGENT FUNCTION
# =============================================================================


@control()
async def answer_question(question: str) -> str:
    """
    Answer a question with quality controls.

    The @control() decorator:
    - Checks 'pre' controls before generating (validates input)
    - Checks 'post' controls after generating (validates output quality)

    DeepEval controls check:
    - Coherence: Is the response logically consistent?
    - Relevance: Does it address the question?
    - Correctness: Is it factually accurate? (if enabled)

    If a control fails, ControlViolationError is raised.
    """
    response = MockQASystem.answer_question(question)
    return response


# =============================================================================
# Q&A AGENT CLASS
# =============================================================================


class QAAgent:
    """
    Question answering agent with DeepEval quality controls.

    Demonstrates graceful error handling when quality controls fail.
    """

    def __init__(self):
        self.conversation_history: list[dict[str, str]] = []

    async def ask(self, question: str) -> str:
        """
        Ask a question and get an answer.

        Handles ControlViolationError gracefully by returning
        a helpful message instead of exposing internal errors.
        """
        self.conversation_history.append({"role": "user", "content": question})

        try:
            # Get answer - protected by DeepEval controls
            answer = await answer_question(question)

            self.conversation_history.append({"role": "assistant", "content": answer})
            return answer

        except ControlViolationError as e:
            # Control triggered - return helpful feedback
            fallback = (
                f"I apologize, but my response didn't meet quality standards. "
                f"({e.control_name})\n\n"
                f"Could you rephrase your question or ask something else?"
            )
            self.conversation_history.append({"role": "assistant", "content": fallback})
            print(f"\n⚠️  Quality control triggered: {e.control_name}")
            print(f"    Reason: {e.message}")
            return fallback


# =============================================================================
# INTERACTIVE MODE
# =============================================================================


def print_header():
    """Print the demo header."""
    print()
    print("=" * 70)
    print("  Q&A Agent with DeepEval Quality Controls")
    print("=" * 70)
    print()
    print("This agent uses DeepEval GEval to enforce response quality:")
    print("  ✓ Coherence - Responses must be logically consistent")
    print("  ✓ Relevance - Answers must address the question")
    print("  ○ Correctness - Factual accuracy (disabled by default)")
    print()
    print("Commands:")
    print("  /test-good       Test with high-quality questions")
    print("  /test-bad        Test quality control triggers")
    print("  /help            Show this help")
    print("  /quit            Exit")
    print()
    print("Or just type a question!")
    print("-" * 70)
    print()


def print_help():
    """Print help information."""
    print()
    print("Available Commands:")
    print("  /test-good      Test with questions that produce quality answers")
    print("  /test-bad       Test questions that trigger quality controls")
    print("  /help           Show this help message")
    print("  /quit or /exit  Exit the program")
    print()
    print("Or ask any question and see how DeepEval evaluates quality!")
    print()


async def run_good_tests(agent: QAAgent):
    """Run tests with good quality responses."""
    print("\n" + "=" * 70)
    print("Testing Good Quality Responses")
    print("=" * 70)
    print("\nThese should pass all quality controls.\n")

    test_questions = [
        "What is Python?",
        "What is the capital of France?",
        "How does photosynthesis work?",
        "What is gravity?",
    ]

    for question in test_questions:
        print(f"Q: {question}")
        answer = await agent.ask(question)
        print(f"A: {answer[:150]}...")
        print()


async def run_bad_tests(agent: QAAgent):
    """Run tests that should trigger quality controls."""
    print("\n" + "=" * 70)
    print("Testing Quality Control Triggers")
    print("=" * 70)
    print("\nThese should trigger DeepEval controls.\n")

    test_questions = [
        "Test trigger_incoherent response please",  # Should fail coherence
        "Tell me about something trigger_irrelevant",  # Should fail relevance
    ]

    for question in test_questions:
        print(f"Q: {question}")
        answer = await agent.ask(question)
        print(f"A: {answer}")
        print()


async def run_interactive(agent: QAAgent):
    """Run interactive mode."""
    print_header()

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.startswith("/"):
            command = user_input.lower().split()[0]

            if command in ("/quit", "/exit"):
                print("Goodbye!")
                break

            elif command == "/help":
                print_help()

            elif command == "/test-good":
                await run_good_tests(agent)

            elif command == "/test-bad":
                await run_bad_tests(agent)

            else:
                print(f"Unknown command: {command}")
                print("Type /help for available commands")

        else:
            # Regular question
            answer = await agent.ask(user_input)
            print(f"\nAgent: {answer}\n")


# =============================================================================
# MAIN
# =============================================================================


async def main():
    """Run the Q&A agent."""
    # Check for OPENAI_API_KEY
    if not os.getenv("OPENAI_API_KEY"):
        print("\n⚠️  Warning: OPENAI_API_KEY not set!")
        print("   DeepEval requires OpenAI API access for GEval.")
        print("   Set it with: export OPENAI_API_KEY='your-key'")
        print()
        response = input("Continue anyway? (y/N): ").strip().lower()
        if response != "y":
            print("Exiting. Set OPENAI_API_KEY and try again.")
            sys.exit(1)

    # Check server connection
    server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
    print(f"\nConnecting to agent-control server at {server_url}...")

    import httpx

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{server_url}/health", timeout=5.0)
            resp.raise_for_status()
            print("✓ Connected to server")
    except Exception as e:
        print(f"\n❌ Cannot connect to server: {e}")
        print("   Make sure the agent-control server is running.")
        print("   Run setup_controls.py first to configure the agent.")
        sys.exit(1)

    # Create and run agent
    agent = QAAgent()
    await run_interactive(agent)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted. Goodbye!")
