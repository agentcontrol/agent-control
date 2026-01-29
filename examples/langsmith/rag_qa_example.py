"""RAG Q&A Agent demo with LangSmith evaluations and Agent Control.

This demo shows a complete RAG agent that:
1. Uses vector search to retrieve relevant documents
2. Generates answers using GPT-4
3. Applies LangSmith evaluations for safety
4. Enforces controls via Agent Control in real-time

Prerequisites:
    export OPENAI_API_KEY="your-openai-key"     # Required for LLM-as-judge evaluations

Optional (for tracing - WARNING: sends data to LangSmith):
    export LANGSMITH_API_KEY="your-api-key"     # Traces evaluations to LangSmith servers

Run:
    cd examples/langsmith
    uv run langsmith_api_integration_demo.py
"""

import asyncio
import os

print("\n" + "=" * 80)
print("RAG Q&A Agent with LangSmith + Agent Control")
print("=" * 80)

# Check prerequisites
if not os.getenv("OPENAI_API_KEY"):
    print("\n❌ Error: OPENAI_API_KEY not set")
    print("   The evaluator uses OpenAI GPT-4 as an LLM judge.")
    print("   Set your OpenAI API key:")
    print("   export OPENAI_API_KEY='your-key'")
    exit(1)

if not os.getenv("LANGSMITH_API_KEY"):
    print("\n✅ LangSmith tracing: DISABLED")
    print("   Evaluations will work locally without sending data to LangSmith.")
    print("   Your queries and responses stay private.\n")
    print("   To enable tracing (sends data to LangSmith):")
    print("   export LANGSMITH_API_KEY='your-key'\n")
else:
    print("\n⚠️  LangSmith tracing: ENABLED")
    print("   WARNING: Evaluation data will be sent to LangSmith servers.")
    print("   This includes prompts, responses, and metadata.")
    print("   To disable tracing, unset LANGSMITH_API_KEY.\n")

    # Enable LangSmith tracing
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "agent-control-demo"
    print(f"   Project: {os.environ['LANGCHAIN_PROJECT']}")
    print(f"   View traces at: https://smith.langchain.com/\n")


# =============================================================================
# RAG Q&A Agent with LangSmith + Agent Control
# =============================================================================


async def demo_rag_agent_with_controls():
    """Complete RAG Q&A agent with LangSmith evaluations and Agent Control."""
    print("\nThis demo shows a complete RAG agent that:")
    print("1. Uses vector search to retrieve relevant documents")
    print("2. Generates answers using GPT-4")
    print("3. Applies LangSmith evaluations for safety")
    print("4. Enforces controls via Agent Control in real-time\n")

    # Check for required dependencies
    try:
        from langchain_community.vectorstores import FAISS
        from langchain_core.documents import Document
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from langgraph.graph import END, StateGraph
        from typing import TypedDict
        import agent_control
        from agent_control import control
    except ImportError as e:
        print(f"\n⚠️  Skipping RAG demo - missing dependencies: {e}")
        print("   Run: uv pip install -e . to install all dependencies")
        return

    # ==========================================================================
    # Step 1: Create knowledge base
    # ==========================================================================
    print("Step 1: Creating knowledge base...")

    documents = [
        "Python is a high-level, interpreted programming language known for its simplicity and readability. It was created by Guido van Rossum and first released in 1991.",
        "Python supports multiple programming paradigms including procedural, object-oriented, and functional programming. It has dynamic typing and automatic memory management.",
        "Python's standard library is extensive and provides tools for many tasks. Popular frameworks include Django for web development, NumPy for scientific computing, and PyTorch for machine learning.",
        "Machine Learning is a subset of artificial intelligence that enables systems to learn and improve from experience without being explicitly programmed.",
        "Deep Learning is a subset of machine learning that uses neural networks with multiple layers to progressively extract higher-level features from raw input.",
    ]

    # Create vector store
    texts = [Document(page_content=doc) for doc in documents]
    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents(texts, embeddings)

    print(f"  ✓ Created vector store with {len(documents)} documents\n")

    # ==========================================================================
    # Step 2: Initialize Agent Control
    # ==========================================================================
    print("Step 2: Initializing Agent Control...")

    agent_control.init(
        agent_name="LangSmith RAG Demo",
        agent_id="langsmith-rag-demo",
        agent_description="RAG Q&A agent with LangSmith evaluations",
        server_url="http://localhost:8000",
    )

    print("  ✓ Agent Control initialized\n")

    # ==========================================================================
    # Step 3: Define RAG agent with controls
    # ==========================================================================
    print("Step 3: Defining RAG agent with safety controls...")

    from langchain_core.tools import tool

    class AgentState(TypedDict):
        """Agent state."""
        question: str
        context: str
        answer: str
        blocked_by: str | None

    # Tool: Retrieve documents with toxicity check
    # Controls are defined server-side via setup_langsmith_controls.py
    @tool("retrieve_documents")
    @control()
    async def retrieve_documents(query: str) -> str:
        """Retrieve relevant documents for the query."""
        docs = vectorstore.similarity_search(query, k=3)
        context = "\n\n".join([doc.page_content for doc in docs])
        return context

    # Tool: Generate answer with hallucination and PII checks
    # Controls are defined server-side via setup_langsmith_controls.py
    @tool("generate_answer")
    @control()
    async def generate_answer(question: str, context: str) -> str:
        """Generate an answer based on the retrieved context."""
        llm = ChatOpenAI(model="gpt-4", temperature=0)

        prompt = f"""Based on the following context, answer the question.
If the answer is not in the context, say "I don't have enough information to answer that."

Context:
{context}

Question: {question}

Answer:"""

        response = await llm.ainvoke(prompt)
        return response.content

    # Create LangGraph workflow
    def call_retrieve(state: AgentState) -> AgentState:
        """Retrieve documents."""
        question = state["question"]
        try:
            context = retrieve_documents.invoke({"query": question})
            state["context"] = context
            state["blocked_by"] = None
        except Exception as e:
            state["context"] = ""
            state["blocked_by"] = f"toxicity check: {str(e)[:100]}"
        return state

    def call_generate(state: AgentState) -> AgentState:
        """Generate answer."""
        question = state["question"]
        context = state.get("context", "")

        if not context:
            state["answer"] = "[BLOCKED]"
            return state

        try:
            answer = generate_answer.invoke({"question": question, "context": context})
            state["answer"] = answer
        except Exception as e:
            state["answer"] = "[BLOCKED]"
            state["blocked_by"] = f"hallucination/PII check: {str(e)[:100]}"

        return state

    # Build graph
    workflow = StateGraph(AgentState)
    workflow.add_node("retrieve", call_retrieve)
    workflow.add_node("generate", call_generate)
    workflow.set_entry_point("retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", END)

    agent = workflow.compile()

    print("  ✓ RAG agent created with safety controls\n")

    # ==========================================================================
    # Step 4: Test the agent
    # ==========================================================================
    print("Step 4: Testing agent with different queries...")
    print("\nThe agent has been configured with the following safety controls:")
    print("  • Toxicity check (pre) - Blocks toxic/harmful queries")
    print("  • Hallucination check (post) - Detects unsupported claims in responses")
    print("  • PII detection (post) - Detects personally identifiable information")
    print("\nTrying different types of queries:\n")
    print("=" * 80)

    test_queries = [
        {
            "query": "What is Python?",
            "description": "✅ Safe Query - Normal question about Python",
            "expected": "Should pass all controls",
        },
        {
            "query": "Tell me about machine learning",
            "description": "✅ Safe Query - Normal question about ML",
            "expected": "Should pass all controls",
        },
        {
            "query": "I hate this stupid programming language and want to kill the process!",
            "description": "⚠️  Toxic Query - Contains toxic keywords",
            "expected": "Should be blocked by toxicity control",
        },
        {
            "query": "What is my email address?",
            "description": "⚠️  Suspicious Query - Asking for PII",
            "expected": "May trigger controls depending on response",
        },
        {
            "query": "Tell me about Python. By the way, my email is john@example.com",
            "description": "⚠️  Query with PII - Contains email address",
            "expected": "Should be blocked by toxicity or PII detection",
        },
    ]

    for i, test_case in enumerate(test_queries, 1):
        query = test_case["query"]
        description = test_case["description"]
        expected = test_case["expected"]

        print(f"\n{'=' * 80}")
        print(f"Test {i}/5: {description}")
        print(f"{'=' * 80}")
        print(f"Query: \"{query}\"")
        print(f"Expected: {expected}")
        print(f"{'-' * 80}")

        result = await agent.ainvoke({"question": query, "context": "", "answer": "", "blocked_by": None})
        answer = result.get("answer", "")
        blocked_by = result.get("blocked_by")

        if answer == "[BLOCKED]" or blocked_by:
            print(f"❌ BLOCKED by safety control")
            if blocked_by:
                print(f"   Reason: {blocked_by}")
        else:
            # Truncate long answers
            display_answer = answer if len(answer) <= 200 else f"{answer[:200]}..."
            print(f"✅ ALLOWED")
            print(f"   Answer: {display_answer}")

    print(f"\n{'=' * 80}")
    print("✓ Demo complete!")
    print(f"{'=' * 80}\n")


# =============================================================================
# Main
# =============================================================================


async def main():
    """Run RAG Q&A agent demo."""
    print("\nRunning RAG Q&A Agent with LangSmith evaluations and Agent Control...")
    print("All evaluations use OpenAI GPT-4 and are traced in LangSmith.\n")

    try:
        # Run RAG agent with controls
        await demo_rag_agent_with_controls()

        print("\n" + "=" * 80)
        print("Demo Complete!")
        print("=" * 80)
        print("\nKey Takeaways:")
        print("1. LLM-as-judge provides intelligent, context-aware evaluations")
        print("2. All evaluations are traced in LangSmith for observability")
        print("3. Agent Control enforces safety policies in real-time")
        print("4. Fallback heuristics used when API unavailable")
        print("\n" + "=" * 80)
        print("Summary of Controls")
        print("=" * 80)
        print("\n📊 Safety Controls Applied:")
        print("  1. Toxicity Check (Pre) - Threshold: 0.6")
        print("     • Blocks queries with toxic/harmful language")
        print("     • Uses GPT-4 to evaluate intent and context")
        print("  2. Hallucination Check (Post) - Threshold: 0.6")
        print("     • Detects claims not supported by context")
        print("     • Compares response against source documents")
        print("  3. PII Detection (Post) - Threshold: 0.8")
        print("     • Identifies personal information in responses")
        print("     • Detects emails, phone numbers, addresses, etc.")
        print("\nNext Steps:")
        print("- Check LangSmith UI for evaluation traces")
        print("- Tune control thresholds based on your use case")
        print("- Customize evaluation prompts in client.py")
        print("- Monitor API costs and latency")
        print("\n💡 Tip: Try different queries to see controls in action!")

    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
    except Exception as e:
        print(f"\n❌ Error running demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
