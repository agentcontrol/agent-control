"""
Q&A RAG Agent with LangSmith Evaluator Controls.

This example demonstrates a document Q&A agent that uses Retrieval Augmented
Generation (RAG) with Agent Control and LangSmith evaluators to ensure:
1. No toxic or harmful queries
2. No hallucinations in responses
3. No PII leakage in responses
4. Relevant responses based on retrieved context

PREREQUISITE:
    Run setup_langsmith_controls.py FIRST to create the controls and policy:

        $ uv run setup_langsmith_controls.py

    Then run this example:

        $ uv run rag_qa_agent.py

The @control() decorator automatically:
1. Checks user queries for toxicity before processing
2. Evaluates generated responses for hallucinations
3. Scans responses for PII before returning to user
4. Ensures responses are relevant to the retrieved context
"""

import asyncio
import os
from typing import Annotated, Literal, TypedDict

import agent_control
from agent_control import (
    AgentControlClient,
    ControlViolationError,
    agents,
    check_evaluation_with_local,
    control,
)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# --- Configuration ---
AGENT_ID = "rag-qa-agent-demo"
AGENT_NAME = "RAG Q&A Agent"
AGENT_DESCRIPTION = "Document Q&A agent with LangSmith safety controls"
USE_LOCAL_CONTROLS = os.getenv("AGENT_CONTROL_LOCAL_EVAL", "false").lower() == "true"


# --- Sample Documents ---
SAMPLE_DOCUMENTS = [
    """
    Python is a high-level, interpreted programming language known for its
    simplicity and readability. It was created by Guido van Rossum and first
    released in 1991. Python supports multiple programming paradigms including
    procedural, object-oriented, and functional programming.
    """,
    """
    Machine Learning is a subset of artificial intelligence that enables systems
    to learn and improve from experience without being explicitly programmed.
    It focuses on the development of computer programs that can access data and
    use it to learn for themselves. Common algorithms include neural networks,
    decision trees, and support vector machines.
    """,
    """
    Cloud Computing refers to the delivery of computing services including servers,
    storage, databases, networking, software, analytics, and intelligence over the
    Internet (the cloud) to offer faster innovation, flexible resources, and
    economies of scale. Major cloud providers include AWS, Google Cloud, and Azure.
    """,
    """
    Cybersecurity is the practice of protecting systems, networks, and programs from
    digital attacks. These attacks are usually aimed at accessing, changing, or
    destroying sensitive information, extorting money from users, or interrupting
    normal business processes. Key principles include confidentiality, integrity,
    and availability.
    """,
]


# --- Setup RAG System ---
def setup_rag_system():
    """Create a simple RAG system with FAISS vector store."""
    print("Setting up RAG system...")

    # Create documents
    documents = [
        Document(page_content=doc, metadata={"source": f"doc_{i}"})
        for i, doc in enumerate(SAMPLE_DOCUMENTS)
    ]

    # Split documents (for demo, keep them as is)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
    )
    splits = text_splitter.split_documents(documents)

    # Create vector store
    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.from_documents(splits, embeddings)

    print(f"✓ Created vector store with {len(splits)} document chunks")
    return vectorstore


# --- Create Controlled RAG Tools ---
def create_rag_tools(vectorstore, *, use_local_controls: bool, local_controls: list[dict] | None):
    """Create RAG tools with Agent Control safety checks."""

    # Tool 1: Retrieve relevant documents (with input toxicity check)
    async def _retrieve_documents_with_validation(query: str):
        """Retrieve relevant documents for a query (protected by @control)."""
        docs = vectorstore.similarity_search(query, k=3)
        return "\n\n".join([f"Document {i+1}:\n{doc.page_content}" for i, doc in enumerate(docs)])

    # Set tool name for @control detection
    _retrieve_documents_with_validation.name = "retrieve_documents"  # type: ignore
    _retrieve_documents_with_validation.tool_name = "retrieve_documents"  # type: ignore

    # Apply @control decorator
    validated_retrieve_func = control()(_retrieve_documents_with_validation)

    @tool("retrieve_documents", description="Retrieve relevant documents for a query")
    async def retrieve_documents(query: str):
        """Retrieve documents with safety checks on the query."""
        print(f"\n[Query Safety Check] Validating query: {query[:60]}...")
        try:
            if use_local_controls:
                agent = agent_control.current_agent()
                if agent is None:
                    raise RuntimeError("Agent is not initialized.")
                if not local_controls:
                    raise RuntimeError("No local controls available for SDK evaluation.")

                step = {
                    "type": "tool",
                    "name": "retrieve_documents",
                    "input": {"query": query},
                }
                async with AgentControlClient() as client:
                    result = await check_evaluation_with_local(
                        client=client,
                        agent_uuid=agent.agent_id,
                        step=step,
                        stage="pre",
                        controls=local_controls,
                    )
                if getattr(result, "errors", None):
                    raise RuntimeError("Local control evaluation failed.")
                if not result.is_safe:
                    raise ControlViolationError(message=result.reason or "Control blocked")
                output = await _retrieve_documents_with_validation(query)
            else:
                output = await validated_retrieve_func(query)
            print("✅ Query validated, documents retrieved")
            return output
        except ControlViolationError as e:
            error_msg = f"🚫 Query blocked by safety control: {e.message}"
            print(error_msg)
            return error_msg
        except RuntimeError as e:
            error_msg = f"⚠️ Safety check unavailable: {str(e)}"
            print(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"❌ Unexpected error: {type(e).__name__}: {str(e)}"
            print(error_msg)
            return error_msg

    # Tool 2: Generate answer (with output hallucination and PII check)
    async def _generate_answer_with_validation(question: str, context: str):
        """Generate answer based on context (protected by @control)."""
        prompt = f"""Answer the following question based ONLY on the provided context.
If the answer cannot be found in the context, say "I don't have enough information to answer that question."

Context:
{context}

Question: {question}

Answer:"""

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        response = await llm.ainvoke(prompt)
        return response.content

    # Set tool name for @control detection
    _generate_answer_with_validation.name = "generate_answer"  # type: ignore
    _generate_answer_with_validation.tool_name = "generate_answer"  # type: ignore

    # Apply @control decorator (post-execution check)
    validated_generate_func = control()(_generate_answer_with_validation)

    @tool("generate_answer", description="Generate an answer based on retrieved context")
    async def generate_answer(question: str, context: str):
        """Generate answer with safety checks on the output."""
        print(f"\n[Answer Safety Check] Generating and validating answer...")
        try:
            if use_local_controls:
                agent = agent_control.current_agent()
                if agent is None:
                    raise RuntimeError("Agent is not initialized.")
                if not local_controls:
                    raise RuntimeError("No local controls available for SDK evaluation.")

                # First generate the answer
                answer = await _generate_answer_with_validation(question, context)

                # Then check it
                step = {
                    "type": "tool",
                    "name": "generate_answer",
                    "input": {"question": question, "context": context},
                    "output": answer,
                }
                async with AgentControlClient() as client:
                    result = await check_evaluation_with_local(
                        client=client,
                        agent_uuid=agent.agent_id,
                        step=step,
                        stage="post",
                        controls=local_controls,
                    )
                if getattr(result, "errors", None):
                    raise RuntimeError("Local control evaluation failed.")
                if not result.is_safe:
                    raise ControlViolationError(message=result.reason or "Control blocked")
                output = answer
            else:
                output = await validated_generate_func(question, context)
            print("✅ Answer validated and safe to return")
            return output
        except ControlViolationError as e:
            error_msg = f"🚫 Answer blocked by safety control: {e.message}"
            print(error_msg)
            return "I cannot provide that answer due to safety concerns."
        except RuntimeError as e:
            error_msg = f"⚠️ Safety check unavailable: {str(e)}"
            print(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"❌ Unexpected error: {type(e).__name__}: {str(e)}"
            print(error_msg)
            return error_msg

    return [retrieve_documents, generate_answer]


# --- Define Agent Graph ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def create_agent(model, tools):
    """Create the LangGraph agent."""
    model_with_tools = model.bind_tools(tools)

    async def agent_node(state: AgentState):
        messages = state["messages"]
        response = await model_with_tools.ainvoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    def should_continue(state: AgentState) -> Literal["tools", END]:
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools"
        return END

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    return workflow.compile()


# --- Main Execution ---
async def main():
    print("=" * 70)
    print("RAG Q&A Agent with LangSmith Evaluator Controls")
    print("=" * 70)
    print()
    print("NOTE: Make sure you've run setup_langsmith_controls.py first!")
    print("      $ uv run setup_langsmith_controls.py")
    print()
    print("Initializing RAG Q&A Agent...")

    # Initialize Agent Control
    agent_control.init(
        agent_name=AGENT_NAME,
        agent_id=AGENT_ID,
        agent_description=AGENT_DESCRIPTION,
        server_url=os.getenv("AGENT_CONTROL_URL"),
    )

    # Check OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        return

    # Setup RAG system
    vectorstore = setup_rag_system()

    # Setup LLM
    llm = ChatOpenAI(model="gpt-4o-mini")

    # Register agent and fetch controls if local evaluation is enabled
    local_controls: list[dict] | None = None
    if USE_LOCAL_CONTROLS:
        agent = agent_control.current_agent()
        if agent is None:
            raise RuntimeError("Agent is not initialized.")
        async with AgentControlClient() as client:
            response = await agents.register_agent(client, agent, steps=[])
            local_controls = response.get("controls", [])
            print(f"✓ Loaded {len(local_controls)} control(s) for local evaluation")

    # Create controlled tools
    tools = create_rag_tools(
        vectorstore,
        use_local_controls=USE_LOCAL_CONTROLS,
        local_controls=local_controls,
    )

    # Create agent
    agent = create_agent(llm, tools)

    # --- Test Scenarios ---

    # Scenario 1: Normal question
    print("\n" + "=" * 70)
    print("SCENARIO 1: Normal Question")
    print("User: What is Python?")
    print("=" * 70)

    async for event in agent.astream(
        {"messages": [HumanMessage(content="What is Python?")]},
        stream_mode="values",
    ):
        event["messages"][-1].pretty_print()

    # Scenario 2: Question with potential toxicity (should be blocked)
    print("\n" + "=" * 70)
    print("SCENARIO 2: Toxic Query")
    print("User: Tell me something stupid about Python")
    print("=" * 70)

    async for event in agent.astream(
        {"messages": [HumanMessage(content="Tell me something stupid about Python")]},
        stream_mode="values",
    ):
        event["messages"][-1].pretty_print()

    # Scenario 3: Question that might lead to hallucination
    print("\n" + "=" * 70)
    print("SCENARIO 3: Potential Hallucination")
    print("User: What is Python's market share in 2025?")
    print("=" * 70)

    async for event in agent.astream(
        {
            "messages": [
                HumanMessage(content="What is Python's market share in 2025?")
            ]
        },
        stream_mode="values",
    ):
        event["messages"][-1].pretty_print()

    # Scenario 4: Question about a different topic
    print("\n" + "=" * 70)
    print("SCENARIO 4: Different Topic")
    print("User: What is Machine Learning?")
    print("=" * 70)

    async for event in agent.astream(
        {"messages": [HumanMessage(content="What is Machine Learning?")]},
        stream_mode="values",
    ):
        event["messages"][-1].pretty_print()


if __name__ == "__main__":
    asyncio.run(main())
