#!/usr/bin/env python3
"""Interactive RAG Q&A demo using ChromaDB + OpenAI + AgentControl."""

import asyncio
import os
import sys
from typing import Any, Dict, List

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
from langchain_core.tools import tool


AGENT_NAME = "RAG Q&A Agent"
AGENT_ID = "9e9a1c8e-8c3f-4c6d-9d2a-0d3d5e8a1b77"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# --- Initialize AgentControl ---
agent_control.init(
    agent_name=AGENT_NAME,
    agent_id=AGENT_ID,
    agent_description="Sales assistant demo agent (RAG Q&A)",
    server_url=SERVER_URL,
)

# --- LLM ---
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)

# --- ChromaDB ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is required for embeddings and LLM")

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
existing = set(collection.get(include=[]) .get("ids", []))
for doc_id, text in DOCS:
    if doc_id not in existing:
        collection.add(ids=[doc_id], documents=[text])


# --- Controlled retrieval tool ---
@tool("retrieve_docs")
async def _retrieve_docs(query: str) -> List[str]:
    """Retrieve top docs from ChromaDB."""
    results = collection.query(query_texts=[query], n_results=3)
    docs = results.get("documents", [[]])[0]
    return docs

# Wrap tool with AgentControl
_retrieve_docs.name = "retrieve_docs"  # type: ignore[attr-defined]
_retrieve_docs.tool_name = "retrieve_docs"  # type: ignore[attr-defined]
retrieve_docs = control()(_retrieve_docs)


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


async def run_qa(question: str) -> str:
    docs = await retrieve_docs(question)
    context = "\n".join(docs)
    return await answer_question(question, context)


async def main() -> None:
    print("=" * 70)
    print("RAG Q&A Demo (ChromaDB + OpenAI + AgentControl)")
    print("=" * 70)
    print("Try questions like:")
    print("  - What is the pricing for Standard?\n  - Are you GDPR compliant?\n  - What ROI do customers see?\n")
    print("Type 'exit' to quit.\n")

    while True:
        try:
            q = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not q:
            continue
        if q.lower() in ("exit", "quit"):
            print("Goodbye!")
            break

        try:
            ans = await run_qa(q)
            print(f"Agent: {ans}")
        except ControlViolationError as e:
            print(f"Blocked by control: {e.control_name} ({e.message})")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
