"""Six prompts → Claude Sonnet, wrapped with @control.

The agent is initialized here in code. The guardrail policy is created in
the UI (http://localhost:4000) and bound to this agent — re-run after
editing the policy to see it take effect, no code changes.
"""

import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

import agent_control
from agent_control import ControlViolationError, control

load_dotenv()

AGENT_NAME = "anthropic-chat-demo"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

QUESTIONS = [
    "What is the capital of France?",
    "Summarize the plot of Hamlet in two sentences.",
    "Explain quantum entanglement to a 10-year-old.",
    "My SSN is 123-45-6789 — can you verify it?",
    "Write a haiku about distributed systems.",
    "What's a good way to keep API keys safe in a Python project?",
]


@control()
def ask_claude(prompt: str) -> str:
    """Send a single prompt to Claude. @control evaluates input and output
    against whatever policy is bound to AGENT_NAME on the server."""
    client = Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def main() -> int:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in.",
            file=sys.stderr,
        )
        return 1

    agent_control.init(
        agent_name=AGENT_NAME,
        agent_description="Six-prompt chat demo against Claude Sonnet",
        server_url=SERVER_URL,
        observability_enabled=True,
    )

    for i, question in enumerate(QUESTIONS, 1):
        print(f"\n[{i}/{len(QUESTIONS)}] Q: {question}")
        try:
            answer = ask_claude(question)
            preview = answer if len(answer) <= 400 else answer[:400] + "…"
            print(f"      A: {preview}")
        except ControlViolationError as e:
            print(f"      🚫 BLOCKED by control '{e.control_name}': {e.message}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
