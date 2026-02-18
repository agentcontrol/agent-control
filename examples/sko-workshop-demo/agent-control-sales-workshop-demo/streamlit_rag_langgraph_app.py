#!/usr/bin/env python3
"""Streamlit RAG Q&A demo using LangGraph + ChromaDB + OpenAI + AgentControl."""

import os
import sys
from typing import Any, Dict, List, TypedDict

import streamlit as st

# SDK fallback path (monorepo checkout)
SDK_FALLBACK = "/Users/namrataghadi/code/agentcontrol/agent-control/sdks/python/src"
if SDK_FALLBACK not in sys.path:
    sys.path.insert(0, SDK_FALLBACK)

import agent_control
from agent_control import ControlViolationError, control

from chromadb import Client
from chromadb.config import Settings
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END, START
from langchain_core.tools import tool


AGENT_NAME = "RAG Q&A Agent"
AGENT_ID = "9e9a1c8e-8c3f-4c6d-9d2a-0d3d5e8a1b77"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# --- Initialize AgentControl ---
agent_control.init(
    agent_name=AGENT_NAME,
    agent_id=AGENT_ID,
    agent_description="RAG Q&A demo agent (LangGraph)",
    server_url=SERVER_URL,
)

# --- LLM ---
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)

# --- ChromaDB ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY is required for embeddings and LLM")
    st.stop()

embedding_fn = OpenAIEmbeddingFunction(
    api_key=OPENAI_API_KEY,
    model_name="text-embedding-3-small",
)

client = Client(Settings(anonymized_telemetry=False))
collection = client.get_or_create_collection(
    name="sales_knowledge",
    embedding_function=embedding_fn,
)

DOCS = [
    (
        "pricing-1",
        "Pricing: Standard plan is $50k/year with 10% max discount. Premium is $120k/year with 30% max discount.",
    ),
    (
        "security-1",
        "Security: SOC2 Type II, GDPR compliant, data encrypted at rest and in transit.",
    ),
    (
        "roi-1",
        "ROI: Customers typically see 20% faster sales cycles and 15% higher win rates.",
    ),
    (
        "support-1",
        "Support: 24/7 support for Premium tier, business-hours support for Standard tier.",
    ),
]

# Index docs (idempotent)
existing = set(collection.get(include=[]).get("ids", []))
for doc_id, text in DOCS:
    if doc_id not in existing:
        collection.add(ids=[doc_id], documents=[text])


# --- Controlled retrieval tool ---
# --- Retrieval tool (LangChain) ---
@tool("retrieve_docs")
async def _retrieve_docs(query: str) -> List[str]:
    """Retrieve top docs from ChromaDB for the user query."""
    results = collection.query(query_texts=[query], n_results=3)
    docs = results.get("documents", [[]])[0]
    return docs

# --- Controlled wrapper (AgentControl) ---
@control(step_name="retrieve_docs")
async def retrieve_docs(query: str) -> List[str]:
    return await _retrieve_docs.ainvoke({"query": query})


# --- Controlled answer generation ---
@control()
async def answer_question(question: str, context: str) -> str:
    prompt = (
        "You are a sales Q&A assistant. Answer the question using the context below. "
        "If the context does not contain the answer, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )
    resp = await llm.ainvoke(prompt)
    return resp.content


# --- LangGraph ---
class QAState(TypedDict, total=False):
    question: str
    context: str
    answer: str


async def node_retrieve(state: QAState) -> QAState:
    docs = await retrieve_docs(state["question"])
    return {**state, "context": "\n".join(docs)}


async def node_answer(state: QAState) -> QAState:
    ans = await answer_question(state["question"], state.get("context", ""))
    return {**state, "answer": ans}


def build_graph():
    graph = StateGraph(QAState)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("answer", node_answer)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


# --- Helper: run async in streamlit ---

def asyncio_run(coro):
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    return asyncio.run(coro)


# --- Streamlit UI ---

st.set_page_config(page_title="AgentControl RAG Q&A", layout="centered")
st.title("AgentControl RAG Q&A Demo (LangGraph)")
st.caption("ChromaDB + OpenAI + AgentControl controls")

st.sidebar.title("RAG Controls Checklist")
st.sidebar.markdown(
    "Create these in the UI for this demo:"
)
st.sidebar.markdown(
    "- `rag-block-prompt-injection` (LLM pre, selector: `input`)\n"
    "- `rag-block-pii-output` (LLM post, selector: `output`)\n"
    "- `rag-block-pii-in-retrieval` (Tool pre, selector: `input.query`)"
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    "Tip: Use **setup_rag_controls.py** to create them automatically."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Ask a question about pricing, security, ROI, support...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                app = build_graph()
                result = asyncio_run(app.ainvoke({"question": prompt}))
                answer = result.get("answer", "")
                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except ControlViolationError as e:
                msg = f"Blocked by control: {e.control_name} ({e.message})"
                st.warning(msg)
                st.session_state.messages.append({"role": "assistant", "content": msg})
            except Exception as e:
                st.error(f"Error: {type(e).__name__}: {e}")
