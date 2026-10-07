"""Cross-package check: StepRecorder trees feed the Galileo record factory.

The galileo extras are normally installed in the dev environment (see
``test_evaluators_optional_imports.py``), so this skips cleanly when they
are not available instead of failing the suite.
"""

from __future__ import annotations

import importlib.util

import pytest

from agent_control import record_step


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


_GALILEO_INSTALLED = _module_available("agent_control_evaluator_galileo.records")

pytestmark = pytest.mark.skipif(
    not _GALILEO_INSTALLED,
    reason="agent-control-evaluator-galileo extras not installed in this environment",
)


def _record_from_step(step):
    from agent_control_evaluator_galileo.records.factory import record_from_step

    return record_from_step(step)


def test_recorder_built_trace_matches_demo_shape():
    """A trace with one llm/tool/retriever child each builds a 3-span Trace."""

    def policy_search(query: str) -> dict:
        return {"docs": ["policy-1"]}

    def account_lookup(account_id: str) -> dict:
        return {"balance": 500}

    def banking_llm(prompt: str) -> str:
        return f"response: {prompt}"

    with record_step("trace", "banking_trace", input={"request": "r1"}) as trace:
        trace.call(
            policy_search, query="refund policy", step_type="retriever", step_name="policy_search"
        )
        trace.call(
            account_lookup, account_id="acct-1", step_type="tool", step_name="account_lookup"
        )
        trace.call(banking_llm, "draft a reply", step_type="llm", step_name="banking_llm")
        trace.output = {"status": "done"}

    record = _record_from_step(trace.build())

    assert type(record).__name__ == "Trace"
    assert len(record.spans) == 3
    assert {type(span).__name__ for span in record.spans} == {
        "LlmSpan",
        "ToolSpan",
        "RetrieverSpan",
    }


def test_recorder_built_session_matches_demo_shape():
    """A session with 2 traces, each with >=2 spans, builds the matching Session."""
    with record_step("session", "banking_session") as session:
        for i in range(2):
            with session.child("trace", f"turn_{i}", input={"turn": i}) as trace:
                with trace.child("llm", "respond", input="hi") as llm:
                    llm.output = "hello"
                with trace.child("tool", "lookup", input={}) as tool:
                    tool.output = {}
                trace.output = {"turn": i, "status": "ok"}

    record = _record_from_step(session.build())

    assert type(record).__name__ == "Session"
    assert len(record.traces) == 2
    for sub_trace in record.traces:
        assert len(sub_trace.spans) >= 2
